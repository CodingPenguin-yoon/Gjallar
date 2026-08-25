# 구현 계획: Verified Operations Control Plane 전환

- 상태: `APPROVED`
- 날짜: `2026-07-20`
- 관련 요구사항: [`Project Specification`](../specifications/project-specification.md)
- 관련 ADR: [`ADR-001`](../decisions/adr-001-proxmox-gjallar-authority-boundary.md), [`ADR-002`](../decisions/adr-002-modular-monolith-domain-boundaries.md), [`ADR-003`](../decisions/adr-003-production-inventory-connection-truth.md), [`ADR-006`](../decisions/adr-006-drs-deprecation-and-insights-convergence.md)
- 승인자: `사용자`

이 Plan은 2026-07-20 사용자 승인을 받았다. 한 번에 전면 rewrite하지 않고 검증 가능한 vertical slice로 전환한다.

> 2026-08-24 제품 기준선 갱신: [`ADR-007`](../decisions/adr-007-observe-first-operations-intelligence.md)이 Verified Operations Control Plane 중심을 Observe-first Operations Intelligence with Verified Actions로 대체했다. 이 Plan의 완료된 단계 0~10-B는 구현 이력으로 보존한다. 미착수 단계 11의 후속 범위는 [`Observe-first Operations Intelligence 전환`](2026-08-24-observe-first-operations-intelligence-transition.md)에 구체화했으며, 사용자가 운영 배포·외부 consumer·보존할 production DRS state가 없다는 전제를 수락해 full repository removal까지 추가 승인·구현했다. production DB 적용·외부 credential revoke·live mutation은 후속 Plan 밖이다.

- 진행 상태: `단계 0~9, 10-A durable recovery foundation과 10-B graceful VM Shutdown 구현 완료; 이후 전환은 ADR-007과 2026-08-24 후속 Plan이 소유`

## 1. 위험도

- 분류: `HIGH`
- 판단 근거: domain boundary, data ownership, public API, 인증·권한, DB transaction, Proxmox mutation, idempotency, concurrency, reconciliation을 다룬다.
- 실패 영향: 같은 VM에 중복 mutation, 잘못된 target 변경, approval/actor/evidence 손실, fake/live 상태 혼동, 실제 성공·실패 오판, API/UI regression.
- 되돌리기 어려운 부분: 적용 DB migration, external Proxmox side effect, audit/history 삭제, public contract break.
- 기본 완화: 문서와 behavior characterization → schema-free pilot → 검토 → 필요한 migration의 별도 상세 승인 순서를 사용한다.

## 2. 확인한 현재 상태

### Runtime과 active surface

- single FastAPI application과 React SPA, PostgreSQL/Alembic, Proxmox API로 구성된다.
- backend entry는 `backend/app/main.py`, public product API는 `backend/app/api/v1/router.py`, auth/admin은 별도 router다.
- active 기능은 Auth/Admin, read-only Inventory, Create VM, VM Start, graceful VM Shutdown, DRS recommendation/policy/approval/migration/reconciliation, Jobs/Artifacts/Risks다.
- production은 single Docker image이고 startup 때 Alembic upgrade, profile seed, optional bootstrap admin을 수행한다.

### 재사용할 강점

- local session/RBAC와 trusted server-side actor.
- read inventory와 mutation client의 분리.
- Create VM의 draft → preflight → plan → approval → create → optional verification 흐름.
- VM Start의 acknowledgement, idempotency, fresh pre-check, task poll, post-check.
- DRS의 identity/policy/approval binding, operation lock, ambiguous result reconciliation.
- DB-backed job/artifact와 broad contract/unit/frontend test asset.

### 먼저 고정·수정할 위험

1. VM Start lock이 idempotency identity 중심이라 same target/different key 동시 mutation을 공통 차단하지 못할 수 있다.
2. Create VM final mutation 직전에 common replay/target guard가 충분히 명시적이지 않다.
3. DRS external dispatch와 UPID/task reference 저장 사이 crash window가 있다.
4. job/artifact 기록이 여러 transaction으로 나뉘고 immutable operation audit 의미가 없다.
5. `list_job_runs()` DB exception이 empty result로 변환돼 장애를 no-data처럼 보이게 한다.
6. 초기 기준선에서는 inventory env가 없을 때 fake fallback이 production에서도 실제 상태처럼 보일 수 있었다. 단계 3에서 product runtime fallback을 제거했다.
7. long-running operation의 durable runner/lease와 restart recovery가 없다.
8. `api/v1/router.py`, `App.jsx`, 주요 workflow/screen에 책임이 집중돼 있다.

### 검증 환경 기준선

- Python 3.13/Linux backend runtime·development lock과 Node 24/pnpm 10 frontend frozen install을 재현 가능한 기준선으로 마련했다.
- backend test와 frontend test/lint/build를 Docker에서 실행할 수 있다. backend formatter/lint/type-check 기준은 아직 없다.
- live Proxmox mutation은 실행하지 않았다.

## 3. 목표와 범위

