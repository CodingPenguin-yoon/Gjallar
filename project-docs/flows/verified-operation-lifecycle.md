# 기능 흐름: Verified Operation Lifecycle

- 상태: `APPROVED`
- 최종 검토일: `2026-09-07`
- 부분 검토: `2026-09-14`, Start/Shutdown 요청 조정과 프리셋·이력 보존 정책
- 관련 요구사항·도메인: [`Project Specification`](../specifications/project-specification.md), [`Domain Map`](../domains/domain-map.md), [`ADR-004`](../decisions/adr-004-postgresql-durable-operation-recovery.md), [`ADR-007`](../decisions/adr-007-observe-first-operations-intelligence.md), [`ADR-008`](../decisions/adr-008-template-based-create-and-persistence-simplification.md)

이 문서는 선택적 Verified Action의 상태 의미, 실제 action별 실행 순서와 recovery 실패 경계를 설명한다. endpoint·payload는 [API 기준선](../api/current-api-v1.md), transaction의 저장 범위는 [DB 기준선](../database/current-schema-and-ownership.md), 실행·운영 절차는 [runbook](../operations/runbook.md)이 담당한다. VM Start, graceful VM Shutdown, Create VM과 Guided `qm unlock`은 공통 Operation core를 사용한다. DRS와 migration은 action/API/runtime에서 제거됐고 이 lifecycle에 포함되지 않는다.

## 현재 구현 범위

- VM Start, VM Shutdown, Create VM과 Guided `qm unlock`은 현재 한 개의 configured Proxmox cluster를 전제로 같은 cluster/VMID의 PostgreSQL durable locator lock을 공유한다. 파일 잠금은 사용하지 않으며 같은 VMID의 다른 node 표기는 별도 target으로 취급하지 않는다. 네 action 모두 action-specific durable recovery item과 GET-only handler를 가진다.
- VM Start/Shutdown은 same-key replay/intent conflict와 ambiguous dispatch·task·post-check의 `needs_reconciliation` 보존을 구현했다. Shutdown은 graceful POST만 허용하고 force-stop/reboot fallback을 금지한다.
- Create VM은 Proxmox 템플릿 clone을 사용한다. 템플릿 직접 입력 또는 선택한 DB 프리셋의 draft/preflight와 plan을 거쳐 common Operation을 준비하고 exact approval, preview, dispatch, checkpoint, task/result, 작업별 workload 결과를 기록한다. completed replay, same-key intent conflict, 진행 중·미확정 작업 guard와 명확한 실패/불명확한 결과의 구분을 유지한다. 빈 VM·ISO 설치·OS 설치 자동화 경로는 없다.
- VM Start/Shutdown은 API compatibility facade에서 infrastructure-free command와 use case로 진입하고 Workloads, mutation, Jobs, Evidence, lock/recovery를 명시적 port로 받는다. 검증 workflow는 각각 `operations/vm_start/workflow.py`, `operations/vm_shutdown/workflow.py`에 있고 공통 projection/event와 기존 job/artifact를 함께 기록한다.
- 첫 Guided Manual action `qm unlock <vmid>`은 typed plan, 5분 expiry, trusted attestation, Proxmox API verification과 reconciliation을 공통 Operation으로 기록한다. backend command executor는 없다.
- Workload Cockpit은 endpoint별 observation provenance와 source availability를 보존하고, exact `/instances/:vmid`에서 VM data와 같은 응답의 availability를 유지한 채 `proxmox_vm`·`vmid:<VMID>`가 정확히 일치하는 Readiness/Placement finding과 target-filtered Operation을 연결한다. Insights·Operations 보조 조회의 HTTP 실패, section unavailable·unknown/stale와 finding truncation은 정상 0건으로 축소하지 않는다. partial base snapshot은 read 화면에서 보존하지만 VM context를 기존 Start/Shutdown acknowledgement dialog와 Guided plan에 전달하는 mutation capability는 `operator+`와 complete live connection을 함께 요구한다.
- VM Start/Shutdown 성공 결과와 오류 응답에 `operation_id` 또는 `job_id`가 포함된 recorded outcome은 common Operation이 조회되면 공통 상세로 이동하고, historical Job-only replay처럼 Operation projection이 없는 경우에는 명시적으로 Jobs compatibility 화면을 사용한다. foreign target lock 충돌은 현재 `planned` Operation과 exact open foreign lock을 한 transaction에서 재확인한 경우에만 `blocked`로 기록하고, 오류는 현재 요청 `operation_id`와 확인 가능한 `conflicting_operation_id`를 포함한다. same-owner 경합은 replay 또는 in-progress로 처리한다. Operation 상세는 non-terminal 상태뿐 아니라 terminal 상태에서 recovery가 incomplete하거나 owned lock이 남은 동안에도 5초 간격 최대 60회 갱신한다. coordination이 닫히거나 recovery가 paused/manual이면 중단하며 request generation이 늦은 이전 응답을 폐기한다.
- `vm_start_observation`, `vm_shutdown_observation`, `vm_create_observation`, `guided_qm_unlock_observation` 네 recovery kind가 opt-in background runner와 operator-triggered observe에서 같은 allowlist를 사용한다. handler는 Proxmox GET과 local evidence/projection만 사용할 수 있고 lease expiry나 process restart만으로 side effect가 없다고 판단하거나 mutation을 재호출하지 않는다.
- `POST /api/v1/operations/{operation_id}/recovery/observe`는 operator/admin이 current Operation version/checksum과 idempotency key로 한 exact recovery item을 관찰하는 additive API다. background runner는 기본 비활성화지만 이 명시적 관찰은 별도로 사용할 수 있다. force unlock, arbitrary terminal 전이와 compensation 권한은 제공하지 않는다.

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
- `succeeded`: action contract가 요구하는 external completion evidence, direct after-state와 해당 성공 event를 기록했다. managed API action은 terminal task를, guided manual action은 authenticated operator attestation을 상관 연결한다. attestation 자체는 성공 권위가 아니다. Start/Shutdown은 이 상태를 먼저 commit한 뒤 Jobs·recovery·lock을 정리하므로 status 하나로 전체 coordination 종료를 판정하지 않는다.

