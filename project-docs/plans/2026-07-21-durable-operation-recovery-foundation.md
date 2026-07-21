# 구현 계획: 단계 10-A PostgreSQL 기반 Durable Operation Recovery Foundation

- 상태: `IMPLEMENTED`
- 날짜: `2026-07-21`
- 관련 요구사항: [`FR-003`, `FR-004`, `FR-008`, `FR-009`, `FR-012`](../specifications/project-specification.md)
- 관련 ADR: [`ADR-001`](../decisions/adr-001-proxmox-gjallar-authority-boundary.md), [`ADR-002`](../decisions/adr-002-modular-monolith-domain-boundaries.md), [`ADR-003`](../decisions/adr-003-production-inventory-connection-truth.md), [`ADR-004`](../decisions/adr-004-postgresql-durable-operation-recovery.md)
- 상위 Plan: [`Verified Operations Control Plane 전환` 단계 10](2026-07-20-verified-operations-control-plane-transition.md)
- 승인자: `사용자`

2026-07-21 사용자는 단계 10 시작을 요청했다. 상위 Plan은 runner, lease, action, runtime과 live smoke를 각각 별도 승인 대상으로 두므로, 이 Plan은 첫 수직 범위를 durable recovery와 공통 target coordination 기반으로 제한한다. `shutdown` 또는 `reboot` action 확장은 이 기반이 검증된 뒤 단계 10-B에서 별도 승인한다.

## 1. 위험도

- 분류: `HIGH`
- 판단 근거: PostgreSQL migration, target-scoped concurrency, time-bounded lease와 fencing, process restart recovery, FastAPI lifecycle의 background runtime, Proxmox task 관찰, 공통 Operation transaction 경계를 변경한다.
- 실패 영향: 같은 VM에 중복 mutation, lease를 잃은 worker의 stale write, ambiguous operation의 lock 조기 해제, process restart 뒤 작업 유실, 복구 관찰을 mutation 재시도로 오인, 기존 VM Start/Create VM/Guided `qm`/DRS 계약 회귀가 가능하다.
- 되돌리기 어려운 부분: 실제 Proxmox side effect는 code rollback으로 취소되지 않는다. open durable lock과 recovery record를 무시하는 구버전 code로 즉시 rollback하면 동시 실행 방어가 약해질 수 있다. 적용된 migration과 evidence는 삭제하지 않고 feature disable과 roll-forward correction을 기본 복구로 사용한다.

## 2. 확인한 현재 상태

- 현재 runtime:
  - production은 React build와 FastAPI를 포함한 single image이고 Uvicorn 한 process를 시작한다.
  - `app.main`에는 lifespan/background runner가 없고 queue, scheduler, cache, 외부 worker dependency도 없다.
  - VM Start와 Create VM은 HTTP request 중 동기적으로 Proxmox task를 polling한다.
- 현재 Operation persistence:
  - `operations`는 current projection, `operation_events`는 checksum-linked append-only event다.
  - `SqlAlchemyOperationStore`는 projection transition과 event append를 짧은 한 DB transaction으로 저장하고 row lock과 expected status로 동시 transition을 막는다.
  - operation status에는 `dispatching`, `running`, `verifying`, `needs_reconciliation`이 있지만 due work, claim, lease owner, retry schedule을 저장하는 구조는 없다.
- 현재 target coordination:
  - VM Start, Create VM, Guided `qm unlock`은 `backend/app/operations/target_lock.py`의 temporary file lock을 공유한다. ambiguity에서는 보존하지만 container 교체, temporary storage 초기화, multi-replica coordination을 견디지 못한다.
  - DRS는 PostgreSQL `operation_locks`에 VM identity, Proxmox locator, route scope를 저장한다. 현재 check constraint와 partial unique index는 DRS operation type 안에서만 동작하므로 다른 operation type과 같은 VM을 공통 차단하지 않는다.
  - `GJALLAR_CLUSTER_ID`가 configured cluster identity로 이미 존재하지만 file lock key는 현재 한 cluster의 `vmid:{vmid}`를 전제한다.
