# API 계약: 현재 `/api/v1` 기준선

- 상태: `APPROVED`
- 최종 검토일: `2026-08-26`
- 소비자: `frontend/src/shared/api/apiV1.js`, compatibility export `frontend/src/services/apiV1.js`, React SPA; 저장소 밖 DRS consumer 상태는 관찰 불가이며 사용자가 repository 제거를 위해 consumer가 없다는 전제를 수락
- 관련 요구사항·ADR: [`Project Specification`](../specifications/project-specification.md), [`ADR-003`](../decisions/adr-003-production-inventory-connection-truth.md), [`ADR-007`](../decisions/adr-007-observe-first-operations-intelligence.md)

이 문서는 active route의 보존용 기준선이다. 세부 payload와 error code는 코드와 contract test가 우선한다. `/api/v1/drs/*` 13개 route와 전용 frontend route/client는 2026-08-24 승인된 repository 전환에서 제거됐다. `/insights`의 legacy source·ID 값과 Jobs의 historical DRS evidence 표시는 별도 compatibility 계약으로 유지한다.

## 계약 개요

- protocol: same-origin HTTP JSON, version prefix `/api/v1`.
- authentication: local DB user와 server-side session, `gjallar_session` HttpOnly cookie.
- role: read는 `viewer+`, operator mutation은 `operator+`, account management는 `admin`.
- success envelope: `{ "ok": true, "data": ..., "meta": ... }`.
- error: 다수 경로가 FastAPI `{ "detail": { "code", "message", ... } }`를 사용한다. 성공 envelope만큼 일관된 공통 error mapper는 없다.
- compatibility: 전환 Plan 동안 existing method/path와 의미를 facade로 유지한다. 호환성을 깨는 변경은 별도 승인과 deprecation이 필요하다.

## Active endpoint inventory

### 인증·계정

| Method | Path | 권한 | 현재 책임 |
|---|---|---|---|
| `POST` | `/api/v1/auth/login` | public | credential 확인, session cookie 발급 |
| `POST` | `/api/v1/auth/logout` | session | current session revoke, cookie 제거 |
| `GET` | `/api/v1/auth/me` | session | authenticated actor 조회 |
| `POST` | `/api/v1/auth/change-password` | session | 본인 password 변경과 session 처리 |
| `GET/POST` | `/api/v1/admin/users` | admin | user 목록·생성 |
| `PATCH` | `/api/v1/admin/users/{username}/role` | admin | role 변경 |
| `POST` | `/api/v1/admin/users/{username}/disable` | admin | account 비활성화와 session revoke |
| `POST` | `/api/v1/admin/users/{username}/reset-password` | admin | password reset와 session revoke |
| `GET` | `/api/v1/admin/sessions` | admin | session inventory |
| `POST` | `/api/v1/admin/sessions/{session_id}/revoke` | admin | 특정 session revoke |

### Inventory·workload read

| Method | Path | 권한 | 현재 책임 |
|---|---|---|---|
| `GET` | `/api/v1/setup/proxmox/connection` | viewer | redacted Proxmox connection truth |
| `GET` | `/api/v1/cluster/summary` | viewer | cluster summary |
| `GET` | `/api/v1/nodes` | viewer | node inventory |
| `GET` | `/api/v1/vms` | viewer | VM inventory |
| `GET` | `/api/v1/vms/{vmid}` | viewer | VM detail |
| `GET` | `/api/v1/profiles` | viewer | Create VM profile options |
| `GET` | `/api/v1/templates` | viewer | template inventory |
| `GET` | `/api/v1/storage` | viewer | storage inventory |
| `GET` | `/api/v1/networks` | viewer | network inventory/readiness |

connection status의 `data`는 `state`, `source`, `cluster_id`, `observed_at`, `freshness`, `reason`, `configured`, `inventory_available`, `missing_configuration`을 반환한다. token, URL, upstream raw error는 반환하지 않는다. 이 endpoint는 mutation token 권한을 추론하지 않는다.