## 성공 흐름

아래는 공통 단계의 개념적 순서다. 하나의 DB transaction이나 모든 action에 동일한 commit 순서를 뜻하지 않으며 실제 완료 순서는 action별 절을 따른다.

```text
Authenticated request
→ Operation intent + idempotency identity 저장
→ Fresh workload observation/capability 확인
→ Action별 validation/pre-check와 필요한 경우 versioned policy 평가
→ Exact plan/evidence digest 생성
→ Action별 필요한 approval/acknowledgement binding 확인
→ Final pre-check + exact target lock 획득
→ Action-specific recovery item/foreground lease와 dispatch attempt 기록
→ managed API dispatch 또는 guided manual bundle 발급
→ Action contract에 따라 external task 또는 operator attestation correlation
→ Direct after-state verification
→ Append-only evidence 저장 + current projection 갱신
→ Lock 해제
→ succeeded
```

### `managed_api`

1. dispatch attempt를 먼저 기록한다.
2. 승인된 각 mutation 단계를 한 번 dispatch한다. Start/Shutdown은 각각 한 action이고 Create는 clone·설정·선택적 부팅의 여러 단계다.
3. task를 반환하는 단계는 형식 검증된 UPID/task reference를 즉시 operation에 연결한다.
4. terminal task와 direct after-state를 확인한다.
5. ambiguity가 있으면 자동 재호출하지 않는다.

### VM Start/Shutdown foreground와 restart recovery