- 현재 recovery:
  - DRS는 stored UPID를 operator가 명시적으로 reconcile할 수 있다.
  - Guided `qm`은 persisted `verifying`을 verification endpoint로 다시 확인할 수 있다.
  - VM Start와 Create VM에는 process restart 뒤 자동 claim/resume runner나 공통 recovery endpoint가 없다.
  - VM Start는 dispatch accepted 뒤 common Operation `details.proxmox_upid`를 저장하지만, UPID 저장 전 crash는 direct observation만 가능하고 동일 mutation 자동 재시도는 금지돼 있다.
- 현재 action surface: mutation client는 Create VM과 VM Start만 제공한다. `shutdown`/`reboot` wrapper와 action-specific safety contract는 없다.
- 관련 검증 자산: Operation domain/repository/schema, target file lock, DRS DB lock, VM Start workflow/application/API, Create VM, Guided `qm` tests가 있다.
- 조사 기준선: Operation domain/repository/schema, target lock, DRS lock, VM Start application focused test `35 passed`; warning 1건은 기존 Alembic path separator deprecation이다.
- 확인되지 않은 항목:
  - production replica 수, operation 발생량, recovery SLA와 evidence retention 수치가 확정되지 않았다.
  - 실제 Proxmox의 completed task 조회 보존 기간과 live cluster recovery 적합성은 확인하지 않았다.
  - 현재 배포 환경이 graceful shutdown에 제공하는 시간과 rolling deployment 방식은 확인하지 않았다.
  - 이 미확정 값은 자동 mutation, lock 만료, 성공 판정의 전제로 사용하지 않는다.

## 3. 목표와 범위

- 목표: process/container restart와 multi-replica 상황에서도 같은 target의 second mutation을 차단하고, 이미 dispatch된 VM Start를 PostgreSQL lease로 한 observer만 claim해 task/post-check/evidence를 안전하게 재개할 수 있게 한다.
- 범위:
  - 기존 PostgreSQL `operation_locks`를 Operations-owned durable target lock substrate로 확장한다.
  - 같은 cluster/VMID의 locator lock은 VM Start, Create VM, Guided `qm unlock`, DRS 사이에서 operation type과 무관하게 하나만 open될 수 있게 한다.
  - time-bounded claim과 fencing을 위한 additive `operation_recovery_items`를 추가한다.
  - 현재 single image 안에 opt-in, bounded-concurrency in-process recovery runner를 추가한다.
  - VM Start만 첫 allowlisted recovery handler로 연결한다.
  - recovery와 target lock 상태를 기존 Operation detail에 additive하게 노출하고 Operations UI에서 읽기 전용으로 표시한다.
  - 기존 file lock은 전환 중 compatibility guard로 dual acquire하며 durable DB lock을 먼저 획득한다.
- 비범위:
  - external queue, message broker, scheduler service, microservice, 별도 privileged executor.
  - recovery runner의 Proxmox mutation POST, missing UPID operation의 자동 성공, same action 자동 재호출.
  - Create VM 자동 reconciliation, Guided `qm` 자동 verification, DRS common Operation 전환.
  - `shutdown`, `reboot`, `stop`, `reset`, `suspend`, migration action 확장.
  - multi-cluster federation UI, credential storage 변경, separate approver role.
  - 기존 jobs DB 공개 오류 의미, DRS data/API 폐기, compatibility table backfill·삭제.
  - run-specific live Proxmox smoke 또는 실제 mutation.
- 인수 조건:
  - 같은 cluster/VMID의 open durable locator lock은 operation type이 달라도 DB constraint로 중복 생성되지 않는다.
  - recovery item은 dispatch 전에 durable하게 등록되며 등록 실패 시 Proxmox mutation을 호출하지 않는다.
  - foreground 또는 runner는 유효한 lease token과 generation을 가진 동안만 recovery transition, evidence append, lock release를 commit할 수 있다.
  - lease expiry는 다른 observer의 claim만 허용하며 target lock 해제, mutation retry, terminal status를 의미하지 않는다.
  - VM Start UPID가 있으면 terminal task와 direct VM state를 다시 관찰해 기존 성공 조건을 만족할 때만 `succeeded`가 된다.
  - UPID가 없거나 task/state가 불명확하면 mutation을 재호출하지 않고 `needs_reconciliation`과 durable target lock을 유지한다.
  - runner disable 또는 shutdown 중에도 operation, recovery item, target lock evidence가 PostgreSQL에 남는다.
  - 기존 `/api/v1` method/path, RBAC, acknowledgement, success/error 의미와 frontend route를 유지한다.