- 목표: Proxmox를 actual-state/execution engine으로 유지하고 Gjallar를 day-2 운영의 verified intent·policy·approval·verification·evidence control plane으로 전환한다.
- 구조 목표: Domain-oriented Modular Monolith와 vertical slice, selective ports/adapters.
- 제품 목표: workload 중심 UI에서 `managed_api`, `guided_manual`, `observe_only` operation을 같은 lifecycle로 관리한다.
- 범위: canonical project docs, connection truth, domain/application boundary, first VM Start operation pilot, 이후 Workload Cockpit/Create VM/guided manual/Insights 전환.
- 비범위: big-bang rewrite, applied migration 수정, microservice/queue 선행 도입, generic shell/SSH executor, autonomous DRS, broad destructive action.

### 전체 인수 조건

- ADR의 authority split과 실행 mode가 코드·UI·문서에서 일치한다.
- product runtime은 `unconfigured`/`live`/`degraded`를 구분하고 fake/demo inventory를 표시하지 않는다.
- supported mutation은 intent, target, actor, idempotency, policy/approval, task/post-check, evidence를 추적한다.
- dispatch ambiguity는 중복 호출 대신 reconciliation으로 남는다.
- 기존 `/api/v1`과 canonical routes는 명시적 deprecation 전 동작한다.
- 각 slice는 focused/full regression, architecture review, 독립 rollback point를 가진다.
- 기존 DRS data/migration/history는 제거 대상 compatibility state로 동결하고 별도 제거 승인 전 보존한다. 신규 Common Operation·automatic recovery·기능 확장은 하지 않는다.

## 4. 아키텍처와 데이터 영향

- 목표 domain: Workloads, Operations, Policy/Approval, Evidence/Audit, Insights; support 영역 Access, Setup/Integration.
- backend direction: `interface → application → domain`; infrastructure는 port 구현이며 composition root에서 연결한다.
- frontend direction: `app → pages/features → entities/shared`; cross-feature private import를 금지한다.
- data ownership: [`Domain Map`](../domains/domain-map.md)의 logical ownership을 사용한다.
- initial pilot: existing table/API contract를 유지하고 schema migration을 하지 않는다.
- 후속 DB: operation/attempt/evidence/lock schema가 필요하면 table·column·backfill·transaction·roll-forward를 적은 별도 Plan 갱신과 승인을 받는다.
- external consistency: DB와 Proxmox를 하나의 transaction으로 묶지 않는다. intent/attempt 기록, dispatch, task ref, verification, evidence 순서를 상태기계로 관리한다.
- security: current RBAC/server-side actor를 유지하며 raw command, browser actor, secret-bearing parameter를 신뢰하지 않는다.

## 5. 선택지와 승인할 결정

### 아키텍처 선택

| 순위 | 선택지 | 적합한 이유 | 단점·비용 | 추천 여부 |
|---:|---|---|---|---|
| 1 | Domain-oriented Modular Monolith + vertical slice | 기존 배포·test·API를 보존하면서 core boundary를 바꿀 수 있음 | 전환 중 혼합 구조 | 추천 |
| 2 | 파일·service 분할만 수행 | 빠른 hotspot 완화 | ownership/operation inconsistency가 남음 | 단기 전술만 |
| 3 | full Clean rewrite 또는 microservice | 강한 물리 격리 | migration·운영·distributed consistency 비용 큼 | 비추천 |

### 문서 초기화 매니페스트

| 분류 | 정확한 범위 | 처리 제안 |
|---|---|---|
| 당시 보존 | `AGENTS.md`, `.agent-harness/**`, `.agents/skills/**`, `.gitignore`의 하네스 지원 변경 | 2026-08-24 Codex 프로젝트 설정 전면 재작성 결정으로 대체됨 |
| 새 source of truth | `project-docs/**` | 현재 코드 기준선과 목표/ADR/Plan을 분리해 재작성 |
| 재작성 | `README.md`, `backend/README.md`, `frontend/README.md` | 설치·실행·검증과 `project-docs` 진입점만 간결히 유지 |
| 흡수 후 삭제 | `docs/**`의 product, current, architecture, ko mirror, engineering, goal, archive PRD/feature/roadmap/status | 새 명세·ADR·API·DB·flow에 durable 내용만 흡수하고 제거 |
| 이동 보존 | `docs/operations/*live-smoke*.md`, `docs/operations/drs-explicit-test-candidate-prep-2026-06-03.md`, `docs/archive/operations/**` | `project-docs/evidence/legacy-live-smoke/`로 옮기고 active 명세가 아닌 historical evidence로 표시 |
| 재작성 후 교체 | `docs/operations/runbook.md` | current runtime 사실을 흡수해 `project-docs/operations/runbook.md`로 교체 |
| 보존·비권위 | `artifacts/rewrite-baseline/**` | 삭제하지 않고 historical raw evidence로만 유지; active docs에서 일반 진입점으로 링크하지 않음 |
| 절대 보존 | source, tests, `backend/alembic/versions/**` | 문서 reset 대상이 아님; applied migration은 수정·삭제 금지 |

2026-08-24 사용자의 최신 결정에 따라 위 하네스 보존 항목은 대체되었다. 범용 `.agent-harness/`, 일회성 도입 스킬, custom agent 설정은 제거하고 `AGENTS.md`, 최소 `.codex/config.toml`, 반복 가치가 있는 세 프로젝트 스킬만 유지한다. 이는 이 Plan의 제품 전환 범위나 소스 코드·테스트·migration 보존 결정을 변경하지 않는다.

권장안은 raw live-smoke evidence와 `artifacts/rewrite-baseline/**`를 보존하고 나머지 기존 `docs/**`를 제거하는 것이다. 전체 evidence까지 삭제하고 Git history에만 의존하려면 사용자의 별도 명시가 필요하다.