1. common Operation intent를 준비하고 durable locator lock을 획득한 직후 Jobs·Operation을 다시 조회한다. 같은 intent의 결과가 있으면 replay하며 terminal Jobs를 running으로 덮거나 mutation을 재실행하지 않는다. 새 실행이 가능한 `planned` 상태에서만 이후 `dispatching`으로 진행한다. lock 충돌 직후도 재조회하며 same-owner는 replay 또는 in-progress로 응답하고, foreign 충돌 상태 기록은 위의 atomic 검사로 보호한다.
2. Proxmox POST 전에 `operation_recovery_items`를 만들고 foreground lease를 획득한다. 이 단계가 실패하면 POST를 호출하지 않는다.
3. recovery item은 action kind, operation type/mode, target/node/VMID, exact durable lock id/cluster와 형식 검증된 stored UPID를 Operation에 결합한다. invalid/empty UPID는 원문을 저장하거나 task GET에 쓰지 않고 ambiguous effect로 reconciliation하며 task poll 중 lease를 heartbeat한다.
4. process가 종료되면 target lock은 남고 lease만 만료된다. enabled runner 하나가 `SKIP LOCKED`로 due item을 claim한다.
5. runner handler는 stored UPID task와 VM status GET만 수행한다. 같은 start/shutdown POST, 다른 mutation, manual fallback을 실행하지 않는다.
6. Start는 task `OK`와 running state, Shutdown은 task `stopped/OK`와 direct stopped state가 일치할 때만 `succeeded`; task가 진행 중이면 bounded `retry_wait`; missing UPID, binding 또는 state mismatch는 `needs_reconciliation`/`paused`와 retained lock이다.
7. Start/Shutdown은 검증된 terminal Operation과 recovery `leased`를 먼저 commit한다. foreground는 이후 Jobs를 별도 저장하고  completion event/recovery와 exact PostgreSQL lock release를 commit한다. restart handler는 유효 lease·허용 Operation 상태·exact lock을 확인하고 Jobs projector와 completion event/recovery/lock release를 같은 transaction에 넣는다. projector에 진입할 수 없는 stale lease는 Jobs도 갱신하지 못한다. Jobs projection 실패가 이미 기록된 `succeeded`/`failed`를 없애지는 않으며 recovery는 미완결이고 DB lock은 남는다.
8. mutation client 생성 실패·부재 또는 recovery 등록 실패에서는 no-effect failed Jobs를 먼저 보존한다. foreground는 Operation row를 잠그고 `planned` 상태·recovery item 부재·exact owned open lock을 확인한 경우에만 canonical `failed`를 commit한 뒤 별도로 lock을 해제한다. replay/recovery가 먼저 item을 만들었으면 foreground는 canonical 전이와 release를 포기하고 해당 owner가 완료하도록 둔다. 늦은 replay의 version/checksum 충돌은 현재 terminal no-effect marker와 같은 lock ID·cluster를 확인한 경우에만 기존 실패 결과로 replay한다.
9. target lock 뒤 recovery item을 만들기 전 crash가 난 최신 contract-marked Operation은 exact owned lock과 task reference 부재가 모두 확인될 때만 no-effect pre-dispatch item으로 채워 local failure를 닫는다. precheck/client/recovery registration failure에서 Jobs·terminal Operation·release 일부만 기록됐어도 current marker·latest event checksum과 exact lock/cluster가 해당 복구 경로의 조건을 충족할 때만 no-effect projection을 닫는다. 과거 marker 없는 Operation은 이 경로로 추정하지 않는다.

### Create VM 입력·검토와 영속 기록

1. draft는 직접 입력 모드에서 Proxmox 템플릿 사양을 사용하고, 프리셋 모드에서 선택한 DB profile의 기본값을 사용한다. preflight는 Proxmox inventory를 검증하며 선택한 profile이 있을 때만 해당 규칙을 적용한다. 두 HTTP 단계는 Proxmox를 변경하지 않지만 Jobs 상태는 저장하므로 “read-only preflight”가 DB write 부재를 뜻하지 않는다.
2. application은 template 직접 입력에서는 Proxmox 템플릿을, 프리셋 경로에서는 조회한 DB 프로필을 draft/preflight 계산에 전달한다. `planner.calculate_vm_create_plan`이 저장 없이 계산하고 `plan_persistence.persist_vm_create_plan`이 `preflight_report`, `plan`, `vm_instance_manifest`, `planned_git_diff`, `review_summary` 다섯 artifact를 만들고 `operation_id=job_id`인 common Operation과 연결한다. 승인·preview·execute도 입력에서 plan을 다시 만들 수 있다. manifest/planned Git diff는 현재 compatibility 산출물이며 실제 생성은 Proxmox API로 수행한다.
3. exact approval·review checksum·stable intent와 replay/VMID owner를 확인한 뒤에만 실행으로 넘어간다. Create 입력·검토는 partial base snapshot에서도 가능하다. Create 실행은 guest agent 외 source의 complete 관찰을 요구한다. 고정 IP는 입력한 주소의 ping 응답과 기존 VM 설정·guest agent IP 정보를 함께 확인한다. 어느 쪽이든 점유가 발견되면 red로 차단하며, 점유 미발견·조회 불가는 yellow로 직접 확보한 IP인지 확인받는다. 기존 VM의 guest agent 누락만으로 차단하지 않는다. DHCP discovery 경고와 최초 mutation 직전 재검증은 유지한다. Start/Shutdown/Guided의 complete-live 조건은 유지한다. 다른 VM guest agent 실패 상세와 비점유 ping의 무응답·실행 불가 사유는 preflight에 남기며 exact plan의 risk summary·승인 checksum에서는 변동하는 상세를 제외한다. 고정 IP의 `static_ip_usage_unverified` 또는 DHCP의 `dhcp_requires_discovery` 경고와 명시적 yellow acknowledgement는 유지한다. 실제 점유가 발견되면 `static_ip_unavailable` red로 차단하며 새 IP 점유와 필수 생성 조건은 실행 직전에도 재검증한다.
4. power policy는 `stopped` 또는 `boot_and_verify`다. 후자는 생성 후 첫 부팅과 readiness 검증을 포함하며 임의 OS 설치 자동화가 아니다. cloud-init 완료를 기다리는 guest-exec status poll도 foreground lease를 갱신하며, 갱신 실패는 전파한다.