- 유지할 기존 계약:
  - trusted server-side actor, `operator+` mutation, `viewer+` query.
  - `managed_api`, `guided_manual`, `observe_only` 경계와 no silent fallback.
  - task `OK`와 direct after-state, evidence 저장 전에는 `succeeded` 금지.
  - applied migration 수정 금지, additive response 우선, ambiguity에서 target lock 보존.

## 4. 아키텍처와 데이터 영향

- 도메인·모듈:
  - Operations가 durable target lock, recovery item, lease/fencing, handler allowlist를 소유한다.
  - action-specific handler는 Operations application port를 통해 Proxmox read/task observation을 사용하고 policy나 HTTP를 직접 알지 않는다.
  - `app.main`은 composition/lifecycle만 담당하고 recovery 판단은 application service에 위임한다.
- 책임과 의존성 방향:
  - `interface/lifespan → recovery application → domain/ports`.
  - SQLAlchemy, clock, worker identity, Proxmox client는 infrastructure adapter다.
  - recovery handler registry는 `operation_type` allowlist이며 arbitrary callable, raw command, dynamic import를 받지 않는다.
- 데이터 소유권:
  - 기존 `operation_locks`는 Operations의 durable target coordination record로 확장한다. DRS producer와 기존 history는 유지한다.
  - 신규 `operation_recovery_items`는 Operations가 소유하며 operation별 recovery state, handler kind, due time, lease token/generation, attempt count, redacted last result를 저장한다.
  - `operations`/`operation_events`는 계속 canonical lifecycle projection/evidence다. recovery item 자체를 성공 authority로 사용하지 않는다.
- 제안 schema:
  - `operation_locks`: operation type check를 현재 supported type으로 expand하고, open `proxmox_locator`에 `(scope_type, scope_key)` cross-operation partial unique index를 추가한다. existing DRS row와 column은 삭제·변경하지 않는다.
  - `operation_recovery_items`: `operation_id` PK/FK, `recovery_kind`, `status`, `available_at`, `lease_owner`, `lease_token`, `lease_generation`, `lease_expires_at`, `attempt_count`, `last_error_code`, redacted `details`, created/updated/completed timestamp를 둔다.
  - recovery status는 `pending`, `leased`, `retry_wait`, `paused`, `completed`로 제한하고 leased query와 due query index를 둔다.
- 트랜잭션·정합성:
  - durable target lock acquisition은 external dispatch 전에 commit한다.
  - operation `dispatching` transition과 recovery item 준비는 각각 짧은 transaction으로 수행하되 recovery item 준비 실패 시 dispatch하지 않는다.
  - worker claim은 PostgreSQL row lock/`SKIP LOCKED`와 compare-and-set lease generation을 사용한다.
  - recovery transition/event append와 lease fencing 확인은 같은 DB transaction에서 commit한다. lease를 잃은 worker는 stale result를 저장하거나 target lock을 해제할 수 없다.
  - external Proxmox read/task poll은 DB transaction 밖에서 수행한다.
  - foreground task polling도 recovery lease heartbeat를 사용한다. heartbeat/fence를 잃으면 polling 결과를 commit하지 않고 operation을 recovery 대상으로 남긴다.
- API·외부 시스템:
  - PostgreSQL과 existing Proxmox API만 사용한다. 신규 network service나 package dependency를 추가하지 않는다.
  - Operation detail에 optional `recovery`와 `target_lock` read model을 추가한다. mutation endpoint와 error code는 유지한다.
  - runner는 Proxmox GET/task observation만 수행하며 POST mutation method를 port로 받지 않는다.