- 필수 설정 누락·invalid mode: `unconfigured`.
- authoritative snapshot이 모든 기대 sub-source를 관찰하면 `live`, `source=live_read_only`, `freshness=fresh`다.
- base snapshot은 있으나 storage, network, VM config, guest-agent 또는 VM detail 일부가 실패하면 `degraded`, `freshness=partial`, `reason=proxmox_inventory_partial`, `inventory_available=true`다. 정상 source 데이터는 유지하고 실패 source를 빈 정상 상태로 해석하지 않는다.
- 설정됐지만 TLS·timeout·network·authentication 또는 base API read 실패로 snapshot 자체가 없으면 `degraded`와 redacted reason code다.
- `cluster/summary`, nodes, VMs, templates, storage, networks는 snapshot이 없을 때 `503`을 반환한다. partial snapshot은 Overview·Workloads·exact VM read에서 계속 읽을 수 있지만 Create VM 실행과 VM Start/Shutdown의 backend provider 및 frontend capability는 complete `live` observation만 허용한다.
- `503 detail.code`는 `PROXMOX_INVENTORY_UNCONFIGURED` 또는 `PROXMOX_INVENTORY_DEGRADED`이며 mutation을 호출하지 않는다.
- inventory endpoint는 data와 meta를 같은 snapshot에서 만들며, meta에는 기존 `source`, `mode`와 함께 `observed_at`, `freshness`, nested `connection`, additive `availability`를 제공한다. `availability`는 aggregate `available`·`complete`와 source별 `available`·`complete`·`expected_targets`·`observed_targets`·`failed_targets`를 포함한다.
- frontend `/instances/:vmid`는 VM data와 같은 응답의 meta를 함께 보존해 config·guest-agent·detail source failure를 unknown/partial로 표시한다. Insights section의 unknown·partial freshness와 bounded finding truncation도 exact target의 정상 no-finding으로 축소하지 않는다.
- `/cluster/summary`의 `cluster_id`는 runtime에 설정된 cluster identity를 사용한다.
- `profiles`, Jobs, Risks, Insights의 stored risk section, auth/account/admin은 Proxmox inventory가 non-live여도 자체 책임 범위에서 계속 사용할 수 있다.

### Jobs·artifacts·risks

| Method | Path | 권한 | 현재 책임 |
|---|---|---|---|
| `GET` | `/api/v1/jobs` | viewer | latest job projection 목록 |
| `GET` | `/api/v1/jobs/{job_id}` | viewer | job 상세 |
| `GET` | `/api/v1/jobs/{job_id}/artifacts` | viewer | artifact metadata 목록 |
| `GET` | `/api/v1/risks` | viewer | job record에서 파생한 risk 목록 |

`job_runs`/`job_artifacts`는 목표 append-only operation/evidence 계약이 아니다. 정상 empty 결과의 기존 success envelope은 유지하지만 persistence read 실패는 빈 목록으로 축소하지 않는다. `/jobs`, job detail·artifacts는 `503 JOBS_PERSISTENCE_UNAVAILABLE`, `/risks`는 `503 RISKS_PERSISTENCE_UNAVAILABLE`을 반환하며 detail에는 `retryable=true`, `side_effects=[]`가 포함된다. 실제로 존재하지 않는 job은 기존 `404`다. `vm_shutdown` compatibility job은 `precheck → shutdown → task_poll → post_check` 단계를 사용한다.

### Insights

| Method | Path | 권한 | side effect | 현재 책임 |
|---|---|---|---|---|
| `GET` | `/api/v1/insights` | viewer | 없음 | risk/readiness/capacity/placement의 availability-aware aggregate |

응답 `data`는 `execution_mode=observe_only`, `read_only=true`, `allowed_actions=[]`를 고정하고 `risk`, `readiness`, `capacity`, `placement` 네 section을 반환한다. 각 section과 finding은 `source`, `observed_at`, `freshness`, `rule_version`, redacted `evidence`와 실행 불가 계약을 가진다. finding은 section당 최대 200개를 반환하고 `finding_count`, `returned_finding_count`, `truncated`로 잘림 여부를 공개한다.