템플릿 직접 입력·선택적 프리셋과 계산·저장 분리는 구현됐다. [ADR-012](../decisions/adr-012-create-preset-and-history-retention.md)에 따라 프리셋은 DB에 유지하고 현재 저장 단위의 입력·검토·승인·작업 기록은 자동 만료·삭제 없이 보존한다. Jobs 최신 projection·artifact identity upsert와 approval·replay 계약은 유지하며, 모든 revision의 불변 보존이나 이력 소유권 이관은 별도 설계다. Create 관찰 조건은 위의 모드별 정책을 따른다.

### Create VM foreground와 restart recovery

1. exact approval·preview·same-target guard 뒤 locator lock을 잡고, request/job 기록이나 Proxmox client 생성보다 먼저 `vm_create_observation` item/lease를 준비한다. plan digest, target/node/VMID, power/readiness expectation과 exact lock identity를 함께 저장한다.
2. `dispatch_prepared` checkpoint 후 client 생성 전에 snapshot/detail cache를 공유하지 않는 새 Proxmox 관찰을 수집한다. Create source 조건을 통과한 관찰로 승인된 VMID를 고정한 preflight와 plan core를 재계산하고 기존 승인 내용과 비교한다. 고정 IP의 ping도 다시 실행하며, 무응답에서 응답으로 바뀌면 첫 mutation 전에 차단한다. snapshot 부재·guest agent 외 source 실패는 503, ping 응답·기존 VM IP 중복을 포함한 승인 영향이 있는 변경은 `409 PROXMOX_CREATE_STATE_CHANGED`로 중단하며 pre-dispatch failure projection·recovery 완료·lock 해제를 수행한다. 이 재검증은 기존 plan artifact를 덮어쓰지 않는다. lease를 재검증한 뒤 native runner는 `clone_pending`과 형식 검증된 UPID가 있는 `clone_dispatched`, clone task, resize/config/start 각 mutation 전후, post-check, `readiness_observed`, artifact 기록을 checkpoint한다. invalid task locator는 원문을 남기거나 task GET에 쓰지 않고 ambiguous result로 닫는다. checkpoint 저장 실패는 즉시 전파되어 다음 mutation을 차단한다.
3. clone POST 이후 timeout·persistence failure처럼 external effect가 가능하면 Operation은 `needs_reconciliation`, recovery는 `paused` 또는 retryable state, target lock은 retained다. 같은 create mutation은 자동 또는 API 재진입으로 다시 호출하지 않는다.
4. task가 아직 실행 중이면 stored UPID를 GET으로 관찰해 `retry_wait`한다. 그 밖의 pending/ambiguous phase는 task/status/config evidence를 남기고 사람이 판단하도록 pause한다.
5. restart recovery는 `readiness_observed` 또는 `observed_after_artifact_recorded`에 `result_success=true`와 persisted observed-after fingerprint가 있을 때 fresh exact VM status/config와 required status·fingerprint를 비교한다. 실제 artifact `content_text` SHA-256과 row/checkpoint checksum이 같고 JSON도 redacted observation과 exact equality여야 한다. foreground와 restart recovery 모두 valid lease·Operation version/checksum·exact lock을 먼저 확인한다. request/job/artifact와 Operation 결과 projection, 최종 succeeded, recovery completion, lock release를 한 DB transaction으로 commit한다. stale lease 또는 artifact/projection 실패는 rollback하고 잠금을 유지한다.
6. approved Operation과 exact owned lock은 있으나 recovery item/request가 없는 acquire 직후 crash는 current pre-dispatch marker가 있을 때만 Proxmox read 없이 side-effect-free `blocked`로 닫는다. 검증된 no-effect 경로에서 compatibility projection과 fenced lock release를 수행한다.
7. stored clone/start task의 terminal non-OK와 strict exact VM status `404`가 함께 target 부재를 증명할 때만 recovered `failed`로 닫는다. target 존재, running task, observation unavailable과 UPID 없는 partial phase는 자동 실패로 추론하지 않는다.
8. readiness는 명시한 `create_operation_id`와 succeeded Create target/workload, 저장된 evidence의 owner·target·job, artifact row의 type/checksum이 일치할 때만 해당 Operation에 연결한다. owner 없는 증거는 Jobs-only이며 같은 evidence identity의 owner 변경은 409다.

