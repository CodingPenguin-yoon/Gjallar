# 구현 계획: 단계 10-B Graceful VM Shutdown과 Recovery Rollout 검증

> 종료된 계획의 당시 조사·승인·검증 기록이다. 현재 구현 지시가 아니며 후속 방향은 [계획 인덱스](../../plans/README.md), 현재 기준은 [문서 안내](../../README.md)를 따른다.

- 상태: `IMPLEMENTED`
- 날짜: `2026-07-21`
- 관련 요구사항: [`FR-003`, `FR-004`, `FR-008`, `FR-009`, `FR-012`](../../specifications/project-specification.md)
- 관련 ADR: [`ADR-001`](../../decisions/adr-001-proxmox-gjallar-authority-boundary.md), [`ADR-002`](../../decisions/adr-002-modular-monolith-domain-boundaries.md), [`ADR-004`](../../decisions/adr-004-postgresql-durable-operation-recovery.md)
- 상위 Plan: [`Verified Operations Control Plane 전환` 단계 10](2026-07-20-verified-operations-control-plane-transition.md)
- 선행 Plan: [`단계 10-A Durable Operation Recovery Foundation`](2026-07-21-durable-operation-recovery-foundation.md)
- 승인자: `사용자`

2026-07-21 사용자는 단계 10-B를 `graceful shutdown + 운영 recovery 검증`으로 진행하는 방향을 승인했다. 이 Plan은 그 방향을 공개 API, operation 상태기계, PostgreSQL lock type, restart recovery, UI와 rollout gate까지 구현 가능한 단위로 구체화한다. 실제 live Proxmox mutation은 정확한 cluster/node/VMID와 run-specific 승인이 없으므로 별도 마지막 gate로 유지한다.

## 1. 위험도

- 분류: `HIGH`
- 판단 근거: running VM을 종료하는 외부 mutation, 신규 `/api/v1` mutation 계약, 새 Operation/recovery kind, PostgreSQL check constraint migration, target-scoped concurrency와 restart recovery handler를 추가한다.
- 실패 영향: 잘못된 VM 종료, shutdown 중 중복 mutation, task 접수만으로 성공 오판, process restart 뒤 관찰 유실, ambiguous dispatch 뒤 lock 조기 해제, VM Start/Create/Guided/DRS와의 충돌 방어 회귀가 가능하다.
- 되돌리기 어려운 부분: 실제 guest shutdown은 code rollback으로 취소할 수 없다. 적용된 migration은 삭제·덮어쓰지 않으며 open lock/recovery row가 있는 상태에서 구버전으로 즉시 rollback하면 coordination을 우회할 수 있다.

## 2. 확인한 현재 상태

- 현재 동작:
  - managed VM lifecycle action은 `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start` 하나다.
  - Workload Cockpit은 stopped non-template VM에만 Start 버튼을 표시한다. 기존 frontend test는 `shutdown`/`reboot`가 없음을 명시적으로 고정한다.
  - `ProxmoxMutationClient`는 `start_vm`, task polling, VM status read를 제공하지만 QEMU shutdown wrapper는 없다.
  - 10-A는 VM Start에 dispatch 전 recovery registration, foreground heartbeat, GET-only restart recovery와 cross-operation durable lock을 구현했다. runner는 기본 disabled다.
- 관련 진입점과 호출 흐름:
  - HTTP `api/v1/router.py` → compatibility facade `vm_actions/start.py` → `operations/vm_start` command/use case/workflow → Proxmox mutation/task/status port 순서다.
  - target lock은 PostgreSQL `operation_locks`를 먼저 획득하고 local file guard를 compatibility 용도로 추가 획득한다.
  - recovery handler는 stored UPID task와 direct VM state를 GET으로만 관찰하고 mutation POST를 받지 않는다.
- 데이터와 constraint:
  - `operation_locks.operation_type`은 현재 `drs_migration`, `vm_start`, `vm_create`, `guided_qm_vm_unlock`만 허용한다. `vm_shutdown`을 쓰려면 새 additive Alembic revision이 필요하다.
  - `operation_recovery_items.recovery_kind`는 DB free-form 문자열이지만 domain allowlist는 `vm_start_observation`만 허용한다.
  - 공통 Operation type 자체에는 DB enum/check가 없어 `vm_shutdown` projection/event는 기존 schema를 재사용할 수 있다.