현재 placement finding의 `source=drs_advisor`와 `drs-rec-*` ID는 DRS 명칭을 포함하지만 공개 compatibility 계약이다. 저장소 안팎 consumer와 stable alias 또는 deprecation 방식을 확인·승인하기 전에는 값이나 의미를 바꾸지 않는다.

- 기존 `/api/v1/risks`는 compatibility payload 의미를 유지하되 strict job read를 사용하고 DB read failure를 `503 RISKS_PERSISTENCE_UNAVAILABLE`로 반환한다. `/insights`도 strict read를 사용하되 risk section 안에서 source 장애를 `unavailable`로 격리한다.
- Proxmox가 `unconfigured`/`degraded`이면 stored risk는 독립 조회하고 readiness/capacity/placement는 source reason을 포함한 `unavailable`로 반환한다. fake나 stale snapshot으로 대체하지 않는다.
- partial snapshot에서 exact VM의 `vm_config`·`guest_agent`·`vm_detail` 또는 node의 storage 관찰이 실패하면 해당 readiness/capacity finding을 `unknown` evidence로 보존한다. 다른 source에서 이미 확인한 config lock 같은 known critical은 unknown finding과 함께 유지하며, 실패한 source의 빈 값만 실제 부재 warning으로 해석하지 않는다.
- live observation에서도 CPU/memory/storage evidence가 일부 없거나 node inventory가 비어 있으면 capacity와 영향받는 placement를 `ready`로 축소하지 않는다.
- Placement는 `backend/app/insights/placement.py`의 infrastructure-free neutral 계산만 사용하며 identity/policy/lock DB 접근을 수행하지 않는다. `drs_advisor`와 `drs-rec-*`는 opaque legacy compatibility 값일 뿐 DRS runtime 호출이나 실행 가능성을 의미하지 않는다. `/insights`에는 check, approval packet, operation, execute, reconciliation action이나 link가 없다.

### VM action

| Method | Path | 권한 | side effect | 현재 gate |
|---|---|---|---|---|
| `POST` | `/api/v1/nodes/{node_id}/vms/{vmid}/actions/start` | operator | Proxmox VM start | acknowledgement, idempotency key, fresh pre-check, lock, task poll, post-check |
| `POST` | `/api/v1/nodes/{node_id}/vms/{vmid}/actions/shutdown` | operator | Proxmox graceful VM shutdown | acknowledgement, idempotency key, running pre-check, recovery registration, task/direct stopped verification |
| `POST` | `/api/v1/nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence` | operator | local evidence only | sanitized payload, live check/command/secret field 거부 |

VM Start는 구현된 `managed_api` Operations vertical slice다. 현재 구현은 같은 node/VMID/idempotency key와 같은 intent를 기존 결과로 replay하고, 그 operation identity에서 expected context가 다른 intent는 `409` conflict로 거부한다. 현재 한 개의 configured Proxmox cluster를 전제로 `vmid` 단위 PostgreSQL durable locator lock과 compatibility file guard를 잡으며, POST timeout·missing UPID·task unknown·post-check mismatch는 mutation을 재호출하지 않고 `needs_reconciliation`과 retained lock으로 보존한다.

VM Start는 기존 job/artifact 계약과 함께 공통 `operations` projection과 `operation_events`를 기록한다. Proxmox POST 전에 recovery item/foreground lease를 등록하며 등록 실패는 `503 VM_START_RECOVERY_UNAVAILABLE`이고 POST를 호출하지 않는다. task poll은 lease를 heartbeat하고 fenced terminal commit만 target lock을 해제한다. 기존 success response envelope과 job payload는 바꾸지 않는다.

