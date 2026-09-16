# 구현 계획: Operation reconciliation과 실행 흐름 안정화

> 종료된 계획의 당시 조사·승인·검증 기록이다. 현재 구현 지시가 아니며 후속 방향은 [계획 인덱스](../../plans/README.md), 현재 기준은 [문서 안내](../../README.md)를 따른다.

- 상태: `IMPLEMENTED`
- 날짜: `2026-08-26`
- 완료일: `2026-08-26`
- 위험도: `HIGH`
- 관련 요구사항: [`Project Specification`](../../specifications/project-specification.md)
- 관련 ADR: [`ADR-004`](../../decisions/adr-004-postgresql-durable-operation-recovery.md), [`ADR-007`](../../decisions/adr-007-observe-first-operations-intelligence.md)
- 관련 현재 상태: [`Architecture Overview`](../../architecture/overview.md), [`Verified Operation Lifecycle`](../../flows/verified-operation-lifecycle.md), [`Current API v1`](../../api/current-api-v1.md), [`Current Schema and Ownership`](../../database/current-schema-and-ownership.md), [`Operations Runbook`](../../operations/runbook.md)
- 선행 구현: [`Create VM common Operation 통합`](2026-07-21-create-vm-common-operation-integration.md), [`Operations backend core와 Guided qm`](2026-07-20-operations-backend-core-and-guided-qm.md), [`Durable Operation recovery foundation`](2026-07-21-durable-operation-recovery-foundation.md), [`Graceful VM Shutdown recovery`](2026-07-21-graceful-vm-shutdown-and-recovery-rollout.md), [`Observe → Explain → Verified Action 흐름 완성`](2026-08-26-observe-explain-evidence-flow-closure.md)
- 승인자: `사용자`
- 승인일: `2026-08-26`

이 Plan은 `Observe → Explain → Verified Action`에서 Operations가 실행 결과와 증거의 canonical surface라는 현재 제품 방향을 유지하면서, Create VM·Guided `qm unlock`·VM Start/Shutdown의 restart, persistence failure, ambiguous external effect와 retained target lock을 안전하게 다루는 가장 작은 공통 기반을 제안한다.

이 문서를 작성한 시점에는 코드, API, DB, UI, production data와 live Proxmox 상태를 변경하지 않았다. 구현은 사용자의 명시적 승인 뒤에만 시작한다.

## 1. 위험 판단과 조사 기준

### 위험 판단

- idempotency, same-target concurrency, durable lock, recovery lease/fencing과 ambiguous external effect의 의미를 바꾸므로 `HIGH` 위험 작업이다.
- 잘못된 자동 판단은 같은 VMID에 mutation을 중복 호출하거나, effect가 남아 있는 target의 lock을 풀거나, evidence가 불완전한 Operation을 성공으로 확정할 수 있다.
- DB schema migration은 현재 추천 범위에 필요하지 않지만, 기존 `operations`, `operation_events`, `operation_recovery_items`, `operation_locks`, Create compatibility request/workload/job projection을 함께 다루므로 transaction과 rollback 경계가 중요하다.
- 고위험 구현 완료 전에는 `$quality-review`로 구현과 분리된 검토를 수행한다.

### 확인한 현재 권위와 코드 경로

- 현재 제품 권위는 APPROVED Specification, ACCEPTED ADR-004/ADR-007, IMPLEMENTED recovery/Create/Guided/Shutdown Plan과 current-state 문서 순으로 확인했다.
- 주요 코드 경로는 다음과 같다.
  - common Operation state/event/repository: `backend/app/operations/core/**`
  - durable locator lock과 compatibility file guard: `backend/app/operations/locks/**`, `backend/app/operations/target_lock.py`
  - durable recovery lease/fencing/runner: `backend/app/operations/recovery/**`, `backend/app/main.py`
  - Create VM orchestration: `backend/app/vm_create/application.py`, `backend/app/vm_create/proxmox_runner.py`, `backend/app/operations/vm_create/**`
  - Guided `qm unlock`: `backend/app/operations/guided_qm/**`, `backend/app/api/v1/guided_qm.py`
  - Start/Shutdown: `backend/app/operations/vm_start/**`, `backend/app/operations/vm_shutdown/**`
  - canonical handoff/UI: `frontend/src/entities/operation/model.js`, `frontend/src/pages/operations/OperationDetailPage.jsx`, `frontend/src/features/guided-qm-unlock/**`, `frontend/src/components/CreateInstanceWizard.jsx`
- 조사 중 live Proxmox mutation, production data read/write, DB row 수정과 외부 시스템 변경은 수행하지 않았다.

## 2. 확인한 현재·전환·목표 상태

### 현재 상태

- common Operation은 append-only checksum event와 projection을 같은 transaction에서 저장하고, target identity와 scoped idempotency를 보존한다.
- VM Start/Shutdown은 external POST 전에 `operation_recovery_items`를 등록하고, stored UPID task와 direct VM state를 GET으로 다시 관찰한다. lease token/generation/expiry fencing과 Operation event/recovery state/durable DB lock release의 transaction 결합이 있다.
- Create VM과 Guided `qm unlock`은 common Operation과 durable locator lock을 사용하지만 recovery item과 restart handler가 없다.
- recovery runner는 Start/Shutdown handler만 allowlist하며 기본 설정은 disabled, concurrency는 1이다. `paused` item은 due claim 대상이 아니고 operator가 다시 관찰할 public control도 없다.
- durable locator lock은 lease expiry로 자동 해제되지 않는다. 이 보수성은 맞지만 Operation/recovery와 별도 transaction 또는 file guard 정리 실패로 terminal Operation 뒤에도 open lock이 남을 수 있다.
- Operation 상세 UI는 recovery와 target lock을 읽기 전용으로 보여주지만 Operation status만 terminal이면 polling을 중단하고, `paused` 또는 terminal Operation+active lock의 다음 행동을 제공하지 않는다.