### `guided_manual`

1. allowlisted structured template과 validated parameter로 instruction bundle을 만든다.
2. bundle은 target identity, precondition, expiry, plan digest, command 또는 PVE UI 절차, 예상 결과, verification 절차를 포함한다.
3. operator는 Proxmox 환경에서 직접 실행하고 attestation을 제출한다.
4. pasted output은 optional sanitized evidence이며 성공 권위가 아니다.
5. Gjallar가 Proxmox API로 after-state를 검증한 뒤에만 성공할 수 있다.

### 현재 `qm unlock` slice

1. `node_id`, JSON integer `vmid`, `idempotency_key`, `qm_unlock_risk_acknowledged=true`만 받는다. command, arguments, options, secret-like extra field는 거부한다.
2. `/access/permissions?path=/nodes/{node}`의 `Sys.Audit`, active task, VM config lock을 initial GET eligibility로 확인한다. task가 있거나 lock이 없거나 lock type이 allowlist 밖이면 어떤 Operation/lock도 만들지 않고 instruction을 발급하지 않는다.
3. 허용 lock은 `backup`, `clone`, `create`, `migrate`, `rollback`, `snapshot`, `snapshot-delete`, `suspending`이다. steady suspended 상태와 혼동될 수 있는 `suspended`는 제외한다.
4. server는 `instruction_exposed=false`인 provisional `planned` Operation과 `guided_qm_unlock_observation` item/lease를 먼저 만들고 같은 `proxmox_vm/vmid:{vmid}` exact target lock을 획득한다. durable lock id/cluster/type/scope/owner와 Operation target을 recovery commit에서 원자적으로 결합한다.
5. active task→config lock→active task와 exact current lock을 authoritative하게 다시 확인한 뒤에만 정확히 `qm unlock <vmid>`를 공개한다. 5분 expiry, observed lock, expected result, verification endpoint, `plan_digest`를 함께 저장한다.
6. checksum-valid하고 bundle/exposed evidence가 없는 `planned`에서 item만 유실된 crash는 item을 재구성할 수 있다. exact own lock도 없으면 Proxmox GET 없이 side-effect-free `blocked`로 닫고 foreign lock은 변경하지 않는다.
7. operator의 `command_executed=true` attestation은 실행 사실 주장만 기록한다. 정상 attestation/verification에는 recorded/current durable lock의 id/type/owner/cluster/VMID/scope와 status `active`가 모두 정확히 일치해야 한다.
8. config lock 부재와 active task 부재를 API로 확인해야 `succeeded`가 되고 target lock을 해제한다. 불일치·관찰 실패·target lock 유실은 `needs_reconciliation`이다.
9. issued item은 expiry까지 `retry_wait`다. attestation 없이 expiry가 도달하면 enabled runner 또는 operator observe가 실제 config/task 상태를 다시 관찰한다. original config lock이 그대로이고 active task와 attestation이 없을 때만 `expired`와 lock 해제로 끝낸다. 관찰 실패는 bounded retry, lock/state 변화는 reconciliation이다.
10. persisted non-late `awaiting_verification`/`verifying`은 GET-only handler가 API verification을 재개할 수 있다. 만료·stale/reconciliation lock 아래 late attestation은 `needs_reconciliation` evidence만 기록하고 generic/background handler가 GET 검증하지 않는다. 명시적 verification endpoint만 manual operator authority이며 그때도 exact lock이 `active`여야 한다.
11. 이후라도 실행 attestation이 들어오면 stale command의 가능한 effect를 숨기지 않는다. UI는 expiry 시각이 지났거나 상태가 `expired`/`needs_reconciliation`인 command를 historical `do_not_execute` evidence로 표시하고 신규 실행을 금지하며, 이미 발생한 실행만 late evidence로 기록한다.

### 공통 operator observe

