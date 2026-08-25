# 기능 흐름: Verified Operation Lifecycle

- 상태: `APPROVED`
- 최종 검토일: `2026-08-25`
- 관련 요구사항·도메인: [`Project Specification`](../specifications/project-specification.md), [`Domain Map`](../domains/domain-map.md), [`ADR-004`](../decisions/adr-004-postgresql-durable-operation-recovery.md), [`ADR-007`](../decisions/adr-007-observe-first-operations-intelligence.md)

이 문서는 선택적 Verified Action의 공통 흐름과 현재 구현된 slice를 함께 설명한다. VM Start, graceful VM Shutdown, Create VM과 Guided `qm unlock`은 공통 Operation core를 사용한다. DRS와 migration은 action/API/runtime에서 제거됐고 이 lifecycle에 포함되지 않는다.

## 현재 구현 범위

- VM Start, VM Shutdown, Create VM과 Guided `qm unlock`은 현재 한 개의 configured Proxmox cluster를 전제로 같은 cluster/VMID의 PostgreSQL durable locator lock을 공유한다. 전환 중 local file guard도 dual acquire하며 같은 VMID의 다른 node 표기는 별도 target으로 취급하지 않는다.
- VM Start/Shutdown은 same-key replay/intent conflict와 ambiguous dispatch·task·post-check의 `needs_reconciliation` 보존을 구현했다. Shutdown은 graceful POST만 허용하고 force-stop/reboot fallback을 금지한다.
- Create VM은 plan에서 common Operation을 준비하고 exact approval, preview, dispatch, task/result, workload linkage를 event로 기록한다. completed replay, same-key intent conflict, VMID owner guard와 명확한 실패/불명확한 결과의 구분을 유지한다.
- VM Start/Shutdown은 API compatibility facade에서 infrastructure-free command와 use case로 진입하고 Workloads, mutation, Jobs, Evidence, lock/recovery를 명시적 port로 받는다. 검증 workflow는 각각 `operations/vm_start/workflow.py`, `operations/vm_shutdown/workflow.py`에 있고 공통 projection/event와 기존 job/artifact를 함께 기록한다.
- 첫 Guided Manual action `qm unlock <vmid>`은 typed plan, 5분 expiry, trusted attestation, Proxmox API verification과 reconciliation을 공통 Operation으로 기록한다. backend command executor는 없다.
- Workload Cockpit은 Nodes/VMs endpoint의 observation provenance를 각각 보존하고, `proxmox_vm`·`vmid:<VMID>`가 정확히 일치하는 Readiness/Placement finding과 최신 200개 반환 범위의 최근 Operation을 VM에 연결한다. Insights·Operations 보조 조회의 HTTP 실패, section unavailable·unknown/stale와 finding truncation은 정상 0건으로 축소하지 않고 inventory availability와 분리한다. VM context는 Guided plan에 전달하며, Operations UI가 공통 projection 목록·상세 evidence timeline·attestation·API verification을 제공한다. viewer는 조회만 가능하고 mutation control은 `operator+`와 live connection을 함께 요구한다.
- VM Start/Shutdown 성공 결과와 오류 응답에 `operation_id` 또는 `job_id`가 포함된 recorded outcome은 common Operation이 조회되면 공통 상세로 이동하고, historical Job-only replay처럼 Operation projection이 없는 경우에는 명시적으로 Jobs compatibility 화면을 사용한다. 현재 target-lock-busy 오류는 common Operation을 먼저 기록하지만 응답에 correlation ID가 없어 Workload Cockpit이 해당 오류 결과를 직접 인계하지 못하며, 완전한 인계에는 additive backend 오류 계약이 필요하다.
- VM Start, VM Shutdown, Create VM과 Guided `qm`이 이 문서의 공통 Operation aggregate를 사용한다.
- VM Start/Shutdown에는 PostgreSQL recovery item/lease와 opt-in observation runner가 있다. generic operator recovery API와 Create VM/Guided 자동 handler는 아직 없으며 lease expiry나 process restart만으로 side effect가 없다고 판단하지 않는다.

## 목적과 진입점

- 해결하는 문제: API와 guided manual operation의 action별 gate, dispatch 또는 operator handoff, completion evidence, post-check와 reconciliation 의미를 통일한다.
- 시작 조건: authenticated actor, supported action, target reference 또는 create input, explicit execution mode.
- 호출 주체: React UI 또는 승인된 `/api/v1` consumer.
- 최종 결과: verified `succeeded`, side-effect 없는 terminal result, 또는 복구 가능한 non-terminal/reconciliation state.