Graceful VM Shutdown은 별도 `vm_shutdown` common Operation과 기존 Jobs/artifact compatibility projection을 함께 기록한다. request는 `vm_shutdown_acknowledged=true`, non-empty `idempotency_key`, optional `expected_name`/`expected_status`를 받으며 exact running non-template VM만 허용한다. Proxmox 호출은 `POST /nodes/{node}/qemu/{vmid}/status/shutdown` 하나이고 hard `stop`, reboot 또는 timeout 후 강제 fallback은 없다. task `status=stopped`, `exitstatus=OK`와 direct VM `status=stopped`가 모두 확인된 경우에만 `succeeded`/`completed`다.

Shutdown recovery registration 실패는 `503 VM_SHUTDOWN_RECOVERY_UNAVAILABLE`이고 POST 전 차단된다. explicit clear 4xx는 `VM_SHUTDOWN_REQUEST_FAILED`; timeout·connection failure·missing UPID는 `VM_SHUTDOWN_REQUEST_RECONCILIATION_REQUIRED`; task/direct state 불일치는 `VM_SHUTDOWN_RESULT_RECONCILIATION_REQUIRED`; lease fencing 실패는 `503 VM_SHUTDOWN_RECOVERY_LEASE_LOST`이며 target lock을 유지한다. same key/same intent는 기존 result를 replay하고 different intent는 `VM_SHUTDOWN_IDEMPOTENCY_CONFLICT`다.

### Operations·Guided `qm`

| Method | Path | 권한 | side effect | 현재 책임 |
|---|---|---|---|---|
| `GET` | `/api/v1/operations` | viewer | 없음 | current projection 최신순 목록; `status`, `operation_type`, exact `target_type`, exact `target_id`, `limit=1..200` filter |
| `POST` | `/api/v1/operations/guided-qm/vm-unlock` | operator | 없음; instruction 발급만 | fixed `qm unlock` plan, pre-check, target lock, 5분 bundle |
| `GET` | `/api/v1/operations/{operation_id}` | viewer | 없음 | current projection, checksum-linked event timeline, optional recovery/target lock 조회 |
| `POST` | `/api/v1/operations/{operation_id}/operator-attestation` | operator | local state only | 외부 command 실행 사실의 trusted actor attestation |
| `POST` | `/api/v1/operations/{operation_id}/verification` | operator | Proxmox read only | config lock·active task after-state 검증 |

목록은 `updated_at DESC`, `operation_id DESC` 순서이며 event와 detail payload를 제외한 projection summary를 반환한다. target filter는 다른 filter와 AND로 결합하고 문자열 exact equality를 사용한다. 상세 조회는 Operation 공통 query boundary가 projection과 event를 조합하고 optional `recovery`, `target_lock`을 additive하게 제공한다. `recovery`에는 kind/status/due/lease owner·generation·expiry/attempt/error/redacted details가 있지만 private lease token은 없다. Guided operation에만 instruction bundle과 no-executor evidence를 추가한다. 없는 상세는 기존 `404 GUIDED_QM_OPERATION_NOT_FOUND`를 유지하고 additive `canonical_code=OPERATION_NOT_FOUND`를 제공한다.

Plan request는 다음 네 field만 허용한다.

```json
{
  "node_id": "node-a",
  "vmid": 306,
  "idempotency_key": "unlock-306-1",
  "qm_unlock_risk_acknowledged": true
}
```

