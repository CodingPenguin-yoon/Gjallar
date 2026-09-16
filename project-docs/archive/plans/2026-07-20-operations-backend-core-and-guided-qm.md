# 구현 계획: Operations Backend Core와 Guided `qm`

> 종료된 계획의 당시 조사·승인·검증 기록이다. 현재 구현 지시가 아니며 후속 방향은 [계획 인덱스](../../plans/README.md), 현재 기준은 [문서 안내](../../README.md)를 따른다.

- 상태: `IMPLEMENTED`
- 날짜: `2026-07-20`
- 관련 요구사항: [`Project Specification`](../../specifications/project-specification.md) FR-003, FR-005, FR-008, FR-009
- 관련 ADR: [`ADR-001`](../../decisions/adr-001-proxmox-gjallar-authority-boundary.md), [`ADR-002`](../../decisions/adr-002-modular-monolith-domain-boundaries.md)
- 상위 Plan: [`Verified Operations Control Plane 전환`](2026-07-20-verified-operations-control-plane-transition.md) 단계 5·7
- 승인자: `사용자`
- 진행 상태: `구현·품질 검토·문서 동기화 완료`
- 승인 문장: `이 승인은 additive Operations projection/event와 Guided qm unlock 구현을 의미하며, 기존 Jobs/Artifacts/DRS 제거, raw shell 실행 또는 automatic fallback을 의미하지 않는다.`

## 1. 위험도

- 분류: `HIGH`
- 판단 근거: Operations와 Evidence의 데이터 소유권, DB schema·transaction, VM Start 외부 mutation 실패 의미, Guided Manual 보안 경계를 함께 다룬다.
- 실패 영향: operation 이력 유실·변조, 같은 target 중복 mutation, 실제 effect와 local status 불일치, arbitrary command 노출, 기존 Jobs/API regression.
- 되돌리기 어려운 부분: 적용된 Alembic migration과 저장된 operation/event data. 기존 migration은 수정하지 않고 additive forward migration만 사용한다.

## 2. 확인한 현재 상태

- VM Start는 `API facade → VmStartUseCase → explicit ports → compatibility workflow adapter`로 진입하지만 실제 workflow body는 `vm_actions/start.py`에 남아 있다.
- `job_runs`는 매 상태 전이마다 같은 row를 갱신하는 operator용 최신 projection이다.
- `job_artifacts`는 checksum을 제공하지만 같은 `job/type/filename` identity를 upsert하므로 append-only event store가 아니다.
- Jobs 조회 helper는 DB exception을 빈 결과·`None`으로 축소한다. 이 공개 의미는 기존 Plan에서 별도 승인 전 보류돼 있다.
- VM Start와 Create VM의 target lock은 local filesystem 기반이며 DRS DB lock과 통합되지 않았다.
- Guided `qm` bundle, expiry, operator attestation, API verification을 지속적으로 소유하는 공통 Operations 저장 구조가 없다.
- canonical 검증 기준은 Python 3.13 container backend `362 passed`다.

## 3. 목표와 범위

- 목표: frontend가 사용할 안정적인 Operation projection과 append-only Event 기반을 만들고 VM Start와 첫 Guided `qm`이 같은 핵심 언어를 사용하게 한다.
- 범위:
  - Operations domain 상태·전이·execution mode 계약
  - operation projection과 append-only event repository
  - 기존 VM Start workflow의 application 경계 추가 분해와 operation correlation
  - allowlisted Guided `qm` instruction bundle, expiry, attestation, API after-state verification
  - 기존 Jobs/API compatibility facade와 전체 regression
- 비범위:
  - raw shell/SSH executor, arbitrary command input, backend-side `qm` 실행
  - queue/worker/scheduler, automatic retry, multi-cluster, frontend 구조 변경
  - 기존 `job_runs`/`job_artifacts`/DRS table 제거 또는 과거 data migration
  - live Proxmox mutation과 live manual command 실행
- 인수 조건:
  - operation과 event를 같은 local transaction에서 기록하며 event row는 application에서 update/delete하지 않는다.
  - VM Start public endpoint·payload·error·job/artifact 계약과 one-dispatch invariant가 유지된다.
  - Guided Manual은 고정 template과 typed parameter만 받고 command fragment를 입력받지 않는다.
  - attestation만으로 성공하지 않고 authoritative API after-state가 확인돼야 완료된다.
  - persistence/evidence 실패는 성공이나 실행 가능 상태로 축소하지 않는다.

## 4. 아키텍처와 데이터 영향

- 도메인·모듈: `operations/core`가 Operation 상태와 전이, `operations/vm_start`와 `operations/guided_qm`이 vertical slice를 소유한다.
- 의존 방향: API → application use case → domain/repository port; SQLAlchemy와 Proxmox concrete adapter는 바깥에서 port를 구현한다.
- 데이터 소유권: operation projection은 Operations, immutable event는 Evidence/Audit가 논리적으로 소유한다.
- 추천 신규 table:
  - `operations`: 현재 projection, target/action/mode/status/idempotency/intent·plan digest/trusted actor/current stage/expiry/timestamps.
  - `operation_events`: operation별 monotonic sequence, event type, redacted payload, previous checksum, checksum, created time.