### 전환 상태

- 기존 ADR-004의 recovery table, lease/fencing, in-process opt-in runner와 Operation/lock ownership을 재사용한다.
- 공통 coordination은 exact Operation/recovery/target/lock binding, dispatch 준비, lease claim, evidence commit, compatibility projection 재시도와 lock cleanup만 담당한다.
- 외부 결과 판정은 Create, Guided, Start, Shutdown의 action-specific GET-only handler가 담당한다.
- public control은 `operator+`의 “다시 관찰”만 먼저 추가한다. 범용 force success, force fail, force cancel, force unlock은 추가하지 않는다.
- Create와 Guided의 새 recovery item은 신규 실행부터 등록한다. 기존 historical Operation을 bulk enqueue하거나 자동 backfill하지 않는다.

### 목표 상태

- external effect 전에는 Operation, exact target lock과 durable recovery coordination이 복구 가능한 순서로 준비되며, 준비 실패 시 mutation 또는 manual instruction handoff를 진행하지 않는다.
- process crash 후 새 observer는 stored phase/task locator와 authoritative current state를 GET으로만 관찰하고, 동일 mutation을 재호출하지 않는다.
- action별 성공·실패 계약이 완전할 때만 local Operation과 compatibility projection을 roll-forward하고, 불명확하면 `needs_reconciliation`과 target lock을 유지한다.
- terminal Operation 전이, recovery completion과 durable DB lock release는 fenced transaction으로 닫히며 compatibility file guard는 owner 검증 후 재시도 가능하게 정리된다.
- 사용자는 canonical Operation 상세에서 recovery reason, latest observation, open lock, 자동/수동 경계와 허용된 다음 행동을 확인하고 `operator+`이면 read-only 재관찰을 요청할 수 있다.

## 3. 목표, 범위와 비범위

### 목표

1. Create VM과 Guided `qm unlock`을 기존 durable recovery coordination에 편입한다.
2. Start/Shutdown에 남은 no-item, `paused`, unbounded retry, terminal+open-lock과 file guard 고착 경로를 보강한다.
3. 모든 recovery에서 external mutation 재호출을 구조적으로 금지하고 action-specific evidence predicate를 유지한다.
4. Operation 상세를 사용자의 recovery evidence와 다음 행동이 모이는 canonical handoff로 완성한다.

### 범위

- `vm_create_observation`, `guided_qm_unlock_observation` recovery kind와 action-specific handler 추가
- mutation capability가 없는 전용 Proxmox observation port/adapter를 recovery runner와 operator-triggered observation에 주입
- Operation type/execution mode/target, recovery details, exact durable lock owner/scope의 binding 검증
- 기존 recovery table을 이용한 dispatch preparation, phase/task checkpoint, lease heartbeat, bounded retry와 `paused` 전환
- `POST /api/v1/operations/{operation_id}/recovery/observe` additive endpoint와 stable error contract
- Create VM의 clone/config/resize/optional start 각 mutation 전후 durable phase와 획득한 UPID/locator의 redacted checkpoint
- Guided plan의 ownerless lock 창 방지, exact original config lock을 이용한 expiry 판정, existing attestation/verification의 fenced recovery 결합
- Start/Shutdown의 `paused` item 재관찰, recovery item이 없는 명백한 pre-dispatch 상태의 side-effect-free 종료, terminal compatibility projection 재시도
- Operation transition/recovery state/exact durable lock status·release의 fenced transaction과 owner-matched compatibility file cleanup 재시도
- Operation detail recovery reason/latest observation/available action, recovery-aware bounded polling, Create readiness summary와 Guided stale-command 표현 보강
- Create post-create readiness evidence를 exact owning Create Operation에 안전하게 연결할 수 있을 때만 additive event/link로 연결
- 관련 backend/frontend unit, contract, failure-injection, PostgreSQL concurrency/restart 테스트와 current-state 문서 갱신

### 비범위

- Proxmox Create/Start/Shutdown/Unlock mutation의 recovery 재호출, inverse action, rollback mutation 또는 자동 remediation
- Gjallar backend에서 `qm unlock` shell command 실행
- “VM이 존재한다” 또는 current power/config state만으로 original operation 성공 추론
- 범용 `force success`, `force failed`, `force cancel`, `force unlock` API
- owner Operation이 없는 historical lock의 자동 삭제 또는 production DB 직접 수정
- 새 terminal status 또는 reconciliation disposition taxonomy, DB schema/data migration, backfill
- 별도 worker process, queue, scheduler, 신규 network service 또는 package dependency
- existing 39개 API route 삭제·변경, compatibility Jobs/request/workload/artifact 삭제, Overview UI 변경 또는 전체 UI 리뉴얼
- live Proxmox smoke/mutation, production data 변경, recovery runner의 production enable, commit 또는 push

## 4. 기능별 현재 상태와 실패 흐름