1. Operation 상세가 제공한 `available_actions`가 있을 때 operator/admin은 current `version`, `last_event_checksum`과 stable idempotency key를 제출한다. key 원문은 영속화하지 않고 SHA-256 digest→최초 fence를 최대 64개 durable ledger와 request event에 남긴다. 기존 entry를 퇴출하지 않아 다른 key가 중간에 사용돼도 최초 fence 재사용 계약을 유지한다.
2. coordinator는 stale fence, same-key/different-fence, live lease, unsupported kind와 exact lock/binding mismatch를 `409`로 거부한다. persistence·authoritative observation 불가 또는 retry exhaustion은 `503`이다.
3. item이 없으면 current pre-dispatch recovery contract marker, action별 허용 상태, task reference 부재와 exact owned durable lock을 모두 확인한 Start/Shutdown/Create만 side-effect-free item을 만들 수 있다. Guided는 checksum-valid unissued `planned`만 item을 복원하며 exact own lock이 없는 no-effect plan은 Proxmox GET 없이 `blocked`로 닫는다.
4. coordinator는 한 item을 claim하고 action-specific GET-only handler를 한 번 실행한 뒤 갱신된 Operation detail을 반환한다. handler가 `paused`로 남기면 자동 polling을 멈추고 evidence를 토대로 수동 판단한다.
5. 이 API는 mutation retry, stale Guided command 실행, force unlock, arbitrary success/failure 지정 또는 reverse compensation을 받지 않는다.

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
- Proxmox payload와 output은 `operations/core/evidence.py`의 allowlist/redaction을 거친 최소 evidence로 변환한다. error/connection/task/status의 raw URL·credential·body/path/poll은 버리고 UPID는 허용 형식만 locator로 사용한다. Guided task는 digest/bounded metadata, config lock은 지원 enum·empty·unsupported marker만 보존한다.

## 상태와 트랜잭션

- 변경되는 상태: operation projection, attempts/steps, approval binding, lock/lease, external task ref, verification, evidence event.
- 데이터 소유자: Operations, Policy/Approval, Evidence/Audit.
- local transaction: intent/attempt/evidence와 projection 변경은 각 상태 전이의 invariant를 지키는 짧은 transaction으로 기록한다.
- external call: PostgreSQL transaction과 하나의 원자적 transaction으로 묶지 않는다.
- dispatch ordering: attempt를 persistent하게 기록한 뒤 external call하고, task reference를 가능한 즉시 별도 transition으로 기록한다.
- current projection은 재구성 가능한 최신 상태이며 immutable evidence와 동일시하지 않는다.
- recovery commit은 유효 lease generation/token/expiry와 Operation row를 확인하고, 호출자가 expected version/checksum을 제공한 경우 그 fence도 확인한다. exact lock 확인 뒤 Operation event/projection, recovery status와 optional target lock release를 같은 PostgreSQL transaction에서 처리한다. Create 성공 projector와 Start/Shutdown restart handler의 terminal Jobs projector가 이 transaction에 참여한다. Start/Shutdown foreground Jobs 기록과 앞선 terminal Operation 전이는 별도이며 external GET·Proxmox mutation은 DB rollback 대상이 아니다. 상세 비교는 [DB 기준선](../database/current-schema-and-ownership.md)을 따른다.

## 실패 흐름

| 실패 지점 | 상태·오류 의미 | 상태 변화 | 재시도·보상 | 사용자 결과 |
|---|---|---|---|---|
| validation/RBAC/capability | 실행 불가 | `blocked`, side effect 없음 | 입력 수정 후 새 plan | block reason과 해결 조건 |
| policy/approval | 거절·만료·drift | `rejected`/`expired` | 재평가·재승인 | 변경된 evidence 표시 |
| lock conflict | 동일 target 충돌 | 현재 side-effect 없는 요청은 `blocked`; 기존 lock owner는 현재 상태 유지 | 현재 `operation_id`와 확인 가능한 `conflicting_operation_id`로 두 operation 확인 | recorded/current owner operation link |
| API explicit reject | side effect 없음이 명확 | `failed` | 정책에 따른 명시적 retry | Proxmox error의 안전한 mapping |
| timeout/missing task ref | side effect 불명 | `needs_reconciliation` | 자동 mutation retry 금지 | verification/reconcile action |
| task terminal failure | external failure 확인 | `failed` 또는 effect 불명 시 reconcile | action별 정책 | task evidence |
| task OK/post-check mismatch | 결과 불일치 | `needs_reconciliation` | direct observation 반복·수동 판단 | expected/observed diff |
| manual attestation only | 권위 있는 검증 없음 | `awaiting_verification` | API 재검증 | verification pending |
| evidence·compatibility projection failure | 성공 evidence 미완결 또는 terminal compatibility 미완결 | action-specific `503`; action·실패 단계에 따라 기존 terminal 상태 또는 reconciliation을 보존하고 recovery retry/pause·exact lock 유지 | exact Operation handoff 뒤 GET-only observation과 idempotent projection | actual effect·Operation status·coordination 완료를 구분; 원본 artifact 추정 재생성 금지 |
| recovery lease loss | stale observer 결과 | canonical 상태 변경 없음 | 새 owner가 stored task/state 재관찰 | retry/reconciliation 상태 조회 |
| recovery binding mismatch | 다른 target/owner/lock ID | `paused`; DB lock 유지 | exact Operation·lock evidence 대조 | force release 없음 |
| Guided instruction expiry | 실행 여부를 시간만으로 확정 불가 | unchanged lock이면 `expired`, effect 가능성은 `needs_reconciliation` | config/task GET-only observation | stale instruction `do_not_execute` |