- 관련 테스트:
  - 현재 mutation client, VM Start contract, recovery application/schema와 target lock focused baseline은 `52 passed`다.
  - canonical baseline은 Python 3.13 backend `475 passed, 1 skipped`, Node 24 frontend 17 tests·ESLint·Vite build, production image build다.
- 공식 외부 계약 확인:
  - Proxmox는 clean shutdown과 hard stop을 구분한다. 이번 action은 QEMU status `shutdown` endpoint만 사용하고 `stop`, force-stop, reboot fallback을 호출하지 않는다.
  - 성공 권위는 UPID 접수가 아니라 terminal task와 direct VM `stopped` state다.
- 확인되지 않은 항목:
  - 현재 workspace `.env`에는 PostgreSQL/Proxmox/cluster/recovery enable 값이 구성돼 있지 않다.
  - production replica 수, rolling deployment 방식, open operation/lock row와 exact live smoke target은 확인되지 않았다.
  - 따라서 구현과 PostgreSQL/container restart 검증은 진행할 수 있지만 실제 production flag 전환과 live shutdown은 대상 정보와 별도 실행 승인 전 수행하지 않는다.

## 3. 목표와 범위

- 목표: running QEMU VM을 강제 종료 없이 graceful shutdown하고, request process가 종료돼도 stored UPID를 한 observer만 재관찰해 terminal task와 direct stopped state가 확인된 뒤에만 성공·lock release를 기록한다.
- 범위:
  - additive `POST /nodes/{node_id}/vms/{vmid}/actions/shutdown` endpoint와 operator RBAC.
  - `vm_shutdown_acknowledged=true`, non-empty idempotency key, expected name/status binding.
  - running non-template exact target pre-check, shared durable+file target lock, common Operation/event, existing Jobs/artifact compatibility projection.
  - Proxmox QEMU graceful shutdown POST wrapper, UPID task poll, direct stopped post-check.
  - dispatch 전 `vm_shutdown_observation` recovery registration과 foreground heartbeat.
  - GET-only shutdown restart recovery handler와 runtime allowlist 등록.
  - `vm_shutdown` durable lock type을 허용하는 additive migration.
  - Workload Cockpit의 running VM shutdown confirmation과 Operations 이동.
  - actual PostgreSQL, two-observer/restart simulation, production image와 read-only rollout audit 절차 검증.
- 비범위:
  - hard `stop`, `reset`, `reboot`, suspend, bulk/node shutdown, force-stop 또는 timeout 후 강제 fallback.
  - scheduled/automatic shutdown, policy-based autonomous remediation, external queue/worker.
  - Create VM/Guided/DRS의 새 자동 recovery handler, generic operator lock-release API, multi-cluster profile.
  - live Proxmox shutdown과 production environment flag 변경을 target/run-specific 승인 없이 수행하는 것.
- 인수 조건:
  - viewer/unauthenticated 요청, ack/idempotency/context/pre-check/lock/recovery 등록 실패는 Proxmox POST 전에 차단된다.
  - 같은 idempotency key/same intent replay는 두 번째 shutdown POST를 호출하지 않고 기존 result를 반환한다. 다른 intent는 conflict다.
  - shutdown POST는 QEMU `status/shutdown`만 호출하고 forced stop/reboot fallback이 없다.
  - task `stopped`/`OK`와 direct VM `stopped`가 모두 확인되고 compatibility projection이 저장된 뒤에만 Operation이 `succeeded`, recovery가 `completed`, target lock이 released 된다.
  - timeout, missing UPID, task/state mismatch, lease loss, persistence failure는 자동 재-dispatch 없이 `needs_reconciliation` 또는 retry/paused와 retained lock으로 남는다.
  - restart handler는 Proxmox GET/task observation만 사용하고 shutdown POST capability를 받지 않는다.
  - 기존 Start/Create/Guided/DRS API·RBAC·error 의미와 same-target lock 계약이 유지된다.