| 기능 | 현재 상태 모델 | 외부 effect 지점 | 현재 recovery 방식 | lock/lease 처리 | 사용자에게 보이는 evidence | 고착 또는 불명확 경로 | 추천 조치 |
|---|---|---|---|---|---|---|---|
| Create VM | `awaiting_approval → approved → dispatching → running → verifying → succeeded`; 불명확 결과는 `needs_reconciliation`, clear rejection은 `failed` | clone POST, disk resize, config update, optional start POST | common Operation replay와 compatibility request ownership guard만 있고 recovery item/handler 없음 | cluster+VMID durable lock 뒤 file guard. recovery lease 없음. ambiguity면 lock 유지 | Operation event/checksum, compact task/fingerprint/artifact checksum. full result와 readiness는 주로 Jobs/artifact에 남음 | request/job/Operation이 별도 transaction; UPID와 phase가 메모리에만 있음. artifact/evidence 또는 projection 실패 시 `dispatching|running|verifying`과 lock 고착. terminal 뒤 release 실패도 복구 불가 | POST 전 recovery item을 필수 등록하고 phase/UPID를 즉시 checkpoint. GET-only Create handler가 complete task+exact fingerprint/readiness일 때만 local projection을 roll-forward. readiness summary와 post-create evidence를 owning Operation에 연결 |
| Guided `qm unlock` | `awaiting_operator → awaiting_verification → verifying → succeeded`; expiry/late/mismatch는 `expired|needs_reconciliation` | backend mutation은 없음. operator가 외부 shell에서 command 실행 | idempotent plan replay, attestation, explicit verification만 있음. expiry는 same-plan/new-plan 경로에서만 lazy 평가 | Operation 생성 전에 durable+file lock을 먼저 잡음. recovery lease 없음. terminal 전이 뒤 별도 release | instruction bundle, attestation, verification event, target lock | lock 획득 후 Operation 저장 전 crash는 ownerless lock. `awaiting_operator`는 재조회만으로 expire하지 않음. expiry는 original lock 동일성을 확인하지 않음. terminal/release 사이 crash. expired 뒤 late attestation은 lock 없이 reconciliation | plan preparation/finalization을 recoverable하게 바꿔 ownerless 창을 제거하고 recovery item을 handoff 전에 저장. exact original config lock+no active task+no attestation일 때만 expiry. `verifying` restart와 explicit verification을 same handler/fenced commit으로 처리. stale command는 historical/do-not-execute로 표시 |
| VM Start | `planned → dispatching → running → verifying → succeeded|failed`; ambiguity는 `needs_reconciliation` | Start POST 1회 | stored UPID task와 VM status를 GET하는 durable handler | POST 전 leased recovery item, heartbeat/fencing. known result는 recovery+Operation+DB lock transaction 후 file guard 정리 | Operation, Jobs, observed-after artifact, recovery/lock summary | recovery item 전 crash는 runner가 못 찾음. POST 후 UPID 저장 전 crash는 missing-UPID `paused`. `paused` 재개 API 없음. retry가 무한. terminal projection 뒤 file cleanup crash 가능 | common prepare transaction으로 no-item 창을 축소. exact pre-dispatch는 side-effect-free `failed`. operator GET-only observe로 `paused` 재관찰. retry budget과 exact binding/file cleanup 보강 |
| VM Shutdown | `planned → dispatching → running → verifying → succeeded`; ambiguity는 `needs_reconciliation` | graceful Shutdown POST 1회 | stored UPID task와 VM status를 GET하는 durable handler | Start와 같은 lease/fencing/retained lock | Operation, Jobs, observed-after artifact, recovery/lock summary | Start와 같은 no-item/paused/unbounded/file 고착. mismatch를 자동 failed로 닫지 않아 manual 판단 대기 | 기존 보수적 outcome predicate를 유지하고 common recovery 보강만 적용. 명확한 task OK+stopped에서만 success, 나머지는 관찰 evidence 후 retained lock |

### Create VM의 확인된 crash·persistence 순서

1. common Operation은 plan 단계에 만들어지지만 execution의 request `running`, job `running`, Operation `dispatching`은 서로 다른 transaction이다.
2. target lock 뒤 compatibility request/job 기록 또는 dispatch event가 실패하면 external effect가 없어도 request `running` 또는 Operation `approved|dispatching`이 남을 수 있다.
3. `run_proxmox_create()` 안에서 clone UPID, resize/config/start phase는 함수가 반환하기 전까지 durable checkpoint가 아니다.
4. clone/config/start 이후 artifact write나 예상하지 못한 예외가 발생하면 Operation `dispatching`, compatibility record `running`, retained lock만 남을 수 있다.
5. 정상 result 뒤에도 `dispatching → running → verifying`, request completed, workload, Jobs completed, Operation succeeded가 분리되어 어느 persistence failure에서도 projection drift가 생길 수 있다.
6. completed compatibility request와 workload가 모두 있으면 replay가 mutation 없이 일부 local projection을 닫을 수 있지만, workload linkage가 없거나 terminal lock이 남은 경로에는 public recovery가 없다.

### Guided `qm unlock`의 확인된 crash·expiry 순서

1. durable lock과 file guard를 먼저 획득하고 authoritative observation 뒤 Operation을 저장한다. lock commit과 Operation create 사이 crash는 owner Operation이 없는 open lock을 만든다.
2. `awaiting_operator` expiry는 common GET이나 Guided get에서 평가되지 않는다. same idempotency plan replay 또는 동일 target의 새 Guided plan이 owner를 검사할 때만 lazy 평가된다.
3. current expiry predicate는 config lock이 non-empty인지 확인할 뿐 발급 시 `observed_before.config_lock`과 같은 값인지 확인하지 않는다.
4. attestation 뒤 verification은 GET-only이며 `verifying` crash는 같은 endpoint로 재개할 수 있다. 이 부분은 유지 대상이다.
5. `succeeded` 또는 `expired` transition 뒤 lock release가 별도라 crash/persistence failure 시 terminal Operation+open lock이 가능하다.
6. 이미 `expired`로 닫혀 lock이 풀린 뒤 late attestation이 들어오면 `needs_reconciliation`으로 전이하지만 target exclusion을 복구하지 못해 verification을 완료할 수 없다.

### Start/Shutdown recovery의 확인된 강점과 잔여 gap