- transaction: event append와 projection 전이는 한 DB transaction에서 수행한다. Proxmox 호출이나 operator 외부 실행은 DB transaction 밖이다.
- compatibility: `job_runs`와 `job_artifacts`는 기존 화면/API를 위해 유지한다. 신규 operation 기록과의 연결 ID를 details에 additive하게 남긴다.
- 보안: server-side actor만 저장하고 template ID·typed parameter 외 arbitrary command를 받지 않는다. secret-like input은 API와 event에서 거부·redact한다.

## 5. 선택지와 결정

| 순위 | 선택지 | 적합한 이유 | 단점·비용 | 추천 여부 |
|---:|---|---|---|---|
| 1 | additive `operations` + append-only `operation_events` | frontend와 Guided Manual이 안정적인 상태·이력 계약을 사용하고 VM Start도 공통 lifecycle로 전환 가능 | migration과 dual-write 실패 설계·DB 테스트 필요 | 추천 |
| 2 | 기존 `job_runs.details` + unique artifact만 확장 | schema 없이 빠르게 시작 가능 | projection과 audit가 혼합되고 이후 frontend/API 재작업 가능성이 큼 | 임시안 |
| 3 | workflow 분리만 하고 persistence 보류 | 가장 작은 변경 | Guided Manual·recovery 핵심 요구를 만족하지 못함 | 비추천 |

- 추천 결정: 1번. 기존 table을 건드리지 않는 additive migration으로 공통 기반을 먼저 만든다.
- 감수할 단점: 구현량과 검증 범위가 늘고, 점진 전환 동안 operation projection과 기존 job projection을 함께 유지해야 한다.
- 사용자 결정: `1번 승인 — 기존 table과 API를 유지하고 additive operation projection + append-only event 저장 구조를 구현한다. 구조는 명확한 책임과 유지보수성을 우선하고 불필요한 추상화를 추가하지 않는다.`
- 승인일: `2026-07-20`

## 6. 구현 단계

| 단계 | 결과 | 변경 책임·예상 파일 | 검증 | 복구 지점 |
|---:|---|---|---|---|
| 1 | Operation domain과 transition matrix | `app/operations/core/domain.py`, 단위 테스트 | invalid transition, terminal/ambiguity, digest | persistence 없음 |
| 2 | additive projection/event persistence | 새 Alembic revision, model, repository adapter | SQLite/PostgreSQL-shaped schema, atomic append/projection, checksum chain | 기존 table·API 미사용 유지; forward correction |
| 3 | VM Start application workflow 분해 | `operations/vm_start/*`, `vm_actions/start.py` facade/adapters | 기존 VM Start·auth·lock·artifact 계약, persistence failure injection | facade wiring만 이전 구조로 복구 |
| 4 | Guided `qm` first slice | `operations/guided_qm/*`, additive `/api/v1/operations/*` | allowlist, injection, expiry, attestation, verification, RBAC | template/route 비활성화; executor 없음 |
| 5 | backend 완료 검증 | full backend, migration, diff, quality review, docs | canonical container와 focused suites | 실패 단계 이후 진행 중단 |

## 7. 성공·실패·데이터 흐름

- VM Start 성공: intent/event 저장 → pre-check/lock → dispatch attempt event → Proxmox API → task/post-check → evidence event + operation projection → 기존 job facade 갱신.
- Guided Manual 성공: operation 계획 → allowlisted bundle event → `awaiting_operator` → trusted actor attestation → `awaiting_verification` → Proxmox API after-state → verified event → `succeeded`.
- 실패 흐름:
  - dispatch 전 persistence/validation/expiry/권한 실패: 외부 effect 없이 block.
  - VM Start dispatch 후 persistence/evidence 실패: success 공표 금지, lock 유지와 reconciliation.
  - manual attestation 누락·만료: 실행 완료로 처리하지 않음.
  - after-state 불명·불일치: `awaiting_verification` 또는 `needs_reconciliation`.
- 재시도: same key/same intent는 같은 operation을 반환하고 different intent는 conflict. API와 Guided Manual 사이 silent fallback은 없다.

## 8. 테스트와 검증 계획

- 단위: state transition, canonical digest, event checksum chain, template/parameter validation, expiry.
- repository: event sequence·append-only API, projection/event atomicity, unique idempotency, rollback.
- VM Start: ack, replay/conflict, target lock, one dispatch, explicit reject, timeout/missing UPID, task/post-check, evidence/persistence failure.
- Guided Manual: unsupported template, extra parameter, injection metacharacter, secret-like input, wrong target, expired bundle, duplicate attestation, API verification unavailable/mismatch.
- 계약: 기존 VM Start/API auth/Jobs contract와 additive operation endpoint.
- 전체: canonical Python 3.13 backend suite, Alembic head/schema checks, `git diff --check`.
- live: 실행하지 않는다. 정확한 target과 side effect를 제시한 별도 사용자 승인 후에만 수행한다.

