# 구현 계획: Create VM Common Operation 통합

- 상태: `IMPLEMENTED`
- 날짜: `2026-07-21`
- 관련 요구사항: [`FR-003`, `FR-004`, `FR-007`, `FR-008`, `FR-009`, `FR-012`](../specifications/project-specification.md)
- 관련 ADR: [`ADR-001`](../decisions/adr-001-proxmox-gjallar-authority-boundary.md), [`ADR-002`](../decisions/adr-002-modular-monolith-domain-boundaries.md)
- 상위 Plan: [`Verified Operations Control Plane 전환` 단계 8](2026-07-20-verified-operations-control-plane-transition.md)
- 승인자: `사용자`

2026-07-21 사용자는 migration 없이 기존 API와 compatibility projection을 유지하며 Create VM을 공통 Operation에 통합하는 추천 범위로 단계 8 진행을 승인했다.

## 1. 위험도

- 분류: `HIGH`
- 판단 근거: 실제 Proxmox mutation, exact-plan approval, 멱등성, target lock, 외부 task와 post-check, 서로 분리된 DB transaction과 공통 operation/evidence 이중 기록을 변경한다.
- 실패 영향: 동일 VMID 중복 생성, 승인되지 않은 plan 실행, partial/unknown 결과의 잘못된 성공 처리, operation과 기존 job/request projection 불일치, target lock 조기 해제, 기존 `/api/v1/vm-create/*`와 frontend 회귀가 가능하다.
- 되돌리기 어려운 부분: live Proxmox effect는 code rollback으로 취소되지 않는다. 적용된 migration이나 기존 data를 변경하지 않고 compatibility facade와 dual record를 유지해 code rollback 가능성을 확보한다.

## 2. 확인한 현재 상태

- 현재 동작: Create VM은 `draft → preflight → plan → approve → preview → final acknowledgement → target lock → native clone/config/optional boot → task/post-check → request/job/artifact/workload linkage` 흐름을 제공한다.
- 관련 진입점과 호출 흐름:
  - HTTP orchestration: `backend/app/api/v1/router.py`의 `/vm-create/*` handler.
  - domain-like logic: `backend/app/vm_create/`의 draft, preflight, plan, approval, runner, evidence.
  - compatibility persistence: `vm_create_requests`, `vm_instances`, `job_runs`, `job_artifacts`와 `backend/app/db/vm_runtime.py`.
  - shared safety: `backend/app/operations/target_lock.py`의 `proxmox_vm/vmid:{vmid}` local target lock.
  - frontend: `CreateInstanceWizard`와 `createVmFlow`; final create 시작 시 `/operations/jobs?job=...`로 이동한다.
- 현재 안전장치:
  - 같은 job/same intent completed replay는 second mutation 없이 기존 결과를 반환한다.
  - 같은 job/different intent와 다른 request/same VMID active·reconciliation·completed 상태를 `409`로 차단한다.
  - 명확한 clone 거절만 lock을 해제하고 partial/unknown 결과는 `apply_failed` 또는 `needs_reconciliation`과 retained lock으로 보존한다.
  - trusted actor, approval artifact/checksum, final acknowledgement, task와 direct observed-after evidence를 기록한다.
- 공통 경계: `operations`/`operation_events`와 `SqlAlchemyOperationStore`가 managed operation 상태·scoped idempotency·checksum event를 이미 지원한다. VM Start와 Guided `qm unlock`이 이를 사용한다.
- 관련 테스트: Create VM API/approval/runner/evidence/idempotency 테스트, Operations domain/repository/query 테스트, frontend Create VM flow/source contract 테스트가 있다.
- 기준선: local Python 3.14에서 관련 backend 114개 테스트가 통과했다. 최초 root 직접 pytest는 import path 오류로 수집 실패했고 backend 작업 위치에서 재실행해 통과했다.
- 확인되지 않은 항목: live cluster의 task/after-state, browser 수동 navigation/a11y, multi-replica target coordination은 이번 구현에서 확인하지 않는다.

## 3. 목표와 범위