- recovery item persistence 실패 시 external POST를 하지 않는 fail-closed 계약, lease takeover/fencing, GET-only result observation과 mutation retry 금지는 유지한다.
- task/state와 Operation outcome, recovery state, durable DB lock release를 transaction으로 묶는 기존 `commit_observation()`은 공통 기반으로 재사용한다.
- `paused`는 due claim에서 제외되고 public observe/resume control이 없으므로 missing UPID와 mismatch는 영구 수동 대기다.
- runner 기본 disabled 환경에서는 `retry_wait`도 process restart 뒤 자동 진전하지 않는다.
- terminal Operation 뒤 compatibility Jobs projection이 실패하면 recovery는 의도적으로 leased/open-lock 상태지만 frontend polling은 terminal Operation만 보고 멈춘다.
- durable DB lock release 뒤 file guard cleanup 사이 crash가 나면 completed recovery는 다시 claim되지 않아 file guard가 고착될 수 있다.

## 5. 확인된 gap 분류

| 분류 | 확인된 경로 | 안전 의미 |
|---|---|---|
| non-terminal 고착 | Create `approved|dispatching|running|verifying`, Guided `awaiting_operator|awaiting_verification|needs_reconciliation`, Start/Shutdown `paused` | 시간 경과만으로 terminal 처리하거나 lock을 풀지 않는다. recovery evidence와 명시적 next action이 필요하다 |
| effect 뒤 evidence 미완결 | Create clone/config/start 뒤 checkpoint/artifact/projection 실패, Guided command 실행 뒤 attestation 저장 실패, Start/Shutdown terminal task 뒤 artifact/Jobs failure | external mutation은 재호출하지 않고 task/current state 관찰과 local projection만 재시도한다 |
| lock 영구 유지 | Guided ownerless lock, Create/Guided terminal-release split, recovery DB release/file cleanup split, paused ambiguity | exact owner/target/evidence binding이 없으면 release하지 않는다. ownerless historical lock은 자동 정리하지 않는다 |
| mutation 재호출 위험 | Create final endpoint 재시도, missing-UPID Start/Shutdown, stale Guided instruction | request/job guard에만 의존하지 않고 recovery handler가 mutation method를 소유하지 않도록 구조적으로 제한한다 |
| 사용자 handoff 단절 | Create가 Operation으로 이동한 뒤 pre-dispatch failure가 `approved`로 남음, terminal Operation+recovery incomplete polling 중단, post-create readiness 별도 Jobs record, no observe control | Operation detail이 recovery 상태와 action별 next action을 canonical하게 제공해야 한다 |
| 중복 구현 | 네 action이 각자 lock release, target evidence, error/result projection을 조합 | coordination primitive만 공통화하고 outcome predicate와 compatibility projection은 action별로 유지한다 |
| manual authority | missing UPID, partial Create, stale/late Guided command, task history 만료, target identity/owner mismatch | generic status override나 unlock은 첫 범위에서 금지하고 후속 action-specific disposition 계약으로 분리한다 |

## 6. 공통화 경계와 action별 책임

### 공통화할 부분

- external effect 또는 instruction handoff 전에 exact Operation, durable locator lock과 recovery item을 준비하는 coordination transaction
- recovery item의 exact claim, token/generation/expiry fencing, heartbeat, bounded backoff와 `paused`
- `recovery_kind ↔ operation_type ↔ execution_mode ↔ target_type/target_id ↔ node/VMID ↔ lock owner/scope` binding 검증
- action-specific observer가 반환한 compact evidence의 redaction, event append, projection version/checksum과 recovery details 갱신
- ambiguity에서 Operation `needs_reconciliation`과 durable lock `reconciliation_required`를 같은 transaction에 기록
- terminal Operation/recovery completion/exact durable lock release의 fenced transaction
- compatibility file guard를 exact owner metadata로 먼저 정리하고, 실패하면 DB lock을 풀지 않는 재시도 가능한 cleanup
- terminal 뒤 compatibility projection 재시도와 recovery-aware Operation read model/polling
- `operator+`의 explicit GET-only observation request, trusted request actor event와 system observer event

### action별로 분리 유지할 부분

- Create: clone/start UPID, resize/config phase, expected config/fingerprint, power policy, guest-agent/cloud-init readiness, request/workload/job/artifact projection
- Guided: allowlisted config lock, `Sys.Audit`, active task double-read, instruction TTL, operator attestation, late/stale command 의미와 no-backend-execution 경계
- Start: task `OK`+VM `running` 성공, terminal non-OK+VM `stopped` 실패 predicate
- Shutdown: task `OK`+VM `stopped` 성공과 그 외 mismatch의 보수적 reconciliation predicate
- action별 user-facing reason, retry eligibility, compatibility payload와 manual disposition 의미

### 만들지 않을 공통화

- status 이름만 보고 outcome을 결정하는 generic recovery handler
- Proxmox POST method를 가진 recovery client
- arbitrary command/callable/dynamic handler registry
- current state만 보고 original effect를 추론하는 generic success evaluator
- Operation owner나 fresh evidence 없이 lock을 해제하는 generic unlock endpoint

## 7. 자동 복구와 수동 판단 경계