- 보안·권한:
  - worker identity와 lease token은 coordination identifier이지 secret/actor가 아니다.
  - recovery event actor는 synthetic system actor로 명시하고 original trusted actor를 대체하지 않는다.
  - Proxmox credential, URL, raw upstream response, lease token 원문은 API/evidence/log에 노출하지 않는다.
  - runtime env는 enabled, poll interval, lease duration, bounded batch/concurrency만 허용한다.

## 5. 선택지와 결정

| 순위 | 선택지 | 적합한 이유 | 단점·비용 | 추천 여부 |
|---:|---|---|---|---|
| 1 | 현재 FastAPI image 안의 in-process runner + PostgreSQL durable lock/recovery lease | 현재 single-image deployment와 modular monolith를 유지하며 추가 서비스 없이 restart/multi-replica claim을 검증할 수 있다. PostgreSQL fencing으로 worker 중복을 막고 action handler를 점진 추가할 수 있다. | API process와 recovery resource를 공유한다. 초기에는 opt-in flag와 concurrency 1이 필요하고, 고부하 시 별도 worker로 분리해야 한다. | 추천 |
| 2 | 같은 image의 별도 worker process + PostgreSQL lease | API와 recovery 실행을 격리하고 독립 scale/shutdown이 쉽다. | deployment topology, process supervision, runbook과 health contract가 즉시 늘어난다. 현재 운영 규모와 배포 방식이 확인되지 않았다. | 후속 분리 후보 |
| 3 | 외부 queue/scheduler 기반 worker | 대규모 throughput, delay/retry tooling에 유리하다. | 새 운영 dependency, delivery semantics, credential/availability 경계와 distributed failure mode가 생긴다. 현재 요구와 ADR의 점진 전환 원칙보다 크다. | 비추천 |

- 추천 결정: `1순위 — current image 내부의 opt-in in-process runner, PostgreSQL durable target lock과 recovery lease, VM Start read-only recovery부터 구현한다.`
- 초기 rollout: `GJALLAR_OPERATION_RECOVERY_ENABLED=false`를 기본으로 두고 schema/contract/restart test 완료 후 명시적으로 enable한다. enabled 상태의 concurrency는 1로 제한하고 throughput 자료가 생기기 전 자동 확대하지 않는다.
- 사용자 결정: `1순위 승인 — current image 내부의 opt-in in-process runner, PostgreSQL durable target lock과 recovery lease, VM Start read-only recovery부터 구현한다.`
- 승인일: `2026-07-21`

## 6. 구현 단계

| 단계 | 결과 | 변경 책임·예상 파일 | 검증 | 복구 지점 |
|---:|---|---|---|---|
| 0 | 현재 coordination/recovery 계약 characterization | 이 Plan, existing operation/lock/workflow tests | focused `35 passed`; current API/source behavior 고정 | production code 미변경 |
| 1 | recovery/lease와 durable target lock domain·port | `backend/app/operations/recovery/**`, `backend/app/operations/locks/**`, domain tests | transition, due, lease generation, fencing, redaction pure/fake-port tests | 새 module 제거 |
| 2 | additive PostgreSQL schema와 repository | 새 Alembic revision, SQLAlchemy models/repositories, schema tests | SQLite migration compatibility + 실제 PostgreSQL partial unique/`SKIP LOCKED`/fencing integration | migration은 유지하고 feature 미사용; 필요 시 additive correction |
| 3 | current mutation의 durable locator lock 전환 | VM Start/Create VM/Guided adapters, DRS lock compatibility facade, target lock tests | cross-action same target conflict, retain/release, file+DB dual guard, old API regression | runner disabled; code wiring 제거 전 open lock audit 필요 |
| 4 | VM Start foreground recovery registration | VM Start ports/tracking/workflow, Proxmox task polling heartbeat hook | recovery item 없으면 dispatch 금지, UPID crash window, lease loss, existing success/error contract | runner disabled; synchronous path 유지 |
| 5 | opt-in in-process runner와 VM Start read-only resume | recovery application/runtime, `app.main` lifespan composition | two-runner claim, expiry takeover, stale worker fencing, graceful shutdown, no POST call | env flag off; pending record와 target lock 보존 |
| 6 | recovery 상태 조회와 UI 표시 | Operation query/API read model, frontend Operation entity/detail, contract tests | viewer read/operator controls 없음, token/redaction, route regression | additive field/UI section 제거 |
| 7 | 전체 검증·독립 리뷰·문서 동기화 | tests, ADR-004, current project-docs | PostgreSQL, backend/full, frontend test/lint/build, image, restart/failover, `$quality-review`, diff | Critical/High/Medium finding 해결 전 enable 금지 |