- `vmid`는 JSON integer `100..999999999`, `node_id`와 `idempotency_key`는 제한된 identifier 문자만 허용한다.
- `command`, `arguments`, `options`, actor, token/password 등 extra field는 `GUIDED_QM_UNSUPPORTED_FIELD`로 거부한다.
- server만 `program=qm`, `arguments=["unlock", "<vmid>"]`를 생성한다. backend shell/SSH executor와 API→CLI fallback은 없다.
- instruction 전 Proxmox token의 `/nodes/{node}` `Sys.Audit`, VM active task 부재, 현재 config lock 존재와 allowlisted lock type을 확인한다.
- allowlisted lock은 `backup`, `clone`, `create`, `migrate`, `rollback`, `snapshot`, `snapshot-delete`, `suspending`이다. `suspended`와 알 수 없는 future lock은 거부한다.
- attestation request는 issued bundle의 `plan_digest`와 `command_executed=true`만 받는다. verification request는 같은 `plan_digest`만 받는다.
- attestation은 성공 증거가 아니다. verification이 config lock 부재와 active task 부재를 확인해야 `succeeded`와 target lock 해제가 가능하다.
- API 관찰 실패, after-state 불일치, late attestation, target lock 유실은 성공으로 축소하지 않고 `needs_reconciliation`을 유지한다. 저장된 `verifying` 상태도 같은 verification endpoint로 재개할 수 있다.
- same scoped key/same intent는 기존 operation을 반환하고 다른 intent/digest는 conflict다.

### Create VM

| Method | Path | 권한 | side effect | 현재 책임 |
|---|---|---|---|---|
| `POST` | `/api/v1/vm-create/drafts` | operator | local only | default draft 생성 |
| `POST` | `/api/v1/vm-create/{draft_id}/preflight` | operator | local/read only | input·inventory preflight |
| `POST` | `/api/v1/vm-create/{draft_id}/plan` | operator | local only | immutable-equivalent plan 생성 |
| `POST` | `/api/v1/vm-create/{draft_id}/approve` | operator | local only | approval validation/evidence |
| `POST` | `/api/v1/vm-create/{draft_id}/proxmox-preview` | operator | local/read only | Proxmox create preview |
| `POST` | `/api/v1/vm-create/{draft_id}/proxmox-create` | operator | Proxmox clone/config/optional boot | approval binding, acknowledgement, native create, optional verification |

이 다단계 endpoint는 전환 동안 호환 facade를 유지하면서 `vm_create` common Operation을 함께 기록한다. `plan`, `approve`, `proxmox-preview`, 성공·replay된 `proxmox-create`의 `data`에는 additive `operation_id`와 `operation` link가 포함된다. operation은 plan에서 `awaiting_approval` 또는 red risk의 `blocked`로 준비되고 exact approval, preview, dispatch, running, verifying, success/reconciliation event를 기록한다.

final create는 같은 job/intent의 완료 결과를 mutation 없이 replay하고, 같은 job의 다른 intent와 같은 VMID를 소유한 다른 active/reconciliation/completed request를 `409`로 차단한다. VM Start와 같은 VMID PostgreSQL locator lock과 compatibility file guard를 사용하며, 명확한 side-effect-free 거절만 common `failed`로 종료·해제하고 partial/unknown result는 common `needs_reconciliation`과 기존 `apply_failed`/`needs_reconciliation` compatibility 상태 및 retained lock으로 남긴다. 외부 effect 뒤 request/workload/job/artifact 또는 common evidence 저장이 실패하면 success를 공표하거나 lock을 해제하지 않는다.

## 공통 mutation 계약 기준선

- actor는 server-side session에서 얻고 request payload actor를 신뢰하지 않는다.
- action별 exact acknowledgement field와 `operator+` role을 요구한다.
- Create VM, VM Start, VM Shutdown과 Guided `qm unlock`은 현재 한 configured cluster의 VMID를 같은 PostgreSQL `proxmox_locator` open-lock namespace로 직렬화한다. Start/Shutdown/Create/Guided는 local file compatibility guard도 함께 사용한다.
- VM Start/Shutdown에서 common Operation을 기록한 뒤 target lock이 충돌하면 현재 요청 Operation을 side-effect 없는 terminal `blocked`로 전이한다. error detail은 현재 요청의 `operation_id`를 포함하며, 현재 lock owner를 확인할 수 있으면 `conflicting_operation_id`도 포함한다. lock evidence는 event와 projection details에 보존한다.
- 네 action slice는 서로 다른 idempotency/approval/error contract를 일부 유지하지만, covered ambiguity를 terminal failure로 축소하거나 자동 재호출하지 않는다.
- VM Start, VM Shutdown, Create VM과 Guided `qm`은 공통 operation resource/event를 기록한다. Start/Shutdown은 restart recovery item도 기록하고, Create VM은 기존 전용 state/job/artifact를 dual record한다.
- secret, token, password와 unsafe evidence field를 저장·응답하지 않아야 한다.