| 범위 | 자동 또는 operator-triggered GET-only로 허용 | 수동 판단 필요 또는 금지 |
|---|---|---|
| 공통 | exact binding 확인, task/current state 재관찰, local evidence append, compatibility projection 재시도, verified terminal 뒤 owner-fenced lock cleanup | lease expiry/process death만으로 terminal 판정 또는 release, different-owner/missing lock 자동 수리 |
| pre-dispatch | durable ordering상 recovery registration 전 POST가 불가능하고 dispatch/task reference가 없음을 증명하면 side-effect-free `failed`로 종료 | 코드 version/ordering을 증명할 수 없는 historical row 또는 ownerless historical lock 자동 종료 |
| Create | known clone/start task와 exact config/fingerprint/power/readiness가 기존 success 계약을 모두 충족할 때 local projection roll-forward. known terminal failure+target absence면 failed | missing UPID, partial clone/resize/config/start, VM 존재만으로 성공, 자동 continuation/delete/compensation, VMID continuity 불명 |
| Guided | unattested expiry에서 exact original config lock이 그대로이고 active task가 없으며 owned lock이 일치할 때 `expired`+release. persisted `verifying`의 GET-only resume | command 실행/재실행, changed/missing lock, late/stale command의 영향 추론, expired Operation의 무조건 lock 재획득 |
| Start | stored UPID task와 direct state가 기존 success/failure predicate를 충족할 때 terminal | missing UPID, task history 만료, task/state mismatch에서 state-only 성공 |
| Shutdown | stored UPID task `OK`와 direct `stopped`가 일치할 때 success | missing UPID, task/state mismatch의 자동 failed/success |

첫 구현에는 generic manual close/release를 넣지 않는다. 현재 status taxonomy의 `cancelled`는 “effect가 불명확하지만 운영자가 residual risk를 수용하고 lock을 해제함”을 정확히 표현하지 않고, generic success/failure override는 action별 evidence 계약을 약화한다. 필요한 경우 다음 Plan에서 action-specific disposition, `admin` 권한, exact latest checksum/version, fresh observation, bounded reason/evidence reference, lock release 의미와 새 terminal status 필요성을 별도 승인한다.

## 8. 선택지 비교와 추천 결정

| 순위 | 선택지 | 적합한 이유 | 단점·비용 | 추천 |
|---:|---|---|---|---|
| 1 | 기존 recovery foundation 보강 + Create/Guided action-specific GET-only handler + operator observe | 기존 ADR-004, table, lease/fencing과 modular monolith를 재사용한다. mutation capability를 늘리지 않고 네 action의 공통 고착 경로와 canonical Operation handoff를 한 vertical slice로 닫는다. DB migration 없이 단계별 rollback이 가능하다. | Create phase checkpoint와 Guided plan coordination ordering을 바꿔 failure-injection/PostgreSQL 검증이 필요하다. ambiguity의 강제 종료는 남는다. | **추천** |
| 2 | Start/Shutdown의 `paused` control과 UI만 우선 보강 | 가장 작고 현재 handler를 그대로 재사용한다. | Create/Guided의 가장 큰 restart/evidence gap과 ownerless/terminal lock이 남아 이번 조사 목표를 충족하지 못한다. | 임시 완화만 가능 |
| 3 | generic recovery/force-release API와 한 개 outcome engine | surface가 단순해 보이고 모든 lock을 닫을 수 있다. | action evidence와 manual authority를 평탄화해 잘못된 success/release 위험이 크다. 새로운 disposition/status 계약과 migration까지 필요할 수 있다. | 비추천 |
| 4 | 별도 worker/queue와 saga로 재설계 | process 격리와 확장성에 유리하다. | 현재 single-image 규모에 비해 deployment, delivery semantics와 운영 의존성을 크게 늘린다. 별도 architecture approval이 필요하다. | 현재 비추천 |

추천 결정은 **선택지 1**이다. 이번 승인 범위는 common coordination primitive와 action-specific observer를 추가하는 것이며, Operations 도메인 경계나 deployment topology를 바꾸지 않으므로 별도 `$architecture-evolution`은 필요하지 않다고 판단한다. 구현 중 새 worker/service, 새 terminal taxonomy 또는 schema migration이 필요해지면 즉시 중단하고 별도 승인을 요청한다.

## 9. 추천 구현 단계

| 단계 | 결과 | 주요 변경 책임 | 검증 | rollback/stop 경계 |
|---:|---|---|---|---|
| 0 | crash/persistence/lock 계약 characterization | backend/frontend tests, existing docs | 네 action의 no-item, missing-UPID, terminal-release, artifact/projection failure, Guided expiry/orphan과 UI polling을 failing/characterization test로 고정 | production code 변경 전 |
| 1 | common recovery coordination hardening | recovery domain/ports/repository/runtime, target lock repository/facade | mutation-free observation adapter, exact kind/type/target/lock binding, exact-item claim, bounded retry, `reconciliation_required`, file cleanup failure, stale lease fencing, PostgreSQL concurrency | schema/new service 필요 시 중단 |
| 2 | Start/Shutdown recovery control 완성 | Start/Shutdown handlers/workflow, Operations API | pre-dispatch no-effect closure, `paused` operator observe, known-UPID outcome, terminal compatibility projection retry, no second POST call count | outcome predicate 변경 시 action별 재검토 |
| 3 | Create VM durable checkpoint/recovery | Create workflow/runner/tracker, recovery handler, compatibility repositories | POST 전 item 필수, clone/resize/config/start phase와 UPID checkpoint, heartbeat, every-step crash, artifact/event/request/workload/job failure, exact success/failed predicate, mutation call-once | partial effect를 계속 실행/보상해야 하면 중단 |
| 4 | Guided durable expiry/restart recovery | Guided use case/ports/handler, coordination repository | ownerless preparation crash 방지, instruction handoff 전 item, exact original lock expiry, active task, attestation persistence, `verifying` restart, terminal+lock transaction, late attestation, no command execution | generic lock reacquire/force release 필요 시 중단 |
| 5 | canonical Operation API/UI handoff | Operations facade/API, frontend model/detail, Create/Guided components | `operator+` observe, viewer read-only, recovery-aware bounded polling, `paused` next action, terminal+open-lock warning, Create readiness/artifact summary, post-create evidence exact link, Guided stale command style | Overview 또는 existing route 변경 필요 시 중단 |
| 6 | 전체 검증과 current-state 동기화 | tests, current API/DB/flow/architecture/runbook docs | backend full, frontend contracts/ESLint/build, PostgreSQL restart/concurrency, container verify, route registry, `git diff --check` | 미실행 검증을 성공으로 표현하지 않음 |
| 7 | 구현과 분리된 고위험 검토 | `$quality-review` | public contract, RBAC, mutation capability, ambiguous outcome, fencing, lock cleanup, redaction과 UI authority 검토 | unresolved Critical/High/Medium이면 완료 중단 |