## 9. 문서 영향

- Architecture·Domain·Flow: 실제 구현된 Operation/Event ownership과 transaction을 갱신한다.
- API: additive operation/manual bundle·attestation·verification endpoint만 구현 후 기록한다.
- Database: 신규 table, 제약, ownership, migration/rollback 전략을 기록한다.
- Specification·ADR: 승인된 방향은 유지한다. 새로운 execution 방식이나 외부 dependency가 생길 때만 새 결정이 필요하다.

## 10. 복구와 위험 완화

- 신규 table은 기존 table과 consumer를 대체하지 않고 먼저 추가한다.
- VM Start compatibility tests가 실패하면 새 operation wiring을 제거하고 기존 job-only workflow로 복구한다.
- applied migration은 downgrade로 운영 data를 삭제하지 않고 필요 시 additive correction revision을 사용한다.
- event checksum, secret redaction, actor provenance가 깨지거나 dispatch 전 durable intent가 보장되지 않으면 중단한다.
- raw command parameter, backend shell execution, automatic API→CLI fallback이 필요해지면 범위를 벗어난 것으로 보고 중단한다.

## 11. 구현 후 대조

- 구현 결과:
  - `operations/core`에 공통 상태 전이·digest·repository port를 만들고 migration `20260720_0026`으로 `operations`, `operation_events`를 additive하게 추가했다.
  - projection create/transition과 checksum-linked event append를 한 DB transaction으로 저장한다. 기존 table, endpoint, job/artifact는 제거하지 않았다.
  - VM Start workflow를 `operations/vm_start/workflow.py`로 옮기고 common operation/event와 기존 job/artifact를 dual record한다. `run_vm_start`와 기존 HTTP 계약은 facade로 유지한다.
  - 사용자 승인에 따라 첫 Guided action을 정확히 `qm unlock <vmid>`로 제한했다. typed input, lock-type allowlist, 5분 expiry, trusted actor attestation, Proxmox API verification과 additive operation API를 구현했다.
- 계획과 달라진 부분:
  - Guided plan은 active task 전체 조회가 완전함을 증명하기 위해 Proxmox token의 node-level `Sys.Audit`을 추가 gate로 요구한다.
  - expiry는 background timer가 아니라 operation 재조회·replay 시 평가한다. attestation 없는 expiry도 config/task 상태를 재관찰하고 외부 effect 가능성이 있으면 `needs_reconciliation`과 target lock을 유지한다.
  - crash window에서 저장된 `verifying` 상태를 같은 verification endpoint가 재개하도록 했다.
  - `suspended`는 정상 정지 상태와 혼동될 수 있어 unlock allowlist에서 제외했다. 허용 lock은 `backup`, `clone`, `create`, `migrate`, `rollback`, `snapshot`, `snapshot-delete`, `suspending`이다.
- 달라진 이유: task 목록의 불완전한 권한, 만료 직전 외부 실행, verification transition 직후 process crash가 false success 또는 조기 lock 해제로 이어지지 않게 fail-closed 의미를 구체화했다.
- 품질 검토: 만료 후 late attestation이 실행 가능성을 잃고 lock을 해제하던 문제, persisted `verifying`을 재개할 수 없던 문제, expiry reconciliation이 attestation 없이 verification으로 진입할 수 있던 문제를 발견했다. 각각 late evidence를 reconciliation으로 재개, idempotent verification resume, attestation evidence 의무화로 수정했고 재검토 후 추가 Critical/High/Medium finding은 없었다.
- 최종 검증 결과:
  - Guided `qm`·auth·Proxmox·target-lock 집중 suite `77 passed`.
  - canonical Python 3.13 container backend 전체 `425 passed`, warnings 55개는 기존 httpx/Alembic deprecation 계열이다.
  - `git diff --check` 통과. live Proxmox API/command와 frontend 검증은 실행하지 않았다.
- 갱신한 현재 상태 문서: Project Profile, Architecture, Domain Map, Verified Operation Flow, current API, current Database, 이 Plan과 상위 전환 Plan.
- 남은 위험:
  - local target lock은 single-container file lock이며 process/container storage 유실과 multi-replica coordination을 해결하지 않는다.
  - instruction 발급 뒤 외부 Proxmox GUI·CLI에서 시작되는 별도 작업은 local lock으로 차단할 수 없다. double task read와 post-verification으로 성공 오판을 막지만 live cluster에서 확인하지 않았다.
  - target lock 획득 직후 operation 저장 전 process가 종료되면 owner operation이 없는 orphan lock이 남을 수 있다. 자동 해제 대신 운영자 진단·durable recovery 설계가 필요하다.
  - common operation API의 frontend timeline과 Create VM·DRS 전환은 후속 단계다.