### 사용자 승인 결정

1. ADR-001의 Proxmox/Gjallar authority split과 3개 execution mode.
2. ADR-002의 modular monolith, domain ownership과 VM Start pilot.
3. production의 silent fake fallback 금지. 2026-07-20 후속 결정으로 product demo mode도 제거하고 fake adapter는 test fixture로만 격리.
4. guided manual을 allowlisted instruction + external execution + API verification으로 제한.
5. 기존 `viewer/operator/admin` 유지; separate approver는 후속 결정.
6. application-level append-only/checksum audit를 1차 목표로 하고 external WORM은 비범위.
7. existing `/api/v1`을 compatibility facade로 유지하는 additive migration.
8. 위 문서 초기화 매니페스트, 특히 live evidence와 `artifacts/` 보존 여부.
9. 단계 9는 additive Insights aggregate와 primary navigation을 추가하고 기존 DRS API/UI/data/execution을 제거 전 compatibility surface로 보존했다. 이 보존은 장기 유지 결정이 아니며 후속 단계는 `ADR-006`의 단계적 폐기다.

- 사용자 결정: `추천안 승인 — 새 방향 우선, 기존 docs 제거, live-smoke evidence와 artifacts 보존, compatibility facade 기반 점진 전환`
- 2026-07-23 방향 정정: `DRS maintenance는 유지·확장 대상이 아니라 제거 대상이며 neutral Placement/Capacity만 Insights/Monitoring에 유지한다.`
- 승인일: `2026-07-20`

## 6. 구현 단계

각 단계는 독립 diff와 verification을 가진다. 이전 단계가 완료됐다는 이유로 다음 단계의 DB·security·external dependency 결정까지 자동 승인된 것으로 간주하지 않는다.

| 단계 | 결과 | 변경 책임·예상 파일 | 검증 | 복구 지점 |
|---:|---|---|---|---|
| 0 | 제품/architecture/문서 reset 승인 | `project-docs/**`, README, 기존 `docs/**` 매니페스트 | 문서 대조, 링크/dirty change 흡수 확인 | code·기존 docs 삭제 전 중단 |
| 1 | 재현 가능한 baseline과 behavior freeze | dependency bootstrap 결정, existing contract tests, 핵심 failure characterization | backend/frontend full suite, lint/build, `git diff --check` | production code 미변경 |
| 2 | mutation safety gap 안정화 | VM Start target lock, Create replay guard, DRS dispatch/task-ref recovery, jobs DB failure semantics | concurrency/replay/crash-window/error contract tests | workflow별 작은 revert; schema 없음 |
| 3 | Setup/Integration connection truth + read slice | `unconfigured`/`live`/`degraded`, product fake 제거, freshness DTO, workload read application boundary | inventory/auth/API/frontend focused + full suite | live adapter와 기존 endpoint facade 유지 |
| 4 | Verified VM Start architecture pilot | Operations use case, Workloads query port, Proxmox mutation port, evidence adapter; existing endpoint facade | ack/precheck/replay/same-target concurrency/task/post-check/actor tests | old `run_vm_start` facade; schema 없음 |
| 5 | pilot 독립 평가와 operation persistence 결정 | architecture diff, transaction/evidence gaps, DB design·Plan 갱신 | `$quality-review`, PostgreSQL/Alembic tests | migration 전 중단 가능 |
| 6 | Workload Cockpit + standardized operation UI | backend workload/operation query, frontend feature boundaries와 timeline | API/frontend/navigation/a11y manual check, full suite | existing screen/routes 유지 |
| 7 | guided manual 첫 action | allowlisted `qm` template, expiry, attestation, API after-state verification | injection/secret/unsupported parameter/expiry/reconciliation tests | feature flag/allowlist 제거; no raw executor |
| 8 | Create VM operation 통합 | current draft/preflight/plan/approval/create를 common operation/evidence와 workload linkage로 전환 | Create VM contracts, idempotency, task/post-check, frontend flow | existing `/vm-create/*` facade 유지 |
| 9 | Insights 제품화와 DRS 중심성 제거 | risk/readiness/capacity/placement insight, navigation 변경; DRS를 제거 전 compatibility로 격리 | insight evidence/freshness, route/API regression | 이 단계에서는 DRS data/API 삭제 없음 |
| 10 | durable recovery와 action 확장 | 승인된 runner/lease/resume/reconcile, shutdown/reboot 등 action별 safety slice | restart/failover/concurrency/live smoke 승인 | action·runtime별 별도 rollback/roll-forward |
| 11 | DRS maintenance 단계적 폐기 | consumer·history·retention 조사, Insights/Monitoring replacement, UI/API deprecation, 마지막 forward data migration | boundary/API/frontend/PostgreSQL contract; DRS live mutation 없음 | 상세 high-risk Plan 승인 전 contract/data 변경 없음 |

### 단계별 추가 승인 gate

- 단계 1의 dependency download/lock 정책
- 단계 2의 public error semantics가 바뀌는 경우
- 단계 5 이후 모든 DB schema/data ownership/transaction migration
- 단계 7의 최초 `qm` allowlist action과 exact parameters
- 단계 11의 DRS API/UI deprecation·제거, history retention과 data migration
- 단계 10의 worker/queue/scheduler/new runtime dependency와 destructive action
- 모든 live Proxmox mutation/smoke target