- 목표: Create VM의 exact plan부터 approval, dispatch, task/post-check, workload linkage까지 하나의 `vm_create` common Operation과 append-only event timeline으로 조회되게 한다.
- 범위:
  - `backend/app/operations/vm_create/`에 Create VM operation identity·intent·tracking 책임을 둔다.
  - plan에서 common Operation을 준비하고 approval·dispatch·result를 공통 상태와 event로 기록한다.
  - 기존 `vm_create_requests`, `vm_instances`, jobs/artifacts를 compatibility projection/evidence로 계속 기록한다.
  - `/api/v1/vm-create/*` response에 additive operation linkage를 제공한다.
  - 기존 `/api/v1/operations` 목록·상세가 `vm_create` projection/event를 그대로 조회한다.
  - frontend Create VM이 operation ID를 보존하고 final create 시 common operation 상세로 이동한다.
- 비범위:
  - DB schema/migration, table rename/backfill, repository 통합 transaction 재설계.
  - 기존 `/vm-create/*`, Jobs route, compatibility table 제거.
  - Create VM reconciliation command, durable runner/lease, shared multi-replica lock.
  - live Proxmox mutation/smoke, DRS common operation 통합, 별도 approver role.
- 인수 조건:
  - plan은 mutation 전에 trusted actor, target, stable intent, idempotency identity, exact review checksum을 common Operation에 기록한다.
  - approval 성공은 exact plan digest에 binding되고 실패·재시도는 mutation 없이 보수적으로 표현된다.
  - dispatch 전 `dispatching`, task/result 관찰 뒤 `running`/`verifying`, required evidence 저장 뒤에만 `succeeded`가 된다.
  - 명확한 side-effect-free 거절은 `failed`, partial/unknown 결과는 `needs_reconciliation`이며 target lock을 유지한다.
  - same job/same intent replay는 second mutation 없이 동일 operation과 기존 결과를 반환하고, 다른 intent는 conflict다.
  - 기존 API status/response/error shape는 additive field 외에 유지한다.
  - frontend는 final create 시작 후 `/operations/{operationId}`로 이동하며 fallback으로 기존 Jobs route를 유지한다.
- 유지할 기존 계약: `operator+`, connection gate, approval metadata, `proxmox_mutation_acknowledged`, success envelope, public error codes, current job/artifact 의미와 canonical routes.

## 4. 아키텍처와 데이터 영향

- 도메인·모듈: Operations가 Create VM operation lifecycle을 소유하고 Workloads의 `vm_instances` linkage와 Integration의 Proxmox runner를 조정한다. 기존 `app.vm_create`는 action-specific policy/runner compatibility 구현으로 유지한다.
- 책임과 의존성 방향: HTTP handler는 기존 facade를 유지하고 새 `operations.vm_create` tracking application에 위임한다. 새 module은 FastAPI에 의존하지 않고 common Operation port/domain을 사용한다.
- 데이터 소유권: `operations`가 canonical lifecycle projection, `operation_events`가 append-only timeline이다. `vm_create_requests`와 jobs/artifacts는 전환 중 compatibility projection/evidence, `vm_instances`는 Workloads linkage다.
- 트랜잭션·정합성: common projection/event 한 전이는 한 DB transaction이다. compatibility write와 Proxmox call은 각각 분리된다. 외부 effect 뒤 persistence 실패 시 success를 공표하거나 lock을 해제하지 않는다.
- API·DB·외부 시스템: 기존 schema와 endpoint를 유지하고 response에 operation linkage만 additive하게 추가한다. Proxmox 호출 순서와 runner contract는 바꾸지 않는다.
- 보안·권한: server-side trusted actor와 기존 `operator` dependency를 유지한다. operation payload/event는 redaction을 거치며 SSH public key 원문, token, session credential을 저장하지 않는다.

## 5. 선택지와 결정