각 단계는 앞 단계의 relevant test가 통과한 뒤 진행한다. 단계 3과 4는 서로 다른 action-specific handler로 유지하며 한 workflow로 합치지 않는다.

## 10. API·DB·권한·UI 영향

### API

- 신규 additive route:
  - `POST /api/v1/operations/{operation_id}/recovery/observe`
  - 요청은 non-empty idempotency key 또는 expected Operation version/checksum을 사용해 중복 request event를 구분한다.
  - live lease는 stable `409`, unsupported/ineligible 상태는 stable `409`, observation/persistence unavailable은 stable `503`으로 구분한다.
- 기존 Guided attestation/verification route는 유지하고 내부적으로 같은 action-specific observation/fenced commit을 재사용한다.
- `GET /api/v1/operations/{operation_id}`의 기존 field를 유지하면서 recovery reason, phase, latest observation summary, automation eligibility와 available actions를 additive하게 제공한다.
- Create execution/error와 post-create readiness response에는 확인 가능한 exact `operation_id`/link를 additive하게 제공한다.
- 기존 39개 route는 삭제하지 않는다. 신규 route 추가에 맞춰 route registry와 RBAC contract를 갱신한다.

### DB와 transaction

- 현재 `operation_recovery_items.recovery_kind`는 `String(80)`이며 DB check constraint는 status에만 있다. 추천 범위의 새 recovery kind는 domain allowlist 확장만으로 저장할 수 있어 새 migration을 예상하지 않는다.
- 기존 `operation_recovery_items.details`에 redacted node/VMID, exact target, phase, UPID/task locator, expected fingerprint/readiness와 projection progress를 bounded payload로 저장한다.
- existing `operation_locks.status`의 `reconciliation_required`를 실제 ambiguity transaction에서 사용하고, exact lock ID/scope/owner만 transition/release한다.
- Operation event/projection, recovery state와 durable DB lock transition/release는 lease fence를 확인한 한 transaction에서 commit한다.
- compatibility file guard는 DB transaction 밖에서 owner/target/lock metadata를 확인해 먼저 정리한다. missing은 idempotent success, mismatch/OSError는 DB lock release 금지와 retry evidence로 처리한다.
- Create request/workload/job/artifact는 기존 compatibility ownership을 유지한다. recovery가 idempotent projection progress를 기록하고 완료될 때까지 target lock을 유지한다.
- historical row bulk backfill, row delete, data rewrite는 하지 않는다. 실제 deployed schema가 조사한 Alembic head와 다르거나 새 constraint가 필요하면 구현을 중단한다.

### 권한과 실행 권위

- `viewer+`: Operation/recovery/lock/evidence와 available action 설명 조회
- `operator+`: 기존 Create/Start/Shutdown/Guided 실행 권위와 신규 GET-only `recovery/observe`
- `admin`: 이번 범위에서 별도 force closure/release 권한을 추가하지 않는다.
- recovery request actor와 system observer actor를 구분해 append-only event에 기록한다.
- runner와 observe endpoint는 mutation method가 없는 port만 받는다. Proxmox credential, URL, raw response, token, password, private key, lease token은 payload/log/API에 노출하지 않는다.
- Guided command는 backend가 실행하지 않으며 TTL 이후에는 UI에서 historical/do-not-execute evidence로만 표시한다.

### UI와 handoff

- Overview 구조와 시각 방향은 변경하지 않는다.
- Operation detail의 Recovery coordination에 reason, phase, latest observation, retry/paused/completed, open lock과 allowed next action을 표시한다.
- `paused` 또는 eligible `needs_reconciliation`에서 operator에게만 `다시 관찰`을 제공한다. 버튼은 mutation 재시도를 의미하지 않음을 명시한다.
- Operation이 terminal이어도 recovery가 incomplete하거나 target lock이 open이면 bounded polling을 계속한다. `paused`는 polling을 멈추고 manual authority 필요를 표시한다.
- Create wizard의 immediate Operation handoff는 유지하되, execution 전후 오류가 해당 Operation event/status에 남도록 backend flow를 닫는다.
- Create Operation에 sanitized readiness summary, artifact checksum/reference와 exact workload link를 표시한다. 별도 post-create readiness evidence는 owning Create Operation이 exact하게 확인될 때 event/link를 추가하고, 그렇지 않으면 기존 Jobs-only record를 유지한다.
- Guided command는 expiry 전 `awaiting_operator`에서만 실행 가능한 instruction으로 보이고, 그 외 상태에서는 historical evidence와 재실행 금지 경고로 표시한다.

## 11. 인수 조건