## 호환성 정책

- additive endpoint와 optional response field를 우선한다.
- 기존 endpoint를 application use case facade로 바꾸더라도 status, response/error shape, actor, acknowledgement, job/artifact 의미를 characterization test로 먼저 고정한다.
- frontend canonical route와 지원되는 legacy alias는 별도 폐기 결정 전 유지한다. exact VM route `/instances/:vmid`는 `/instances`, Insights target/finding과 Operations target을 `proxmox_vm`·`vmid:<VMID>` identity로 연결한다. 제거된 `/drs`와 `/instances/drs-policies`는 전용 redirect 없이 일반 unknown-path 처리된다.
- Operation 상세 UI는 intent/plan digest, 마지막 event checksum, event별 redacted payload와 checksum chain을 표시한다. non-terminal 상태는 5초 간격, 최대 60회로 제한해 조회하고 terminal·오류·unmount에서 중단한다. request generation guard가 route 변경·수동 refresh·background polling의 늦은 이전 응답을 폐기한다.
- exact-target Insights는 `ready|attention`과 `fresh|recorded|fixture`, non-truncated 응답에서만 finding 부재를 확정한다. 오래된 `finding` query ID가 현재 응답에 없으면 같은 target의 새 finding을 숨기지 않고 stale link를 별도 안내한다.
- Insights canonical route는 `/insights`, `/insights/risks`, `/insights/readiness`, `/insights/capacity`, `/insights/placement`다. 기존 `/operations/risks`, `/risks`는 compatibility route로 유지한다.
- operation API가 확장되고 모든 internal consumer가 전환된 뒤에만 기존 workflow endpoint deprecation을 제안한다.

## 구현과 검증

- 진입점: `backend/app/auth/api.py`, `backend/app/auth/admin_api.py`, `/api/v1` composition root `backend/app/api/v1/router.py`.
- query route module: `backend/app/api/v1/inventory.py`, `operations.py`, `insights.py`, `jobs_compat.py`; shared inventory provider는 `inventory_context.py`.
- Guided `qm` route module: `backend/app/api/v1/guided_qm.py`; plan·attestation·verification의 operator dependency, observation client provider와 error mapping을 소유한다.
- VM action route module: `backend/app/api/v1/vm_actions.py`; Start/Shutdown application workflow와 post-create readiness facade를 HTTP에 mapping한다.
- Create VM route module: `backend/app/api/v1/vm_create_compat.py`; 기존 6개 path와 operator dependency, response/error mapping을 유지하고 `backend/app/vm_create/application.py`의 draft→preflight→plan→approval→preview/execute orchestration을 호출한다.
- success helper: `backend/app/api/v1/responses.py`.
- frontend consumer: `frontend/src/shared/api/apiV1.js`; 기존 `frontend/src/services/apiV1.js`는 compatibility export다.
- contract test: `backend/tests/contracts/test_api_v1_route_registry.py`, 나머지 `backend/tests/contracts/`, frontend `apiV1Client`, auth, navigation과 feature tests.
- `/api/v1`은 39개 route이며 exact method/path/auth contract와 `/api/v1/drs` 부재를 test로 고정한다. 2026-08-26 기준 backend 전체 422개 test와 5개 skip, frontend 17개 contract test 파일, ESLint와 production build가 통과했으며 세부 결과는 현재 구현 Plan에 기록한다. Python 3.13 backend-test container와 Node 24 production image도 같은 worktree에서 검증했으며, 이번 변경에서는 DB schema/data와 live Proxmox mutation을 다루지 않았다.