| 순위 | 선택지 | 적합한 이유 | 단점·비용 | 추천 여부 |
|---:|---|---|---|---|
| 1 | 기존 schema·API를 유지하고 common Operation을 dual record | 승인된 vertical slice·compatibility 전략과 일치하고 rollback 가능 | 전환 기간 projection이 중복되고 transaction이 완전히 원자적이지 않음 | 추천·승인 |
| 2 | `vm_create_requests`를 즉시 폐기하고 common schema로 일괄 이전 | 최종 구조는 단순 | migration/backfill·consumer 전환·rollback 위험이 크고 별도 승인이 필요 | 비추천 |
| 3 | frontend 링크만 바꾸고 backend common Operation은 보류 | 변경량이 작음 | FR-003/007/008과 단계 8 목적을 충족하지 못함 | 비추천 |

- 사용자 결정: `1순위 승인 — migration 없이 기존 API·compatibility projection을 유지하며 common Operation을 dual record하고 frontend를 연결한다.`
- 승인일: `2026-07-21`

## 6. 구현 단계

| 단계 | 결과 | 변경 책임·예상 파일 | 검증 | 복구 지점 |
|---:|---|---|---|---|
| 1 | 현재 Create VM 계약과 common state mapping 고정 | Plan, backend characterization tests | 기존 focused 114 tests | production code 미변경 |
| 2 | Create VM operation identity·intent·tracking | `backend/app/operations/vm_create/**`, operations tests | domain/tracking fake-store tests | 새 module 제거 |
| 3 | HTTP compatibility facade dual record | `backend/app/api/v1/router.py`, Create VM contract tests | plan/approval/replay/conflict/failure/success tests | tracking 호출 제거; 기존 workflow 유지 |
| 4 | common operation query/timeline linkage | operation query/API tests | list/detail/event/redaction tests | additive response/link 제거 |
| 5 | frontend operation route 연결 | `createVmFlow`, `CreateInstanceWizard`, frontend tests | Create VM flow/source/navigation contract | 기존 Jobs route fallback |
| 6 | 전체 검증·독립 리뷰·문서 동기화 | tests, project-docs | backend/full, frontend test/lint/build, diff, quality review | 실패 단계 이후 진행 중단 |

## 7. 성공·실패·데이터 흐름

- 성공 흐름:
  1. plan이 `operation_id=job_id`, type `vm_create`, mode `managed_api`, target `proxmox_vm/vmid:{vmid}`와 stable intent/plan digest를 저장한다.
  2. exact approval validation 뒤 `approved`를 기록한다.
  3. existing request/target guard와 target lock 뒤 `dispatching`을 기록하고 Proxmox runner를 한 번 호출한다.
  4. task와 observed-after를 `running`/`verifying` evidence로 기록한다.
  5. compatibility request/job/artifact와 workload linkage 저장을 확인한 뒤 `succeeded`를 기록하고 lock을 해제한다.
- 실패 흐름:
  - plan red risk: `blocked`, 외부 호출 없음.
  - approval mismatch/ack 누락: 승인 대기 상태 또는 rejection evidence, 외부 호출 없음.
  - target/idempotency conflict: 기존 public `409`, 관련 operation evidence만 안전하게 추가.
  - 명확한 clone reject: `failed`, lock 해제 가능.
  - timeout/missing task/partial apply/post-check 불명: `needs_reconciliation`, 자동 mutation retry 금지, lock 유지.
  - operation/evidence persistence 실패: success 응답 금지, lock 유지, 실제 compatibility 상태와 external state를 후속 reconcile 대상으로 남김.
- 데이터 변환: 기존 row backfill이나 schema 변환 없음. 신규 호출부터 common Operation을 dual record한다.
- 재시도·멱등성·보상: same job/same plan은 기존 result/operation을 replay한다. same job/different plan은 conflict다. external effect를 자동 inverse action으로 보상하지 않는다.

## 8. 테스트와 검증 계획

- 단위 테스트: operation identity, stable redacted intent, plan digest, status/event mapping, replay와 invalid transition.
- 통합·계약 테스트: plan operation 생성, exact approval, success timeline, side-effect-free failure, reconciliation, same-key replay, different-intent conflict, target lock과 actor/redaction.
- 경계·실패 테스트: common persistence 실패 전 dispatch 금지, external effect 뒤 evidence failure에서 success/lock release 금지, completed compatibility replay의 operation linkage.
- Formatter·Lint·타입: backend 별도 formatter/lint/type 명령은 없음. frontend ESLint 실행.
- 빌드·수동 확인: backend focused/full, frontend test/build, `git diff --check`; browser 수동 확인과 live Proxmox mutation은 비범위로 보고한다.