## 상태 모델

```text
draft
→ planned
→ [action별 필요한 경우 awaiting_approval → approved]
→ dispatching
→ running | awaiting_operator
→ verifying | awaiting_verification → verifying
→ succeeded

어느 단계에서든 조건에 따라:
blocked | rejected | expired | failed | needs_reconciliation | cancelled
```

- `blocked`: dispatch 전에 validation, RBAC, capability, pre-check, policy가 실패했다.
- `failed`: external system이 side effect 없이 명확히 거절했거나 terminal failure가 명확하다.
- `needs_reconciliation`: side effect 여부 또는 external result가 불명확하거나 post-check가 불일치한다.
- `awaiting_operator`: guided manual bundle을 발급했고 외부 실행/attestation을 기다린다.
- `awaiting_verification`: operator attestation은 있으나 authoritative after-state 확인이 끝나지 않았다.
- `succeeded`: action contract가 요구하는 external completion evidence, direct after-state와 evidence append가 모두 완료됐다. managed API action은 terminal task를, guided manual action은 authenticated operator attestation을 상관 연결한다. attestation 자체는 성공 권위가 아니다.

## 성공 흐름

```text
Authenticated request
→ Operation intent + idempotency identity 저장
→ Fresh workload observation/capability 확인
→ Action별 validation/pre-check와 필요한 경우 versioned policy 평가
→ Exact plan/evidence digest 생성
→ Action별 필요한 approval/acknowledgement binding 확인
→ Final pre-check + target lock/lease 획득
→ Dispatch attempt 기록
→ managed API dispatch 또는 guided manual bundle 발급
→ Action contract에 따라 external task 또는 operator attestation correlation
→ Direct after-state verification
→ Append-only evidence 저장 + current projection 갱신
→ Lock 해제
→ succeeded
```

### `managed_api`

1. dispatch attempt를 먼저 기록한다.
2. Proxmox API를 한 번 호출한다.
3. UPID/task reference를 즉시 operation에 연결한다.
4. terminal task와 direct after-state를 확인한다.
5. ambiguity가 있으면 자동 재호출하지 않는다.

### VM Start/Shutdown foreground와 restart recovery

1. durable locator lock과 compatibility file guard를 획득한 뒤 common Operation을 `dispatching`으로 기록한다.
2. Proxmox POST 전에 `operation_recovery_items`를 만들고 foreground lease를 획득한다. 이 단계가 실패하면 POST를 호출하지 않는다.
3. UPID를 저장하고 task poll 중 lease를 heartbeat한다. terminal task와 direct VM status를 확인한 fenced transaction만 success/failure와 lock release를 commit한다.
4. process가 종료되면 target lock은 남고 lease만 만료된다. enabled runner 하나가 `SKIP LOCKED`로 due item을 claim한다.
5. runner handler는 stored UPID task와 VM status GET만 수행한다. 같은 start/shutdown POST, 다른 mutation, manual fallback을 실행하지 않는다.
6. Start는 task `OK`와 running state, Shutdown은 task `stopped/OK`와 direct stopped state가 일치할 때만 `succeeded`; task가 진행 중이면 `retry_wait`; missing UPID 또는 mismatch는 `needs_reconciliation`/`paused`와 retained lock이다.

### `guided_manual`

1. allowlisted structured template과 validated parameter로 instruction bundle을 만든다.
2. bundle은 target identity, precondition, expiry, plan digest, command 또는 PVE UI 절차, 예상 결과, verification 절차를 포함한다.
3. operator는 Proxmox 환경에서 직접 실행하고 attestation을 제출한다.
4. pasted output은 optional sanitized evidence이며 성공 권위가 아니다.
5. Gjallar가 Proxmox API로 after-state를 검증한 뒤에만 성공할 수 있다.

### 현재 `qm unlock` slice