- Create, Start, Shutdown은 external POST 전에 exact Operation, target lock과 durable recovery item이 준비된다. 준비 실패 시 mutation client의 POST call count는 0이다.
- Guided instruction은 recovery 가능한 Operation/lock/item coordination이 durable해지기 전 사용자에게 반환되지 않는다.
- Create의 clone/resize/config/start 각 mutation phase와 획득한 UPID/task locator가 다음 mutation 전에 durable하게 checkpoint된다. checkpoint 실패 뒤 후속 mutation을 진행하지 않는다.
- restart recovery와 operator observe가 Proxmox GET/task observation만 호출하며 Create/Start/Shutdown POST 또는 `qm` command를 재호출하지 않는다.
- action-specific terminal predicate가 완전할 때만 success/failed로 닫고, missing UPID, partial effect, task/state/identity mismatch는 `needs_reconciliation`과 lock을 유지한다.
- Guided unattested expiry는 exact original config lock, no active task와 exact owned lock이 모두 확인될 때만 `expired`와 release가 같은 fenced flow로 완료된다.
- `paused` Start/Shutdown/Create/Guided eligible item은 operator가 다시 관찰할 수 있고 request/result actor·evidence가 checksum chain에 남는다.
- terminal Operation 뒤 compatibility projection이나 file guard cleanup이 실패하면 recovery/lock이 incomplete로 보이며, 재시도로 local coordination만 완료된다.
- Operation/recovery/lock exact binding이 깨지면 fail-closed하고 다른 target 또는 owner의 lock을 release하지 않는다.
- terminal Operation+open lock도 UI에서 숨지 않고 polling 또는 action-required 상태로 보인다.
- Create success/readiness와 post-create evidence가 exact owning Operation에 연결되며 Jobs compatibility record는 유지된다.
- viewer/operator/admin RBAC, secret redaction, existing response envelope, 기존 39개 route와 canonical Workloads → Insights → Operations deep link가 회귀하지 않는다.
- full backend/frontend/container/PostgreSQL 검증, `git diff --check`와 독립 `$quality-review`가 통과한다.

## 12. 검증 전략

### 단위·도메인 테스트

- recovery kind/type/execution mode/target/lock exact binding과 malformed/corrupted row fail-closed
- exact-item claim, live lease `409`, expired lease takeover, stale generation/token commit 거부
- attempt/backoff budget, unavailable retry와 `paused` threshold
- owner-matched file cleanup의 missing/mismatch/OSError 의미
- secret-bearing upstream details가 method/path/status/error type 중심 allowlist evidence로 축소됨

### action별 failure-injection

- Create:
  - lock, request running, job running, dispatch/recovery prepare 각 persistence failure에서 POST 미호출
  - clone call 직전/직후, UPID checkpoint, clone poll, resize, config, optional start, post-check, artifact write 각 crash
  - Operation running/verifying, request completed, workload, Jobs completed, Operation succeeded 각 projection failure
  - every replay/recovery에서 clone/resize/config/start call count가 증가하지 않음
- Guided:
  - provisional plan lock 뒤 Operation/item finalize 전 crash와 stale finalizer fencing
  - common GET이 임의로 state를 mutate하지 않음
  - exact original lock 유지/no task expiry, changed lock, lock absent, active task, observation unavailable
  - attestation 전/후 crash, `verifying` restart, terminal transition 뒤 cleanup failure, expired 뒤 late attestation
  - backend command executor와 arbitrary command field 부재
- Start/Shutdown:
  - pre-dispatch Operation/lock/no-item, POST 후 UPID 미저장, known UPID task running/success/mismatch
  - `paused` explicit observe, terminal compatibility projection retry, file cleanup failure
  - existing action-specific success/failure semantics 회귀 없음

### API·frontend 계약

- viewer는 observe `403`, operator/admin은 eligible state에서만 observe 가능
- same request idempotency, live lease/state/version conflict, stable `409/503`, response envelope와 route registry
- Operation detail recovery-aware polling start/stop, stale-response guard, unmount/error handling
- `paused`, terminal+open-lock, Create readiness, Guided expiry/stale command와 next-action 표현
- existing Workloads/Insights/Operations exact-target navigation, Create handoff와 Guided attestation/verification 회귀

### 통합·전체 검증

- actual PostgreSQL에서 concurrent exact-item claim, `SKIP LOCKED`, stale fencing, Operation/recovery/exact lock transaction과 crash takeover를 확인한다.
- recovery runner disabled/enabled, process restart, graceful shutdown과 two-runner contention을 fake Proxmox observation adapter로 검증한다.
- `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests`
- frontend contract tests, ESLint, production build
- `pnpm run verify`
- `pnpm run verify:container`
- Python 3.13 backend container와 production image build
- `git diff --check`
- live Proxmox mutation은 별도 run-specific 승인 없이는 실행하지 않는다.

## 13. rollback, roll-forward와 운영 경계

- background recovery flag는 기존처럼 default off를 유지한다. repository 구현과 PostgreSQL/failure-injection 검증 뒤에도 production enable은 이 Plan 승인에 포함하지 않는다.
- 신규 API/UI는 additive하므로 route/control wiring과 handler registration을 단계별로 비활성화할 수 있다.
- 새 recovery item/event는 삭제하지 않는다. rollback 시 runner와 observe endpoint를 disable하고 open item/lock을 read-only audit한다.
- code rollback은 old version이 신규 recovery/lock을 무시하지 않도록 mutation drain과 open coordination audit 뒤에만 수행한다.
- compatibility file cleanup 또는 durable lock release가 불완전하면 자동 DB delete를 하지 않고 same owner-fenced cleanup을 roll-forward한다.
- already dispatched effect는 task/current state를 관찰해 evidence만 추가하며 inverse mutation을 자동 실행하지 않는다.
- migration이 없으므로 schema downgrade는 없다. 구현 중 migration이 필요해지면 이 rollback 전략은 유효하지 않으므로 재승인한다.

## 14. 중단 조건과 남은 불확실성

### 중단 조건