## 9. 문서 영향

- Project Specification: 요구사항은 이미 승인됐으므로 실제 범위가 바뀌지 않으면 수정하지 않는다.
- Architecture·ADR: Architecture current state만 Create VM slice 구현 결과로 갱신한다. ADR 결정은 유지한다.
- Domain·Flow: 현재 구현 범위와 common lifecycle mapping을 갱신한다.
- API·Database: Create VM additive operation linkage, common projection dual record와 무-migration 상태를 갱신한다.
- Project Profile·상위 Plan: 진행 상태, 현재 아키텍처와 검증 기준선을 갱신한다.

## 10. 복구와 위험 완화

- 주요 위험: old/new projection drift, operation transition 실패 뒤 external effect, existing replay와 operation 상태 불일치, actor/secret leakage, frontend가 없는 operation route로 이동하는 회귀.
- 예방·관찰 방법: dispatch 전 common write, target lock retention, compatibility contract tests, redaction tests, additive API, operation fallback route, full regression.
- rollback 또는 roll-forward: schema가 없으므로 tracking wiring과 frontend link를 code rollback할 수 있다. 이미 기록된 operation/event는 삭제하지 않고 read-compatible historical evidence로 둔다. live effect는 actual state 확인 후 reconcile한다.
- 중단 기준:
  - exact plan/approval binding 전에 dispatch가 가능해짐.
  - common write 실패에도 Proxmox mutation 또는 success 응답이 발생함.
  - ambiguous result가 `failed`/`succeeded`로 축소되거나 lock이 해제됨.
  - existing same-intent replay가 second mutation을 호출함.
  - 기존 API/error/RBAC/frontend route 회귀 또는 secret-bearing event가 발견됨.
  - schema/new runtime dependency가 필요해짐.

## 11. 구현 후 대조

- 계획과 달라진 부분: operation tracking을 action-specific runner 전체의 새 use case로 옮기지 않고, 기존 HTTP compatibility orchestration이 `operations/vm_create` tracking facade와 기존 runner를 조립하도록 유지했다. completed compatibility replay는 저장된 workload linkage가 없으면 common `succeeded`로 채택하지 않고 guard event와 non-terminal 상태를 유지한다.
- 달라진 이유: 기존 `/vm-create/*`, monkeypatch seam, request/job/artifact transaction과 runner ordering을 보존하면서 schema 없이 common lifecycle을 도입해야 했다. 외부 성공 evidence만 있고 Workloads linkage가 사라진 경우를 성공으로 재공표하면 FR-008의 검증 조건을 위반하므로 보수적으로 처리했다.
- 최종 검증 결과:
  - backend Create VM·Operations focused suite: `32 passed`.
  - canonical Python 3.13 container backend 전체: `443 passed`.
  - canonical Node 24/pnpm 10: frontend test 16개, ESLint, Vite production build 통과.
  - production image: `docker build -t gjallar:local .` 통과.
  - `git diff --check` 통과.
  - browser 수동 navigation/a11y와 live Proxmox mutation은 비범위로 실행하지 않았다.
- 품질 검토: failed operation 재시도의 기존 public error code 보존, same operation ID/different scope repository 충돌의 domain conflict 변환, common dispatch persistence 실패 시 Proxmox 미호출을 보강했다. 수정 후 Critical/High/Medium 미해결 finding은 없다.
- 갱신한 현재 상태 문서: Project Profile, Architecture Overview, Domain Map, Verified Operation Lifecycle, current API v1, current Schema/Ownership, 상위 전환 Plan과 이 상세 Plan.
- 남은 위험: common operation/event와 compatibility request/workload/job/artifact는 하나의 원자적 transaction이 아니다. 외부 effect 뒤 persistence 실패는 retained lock과 non-success 상태로 보존되지만 자동 reconciliation worker와 Create VM 전용 reconcile API가 없다. local target lock은 single-container이며 기존 row backfill, DRS 통합, live cluster 확인은 수행하지 않았다.