- 유지할 기존 계약:
  - trusted server-side actor와 `operator+` mutation.
  - no silent fallback, no automatic mutation retry, no inverse action compensation.
  - task+direct after-state+evidence 전에는 success 금지.
  - additive API/route 우선, 기존 migration 덮어쓰기 금지, private lease token/secret 비노출.

## 4. 아키텍처와 데이터 영향

- 도메인·모듈:
  - `operations/vm_shutdown`이 command, stable intent, pre-check, port, use case와 workflow를 소유한다.
  - 기존 `vm_actions/shutdown.py` compatibility facade가 HTTP와 concrete adapter를 연결한다.
  - Operations recovery에 명시적인 `VmShutdownRecoveryHandler`를 추가한다. 첫 action에서 VM Start 전체를 generic power engine으로 재작성하지 않는다.
- 책임과 의존성 방향:
  - `HTTP → vm_actions facade → operations/vm_shutdown application/domain/ports → infrastructure adapter`를 따른다.
  - recovery handler는 observation port만 받으며 mutation method나 router dependency를 갖지 않는다.
  - start/shutdown이 공유하는 것은 Operations core, durable lock, recovery repository와 작은 evidence utility로 제한한다.
- 데이터 소유권:
  - 새 table은 만들지 않는다. `operations`, `operation_events`, `operation_locks`, `operation_recovery_items`, 기존 `job_runs`/`job_artifacts`를 재사용한다.
  - 새 migration은 `operation_locks`의 operation type check에 `vm_shutdown`만 additive하게 추가한다.
  - recovery details는 node/VMID/UPID와 compact task/status만 저장하며 raw poll history, credential, lease token을 저장하지 않는다.
- 트랜잭션·정합성:
  - durable target lock과 recovery item은 external dispatch 전에 commit한다.
  - shutdown POST와 PostgreSQL은 원자적이지 않으므로 missing UPID/timeout을 no-side-effect로 추정하지 않는다.
  - valid lease fencing, Operation event/projection, recovery state와 target lock release는 기존 10-A transaction 경계를 재사용한다.
  - terminal Jobs compatibility projection 실패 시 recovery/lock을 완료하지 않고 재시도한다.
- API·DB·외부 시스템:
  - 공개 API는 additive endpoint와 response/error code만 추가한다.
  - PostgreSQL과 existing Proxmox API 외 신규 dependency는 없다.
  - Proxmox wrapper는 `POST /nodes/{node}/qemu/{vmid}/status/shutdown`, task status GET, current status GET만 사용한다.
- 보안·권한:
  - endpoint는 `require_operator`, server-side actor, origin/session 보호를 그대로 사용한다.
  - ack는 권한을 대체하지 않으며 exact target/name/status와 idempotency에 binding한다.
  - response/artifact/log는 secret과 raw upstream response를 redact한다.

## 5. 선택지와 결정

| 순위 | 선택지 | 적합한 이유 | 단점·비용 | 추천 여부 |
|---:|---|---|---|---|
| 1 | 독립 `vm_shutdown` vertical slice + 10-A 공통 lock/recovery 재사용 | VM Start를 크게 재작성하지 않아 회귀 범위를 제한하고 shutdown 고유 pre/post-condition과 오류 코드를 명확히 유지한다. 이후 두 action의 검증된 공통부만 추출할 수 있다. | workflow 일부가 VM Start와 유사해 단기 중복이 생긴다. | 추천 |
| 2 | VM Start와 Shutdown을 즉시 generic `vm_power` engine으로 통합 | 중복을 줄이고 다음 reboot 확장 기반이 될 수 있다. | 이미 검증된 Start 상태기계를 동시에 크게 바꿔 첫 destructive action의 실패 표면이 넓어진다. | 후속 리팩터링 후보 |
| 3 | Guided Manual shutdown부터 제공 | backend mutation 권한을 늘리지 않는다. | 사용자가 승인한 managed graceful shutdown/restart recovery 목표를 충족하지 못하고 기존 `qm unlock`과 달리 일반 lifecycle API가 이미 존재한다. | 비추천 |