1. `node_id`, JSON integer `vmid`, `idempotency_key`, `qm_unlock_risk_acknowledged=true`만 받는다. command, arguments, options, secret-like extra field는 거부한다.
2. 같은 `proxmox_vm/vmid:{vmid}` local target lock을 잡고 `/access/permissions?path=/nodes/{node}`에서 `Sys.Audit`을 확인한다.
3. active task를 읽고 VM config lock을 읽은 뒤 active task를 다시 읽는다. task가 있거나 lock이 없거나 lock type이 allowlist 밖이면 instruction을 발급하지 않는다.
4. 허용 lock은 `backup`, `clone`, `create`, `migrate`, `rollback`, `snapshot`, `snapshot-delete`, `suspending`이다. steady suspended 상태와 혼동될 수 있는 `suspended`는 제외한다.
5. server가 정확히 `qm unlock <vmid>`를 생성하고 5분 expiry, observed lock, expected result, verification endpoint, `plan_digest`와 함께 저장한다.
6. operator의 `command_executed=true` attestation은 실행 사실 주장만 기록한다. 같은 digest를 제출해도 성공 권위는 아니다.
7. config lock 부재와 active task 부재를 API로 확인해야 `succeeded`가 되고 target lock을 해제한다. 불일치·관찰 실패·late attestation·target lock 유실은 `needs_reconciliation`이다.
8. attestation 없이 expiry가 도달하면 실제 config/task 상태를 다시 관찰한다. 외부 effect 가능성이 없을 때만 `expired`와 lock 해제로 끝낸다. 이후라도 실행 attestation이 들어오면 기록을 `needs_reconciliation`으로 다시 열어 stale command의 가능한 effect를 숨기지 않는다.
9. UI는 server가 발급한 command만 표시한다. expiry 시각이 지났거나 상태가 `expired`/`needs_reconciliation`이면 신규 실행을 금지하고, 이미 발생한 실행을 late evidence로 기록하는 문구와 control만 제공한다.

## 데이터 변환

```text
HTTP payload
→ Operation command DTO
→ Workload identity/capability + policy evidence
→ Immutable plan + digest
→ Managed API parameters 또는 Manual instruction bundle
→ External task/attestation
→ Verification result
→ Evidence event + Operation projection
→ HTTP resource
```

- browser actor는 DTO field가 아니라 server-side session에서 주입한다.
- human-readable plan과 canonical digest input을 분리한다.
- Proxmox payload와 output은 allowlist/redaction을 거친 최소 evidence로 변환한다.

## 상태와 트랜잭션

- 변경되는 상태: operation projection, attempts/steps, approval binding, lock/lease, external task ref, verification, evidence event.
- 데이터 소유자: Operations, Policy/Approval, Evidence/Audit.
- local transaction: intent/attempt/evidence와 projection 변경은 각 상태 전이의 invariant를 지키는 짧은 transaction으로 기록한다.
- external call: PostgreSQL transaction과 하나의 원자적 transaction으로 묶지 않는다.
- dispatch ordering: attempt를 persistent하게 기록한 뒤 external call하고, task reference를 가능한 즉시 별도 transition으로 기록한다.
- current projection은 재구성 가능한 최신 상태이며 immutable evidence와 동일시하지 않는다.
- recovery commit은 유효 lease generation/token 확인, Operation event/projection, recovery status와 optional target lock release를 같은 PostgreSQL transaction에서 처리한다.

## 실패 흐름

| 실패 지점 | 상태·오류 의미 | 상태 변화 | 재시도·보상 | 사용자 결과 |
|---|---|---|---|---|
| validation/RBAC/capability | 실행 불가 | `blocked`, side effect 없음 | 입력 수정 후 새 plan | block reason과 해결 조건 |
| policy/approval | 거절·만료·drift | `rejected`/`expired` | 재평가·재승인 | 변경된 evidence 표시 |
| lock conflict | 동일 target 충돌 | `blocked` 또는 대기 | 기존 operation 확인 | conflicting operation link |
| API explicit reject | side effect 없음이 명확 | `failed` | 정책에 따른 명시적 retry | Proxmox error의 안전한 mapping |
| timeout/missing task ref | side effect 불명 | `needs_reconciliation` | 자동 mutation retry 금지 | verification/reconcile action |
| task terminal failure | external failure 확인 | `failed` 또는 effect 불명 시 reconcile | action별 정책 | task evidence |
| task OK/post-check mismatch | 결과 불일치 | `needs_reconciliation` | direct observation 반복·수동 판단 | expected/observed diff |
| manual attestation only | 권위 있는 검증 없음 | `awaiting_verification` | API 재검증 | verification pending |
| evidence append failure | 성공 공표 불가 | recoverable non-success | evidence recovery | actual effect와 기록 상태를 구분 |
| recovery lease loss | stale observer 결과 | canonical 상태 변경 없음 | 새 owner가 stored task/state 재관찰 | retry/reconciliation 상태 조회 |