## 7. 성공·실패·데이터 흐름

### 목표 성공 흐름

1. trusted actor와 operation intent/idempotency를 저장한다.
2. fresh Proxmox observation과 stable target identity/capability를 확인한다.
3. versioned policy를 평가하고 exact plan/evidence digest를 만든다.
4. approval과 acknowledgement를 확인한다.
5. final pre-check와 target lock을 획득한다.
6. dispatch attempt를 저장한 후 API를 한 번 호출하거나 manual bundle을 발급한다.
7. task reference 또는 operator attestation을 operation에 연결한다.
8. direct after-state/fingerprint를 검증한다.
9. append-only evidence와 current projection을 기록하고 lock을 해제한다.
10. 필요한 evidence가 저장된 뒤에만 `succeeded`가 된다.

### 보존할 실패 의미

- dispatch 전 validation/RBAC/policy/pre-check: `blocked`, side effect 없음.
- approval reject/expire/plan drift: `rejected`/`expired`, side effect 없음.
- explicit Proxmox reject와 no side effect: `failed`.
- POST timeout, missing UPID, crash-after-dispatch, task unknown: `needs_reconciliation`, 자동 mutation retry 금지.
- task OK/post-check mismatch: `needs_reconciliation`.
- manual attestation만 존재: `awaiting_verification`.
- evidence 저장 실패: success 공표 금지, 복구 상태 유지.

### 멱등성·동시성·보상

- same idempotency key/same intent는 existing operation을 반환한다.
- same key/different payload 또는 digest는 conflict다.
- different key/same target의 충돌 action도 target lock으로 차단한다.
- external effect는 code rollback만으로 보상하지 않는다. stored task/evidence와 actual state로 reconcile한다.
- automatic inverse action은 각 action의 별도 승인 없이는 도입하지 않는다.

## 8. 테스트와 검증 계획

### Baseline

- Backend full: `pnpm run test:backend`
- Frontend full: `pnpm run test:frontend`
- Frontend lint/build: `pnpm run lint:frontend`, `pnpm run build:frontend`
- 공통 검증 진입점: `pnpm run verify`
- 기준 container 검증: `pnpm run verify:container`
- Diff: `git diff --check`
- Container: 필요 단계에서 `docker build -t gjallar:local .`

### High-signal suites

- Auth/Admin: auth, admin user, bootstrap contract tests.
- Inventory/API: API shape, inventory, jobs/risks contract tests.
- VM Start: ack, idempotency replay, same-target concurrency, task failure, post-check failure, actor evidence.
- Create VM: draft/preflight/plan/approval, duplicate/replay, native create, task/post-check.
- DRS: identity, policy, approval binding, operation lock, dispatch crash window, reconciliation.
- DB: Alembic chain, PostgreSQL-vs-test schema drift, transaction failure.
- Guided manual: template allowlist, parameter validation, command injection, secret redaction, expiry, attestation, API verification.
- Frontend: auth, navigation, API client, workload/operation timeline, Create VM, DRS/Insights compatibility.

### Live 확인

- 기본 architecture refactor는 fake client와 contract test로 검증한다.
- live Proxmox smoke는 exact cluster/node/VMID/action/side effect/rollback을 제시하고 매번 사용자 승인을 받은 뒤 수행한다.
- live result는 historical evidence로 보존하되 secret과 raw credential을 기록하지 않는다.

## 9. 문서 영향

- Project Specification: approved product scope와 operation invariant의 source of truth.
- Architecture/ADR: current 구현과 target decision을 구분하고 slice 구현 후 실제 상태만 갱신한다.
- Domain/Flow: logical ownership과 operation lifecycle이 바뀔 때 갱신한다.
- API: current compatibility와 신규 operation contract를 별도 문서로 관리한다.
- Database: current schema와 target ownership을 구분하고 migration 승인 시 상세 forward plan을 추가한다.
- Operations: runtime setup, connection mode, migration, smoke/recovery만 runbook에 둔다.
- 일반 작업 이력과 완료 goal은 새 문서로 축적하지 않고 Git/PR이 담당한다.

## 10. 복구와 위험 완화

- 주요 위험: big-bang 이동, behavior drift, duplicate mutation, target lock 누락, task-ref crash gap, fake/live 혼동, audit 손실, half-migrated frontend route/import.
- 예방: characterization test, compatibility facade, schema-free pilot, target-level concurrency test, explicit mode, slice별 independent review.
- code rollback: 기존 endpoint/public function을 facade로 유지하고 migrated wiring만 이전 implementation으로 되돌릴 수 있게 한다.
- data roll-forward: applied migration을 rollback-edit하지 않고 additive correction을 사용한다.
- external effect: code rollback 전 stored task/evidence와 actual state를 확인하고 reconcile한다.
- 문서 삭제: 단계 0에서 매니페스트에 따라 `docs/`를 제거하고 raw live evidence를 checksum과 함께 보존했다.

### 중단 기준