- 방향 결정: `graceful shutdown + 운영 recovery 검증`은 사용자 승인됨.
- 상세 추천안: `1순위 — 독립 vm_shutdown vertical slice, additive endpoint/migration, GET-only restart recovery, force fallback 금지`.
- 상세 승인 상태: `승인 — 1순위 독립 vm_shutdown vertical slice`.
- 승인일: `2026-07-21`.

## 6. 구현 단계

| 단계 | 결과 | 변경 책임·예상 파일 | 검증 | 복구 지점 |
|---:|---|---|---|---|
| 0 | 현재 계약 characterization과 Plan 승인 | 이 Plan, mutation/recovery/frontend tests | focused baseline `52 passed`, public route/forbidden action source 고정 | production code 미변경 |
| 1 | shutdown domain·pre-check·port·use case | `backend/app/operations/vm_shutdown/**` | stable intent, ack/idempotency, running/template/moved/context tests | 새 module 제거 |
| 2 | Proxmox wrapper와 compatibility facade | `backend/app/proxmox/client.py`, `backend/app/vm_actions/shutdown.py` | exact endpoint, no force payload/fallback, redaction/error mapping | router 미연결 상태로 제거 가능 |
| 3 | durable lock type과 foreground recovery | 새 Alembic `0028`, lock/recovery domain allowlist, shutdown workflow | migration head, dispatch-before-recovery 금지, lease heartbeat/fencing, cross-action conflict | migration은 유지하고 endpoint/feature 미사용; additive correction |
| 4 | GET-only restart recovery와 runtime allowlist | recovery application/runtime/job projection | new runner instance resume, no second POST, lease takeover/stale fencing, mismatch lock retention | runner flag false, pending evidence 보존 |
| 5 | additive API·UI | router, API client, Workload Cockpit와 tests | auth/RBAC, ack modal, running-only affordance, route regression | endpoint/UI 제거; persisted evidence 유지 |
| 6 | production-like rollout 검증 | PostgreSQL integration, container restart harness 또는 equivalent test, runbook | actual PG migration/claim/fencing, disabled/enabled lifecycle, production image | flag false, open row audit, mutation drain |
| 7 | 독립 리뷰·문서 동기화 | quality review, project-docs/README | full suite, frontend lint/build, image, diff, docs link | Critical/High/Medium 해결 전 enable 금지 |
| 8 | run-specific live smoke | 별도 승인된 환경과 정확한 test VM | running→shutdown UPID→stopped, restart observer evidence | 대상 미지정이면 미실행으로 명시하고 Plan 구현 상태와 운영 rollout 상태를 구분 |

## 7. 성공·실패·데이터 흐름

- foreground 성공 흐름:
  1. authenticated operator, ack, idempotency와 expected target context를 확인한다.
  2. fresh inventory가 exact running non-template VM임을 확인한다.
  3. common Operation을 준비하고 durable+file target lock을 획득한다.
  4. Operation을 `dispatching`으로 전환하고 recovery item/foreground lease를 저장한다.
  5. graceful shutdown POST를 한 번 호출하고 UPID를 저장한다.
  6. lease heartbeat와 함께 task를 polling하고 direct VM state를 조회한다.
  7. task `OK`와 VM `stopped`를 확인해 `verifying → succeeded`, Jobs/artifact, fenced recovery completion과 lock release를 기록한다.
- restart recovery 성공 흐름:
  1. foreground process가 종료돼 lease가 만료돼도 recovery item과 target lock은 남는다.
  2. enabled runner가 새 generation/token으로 item을 claim한다.
  3. stored UPID task와 current VM status를 GET으로 관찰한다.
  4. 명확한 terminal success만 commit하고 Jobs projection 저장 후 lock을 release한다.