단계 10-B의 첫 새 action은 이 Plan을 `IMPLEMENTED`로 종료하고 recovery foundation을 enable한 환경에서 검증한 뒤 별도 Plan으로 선택한다. 현재 추천 후보는 post-state가 명확한 graceful `shutdown`이며 `reboot`는 before/after power state가 같아 더 강한 task/boot identity evidence가 필요하다.

## 7. 성공·실패·데이터 흐름

- foreground 성공 흐름:
  1. authenticated actor, intent, idempotency와 fresh target을 확인한다.
  2. cluster/VM locator durable target lock을 획득하고 compatibility file lock을 잡는다.
  3. common Operation을 `dispatching`으로 전환한다.
  4. VM Start recovery item과 foreground lease를 저장한다. 저장 실패 시 Proxmox POST를 호출하지 않는다.
  5. Proxmox start를 정확히 한 번 호출하고 UPID를 즉시 Operation evidence/details에 저장한다.
  6. task poll 중 lease heartbeat를 갱신한다.
  7. terminal task, direct VM state와 evidence를 확인하고 fenced transaction으로 `succeeded`를 기록한다.
  8. recovery item을 `completed`로 만들고 DB/file target lock을 release한다.
- restart recovery 성공 흐름:
  1. process 종료 뒤 foreground lease가 만료돼도 durable target lock과 recovery item은 남는다.
  2. enabled runner 하나가 due item을 claim하고 새 generation/token을 얻는다.
  3. allowlisted VM Start handler가 stored UPID task와 current VM state를 GET으로 관찰한다.
  4. task가 계속 실행 중이면 evidence를 bounded하게 갱신하고 `retry_wait`로 reschedule한다.
  5. terminal task와 direct state가 일치하면 fenced transition/evidence append 후 lock을 release한다.
- 실패 흐름:
  - lock conflict: 외부 호출 없이 기존 `409` 의미와 conflicting owner evidence를 반환한다.
  - recovery item 준비 실패: dispatch 금지, non-success operation/event와 lock의 안전한 release 또는 retained diagnostic 상태를 기록한다.
  - lease heartbeat/DB loss: 현재 observer는 결과 commit을 중단한다. lease expiry는 takeover만 허용한다.
  - crash before dispatch: external effect 없음. item과 operation을 side-effect-free recovery path에서 종료할 수 있다.
  - crash after dispatch before UPID: mutation retry 금지. direct observation을 기록하되 `needs_reconciliation`과 target lock을 유지한다.
  - stored UPID task read 실패/unknown: bounded backoff 후 재관찰하며 unavailable을 success/failed로 축소하지 않는다.
  - task `OK`/VM not running 또는 task failure/VM state 불명: `needs_reconciliation`, lock 유지.
  - evidence append 또는 compatibility write failure: success/lock release 금지, recovery item을 paused/retry state로 보존한다.
- 데이터 변환:
  - existing Operation/event와 compatibility jobs/artifacts를 삭제·backfill하지 않는다.
  - new recovery item은 신규 또는 현재 non-terminal VM Start부터 생성한다. 기존 historical operation 전체를 자동 enqueue하지 않는다.
  - deployment 전 open file lock과 non-terminal operation은 read-only audit 대상으로 보고하고 자동 success/backfill하지 않는다.