- role/ack/fresh identity/policy/approval 전에 Proxmox mutation port가 호출된다.
- 같은 intent 또는 같은 target에 의도하지 않은 second mutation이 발생한다.
- ambiguous dispatch가 `failed`/`succeeded`로 축소되거나 자동 fallback한다.
- actor, secret redaction, response/error, job/artifact compatibility가 설명 없이 바뀐다.
- external network call 전체가 long DB transaction에 포함된다.
- schema/data ownership/new dependency가 승인된 상세 없이 필요해진다.
- non-live 상태가 fake inventory나 실행 가능한 상태로 축소된다.
- focused 또는 full regression test 실패를 숨기고 다음 slice로 진행한다.

## 11. 구현 후 대조

### 단계 0: 문서 초기화

- 계획과 달라진 부분: 기존 `docs/ko` 존재를 강제하던 cleanup contract test를 `project-docs` 필수 파일·링크·legacy `docs/` 부재 검증으로 교체했다.
- 달라진 이유: 문서 directory만 삭제하면 기존 test가 의도적으로 실패하므로 새 하네스 계약을 executable guard로 유지할 필요가 있었다.
- 검증 결과: `docs/` 부재 확인, active markdown 상대 링크 확인, legacy cleanup 10개 함수를 현재 system Python으로 직접 실행해 통과, `git diff --check` 통과.
- 미실행: repository pytest suite는 현재 Python 환경에 pytest가 없고 `backend/venv`도 없어 실행하지 못했다. frontend lint/test/build도 dependency baseline 복구 전 미실행이다.
- 갱신한 현재 상태 문서: Project Profile, Specification, Architecture, ADR 2개, Domain Map, Operation Flow, API, Database, Operations Runbook, root/backend/frontend README.
- 보존: live-smoke 원본 6개는 이동 전후 SHA-256을 대조해 `project-docs/evidence/legacy-live-smoke/`에 보존했고 `artifacts/rewrite-baseline/`은 변경하지 않았다.
- 남은 위험: dependency/test baseline 복구, 이후 mutation safety slice의 상세 검증.

### 단계 1: 재현 가능한 baseline과 behavior freeze

- Python `3.13`, Node.js `24`, pnpm `10.34.5`를 local/container 기준으로 고정하고 root verification script를 정리했다.
- frontend frozen lock과 Python 3.13/Linux runtime·development lock을 마련했다. Dockerfile에 frontend test/lint/build와 backend-test stage를 추가했다.
- dependency/container contract test와 test 전용 target-lock 격리를 추가했다.
- 검증 결과: canonical Python 3.13 container backend 전체 `352 passed`; Node 24/pnpm 10에서 frontend test 14개, lint, build와 production image build 통과.

### 단계 2: mutation safety gap 안정화

- VM Start: same-key intent 충돌을 차단하고, 한 configured cluster의 VMID target lock을 mutation 전 획득한다. timeout·missing UPID·task unknown·post-check mismatch는 `needs_reconciliation`과 retained lock으로 보존하며 자동 재호출하지 않는다.
- Create VM: completed same-intent replay, same-key different-intent conflict, cluster-wide VMID owner guard와 shared target lock을 추가했다. 명확한 side-effect-free 거절만 `failed`로 종료하고 partial/unknown 결과는 `apply_failed` 또는 `needs_reconciliation`로 보존한다.
- DRS: DB lock 획득 후 Proxmox POST 전에 durable `dispatch_attempt.state=prepared`를 저장하고, UPID 수락을 `accepted`로 기록한다. prepared/no-UPID 재진입은 second mutation 없이 reconciliation-required로 전환하며 read-only reconcile만 허용한다.
- schema migration과 새 운영 dependency는 추가하지 않았다. DRS는 기존 row/evidence column을, Create/Start는 local file lock을 사용했다.
- 계획과 달라진 부분: `list_job_runs()` DB exception의 공개 error semantics 변경은 단계 2 승인 gate에 해당해 구현하지 않았다. 별도 계약 결정 후 처리한다.
- 현재 제한: file lock은 single-container이고 cluster identity를 명시적으로 저장하지 않는다. DRS DB lock과도 통합되지 않았으며 retained lock의 operator API가 없다.
- 검증 결과: canonical Python 3.13 container backend 전체 `352 passed`; DRS 전체 87개 및 VM Start/Create focused suite 통과. Node 24/pnpm 10 frontend test 14개, lint, build와 production image build도 통과했다. live Proxmox mutation은 실행하지 않았다.

### 단계 3: Connection Truth 구현 결과