- 실패 흐름:
  - dispatch 전 validation/lock/recovery 저장 실패: POST 미호출, side effect 없음.
  - explicit non-ambiguous 4xx reject: `failed`, recovery/lock 안전 종료.
  - timeout, 408/425/429, connection failure, missing UPID: mutation retry 금지, reconciliation과 lock 유지.
  - task running: bounded retry wait. task/state mismatch나 unknown: paused/reconciliation, lock 유지.
  - lease loss: stale observer 결과 commit/lock release 금지.
  - Jobs/artifact 저장 실패: Operation terminal만으로 lock release하지 않고 compatibility projection 재시도.
- 데이터 변환:
  - historical row backfill/enqueue는 하지 않는다. 새 shutdown operation부터 신규 type/kind를 사용한다.
  - applied `0027`을 수정하지 않고 `0028`에서 check constraint만 확장한다.
- 재시도·멱등성·보상:
  - 동일 intent replay만 기존 result를 반환한다.
  - recovery는 observation/local projection만 재시도한다. shutdown POST, hard stop, reboot, start 보상을 자동 실행하지 않는다.

## 8. 테스트와 검증 계획

- 단위 테스트:
  - shutdown intent/job ID, ack/idempotency, running/template/moved/name/status pre-check.
  - task/state success mapping, compact recovery details, unknown/mismatch의 보수 처리.
- 통합·계약 테스트:
  - mutation client exact shutdown endpoint와 UPID requirement.
  - API auth/operator/admin, response envelope, idempotent replay/conflict, target lock conflict.
  - recovery registration failure·lease loss·persistence fault가 POST/lock/result 의미를 보존하는지 확인.
  - VM Start/Create/Guided/DRS와 shutdown의 cross-operation locator conflict.
  - migration head에서 `vm_shutdown` 허용과 기존 type 유지.
- 경계·실패 테스트:
  - crash after dispatch before UPID, after UPID before event, task timeout, post-check still running, compatibility projection failure.
  - 두 runner claim, expired lease takeover, stale worker fencing, disabled runtime, graceful application shutdown.
  - restart handler에 POST capability가 없고 second mutation 호출이 불가능한지 확인.
- Formatter·Lint·타입:
  - backend 별도 formatter/lint/type 명령은 없으므로 compile/import와 full test를 사용한다.
  - frontend Node test와 ESLint를 실행한다.
- 빌드·수동 확인:
  - local/backend full, canonical Python 3.13 container, actual PostgreSQL integration, frontend test/lint/Vite build, production image, `git diff --check`.
  - UI modal과 running/stopped action visibility를 browser에서 확인한다.
  - live smoke는 exact target과 별도 승인이 제공된 경우에만 실행한다.

## 9. 문서 영향

- Project Specification: graceful shutdown을 구현된 첫 destructive lifecycle action으로 범위/승인 기록에 반영한다.
- Architecture·ADR: current component/flow와 ADR-004의 action expansion 결과를 갱신한다. 10-A의 핵심 결정이 바뀌지 않으면 새 ADR은 만들지 않는다.
- Domain·Flow: Operations의 shutdown ownership, success/reconciliation과 restart observation 흐름을 추가한다.
- API·Database: additive endpoint/error/response와 migration `0028` lock type 확장을 기록한다.
- Runbook·Profile·상위 Plan: rollout audit, runner enable/disable, live smoke gate, 검증 baseline과 단계 10-B 결과를 반영한다.

## 10. 복구와 위험 완화

- 주요 위험:
  - 잘못된 target 종료, forced fallback, stale worker commit, lock 조기 release, 구버전 replica의 DB lock 우회.
- 예방·관찰 방법:
  - exact node/VMID/name/status binding, explicit ack/idempotency, POST 전 durable state, no-force client contract, task+direct post-check, lease fencing, Operation timeline/recovery/lock read model.
- rollback 또는 roll-forward:
  - endpoint/UI를 비활성화하고 runner flag를 false로 되돌린다. migration과 evidence는 유지한다.
  - 모든 replica를 durable-lock-aware version으로 맞추고 open lock/recovery row를 audit한 뒤에만 mutation traffic을 재개한다.
  - schema 문제가 있으면 applied revision을 수정하지 않고 additive correction migration을 사용한다.