- 재시도·멱등성·보상:
  - runner retry는 Proxmox observation과 local evidence commit만 반복한다.
  - Proxmox mutation POST, 다른 execution mode fallback, inverse action 보상은 하지 않는다.
  - lease generation과 token은 stale worker write를 fencing한다.
  - target lock은 lease와 독립적이며 operation이 verified terminal일 때만 release한다.

## 8. 테스트와 검증 계획

- 단위 테스트:
  - recovery state, due calculation, backoff bound, lease expiry/takeover, fencing token/generation, system actor, payload redaction.
  - VM Start task/state outcome mapping과 missing UPID 보수 처리.
- 통합·계약 테스트:
  - migration head, recovery table constraint/index/FK, cross-operation locator unique constraint.
  - 두 repository/runner가 같은 item을 동시에 claim할 때 하나만 성공.
  - lease를 잃은 worker의 operation transition/event/lock release 거부.
  - VM Start dispatch 전에 durable recovery item 저장 실패 시 mutation client 미호출.
  - process restart를 모사한 새 runner instance가 stored UPID를 읽어 second POST 없이 완료.
  - 기존 VM Start/Create VM/Guided `qm`/DRS API status/error/RBAC/idempotency와 retained lock 계약.
- 경계·실패 테스트:
  - crash after dispatch before UPID, after UPID before event, after verification before lock release.
  - DB unavailable, heartbeat failure, Proxmox GET timeout, task unknown, post-check mismatch, evidence failure, graceful shutdown timeout.
  - runner disabled, non-live connection, unsupported operation type, malformed/redacted recovery details.
  - old file lock과 durable DB lock acquisition ordering/rollback.
- PostgreSQL 필수 검증:
  - actual PostgreSQL에서 partial unique locator index, row lock/`SKIP LOCKED`, timestamp timezone, concurrent claim/fencing을 확인한다.
  - 이 검증을 실행할 수 없으면 runner를 enable하지 않고 구현 단계를 중단한다.
- Formatter·Lint·타입:
  - backend formatter/lint/type 명령은 아직 없다. syntax/import와 backend test로 검증하고 새 suppression을 추가하지 않는다.
  - frontend ESLint를 실행한다.
- 빌드·수동 확인:
  - focused/backend full/canonical Python 3.13, frontend test/ESLint/Vite build, production image, `git diff --check`.
  - local PostgreSQL에서 두 runner와 forced restart/failover를 검증한다.
  - browser Operations recovery 표시와 a11y/navigation을 수동 확인한다.
  - live Proxmox smoke와 mutation은 run-specific 별도 승인 전 실행하지 않는다.

## 9. 문서 영향

- Project Specification: FR-003/004/008/009와 quality recovery 요구가 이미 있으므로 범위가 유지되면 수정하지 않는다.
- Architecture·ADR:
  - 사용자 승인 후 `ADR-004`에 in-process runner, PostgreSQL lease/fencing, no-auto-mutation recovery 결정을 기록한다.
  - 구현 후 Architecture current state와 runtime component를 갱신한다.
- Domain·Flow:
  - Domain Map의 Operations target lock/lease ownership과 Verified Operation Lifecycle의 foreground/restart recovery 흐름을 갱신한다.
- API·Database:
  - Operation detail의 additive recovery field, `operation_locks` 확장과 `operation_recovery_items` schema/ownership을 갱신한다.
- Runbook·Project Profile·상위 Plan:
  - runner enable/disable, lease 진단, open target lock/recovery item, graceful shutdown, rollback/roll-forward 절차와 단계 10-A 결과를 실제 구현 후 동기화한다.

## 10. 복구와 위험 완화

- 주요 위험:
  - stale worker가 terminal transition 또는 lock release를 commit.
  - lease expiry를 side-effect 없음으로 오판.
  - old/new lock 경로가 같은 target을 서로 차단하지 못함.
  - background loop가 API latency/DB pool을 고갈.
  - rollout 중 구버전 process가 durable lock을 무시.
  - missing UPID를 observed state만으로 자동 성공 처리.