- 사용자 결정: product runtime에 demo/mock inventory를 제공하지 않고 미연결 운영 화면을 숨긴다.
- 상태 계약: 필수 설정 누락·invalid mode는 `unconfigured`, authoritative snapshot 성공은 `live`, configured connection 실패는 `degraded`다.
- API 범위: additive redacted connection status, live inventory meta의 observed time/freshness, non-live inventory-dependent endpoint의 `503`.
- 구조 범위: Setup/Integration connection status와 Workloads inventory query를 application boundary로 분리하고 기존 endpoint를 facade로 유지한다.
- UI 범위: Dashboard/VM/Create/Network/DRS는 live일 때만 실제 화면을 표시한다. Jobs/Risks/Account/Admin은 non-live에서도 유지한다.
- 테스트 전략: `FakeProxmoxInventoryAdapter`는 environment runtime mode가 아니라 test fixture injection으로만 사용한다.
- 비범위: DB schema, stale snapshot persistence, in-app credential 저장, multi-cluster, VM operation 구조 변경, `qm` 기능.
- 복구: 새 status/query wiring과 UI gate를 제거하면 기존 live adapter와 endpoint path로 돌아갈 수 있다. fake runtime fallback은 안전 요구 때문에 복구 대상으로 삼지 않는다.
- 구현: environment runtime은 `live`와 live-only `auto`만 허용하며 설정 누락·invalid mode는 non-data unavailable adapter가 된다. `setup_integration` status와 `workloads` query boundary, additive connection endpoint와 non-live `503`을 추가했다.
- UI: connection 상태를 로그인 후 먼저 조회하고 Overview/VM/Create/Network/DRS route를 live-only로 gate한다. non-live navigation에서는 VM Instances와 DRS를 숨기며 Jobs/Risks/Account/Admin은 유지한다.
- capability 경계: `live`는 authoritative inventory read 성공만 뜻하며 mutation permission을 추론하지 않는다. 기존 RBAC·approval·Proxmox response gate는 유지한다.
- 품질 검토: inventory 성공을 mutation capability로 과대 표시하던 초기 필드를 제거했다. 최종 재검토에서 추가 Critical/High/Medium finding은 없었다.
- 검증 결과: canonical Python 3.13 container backend 전체 `355 passed`; Node 24/pnpm 10 frontend test 15개, lint, build와 production image build 통과. `git diff --check` 통과. DB migration과 live Proxmox mutation은 실행하지 않았다.

### 단계 4: Verified VM Start Architecture Pilot 승인 범위

- 목표: 기존 VM Start endpoint와 안전 동작을 유지하면서 `API facade → Operations application use case → explicit ports → compatibility workflow adapter` 의존 방향을 만든다.
- domain contract: VM Start command, target, expected observation과 stable intent 생성 규칙을 FastAPI·SQLAlchemy·Proxmox concrete client에 의존하지 않는 모듈로 분리한다.
- application contract: use case는 Workloads inventory, Proxmox mutation, Jobs projection, Evidence artifact, target/request lock port만 받는다.
- compatibility: `/api/v1/nodes/{node_id}/vms/{vmid}/actions/start`, success/error payload, `run_vm_start` Python facade, job/artifact 형태와 기존 patch seam을 유지한다.
- adapter: 현재 `job_runs`, JSON artifact, local file lock, `ProxmoxMutationClient`를 port 구현으로 감싸고 기존 workflow body를 compatibility adapter로 연결한다.
- 테스트: domain/application fake-port test와 기존 ack, actor, replay, intent conflict, same-target lock, task failure, ambiguity, post-check, artifact failure contract를 함께 실행한다.
- 비범위: DB schema·transaction 의미 변경, 신규 operation endpoint, frontend 변경, Create VM/DRS 전환, durable worker, shared lock, `qm`, live mutation.
- 복구: router가 유지된 `run_vm_start` facade를 계속 사용하므로 새 application composition을 제거하고 기존 workflow 진입으로 되돌릴 수 있다. persistent data migration은 없다.
- 중단 기준: port 호출 전 gate가 약화되거나, second mutation·error/status/job/artifact contract drift가 발생하거나, concrete FastAPI/DB/Proxmox import가 domain/application 모듈에 유입된다.

### 단계 4: 구현 결과

- `backend/app/operations/vm_start/`에 infrastructure-free command·stable intent 규칙, application use case, Workloads/Mutation/Jobs/Evidence/Lock port를 추가했다.
- 기존 `/api/v1/nodes/{node_id}/vms/{vmid}/actions/start`와 `run_vm_start`를 compatibility facade로 유지하고 현재 DB/job/artifact/file-lock/Proxmox 구현을 adapter로 조립했다.
- 기존 verified workflow body는 behavior drift를 피하기 위해 `vm_actions/start.py`의 compatibility adapter에 남겼다. 이번 단계는 완전한 workflow 분해나 공통 Operation aggregate 구현이 아니다.
- DB schema, public API·error·job/artifact 계약, frontend, Create VM/DRS, external dependency는 변경하지 않았다.
- architecture test는 domain/application 모듈의 FastAPI·SQLAlchemy·DB·Jobs·Proxmox concrete import 금지와 facade composition을 검증한다.
- 품질 검토에서 application port가 local `Path`/`run_dir`를 노출하는 경계 누수 1건을 발견해, logical `job_id`만 받고 경로 계산은 current adapter 내부에서 수행하도록 수정했다. 재검토 후 추가 Critical/High/Medium finding은 없었다.
- 검증 결과: VM Start/application/API auth focused suite `50 passed`; canonical Python 3.13 container backend 전체 `362 passed`; `git diff --check` 통과. DB migration과 live Proxmox mutation은 실행하지 않았다.
- 복구 지점: persistent migration이 없고 router는 동일 `run_vm_start` symbol을 사용하므로 application composition과 port adapter wiring만 제거해 이전 진입 구조로 복구할 수 있다.
- 후속 결과: 단계 5에서 공통 Operation projection + append-only event를 선택했고 별도 상세 Plan 승인 후 additive migration으로 구현했다.

### 단계 5: Operation Persistence 결정·구현 결과