- 중단 기준:
  - PostgreSQL partial unique/fencing/restart 검증 실패.
  - shutdown POST 전 recovery/lock durable 보장을 입증하지 못함.
  - forced stop/reboot fallback 또는 second POST 가능 경로 발견.
  - task/direct state 불일치를 success로 축소하거나 compatibility persistence 전에 lock이 풀림.
  - Critical/High/Medium quality finding 미해결.

## 11. 구현 후 대조

- 계획과 달라진 부분: foreground와 restart recovery는 계획대로 구현했다. production-like restart gate는 별도 container process를 장시간 운영하는 대신 실제 PostgreSQL 18.4에서 foreground lease expiry 후 새 repository/handler instance가 claim해 GET-only completion하는 integration으로 먼저 검증했다. 구현 완료 당시에는 exact target과 run-specific 승인이 없어 live smoke를 보류했지만, 2026-07-23 승인된 private test target `gjallar-mvp/yoonserver3/100/test`가 제공돼 별도 rollout 검증으로 수행했다.
- 달라진 이유: 구현 시점에는 실제 Workload Cockpit shutdown을 안전하게 재현할 대상이 없었고 product runtime에는 fake inventory mode가 없었다. 이후 사용자가 해당 test VM의 shutdown·restart와 장애 복구 smoke를 명시 승인해 미실행 gate를 해소했다.
- 최종 검증 결과:
  - local Python 3.14 backend 전체 `504 passed, 2 skipped`; 두 skip은 opt-in PostgreSQL integration.
  - canonical Python 3.13 container backend 전체 `504 passed, 2 skipped`.
  - PostgreSQL 18.4에서 migration head `0028` upgrade, downgrade `0027`, roll-forward와 `vm_shutdown` lock/partial unique/동시 claim/fencing/new-process GET-only recovery integration `2 passed`.
  - canonical Node 24/pnpm 10 production image stage에서 frontend test 17개, ESLint, Vite build 통과. host Node 26에서도 같은 17개와 lint/build를 보조 검증했다.
  - `docker build -t gjallar:local .`과 `git diff --check` 통과. 기존 Vite 500 kB chunk warning은 유지된다.
  - 2026-07-23 foreground live smoke에서 `test` VM의 running→graceful shutdown→stopped와 Start→running을 확인했다. 두 Operation은 각각 evidence 6개, recovery `completed`, locator lock `released`로 종료됐고 Proxmox active task는 0이었다.
  - 같은 target의 restart recovery smoke에서 새 shutdown의 `dispatch_accepted` 직후 backend를 중단했다. 중단 직후 VM `stopped`, Operation `running`, recovery `leased`, locator lock `active`가 보존됐고, 새 runner가 lease generation `1→2`, attempt `1→2`로 takeover해 `recovery_*` evidence 3개를 추가한 뒤 Operation `succeeded`, recovery `completed`, lock `released`를 기록했다. `dispatch_accepted`는 1개뿐이어서 shutdown mutation 재전송은 없었다.
  - 복구 smoke 후 VM Start를 완료해 최종 target은 `running`, active task 0이며 전체 non-terminal Operation·미완료 recovery·open locator lock은 0이다. 시험용 runner-enabled process는 종료하고 기본 disabled backend로 복원했다.
- 갱신한 현재 상태 문서: `README.md`, `backend/README.md`, Project Profile, Specification, Architecture, Domain Map, Verified Operation Lifecycle, API, Database, Runbook, ADR-004 후속 구현 기록과 상위 Plan.
- 남은 위험: production recovery flag 상시 enable과 production VM smoke는 수행하지 않았다. 이번 검증은 `PROXMOX_TLS_INSECURE=true`인 private test 환경의 단일 VM에 한정된다. runner는 API process와 resource를 공유하고 concurrency 1이며 Create VM/Guided/DRS 자동 handler와 generic operator unlock API는 없다. common Operation/recovery와 legacy Jobs/artifact projection은 하나의 원자적 transaction이 아니므로 terminal compatibility projection은 retained lock 상태에서 재시도한다.