## Recovery 재시도 한계

- runtime의 `max_attempts`는 기본 5이며 환경 설정 허용 범위는 1~20이다. claim 시 `attempt_count`가 증가하므로 단순히 “foreground 이후 5번 추가 재시도”를 뜻하지 않는다.
- running task나 재시도 가능한 observation·projection·cleanup failure는 제한된 `retry_wait`로 남고 상한에 도달하면 `paused`와 exhaustion evidence를 기록한다. ambiguity·잘못된 binding·manual authority가 필요한 상태는 횟수가 남아도 즉시 pause할 수 있다.
- retry는 stored task/state와 로컬 projection의 재관찰·완결이며 clone/start/shutdown을 재호출하는 기능이 아니다. 구체적 environment 값과 operator 대응은 [runbook](../operations/runbook.md)을 따른다.

## 멱등성과 동시성

- 중복 요청: actor/action/target/intent에 연결된 idempotency key로 동일 operation resource를 반환한다.
- 같은 key의 payload 또는 plan digest가 다르면 conflict다.
- 다른 key라도 같은 target의 충돌 operation은 target-scoped lock/lease로 직렬화한다.
- Start/Shutdown은 최초 조회 후 선행 요청이 완료했더라도 lock 뒤 재조회한 결과를 replay한다. 뒤늦은 foreign busy 처리와 recovery lease 경쟁 패자는 선행 Operation·Jobs 결과나 다른 owner의 lock을 덮어쓰거나 해제하지 않는다.
- timeout·process crash 후에는 stored attempt/task ref/checkpoint와 actual state를 reconcile하고 mutation을 재호출하지 않는다.
- lease expiry만으로 side effect가 없다고 가정하지 않는다.

recovery observe idempotency는 action 실행 idempotency와 별개다. 같은 observe key는 durable ledger에 기록된 최초 Operation version/checksum fence에만 replay되며 K1→K2→K1 순서에서도 다른 fence K1은 conflict다. current state가 바뀌면 새 detail을 읽어 새 key/fence로 요청해야 한다. ledger 64개 상한에서는 새 key를 fail closed한다. manual authority 또는 exact binding repair가 필요한 error code는 read model에서 observe action을 제공하지 않고 coordinator도 GET 전에 fail closed한다.

canonical target coordination은 `(GJALLAR_CLUSTER_ID, VMID)` PostgreSQL locator lock이다. 파일 잠금은 사용하지 않는다. multi-cluster connection 도입은 별도 identity 설계가 필요하다.

## 구현 위치

| 단계 | 현재 구현 위치 | 책임 |
|---|---|---|
| HTTP facade | `backend/app/api/v1/router.py` | auth/validation, DTO, error/response mapping |
| Operation core | `backend/app/operations/core/` | 상태 전이, digest, projection/event port와 SQLAlchemy adapter |
| Durable coordination | `backend/app/operations/locks/`, `backend/app/operations/recovery/` | locator lock, due/lease/fencing, 네 action handler allowlist, opt-in runner와 operator observe coordinator |
| VM Start application | `backend/app/operations/vm_start/` | command·stable intent, use case, 외부 port 계약 |
| VM Start compatibility | `backend/app/vm_actions/start.py` | 기존 공개 facade와 현재 infrastructure adapter 조립 |
| VM Shutdown application | `backend/app/operations/vm_shutdown/` | graceful shutdown command·stable intent, running pre-check, use case와 외부 port 계약 |
| VM Shutdown compatibility | `backend/app/vm_actions/shutdown.py` | 공개 facade, Proxmox/Jobs/Evidence/Lock/Recovery adapter 조립 |
| Create VM tracking | `backend/app/operations/vm_create/` | stable redacted intent, checkpoint/session, GET-only recovery와 idempotent request/job/artifact와 Operation 결과 projection |
| Create VM compatibility | `backend/app/api/v1/vm_create_compat.py`, `backend/app/vm_create/` | 기존 `/vm-create/*`, runner, request/workload/job/artifact dual record 조립 |
| Guided `qm` | `backend/app/operations/guided_qm/` | fixed template, typed validation, durable handoff/expiry, attestation, API verification와 GET-only recovery |
| workload observation | `backend/app/proxmox/inventory.py` | Workloads query + Integration read port |
| managed dispatch | `backend/app/proxmox/client.py` | Integration mutation adapter |
| local persistence | `backend/app/operations/core/infrastructure/`, `operations/recovery/infrastructure/`, `jobs/*` | common operation/event/recovery와 기존 Jobs/Artifacts compatibility 저장을 병행 |
| UI composition | `frontend/src/app/`, `pages/operations/`, `pages/workloads/` | route shell, Workload/exact VM context, target-filtered operation list, detail/timeline과 bounded polling |
| UI feature/entity/shared | `frontend/src/features/guided-qm-unlock/`, `features/workloads/`, `entities/operation/`, `shared/` | typed plan, target path, expiry-safe handoff, digest/checksum evidence, attestation/verification, read model과 API/RBAC/connection 계약 |