## 멱등성과 동시성

- 중복 요청: actor/action/target/intent에 연결된 idempotency key로 동일 operation resource를 반환한다.
- 같은 key의 payload 또는 plan digest가 다르면 conflict다.
- 다른 key라도 같은 target의 충돌 operation은 target-scoped lock/lease로 직렬화한다.
- timeout·process crash 후에는 stored attempt/task ref와 actual state를 reconcile하고 mutation을 재호출하지 않는다.
- lease expiry만으로 side effect가 없다고 가정하지 않는다.

canonical target coordination은 `(GJALLAR_CLUSTER_ID, VMID)`의 PostgreSQL partial unique locator lock이다. local file guard는 구버전·동일 container 호환을 위해 남아 있으며 recovery lease와 독립적이다. cluster identity는 environment의 단일 configured cluster를 전제로 하므로 multi-cluster connection profile을 도입할 때 partition·identity 계약을 다시 정해야 한다.

## 구현 위치

| 단계 | 현재 구현 후보 | 목표 책임 |
|---|---|---|
| HTTP facade | `backend/app/api/v1/router.py` | auth/validation, DTO, error/response mapping |
| Operation core | `backend/app/operations/core/` | 상태 전이, digest, projection/event port와 SQLAlchemy adapter |
| Durable coordination | `backend/app/operations/locks/`, `backend/app/operations/recovery/` | locator lock, due/lease/fencing, VM Start/Shutdown observation handler와 opt-in runner |
| VM Start application | `backend/app/operations/vm_start/` | command·stable intent, use case, 외부 port 계약 |
| VM Start compatibility | `backend/app/vm_actions/start.py` | 기존 공개 facade와 현재 infrastructure adapter 조립 |
| VM Shutdown application | `backend/app/operations/vm_shutdown/` | graceful shutdown command·stable intent, running pre-check, use case와 외부 port 계약 |
| VM Shutdown compatibility | `backend/app/vm_actions/shutdown.py` | 공개 facade, Proxmox/Jobs/Evidence/Lock/Recovery adapter 조립 |
| Create VM tracking | `backend/app/operations/vm_create/` | stable redacted intent, plan·approval·dispatch·result·replay 상태/event mapping |
| Create VM compatibility | `backend/app/api/v1/router.py`, `backend/app/vm_create/` | 기존 `/vm-create/*`, runner, request/workload/job/artifact dual record 조립 |
| Guided `qm` | `backend/app/operations/guided_qm/` | fixed template, typed validation, handoff, attestation, API verification |
| workload observation | `backend/app/proxmox/inventory.py` | Workloads query + Integration read port |
| managed dispatch | `backend/app/proxmox/client.py` | Integration mutation adapter |
| local persistence | `backend/app/operations/core/infrastructure/`, `operations/recovery/infrastructure/`, `jobs/*` | common operation/event/recovery와 기존 Jobs/Artifacts compatibility 저장을 병행 |
| UI composition | `frontend/src/app/`, `pages/operations/`, `pages/workloads/` | route shell, Workload context, operation list/detail/timeline |
| UI feature/entity/shared | `frontend/src/features/guided-qm-unlock/`, `features/workloads/`, `entities/operation/`, `shared/` | typed plan, expiry-safe handoff, attestation/verification, read model과 API/RBAC/connection 계약 |

## 검증

- 정상: intent, policy, approval, one dispatch, task, post-check, evidence 순서와 `succeeded` 조건.
- 경계: ack 누락, stale identity, plan drift, role 부족은 port 호출 전 차단.
- 중복: same key replay와 different key/same target conflict.
- ambiguity: timeout, crash after dispatch, missing UPID, post-check mismatch가 second mutation 없이 reconciliation으로 전환.
- recovery: registration failure의 no-dispatch, lease takeover/fencing, stored-UPID GET-only resume, cross-operation locator conflict.
- manual: unsupported field/lock/secret 거부, exact command, expiry, digest binding, trusted attestation, API verification, crash-resume와 lock retention.
- 계약: 기존 endpoint facade와 신규 operation API가 같은 application result를 표현.
- UI: viewer/operator 경계, 기존 route alias, server-generated command only, expiry/late evidence, architecture import 방향을 contract test로 보호한다.