- 독립 검토 결과 기존 `job_runs`/`job_artifacts`만 확장하면 mutable projection과 immutable evidence가 섞이므로 공통 persistence가 필요하다고 판단했다.
- 사용자 승인 상세 Plan [`Operations Backend Core와 Guided qm`](2026-07-20-operations-backend-core-and-guided-qm.md)에 따라 migration `20260720_0026`으로 `operations`, `operation_events`를 additive하게 추가했다.
- common repository는 projection transition과 checksum-linked event append를 한 transaction으로 기록한다. 기존 table/API/Jobs consumer는 유지한다.
- VM Start workflow를 Operations 내부로 옮기고 common operation/event와 기존 job/artifact를 dual record한다.

### 단계 7: 첫 Guided Manual Backend 결과

- 사용자 승인 first action은 정확히 `qm unlock <vmid>`다. backend shell/SSH executor, arbitrary command input과 API→CLI fallback은 추가하지 않았다.
- `operator` 이상만 typed plan을 만들 수 있고, server가 5분 instruction bundle과 `plan_digest`를 생성한다.
- target lock, Proxmox node `Sys.Audit`, active task 부재, allowlisted config lock을 확인한 뒤에만 bundle을 발급한다.
- trusted actor attestation 뒤에도 성공 처리하지 않고 Proxmox API에서 config lock·active task after-state를 검증한다. 불명·불일치·late execution·lock loss는 reconciliation으로 남긴다.
- additive API는 plan, operation query, attestation, verification 네 endpoint로 시작했고, 단계 6에서 공통 목록 query와 frontend consumer를 완성했다.
- 품질 검토에서 expiry/late-attestation lock release, persisted `verifying` resume, attestation 없는 expiry reconciliation verification 문제를 수정했다.
- 검증 결과: Guided focused `77 passed`, canonical Python 3.13 container backend 전체 `425 passed`, `git diff --check` 통과. live Proxmox command/API smoke와 frontend 검증은 실행하지 않았다.

### 단계 6: Workload Cockpit·Operations UI 결과

- frontend root를 `app → pages/features → entities/shared` 방향으로 분리했다. root `App.jsx`는 compatibility entrypoint이고 app shell/navigation/session, Dashboard/Auth/Account page, Workload·Operations page/feature가 물리적으로 분리됐다.
- `/instances`는 Workload Cockpit으로 유지하며 VM row에서 typed Guided `qm unlock` plan으로 node/VMID context를 전달한다. `/operations` 목록, `/operations/:operationId` 상세 evidence timeline, Guided plan·attestation·verification UI를 추가했다.
- `GET /api/v1/operations`는 status/type/limit filter와 최신 projection summary를 제공한다. 상세 query는 공통 Operations application boundary가 projection과 events를 조합하고 Guided operation에만 instruction evidence를 붙인다.
- viewer는 목록·상세만 조회하고 Guided mutation control은 `operator+`와 live Proxmox connection을 함께 요구한다. Browser는 command field를 보내지 않으며 server bundle만 표시한다. 만료·reconciliation instruction은 신규 실행을 금지하고 late evidence만 기록하도록 구분한다.
- 기존 `/instances`, `/operations/jobs`, `/operations/risks`와 alias route, legacy screen/API consumer는 compatibility adapter로 유지했다. DB schema, dependency, Proxmox mutation은 변경하지 않았다.
- 품질 검토에서 expired instruction 신규 실행 오인과 managed operation detail의 Guided 전용 facade 결합을 발견해 수정했다.
- 검증 결과: local Python 3.14 backend 전체 `436 passed`, local Node 24 frontend test 16개·ESLint·Vite production build 통과. container build, browser 수동 a11y/navigation, live Proxmox 실행은 수행하지 않았다.

### 단계 8: Create VM Common Operation 통합 결과

- 사용자 승인 상세 Plan [`Create VM Common Operation 통합`](2026-07-21-create-vm-common-operation-integration.md)에 따라 migration 없이 기존 `/vm-create/*`, `vm_create_requests`, `vm_instances`, job/artifact 계약을 유지했다.
- `operations/vm_create`가 stable redacted intent와 plan·approval·preview·dispatch·running·verifying·success/reconciliation event mapping을 소유한다. 신규 plan부터 `operation_id=job_id`인 `vm_create` projection/event를 compatibility record와 dual record한다.
- API response에 additive operation link를 제공하고 frontend Create VM flow가 이를 보존해 final create 직후 `/operations/{operationId}`로 이동한다. operation ID가 없으면 기존 Jobs route로 fallback한다.
- 명확한 side-effect-free 실패만 common `failed`로 종료하며 partial/unknown 결과와 외부 effect 뒤 persistence failure는 success로 축소하지 않고 lock을 유지한다. completed replay는 workload linkage가 확인될 때만 common success로 채택한다.
- 독립 검토에서 failed retry 공개 오류 drift, same operation ID/different scope repository 충돌, dispatch 전 common persistence failure 검증 누락을 발견해 오류 mapping·repository identity 비교·fault-injection contract test를 보강했다.
- 검증 결과: Create VM·Operations focused `32 passed`; canonical Python 3.13 container backend 전체 `443 passed`; canonical Node 24/pnpm 10 frontend test 16개·ESLint·Vite production build와 production image build 통과; `git diff --check` 통과. DB migration, browser 수동 확인, live Proxmox mutation은 수행하지 않았다.

### 단계 9: Insights 제품화와 DRS Maintenance 전환 결과