- 예방·관찰 방법:
  - DB-enforced cross-operation unique locator, lease generation/token fencing, action allowlist, GET-only recovery port, concurrency 1, bounded query/payload/backoff.
  - runner state와 마지막 redacted error를 Operation detail/timeline에 노출한다.
  - feature flag default off, schema → code-disabled → characterization/restart test → explicit enable 순서로 배포한다.
  - enable 전 모든 API replica가 durable lock-aware version인지 확인한다.
- rollback 또는 roll-forward:
  - 즉시 안전 조치는 runner env flag를 off하고 API mutation을 필요하면 운영적으로 중지하는 것이다. lease expiry와 무관하게 durable target lock은 유지한다.
  - migration/table/event는 삭제하지 않는다. constraint/repository 문제는 additive correction revision으로 수정한다.
  - code rollback은 open durable lock/recovery item을 audit하고 old version이 이를 무시하지 않도록 mutation drain 후 수행한다.
  - already dispatched effect는 Proxmox actual state와 stored task evidence로 reconcile하며 inverse action을 자동 실행하지 않는다.
- 중단 기준:
  - recovery 경로에서 Proxmox POST 또는 silent managed/manual fallback이 필요함.
  - recovery item persistence 실패에도 dispatch가 가능함.
  - stale lease owner가 event/transition/lock release를 commit할 수 있음.
  - lease expiry 또는 process death만으로 target lock을 release하거나 terminal success/failed를 결정함.
  - 같은 cluster/VMID를 operation type 간 동시에 lock할 수 있음.
  - existing API/RBAC/idempotency/error 의미가 깨지거나 secret-bearing payload가 저장·노출됨.
  - actual PostgreSQL concurrency/restart 검증 없이 runner enable이 필요함.

## 11. 구현 후 대조

- 계획과 달라진 부분:
  - 실제 PostgreSQL 검증에서 ORM relationship이 없는 `operations`/`operation_events` 생성 flush 순서가 FK를 보장하지 않는 기존 결함을 발견해, 같은 transaction 안에서 parent projection을 먼저 flush하도록 수정했다.
  - terminal Operation 전이와 compatibility Jobs projection 사이의 실패가 durable lock 조기 해제로 이어지지 않도록 recovery를 `leased`로 유지한 뒤 Jobs projection과 마지막 fenced completion/release를 수행하는 2단계 terminal commit을 적용했다.
  - quality review에서 restart handler의 Jobs projection 누락과 file guard `OSError` 시 DB lock orphan 가능성을 발견해 recovery projection port와 acquire rollback을 추가했다.
- 달라진 이유: PostgreSQL FK/동시성 및 container restart 실패 시나리오에서 계획의 `compatibility write failure 시 lock release 금지`와 기존 Jobs read 계약을 실제로 지키기 위해서다.
- 최종 검증 결과:
  - local Python 3.14 backend 전체 `475 passed, 1 skipped`; skip은 opt-in PostgreSQL integration.
  - PostgreSQL 18.4에 Alembic head `20260721_0027` 적용 후 partial unique locator, concurrent `SKIP LOCKED` claim, timezone, stale lease fencing integration `1 passed`.
  - canonical Python 3.13 container backend `475 passed, 1 skipped`.
  - canonical Node 24/pnpm 10 frontend test 17개, ESLint, Vite production build와 `gjallar:local` production image build 통과. 기존 500KB chunk warning은 유지된다.
  - `git diff --check` 통과. live Proxmox mutation, production rollout enable, browser 수동 확인은 실행하지 않았다.
- 갱신한 현재 상태 문서: Project Profile, Specification, Architecture, Domain Map, Verified Operation Lifecycle, API, Database, Runbook, root/backend README와 `.env.example`.
- 남은 위험:
  - runner는 기본 disabled이며 모든 replica migration/code 전환과 open row audit 후 운영자가 명시적으로 enable해야 한다.
  - 실제 production rolling restart와 live Proxmox completed-task retention은 검증하지 않았다.
  - Create VM/Guided/DRS 자동 recovery handler, generic operator recovery/unlock API와 multi-cluster partition은 후속 범위다.