## 검증

- 정상: intent, policy, approval, one dispatch, task, post-check, evidence 순서와 `succeeded` 조건.
- 경계: ack 누락, stale identity, plan drift, role 부족은 port 호출 전 차단.
- 중복: same key replay와 different key/same target conflict.
- ambiguity: timeout, crash after dispatch, missing UPID, post-check mismatch가 second mutation 없이 reconciliation으로 전환.
- recovery: registration failure의 no-dispatch, exact binding, lease takeover/fencing, stored-UPID/checkpoint GET-only resume, compatibility projection/DB coordination failure, cross-operation locator conflict와 operator observe의 version/checksum/idempotency fence.
- manual: unsupported field/lock/secret 거부, exact command, crash-before-handoff, expiry observation, stale instruction 금지, late attestation, digest binding, trusted attestation, API verification와 lock retention.
- 계약: 기존 endpoint facade와 신규 operation API가 같은 application result를 표현.
- UI: partial read/Create 모드별 관찰·다른 action complete-live 경계, viewer/operator 경계, 기존 route alias와 availability-aware exact VM route, target deep link/filter, digest/checksum payload 보존, bounded polling과 out-of-order response 폐기, server-generated command only, expiry/late evidence, architecture import 방향을 contract test로 보호한다.

### Create 완료 replay의 역사 결과

succeeded Operation의 workload 결과는 현재 VM 상태와 분리해 반환한다. 현재 node:VMID linkage 변경·부재가 과거 결과를 바꾸지 않는다. operation type/mode/target·node·VMID·결과 필드가 손상되면 기존 409 복구 필요 오류로 닫는다. succeeded Operation이 없는 legacy 요청만 exact job linkage를 이용해 기존 호환 채택 절차를 따른다. evidence summary도 역사 결과로 이관됐다. 완료 VMID 독점 guard·readiness owner 추정·current-workload writer도 제거됐다.

## 생성 화면의 단계

기본 정보(템플릿·이름·VMID) → 배치·사양 → 네트워크·접속 → 최종 검토 순서다. VMID는 추천값을 수정할 수 있고 추천은 예약이 아니다. 이전 이동은 입력을 보존한다. 검토 후 설정 수정은 새 작업 identity를 만들고 기존 검토·승인·동의를 초기화한다. 비동기 검토·승인·생성 중에는 입력과 이전 이동을 차단한다.

DHCP에서는 고정 IP 입력을 숨긴다. 최종 단계에서 생성 후 상태를 선택하고 검토 결과의 차단·주의 항목을 확인한다. 고정 IP 검토는 계획 응답에 포함된 같은 시점의 preflight를 기준으로 기존 VM 정보와 Ping 응답을 따로 표시한다. 점유를 발견하지 못했거나 검사하지 못한 경우에는 미사용을 보장하지 않는다고 표시하고, 기존 yellow acknowledgement로 직접 확보한 IP인지 확인받는다. 다시 검토할 때에도 새 작업 ID를 사용하고 기존 승인·동의를 초기화하며, 이전 작업의 exact plan과 이력은 보존한다. 작업 ID·세션 사용자는 접힌 상세에 표시한다. 명시적 생성 동의와 기존 승인 검증 뒤 요청하며, 이후 Operation 진행 화면으로 이동한다.

Dashboard는 guest agent만 불완전하고 나머지 inventory source와 인접 조회가 정상인 경우 상단 경고를 표시하지 않는다. VM 요약에는 VM 응답 metadata의 guest agent 실패 대상 수를 내부 IP 확인 불가 대수로 표시하고, VM 상세에는 agent 설정·내부 서비스 확인 안내를 표시한다. 노드 online 표시는 노드 관찰을 기준으로 하며, source metadata 부재·다른 source 누락·HTTP 조회 실패는 기존 부분 실패 안내를 유지한다.