- 사용자 승인 상세 Plan [`Insights 제품화와 DRS Maintenance 전환`](2026-07-21-insights-productization-and-drs-maintenance.md)에 따라 `risk`, `readiness`, `capacity`, `placement`를 공통 source·observed time·freshness·rule version·redacted evidence 계약으로 조회하는 `GET /api/v1/insights`를 추가했다.
- `backend/app/insights/`는 command port 없이 read application과 pure rule을 소유한다. stored job risk와 current Workloads observation을 독립 수집하고 기존 DRS advisor를 placement compatibility adapter로 재사용한다.
- 기존 Jobs/Risks의 DB exception → empty list 의미는 유지하되 Insights는 strict read로 장애를 risk `unavailable`로 드러낸다. non-live inventory에서는 stored risk만 유지하고 readiness/capacity/placement는 `unavailable`이며 fake/stale fallback이 없다.
- frontend primary navigation을 Insights로 전환하고 `/insights`와 category route를 추가했다. `/drs`, `/api/v1/drs/*`, DRS policy/approval/execution/data, `/operations/risks`, `/risks`는 유지하고 `/drs`를 maintenance compatibility surface로 표시한다.
- 2026-07-23 `ADR-006`으로 이 maintenance 보존은 제거 전 호환 단계임을 명확히 했다. DRS execution의 Common Operation 통합과 automatic recovery는 후속 범위가 아니며, 단계 11에서 consumer·retention을 확인한 뒤 UI/API/state를 제거한다.
- 독립 품질 검토에서 partial capacity metric과 unknown placement가 `ready`로 축소되는 문제, bounded finding의 total truncation 미표시를 발견해 보수적 unknown 판정과 `returned_finding_count`/`truncated` metadata로 수정했다.
- DB schema/migration, scheduler/cache/worker/dependency, Proxmox mutation은 추가하지 않았다. canonical Python 3.13 backend 전체 `457 passed`, canonical Node 24/pnpm 10 frontend test 17개·ESLint·Vite production build와 production image build가 통과했다.

### 단계 10-A: Durable Operation Recovery Foundation 결과

- 사용자 승인 상세 Plan [`Durable Operation Recovery Foundation`](2026-07-21-durable-operation-recovery-foundation.md)과 [`ADR-004`](../decisions/adr-004-postgresql-durable-operation-recovery.md)에 따라 `operation_locks`를 VM Start/Create VM/Guided `qm unlock`/DRS 공통 locator coordination으로 확장하고 `operation_recovery_items` lease/fencing schema를 추가했다.
- VM Start는 dispatch 전에 recovery item/foreground lease를 저장하고 task poll 중 heartbeat한다. opt-in FastAPI lifespan runner는 stored UPID task와 direct VM status를 GET으로만 재관찰하며 mutation POST를 재호출하지 않는다.
- recovery generation/token 검증, Operation event/projection, recovery status와 target lock release는 같은 PostgreSQL transaction으로 commit한다. terminal Jobs compatibility projection이 실패하면 durable lock을 유지하고 runner가 Proxmox 재관찰 없이 projection completion을 재시도한다.
- Operation detail과 UI는 private lease token 없이 recovery와 target lock 상태를 읽기 전용으로 제공한다. runtime flag 기본값은 disabled다.
- 실제 PostgreSQL 18.4 migration/partial unique/concurrent claim/timezone/fencing integration `1 passed`; local 및 canonical Python backend `475 passed, 1 skipped`; canonical Node frontend 17 tests·ESLint·Vite build와 production image build가 통과했다. live Proxmox mutation과 production enable은 수행하지 않았다.
- 단계 10-B는 별도 승인된 [`Graceful VM Shutdown과 Recovery Rollout`](2026-07-21-graceful-vm-shutdown-and-recovery-rollout.md) Plan으로 구현했다. exact target이 필요한 live shutdown smoke와 production flag 전환은 계속 run-specific gate다.

### 단계 10-B: Graceful VM Shutdown과 Recovery Rollout 결과

- additive `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/shutdown`과 `operations/vm_shutdown` vertical slice를 추가했다. running non-template exact target, operator role, acknowledgement, idempotency intent와 same-target durable/file lock을 dispatch 전에 검증한다.
- Proxmox 연동은 QEMU `status/shutdown` POST만 한 번 호출하며 hard `stop`, reboot, timeout fallback을 제공하지 않는다. task `stopped/OK`와 direct VM `stopped`가 모두 확인된 경우에만 success를 기록한다.
- `vm_shutdown_observation` handler는 stored UPID task와 current VM status를 GET으로만 재관찰한다. missing UPID, ambiguity, mismatch, lease loss와 compatibility projection 실패는 lock을 유지하고 reconciliation 또는 recovery retry로 남긴다.
- migration `20260721_0028`은 `operation_locks.operation_type`에 `vm_shutdown`만 additive하게 허용한다. PostgreSQL 18.4에서 upgrade/downgrade/roll-forward, cross-operation lock, claim/fencing과 새 process restart observation을 검증했다.
- Workload Cockpit은 running VM에 graceful shutdown 확인 UI를 표시하고 결과 Operation 상세로 이동한다. live Proxmox shutdown과 production recovery enable은 실행하지 않았다.
- canonical Python 3.13 backend 전체 `504 passed, 2 skipped`, PostgreSQL 18.4 integration `2 passed`, canonical Node frontend 17 tests·ESLint·Vite build와 production image build가 통과했다. 두 backend skip은 별도로 통과한 opt-in PostgreSQL tests다.