- recovery path가 Proxmox POST, shell command, mutation continuation 또는 inverse action을 요구한다.
- recovery item/checkpoint persistence 실패에도 다음 external effect를 실행할 수 있다.
- stale lease owner가 event/transition/lock release를 commit하거나 exact target 외 lock을 release할 수 있다.
- lease expiry, process death, VM 존재/current state만으로 terminal success 또는 lock release를 결정해야 한다.
- owner Operation이 없는 historical lock을 자동 삭제해야 구현을 완료할 수 있다.
- generic manual closure, 새 terminal/reconciliation taxonomy, DB migration/backfill/delete가 필요하다.
- separate worker/queue/service 또는 Operations domain ownership/architecture를 바꿔야 한다.
- existing 39개 route 제거, Overview 변경, live Proxmox mutation 또는 production data 변경이 검증에 필수다.
- secret/raw credential/upstream payload를 evidence나 log에 저장해야 한다.

### 남은 불확실성

- 실제 배포 환경에서 recovery runner가 enable되어 있는지와 historical open lock/recovery item의 수는 repository만으로 확인할 수 없다.
- Proxmox task history retention과 clone/resize/config/start API가 제공하는 durable locator의 장기 조회 가능 범위는 fake와 current client contract 이상으로 확인되지 않았다.
- ownerless historical lock 또는 missing-UPID ambiguity를 최종 종료할 manual disposition taxonomy와 권한은 아직 승인되지 않았다.
- Guided expired 뒤 실제 late command가 실행된 경우 target lock 재획득과 VM generation continuity를 안전하게 증명하는 계약은 현재 없다.

이 불확실성은 자동 success/release 근거로 사용하지 않는다. production audit, manual disposition 또는 new schema가 필요하면 별도 Plan으로 분리한다.

## 15. 사용자 결정이 필요한 항목

1. **추천: 이 Plan의 선택지 1을 승인한다.** common coordination hardening, Create/Guided action-specific GET-only recovery, `operator+` observe와 Operation UI handoff까지 구현한다.
2. **추천: generic manual close/release는 이번 범위에서 제외한다.** missing UPID, partial Create, ownerless historical lock과 stale Guided command의 최종 disposition은 관찰 결과를 축적한 뒤 별도 Plan에서 admin 권한과 status 의미를 승인한다.
3. **추천: Guided unattested expiry의 자동 closure를 제한적으로 허용한다.** exact original config lock이 그대로이고 active task가 없으며 exact owned lock과 no attestation이 모두 확인될 때만 `expired`+release한다. 하나라도 불명확하면 `needs_reconciliation`+retained lock이다.

별도 반대 지시가 없으면 2번과 3번은 추천안으로 고정한다. 다만 1번 Plan 승인이 있기 전에는 구현을 시작하지 않는다.

## 16. 승인 문구

이 Plan의 승인은 **기존 Operations recovery foundation 안에서 common coordination과 lock/lease/fencing을 보강하고, Create VM과 Guided `qm unlock`의 action-specific GET-only recovery handler, Start/Shutdown의 operator-triggered 재관찰, additive recovery API/UI handoff, 관련 테스트와 current-state 문서 갱신을 구현하는 것**을 의미한다.

이 승인은 **live Proxmox mutation, production runner enable, production data 수정, generic force success/fail/cancel/unlock, ownerless historical lock 자동 삭제, 새 terminal status, DB schema/data migration, 별도 worker/queue/service, existing route 삭제, Overview 변경, 전체 UI 리뉴얼, commit 또는 push**를 의미하지 않는다.

승인하려면 `추천안대로 이 Plan을 승인한다`고 명시한다.

## 17. 구현 결과

사용자가 추천안을 승인한 뒤 다음 범위를 구현했다.

- Start/Shutdown/Create/Guided `qm unlock`에 공통 recovery coordination, lease·generation·Operation version/checksum·exact target lock fencing과 action-specific GET-only observation handler를 적용했다.
- `operator+`가 사용할 additive `POST /api/v1/operations/{id}/recovery/observe`와 Operation 상세의 recovery evidence·next action handoff를 추가했다. 기존 39개 route는 유지되며 전체 route는 40개다.
- external effect 뒤 persistence 실패, invalid task locator, partial/ambiguous effect, late attestation, malformed compatibility guard와 evidence append 실패를 `needs_reconciliation` 또는 보수적인 재관찰 경로로 닫았다. recovery는 mutation이나 shell command를 재호출하지 않는다.
- Start/Shutdown compatibility Jobs projection과 Operation/recovery/lock 전이를 같은 fenced transaction에 결합하고, Create artifact content hash·workload ownership과 post-create readiness의 exact Operation 연결을 검증한다.
- operator observe idempotency는 최초 version/checksum fence를 보존하는 최대 64개 durable ledger로 제한했으며, 상한 초과 요청은 lease claim 전 `409`로 거부되어 recovery state를 변경하지 않는다.
- recovery runner는 계속 default off다. generic force success/fail/cancel/unlock, historical backfill, DB schema/data migration, production runner enable, Overview 변경과 전체 UI 리뉴얼은 구현하지 않았다.

검증 결과는 다음과 같다.

- host backend 전체: `591 passed, 6 skipped`
- Python 3.13 backend container: `591 passed, 6 skipped`
- frontend 계약 테스트: `18`개 파일 통과
- ESLint와 production frontend build: 통과
- Node 24/pnpm 10 production image build: 통과
- disposable PostgreSQL 16에서 기존 migration head 적용 후 recovery integration: `3 passed`
- `git diff --check`: 통과
- 독립 Quality Review 2회: unresolved Critical/High/Medium/Low `0`

검증 과정에서 live Proxmox mutation과 production data 변경은 수행하지 않았고, disposable PostgreSQL container는 검증 뒤 제거했다. commit과 push도 수행하지 않았다.
