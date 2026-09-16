# API 계약: 현재 `/api/v1` 기준선

- 상태: `APPROVED`
- 최종 검토일: `2026-09-07`
- 부분 검토: `2026-09-14`, Start/Shutdown 요청 조정과 프리셋·이력 보존 정책
- 검토 범위: 현재 route 선언·registry contract, inventory gate, 네 action recovery와 frontend 경로
- 문서 안내: [문서 홈](../README.md) · [실행·장애 대응](../operations/runbook.md)
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
| `POST` | `/api/v1/auth/logout` | public | cookie의 session이 있으면 revoke, cookie 제거 |
| `GET` | `/api/v1/auth/me` | public | session 상태 조회; 미인증이면 `authenticated=false`, `user=null` |
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
| `GET` | `/api/v1/networks` | viewer | network inventory |

connection status의 `data`는 `state`, `source`, `cluster_id`, `observed_at`, `freshness`, `reason`, `configured`, `inventory_available`, `missing_configuration`을 반환한다. token, URL, upstream raw error는 반환하지 않는다. 이 endpoint는 mutation token 권한을 추론하지 않는다.

- 필수 설정 누락·invalid mode: `unconfigured`.
- authoritative snapshot이 모든 기대 sub-source를 관찰하면 `live`, `source=live_read_only`, `freshness=fresh`다.
- base snapshot은 있으나 storage, network, VM config, guest-agent 또는 VM detail 일부가 실패하면 `degraded`, `freshness=partial`, `reason=proxmox_inventory_partial`, `inventory_available=true`다. 정상 source 데이터는 유지하고 실패 source를 빈 정상 상태로 해석하지 않는다.
- 설정됐지만 TLS·timeout·network·authentication 또는 base API read 실패로 snapshot 자체가 없으면 `degraded`와 redacted reason code다.
- `cluster/summary`, nodes, VMs, templates, storage, networks는 snapshot이 없을 때 `503`을 반환한다. Create 입력·검토는 partial base snapshot에서도 가능하다. Create 실행은 guest agent 외 source의 complete 관찰을 요구한다. 고정 IP는 입력한 주소의 ping 응답과 기존 VM 설정·guest agent IP 정보를 함께 확인한다. 어느 쪽이든 점유가 발견되면 red로 차단하며, 점유 미발견·조회 불가는 yellow로 직접 확보한 IP인지 확인받는다. 기존 VM의 guest agent 누락만으로 차단하지 않는다. DHCP discovery 경고와 최초 mutation 직전 재검증은 유지한다. Start/Shutdown/Guided의 complete-live 조건은 유지한다.
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
- Proxmox snapshot이 없으면 stored risk는 독립 조회하고 readiness/capacity/placement는 source reason을 포함한 `unavailable`로 반환한다. `degraded/partial`이어도 snapshot이 있으면 정상 source를 사용하고 실패 source의 불확실성을 표시한다. fake나 durable stale snapshot으로 대체하지 않는다.
- partial snapshot에서 exact VM의 `vm_config`·`guest_agent`·`vm_detail` 또는 node의 storage 관찰이 실패하면 해당 readiness/capacity finding을 `unknown` evidence로 보존한다. 다른 source에서 이미 확인한 config lock 같은 known critical은 unknown finding과 함께 유지하며, 실패한 source의 빈 값만 실제 부재 warning으로 해석하지 않는다.
- live observation에서도 CPU/memory/storage evidence가 일부 없거나 node inventory가 비어 있으면 capacity와 영향받는 placement를 `ready`로 축소하지 않는다.
- Placement는 `backend/app/insights/placement.py`의 infrastructure-free neutral 계산만 사용하며 identity/policy/lock DB 접근을 수행하지 않는다. `drs_advisor`와 `drs-rec-*`는 opaque legacy compatibility 값일 뿐 DRS runtime 호출이나 실행 가능성을 의미하지 않는다. `/insights`에는 check, approval packet, operation, execute, reconciliation action이나 link가 없다.

### VM action

| Method | Path | 권한 | side effect | 현재 gate |
|---|---|---|---|---|
| `POST` | `/api/v1/nodes/{node_id}/vms/{vmid}/actions/start` | operator | Proxmox VM start | acknowledgement, idempotency key, fresh pre-check, lock, task poll, post-check |
| `POST` | `/api/v1/nodes/{node_id}/vms/{vmid}/actions/shutdown` | operator | Proxmox graceful VM shutdown | acknowledgement, idempotency key, running pre-check, recovery registration, task/direct stopped verification |
| `POST` | `/api/v1/nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence` | operator | local evidence only | sanitized payload, live check/command/secret field 거부 |

VM Start는 구현된 `managed_api` Operations vertical slice다. 현재 구현은 같은 node/VMID/idempotency key와 같은 intent를 기존 결과로 replay하고, 그 operation identity에서 expected context가 다른 intent는 `409` conflict로 거부한다. 현재 한 개의 configured Proxmox cluster를 전제로 `vmid` 단위 PostgreSQL durable locator lock을 잡으며, POST timeout·missing UPID·task unknown·post-check mismatch는 mutation을 재호출하지 않고 `needs_reconciliation`과 retained lock으로 보존한다.

VM Start는 기존 job/artifact 계약과 함께 공통 `operations` projection과 `operation_events`를 기록한다. Proxmox POST 전에 recovery item/foreground lease를 등록하며 등록 실패는 `503 VM_START_RECOVERY_UNAVAILABLE`이고 POST를 호출하지 않는다. dispatch 이후 task poll은 lease를 heartbeat하고 recovery가 소유한 target lock은 fenced terminal commit으로 해제한다. 기존 success response envelope과 job payload는 바꾸지 않는다.

Start recovery는 recovery kind, operation type/mode, exact target/node/VMID, stored UPID와 현재 durable lock owner/id를 함께 검증한다. 진행 중 task는 bounded `retry_wait`다. 명확한 task/after-state 성공·실패는 먼저 terminal Operation event를 기록하면서 recovery lease와 target lock을 유지한다. 이후 Jobs projection·후속 Operation event·recovery completion·exact DB lock release를 같은 transaction으로 commit한다. 따라서 terminal Operation도 coordination이 끝났다는 뜻은 아니다. binding mismatch, missing UPID, task/actual-state mismatch와 projection 실패는 lock을 유지한다. current recovery contract가 표시한 genuine pre-dispatch no-effect terminal(`blocked|failed`)은 latest event checksum과 exact lock binding을 검증한 뒤 Proxmox GET 없이 누락 Jobs projection·DB lock만 닫는다.

Graceful VM Shutdown은 별도 `vm_shutdown` common Operation과 기존 Jobs/artifact compatibility projection을 함께 기록한다. request는 `vm_shutdown_acknowledged=true`, non-empty `idempotency_key`, optional `expected_name`/`expected_status`를 받으며 exact running non-template VM만 허용한다. Proxmox 호출은 `POST /nodes/{node}/qemu/{vmid}/status/shutdown` 하나이고 hard `stop`, reboot 또는 timeout 후 강제 fallback은 없다. task `status=stopped`, `exitstatus=OK`와 direct VM `status=stopped`가 모두 확인된 경우에만 `succeeded`/`completed`다.

Shutdown recovery registration 실패는 `503 VM_SHUTDOWN_RECOVERY_UNAVAILABLE`이고 POST 전 차단된다. explicit clear 4xx는 `VM_SHUTDOWN_REQUEST_FAILED`; timeout·connection failure·missing UPID는 `VM_SHUTDOWN_REQUEST_RECONCILIATION_REQUIRED`; task/direct state 불일치는 `VM_SHUTDOWN_RESULT_RECONCILIATION_REQUIRED`; lease fencing 실패는 `503 VM_SHUTDOWN_RECOVERY_LEASE_LOST`이며 target lock을 유지한다. same key/same intent는 기존 result를 replay하고 different intent는 `VM_SHUTDOWN_IDEMPOTENCY_CONFLICT`다.

Shutdown recovery도 exact Operation/target/UPID/lock binding과 bounded task observation을 사용한다. Start와 같이 terminal evidence를 먼저 저장하고, Jobs projection·후속 event·recovery completion·DB lock release를 fenced transaction으로 닫는다. current contract의 genuine pre-dispatch no-effect terminal도 Start와 같은 marker/checksum/lock 검증 뒤 local projection만 복구한다. recovery observer는 graceful shutdown POST, hard stop, reboot를 호출할 capability가 없다.

Start/Shutdown mutation client 생성 실패·부재와 recovery 등록 실패는 no-effect failed Jobs를 먼저 저장한다. Operation row를 잠근 상태에서 recovery item이 없고 `planned`·exact owned lock이 확인된 경우에만 foreground가 canonical `failed`를 commit한 뒤 별도로 lock을 해제한다. replay/recovery가 먼저 item을 만들었거나 canonical 상태가 바뀌었으면 foreground는 전이·release를 수행하지 않는다. 늦은 replay의 version/checksum 충돌도 현재 terminal no-effect marker와 같은 lock ID·cluster가 확인되면 기존 실패 결과로 replay하며 mutation을 호출하지 않는다. 기존 client/recovery unavailable 오류 계약은 유지한다.

Start/Shutdown에서 external effect와 canonical task/state observation 뒤 observed-after artifact 저장이 실패하면 각각 `503 VM_START_OBSERVED_EVIDENCE_PERSISTENCE_UNAVAILABLE`, `503 VM_SHUTDOWN_OBSERVED_EVIDENCE_PERSISTENCE_UNAVAILABLE`을 반환한다. terminal Operation 뒤 Jobs projection 실패는 `*_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE`이다. 네 응답은 exact `operation_id=job_id`, target, bounded side effects, evidence/Operation/recovery 상태와 retained lock을 제공하며 recovery를 가능한 경우 즉시 `retry_wait`로 넘긴다. secondary handoff write도 실패하면 기존 lease와 lock을 보존하고 stable `503`을 유지한다. recovery는 fresh GET evidence와 Jobs projection만 보강하고 원본 artifact payload를 추정 재생성하지 않는다.

### Operations·Guided `qm`

| Method | Path | 권한 | side effect | 현재 책임 |
|---|---|---|---|---|
| `GET` | `/api/v1/operations` | viewer | 없음 | current projection 최신순 목록; `status`, `operation_type`, exact `target_type`, exact `target_id`, `limit=1..200` filter |
| `POST` | `/api/v1/operations/guided-qm/vm-unlock` | operator | Proxmox GET·local plan/lock 기록 | fixed `qm unlock` plan, pre-check, target lock, 5분 bundle; backend command 실행 없음 |
| `GET` | `/api/v1/operations/{operation_id}` | viewer | 없음 | current projection, checksum-linked event timeline, optional recovery/target lock 조회 |
| `POST` | `/api/v1/operations/{operation_id}/operator-attestation` | operator | local state only | 외부 command 실행 사실의 trusted actor attestation |
| `POST` | `/api/v1/operations/{operation_id}/recovery/observe` | operator | Proxmox GET·local recovery commit only | exact Operation version/checksum으로 action별 recovery observer 1회 요청 |
| `POST` | `/api/v1/operations/{operation_id}/verification` | operator | Proxmox GET·local 검증/lock 기록 | config lock·active task after-state 검증 |

목록은 `updated_at DESC`, `operation_id DESC` 순서이며 event와 detail payload를 제외한 projection summary를 반환한다. target filter는 다른 filter와 AND로 결합하고 문자열 exact equality를 사용한다. 상세 조회는 Operation 공통 query boundary가 projection과 event를 조합하고 optional `recovery`, `target_lock`, recovery `available_actions`와 `coordination_incomplete`를 additive하게 제공한다. `recovery`에는 kind/status/due/lease owner·generation·expiry/attempt/error/redacted details가 있지만 private lease token은 없다. Guided operation에는 instruction bundle과 `active|historical|do_not_execute` 상태를, Create VM에는 readiness·fingerprint·artifact checksum·작업별 workload 결과 요약을 추가한다. 없는 상세는 기존 `404 GUIDED_QM_OPERATION_NOT_FOUND`를 유지하고 additive `canonical_code=OPERATION_NOT_FOUND`를 제공한다.

Recovery observe request는 현재 Operation 상세에서 읽은 fence를 그대로 제출한다.

```json
{
  "expected_version": 7,
  "expected_checksum": "sha256:...",
  "idempotency_key": "recovery-observe:7:0123456789abcdef"
}
```

- `operator` 또는 `admin`만 호출할 수 있고, `expected_version`은 양의 정수이며 checksum과 최대 160자의 non-empty idempotency key가 필요하다. browser는 current Operation version/checksum으로 stable request key를 만든다.
- route는 action 이름이나 command를 받지 않는다. recovery kind allowlist는 `vm_start_observation`, `vm_shutdown_observation`, `vm_create_observation`, `guided_qm_unlock_observation` 네 개이고 handler에는 Proxmox GET과 local projection/coordination port만 제공된다.
- 같은 key와 같은 최초 fence는 결과를 replay한다. idempotency key 원문은 request 경계에서만 사용하고 event/recovery details에는 `sha256:` digest와 최초 version/checksum만 최대 64개 ledger로 저장한다. ledger를 교체·퇴출하지 않으므로 중간에 다른 key가 사용돼도 기존 key의 다른 fence 재사용은 `409`다. 안전 상한에 도달하면 새 key도 `409`로 거부한다. stale version/checksum, live lease, unsupported/binding mismatch, exact owned lock 부재와 side-effect-free임을 증명할 수 없는 no-item 상태도 `409`다.
- Proxmox observation 또는 recovery persistence가 일시적으로 불가능하거나 bounded retry가 소진되면 `503`이다. invalid request는 `422`, 없는 Operation은 `404`다.
- background runner의 enable 여부와 무관하게 이 endpoint는 요청 시 한 exact item만 claim한다. 성공 응답은 갱신된 Operation detail과 `recovery_observation.observation_only=true`를 반환하며 원래 mutation, Guided command 또는 compensating action을 실행하지 않는다.
- 상세의 observe action은 retry 가능 observation/projection/cleanup 또는 fresh evidence로 의미가 바뀔 수 있는 action-specific 상태에만 제공한다. missing task reference, exact binding/lock 유실, attestation 필요처럼 수동 권위나 사전 repair가 필요한 paused 상태에는 버튼을 advertise하지 않으며 직접 호출도 `409`로 차단한다.

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
- 최초 GET eligibility 확인 뒤 provisional `planned` Operation과 recovery item/lease를 만들고 exact target lock을 획득·원자적으로 결합한다. 다시 authoritative config/task와 exact lock을 확인한 뒤에만 instruction을 공개한다. issued instruction은 expiry 시각까지 `retry_wait`이며 enabled runner 또는 operator observe가 planned handoff, expiry observation과 attested verification을 GET-only로 재개할 수 있다. checksum-valid `planned`에 bundle/exposed evidence가 전혀 없는 no-item crash만 item을 복원할 수 있고, exact own lock도 없으면 Proxmox GET 없이 side-effect-free `blocked`로 닫는다.
- expiry 전 `awaiting_operator` instruction만 active다. expiry 시 original config lock이 그대로 있고 active task와 attestation이 없다는 authoritative observation이 있을 때만 `expired`와 lock release가 가능하다. lock 부재·변경, active task, lock 해제 가능성, observation 실패는 reconciliation 또는 bounded retry다.
- expiry 이후와 `expired`/`needs_reconciliation` instruction은 historical `do_not_execute` evidence다. late attestation은 이미 발생한 실행만 기록해 `needs_reconciliation`으로 다시 열며 stale command를 실행하거나 replay하지 않는다. late attestation은 generic/background recovery가 자동 검증하지 않고 pause한다. 기존 verification endpoint만 수동 operator 권위로 사용할 수 있으며 그 경우에도 recorded/current exact target lock이 모두 `active`여야 한다.
- same scoped key/same intent는 기존 operation을 반환하고 다른 intent/digest는 conflict다.

### Create VM

| Method | Path | 권한 | side effect | 현재 책임 |
|---|---|---|---|---|
| `POST` | `/api/v1/vm-create/drafts` | operator | local only | default draft 생성 |
| `POST` | `/api/v1/vm-create/{draft_id}/preflight` | operator | local/read only | input·inventory preflight |
| `POST` | `/api/v1/vm-create/{draft_id}/plan` | operator | local/read only | 현재 입력·inventory로 plan 재구성, artifact와 Operation 기록 |
| `POST` | `/api/v1/vm-create/{draft_id}/approve` | operator | local only | approval validation/evidence |
| `POST` | `/api/v1/vm-create/{draft_id}/proxmox-preview` | operator | local/read only | Proxmox create preview |
| `POST` | `/api/v1/vm-create/{draft_id}/proxmox-create` | operator | Proxmox template clone/resize/config/optional start | approval binding, acknowledgement, task·after-state·선택한 readiness 검증 |

현재 생성 방식은 기존 Proxmox template의 clone이다. ISO 설치·빈 VM 생성 API는 없다. `profile_id`는 DB의 활성 Create profile을 사용하며 생략 시 `general-vm` 기본값을 적용한다. template/node/storage/network와 hardware·access 입력은 해당 profile의 기본값·제약과 live inventory를 기준으로 검토한다. 기본 UI는 아래 template 직접 입력 모드를 사용한다.

`draft_id`는 저장된 draft를 조회하는 API resource가 아니다. 각 단계가 같은 identity와 입력으로 draft/plan을 다시 구성하며, `drafts`·`preflight`·`plan`·`approve`·`proxmox-preview`도 Jobs/artifact·Operation 등 로컬 DB 쓰기를 수행한다. 외부 Proxmox mutation이 없다는 의미의 `local/read only`이지 DB 무변경 계약은 아니다. Create 입력·검토는 partial base snapshot에서도 가능하다. Create 실행은 guest agent 외 source의 complete 관찰을 요구한다. 고정 IP는 입력한 주소의 ping 응답과 기존 VM 설정·guest agent IP 정보를 함께 확인한다. 어느 쪽이든 점유가 발견되면 red로 차단하며, 점유 미발견·조회 불가는 yellow로 직접 확보한 IP인지 확인받는다. 기존 VM의 guest agent 누락만으로 차단하지 않는다. DHCP discovery 경고와 최초 mutation 직전 재검증은 유지한다. Start/Shutdown/Guided의 complete-live 조건은 유지한다. 다른 VM guest agent 실패 상세와 비점유 ping의 무응답·실행 불가 사유는 preflight에 남기며 exact plan의 risk summary·승인 checksum에서는 변동하는 상세를 제외한다. 고정 IP의 `static_ip_usage_unverified` 또는 DHCP의 `dhcp_requires_discovery` 경고와 명시적 yellow acknowledgement는 유지한다. 실제 점유가 발견되면 `static_ip_unavailable` red로 차단하며 새 IP 점유와 필수 생성 조건은 실행 직전에도 재검증한다.

`creation_mode=template`을 지정하면 `template_node_id`와 `template_vmid`가 필수이며 DB 프로필을 조회하지 않는다. 선택적 `template_id`는 같은 template를 가리켜야 한다. CPU·memory_mb·disk_gb는 생략하면 template 기본값, 입력하면 양의 정수여야 한다. 사용자명은 직접 입력하며 기존 SSH·네트워크 검증을 유지한다. 이 모드의 `profile_id`는 빈 문자열, `profile_hardware_limits`는 빈 객체로 기록한다.

선택적 프리셋은 기존 DB 저장을 유지한다. [ADR-012](../decisions/adr-012-create-preset-and-history-retention.md)에 따라 현재 저장 단위의 입력·검토·승인·작업 기록은 자동 만료·삭제 없이 보존하지만, Jobs는 최신 상태이고 동일 artifact identity는 upsert하므로 revision 전체를 조회하는 계약은 아니다. 이 정책은 endpoint·요청 필드·승인 checksum과 기존 조회·replay 계약을 변경하지 않는다.

mode 생략 또는 `creation_mode=profile`은 기존 DB profile 경로다. template mode와 profile_id의 동시 선택은 `422 AMBIGUOUS_CREATE_MODE`, 알 수 없는 mode는 `422 INVALID_CREATE_MODE`, template 부재/불일치는 `422 CREATE_TEMPLATE_UNAVAILABLE`/`CREATE_TEMPLATE_ID_MISMATCH`, 잘못된 직접 사양은 `422 INVALID_CREATE_HARDWARE`다. 직접 입력의 CPU·memory는 관찰된 대상 노드 용량을 넘으면 preflight red가 된다. 승인 이후 fresh 재검증에서 template가 사라진 경우는 입력 오류 대신 기존 `409 PROXMOX_CREATE_STATE_CHANGED`로 처리한다. 6개 route와 compatibility write·기존 profile 요청의 의미는 유지한다.

이 다단계 endpoint는 전환 동안 호환 facade를 유지하면서 `vm_create` common Operation을 함께 기록한다. `plan`, `approve`, `proxmox-preview`, 성공·replay된 `proxmox-create`의 `data`에는 additive `operation_id`와 `operation` link가 포함된다. operation은 plan에서 `awaiting_approval` 또는 red risk의 `blocked`로 준비되고 exact approval, preview, dispatch, running, verifying, success/reconciliation event를 기록한다.

final create는 같은 job/intent의 완료 결과를 mutation 없이 replay하고, 같은 job의 다른 intent와 같은 VMID를 소유한 다른 active/reconciliation request를 `409`로 차단한다. VM Start와 같은 VMID PostgreSQL locator lock을 사용하며, lock 직후 external mutation 전에 `vm_create_observation` item/foreground lease를 저장한다. recovery details는 plan digest, target/node/VMID, power/readiness contract와 exact lock id/cluster를 결합한다.

runner는 clone 전·UPID 직후, resize/config/start 각 mutation 전후, task/post-check, `readiness_observed`, `observed_after_artifact_recorded`를 durable checkpoint로 남긴다. checkpoint 실패 뒤 후속 mutation을 호출하지 않는다. 명확한 side-effect-free 거절만 common `failed`로 종료·해제하고 partial/unknown result는 common `needs_reconciliation`과 기존 `apply_failed`/`needs_reconciliation` compatibility 상태 및 retained lock으로 남긴다. 외부 effect 뒤 request/workload/job/artifact 또는 common evidence 저장이 실패하면 success를 공표하거나 lock을 해제하지 않는다.

recovery handler는 pending/dispatched phase에서 형식이 검증된 stored UPID task, exact VM status/config만 읽고 mutation을 replay하지 않는다. invalid task locator는 원문을 새 evidence에 남기거나 task GET에 쓰지 않고 scrub 후 수동 reconciliation으로 pause한다. `readiness_observed` 또는 artifact checkpoint에 성공 결과와 persisted fingerprint가 있으면 fresh exact status/config가 일치할 때만 observed-after artifact와 request/job와 Operation 결과 projection을 idempotent하게 재구성해 roll-forward한다. 이때 실제 `job_artifacts.content_text`의 SHA-256이 row checksum·checkpoint checksum과 일치하고 JSON이 redacted `observed_after`와 추가 field 없이 정확히 같아야 하며, 손상·불일치는 전체 projection을 rollback한다. stored clone/start task가 명확한 non-OK terminal이고 exact VM status GET이 `404`로 target 부재를 확인한 경우만 compatibility failure projection을 닫고 `failed`로 종료한다. mismatch, 불충분한 evidence와 ambiguous mutation phase는 수동 판단을 위해 `paused`/`needs_reconciliation`과 lock을 유지한다. exact approved Operation+owned lock+공통 pre-dispatch marker가 있지만 recovery item이 없는 acquire 직후 crash window만 mutation·Proxmox read 없이 side-effect-free `blocked`로 닫을 수 있다.

고정 IP의 `static_ip_available` check는 `detail.result`(`in_use`/`unverified`), `conflicts`, `inventory`(관찰된 중복·guest agent 관찰 완전성·실패 대상), `ping`(`status`, 안전한 `reason`, `source=icmp`, `execution_location=gjallar_backend`)을 제공한다. 무응답·실행 불가를 pass/미사용으로 표시하지 않는다. `plan` 응답의 additive `preflight`는 계획과 같은 계산 결과이며 UI는 앞선 별도 preflight 응답보다 이를 우선한다. preflight의 ICMP 요청은 활성 네트워크 관찰이며, 기존 `side_effects=[]`는 Proxmox mutation이 없다는 의미다.

`proxmox-create`는 durable dispatch 준비 후 client 생성 전에 cache 없는 새 관찰로 승인 내용을 재검증한다. 승인 관련 상태가 바뀌면 `409 PROXMOX_CREATE_STATE_CHANGED`, snapshot 부재·guest agent 외 source 실패이면 `503 PROXMOX_INVENTORY_DEGRADED`(미설정은 `PROXMOX_INVENTORY_UNCONFIGURED`)를 반환한다. `side_effects=[]`이며 정상적인 실패 기록 완료 시 새 검토·새 작업으로 진행한다. 기록/lock 정리 실패는 기존 recovery persistence 오류로 보존한다. 이 검사는 완료된 동일 요청의 historical replay에는 수행하지 않는다.

Create completed replay는 succeeded Operation의 target·node·VMID와 저장된 workload 결과를 검증해 생성 당시 결과를 반환한다. 현재 `vm_instances` linkage가 삭제되거나 다른 작업 소유가 되어도 유효한 과거 결과는 유지한다. succeeded Operation의 결과가 누락·손상되면 `409 PROXMOX_CREATE_RECONCILIATION_REQUIRED`로 중단한다. 아직 succeeded Operation이 없는 legacy 호환 요청만 exact `create_job_id`·node·VMID linkage를 사용한다. 응답의 VM 정보는 현재 상태를 뜻하지 않으며 mutation을 다시 실행하지 않는다.

post-create readiness endpoint의 기존 Jobs/artifact record는 유지한다. 명시된 `create_operation_id`와 저장된 evidence owner가 succeeded Create Operation을 가리키고 node/VMID/target/workload가 정확히 일치하며 실제 `job_artifacts` row의 job/type/checksum도 요청 결과와 일치할 때만 `post_create_readiness_evidence_linked` event와 checksum reference를 owning Operation에 한 번 추가한다. owner 또는 artifact binding이 없거나 손상됐으면 Jobs-only로 남고 다른 Operation에 추정 연결하지 않는다. evidence 기록 뒤 Operation append만 실패하면 stable `503`으로 exact job/target을 반환하며 같은 evidence identity replay가 artifact 중복 없이 link를 repair한다.

## 공통 mutation 계약 기준선

- actor는 server-side session에서 얻고 request payload actor를 신뢰하지 않는다. operator recovery 요청 event는 그 session actor를 기록하고, 이후 자동 GET observation·projection event는 `system:operation-recovery` actor를 기록한다.
- action별 exact acknowledgement field와 `operator+` role을 요구한다.
- Create VM, VM Start, VM Shutdown과 Guided `qm unlock`은 현재 한 configured cluster의 VMID를 같은 PostgreSQL `proxmox_locator` open-lock namespace로 직렬화한다. 파일 guard는 사용하지 않는다.
- VM Start/Shutdown은 target lock 획득 직후와 충돌 직후 Jobs·Operation을 다시 조회한다. 같은 intent의 저장된 결과는 replay하고, 자신의 lock을 사용하는 동시 요청은 결과가 없으면 `409 VM_START_IN_PROGRESS` 또는 `VM_SHUTDOWN_IN_PROGRESS`로 응답하며 owner Operation을 `blocked`로 덮지 않는다. 완료 기록은 새 running projection이나 mutation으로 되돌리지 않는다.
- 다른 owner의 target lock 충돌은 기존 `409 *_TARGET_LOCK_BUSY` 계약으로 응답하며 현재 요청 `operation_id`와 확인 가능한 `conflicting_operation_id`를 포함한다. Operation이 여전히 `planned`이고 충돌했던 exact foreign lock이 open인 경우에만 같은 transaction에서 side-effect 없는 `blocked`와 lock evidence를 기록한다. 선행 요청이 그사이 Operation이나 lock을 변경했으면 해당 상태를 덮지 않는다. 과거 pre-dispatch no-effect replay는 기존 marker·binding·recovery fence 조건으로만 닫는다.
- 네 action slice는 서로 다른 idempotency/approval/error contract를 일부 유지하지만, covered ambiguity를 terminal failure로 축소하거나 자동 재호출하지 않는다.
- VM Start, VM Shutdown, Create VM과 Guided `qm`은 공통 operation resource/event와 action별 recovery item을 기록한다. Create VM은 기존 전용 request/workload/job/artifact를, Start/Shutdown은 기존 Jobs/Artifacts를 dual record한다.
- recovery commit은 current lease generation/token으로 처리 권한을 확인하고 경로별 Operation version/checksum·상태와 exact target lock binding을 검증한다. Create의 검증된 성공은 compatibility projection·terminal Operation event·recovery completion·DB lock release를 같은 transaction으로 기록한다. Start/Shutdown은 terminal event를 먼저 기록한다. 이후 foreground는 Jobs를 별도 저장한 뒤 completion·lock release를 commit하고, restart recovery는 Jobs projection·후속 event·recovery completion·DB lock release를 같은 마지막 transaction에 포함한다. coordination이 끝나기 전에는 DB lock을 유지하며 lease expiry만으로 풀지 않는다. 상세 순서는 [작업 흐름](../flows/verified-operation-lifecycle.md)을 따른다.
- `operations/core/evidence.py`가 Proxmox error·connection·task·VM status를 allowlist로 축소한다. raw API URL/credential/body·JSON value·exception/request path·poll history는 Operation/Jobs/artifact/recovery/API evidence에 남기지 않는다. Guided task identity는 digest와 bounded field만, config lock은 지원 enum·empty·`unsupported_present` marker만 보존한다.

## 호환성 정책

- additive endpoint와 optional response field를 우선한다.
- 기존 endpoint를 application use case facade로 바꾸더라도 status, response/error shape, actor, acknowledgement, job/artifact 의미를 characterization test로 먼저 고정한다.
- frontend canonical route와 지원되는 legacy alias는 별도 폐기 결정 전 유지한다. exact VM route `/instances/:vmid`는 `/instances`, Insights target/finding과 Operations target을 `proxmox_vm`·`vmid:<VMID>` identity로 연결한다. 제거된 `/drs`와 `/instances/drs-policies`는 전용 redirect 없이 일반 unknown-path 처리된다.
- 독립 Network readiness frontend 화면은 종료됐으며 `/instances/networks`와 `/networks`는 인증 후 `/instances`로 redirect한다. network inventory API `/api/v1/networks`, Create VM network preflight와 Insights의 VM readiness 계약은 유지한다.
- Operation 상세 UI는 intent/plan digest, 마지막 event checksum, event별 redacted payload와 checksum chain, recovery/target lock과 latest observation을 표시한다. recovery가 incomplete하거나 terminal Operation에 owned lock이 남으면 polling을 계속하고, paused/manual 상태에서는 자동 polling을 멈춘다. 자동 polling은 5초 간격·최대 60회로 제한한다. backend가 advertise한 observe action은 operator/admin에게 보여 주며 current version/checksum으로 fenced request를 보낸다. authoritative Proxmox GET이 필요한 recovery는 연결 불가 시 stable `503`으로 실패하고, local-only closure까지 mutation availability에 종속시키지 않는다. request generation guard가 route 변경·수동 refresh·background polling의 늦은 이전 응답을 폐기한다.
- exact-target Insights는 `ready|attention`과 `fresh|recorded|fixture`, non-truncated 응답에서만 finding 부재를 확정한다. 오래된 `finding` query ID가 현재 응답에 없으면 같은 target의 새 finding을 숨기지 않고 stale link를 별도 안내한다.
- Insights canonical route는 `/insights`, `/insights/risks`, `/insights/readiness`, `/insights/capacity`, `/insights/placement`다. 기존 `/operations/risks`, `/risks`는 compatibility route로 유지한다.
- operation API가 확장되고 모든 internal consumer가 전환된 뒤에만 기존 workflow endpoint deprecation을 제안한다.

## 구현과 검증

- 진입점: `backend/app/auth/api.py`, `backend/app/auth/admin_api.py`, `/api/v1` composition root `backend/app/api/v1/router.py`.
- query route module: `backend/app/api/v1/inventory.py`, `operations.py`, `insights.py`, `jobs_compat.py`; shared inventory provider는 `inventory_context.py`.
- Guided `qm` route module: `backend/app/api/v1/guided_qm.py`; plan·attestation·verification의 operator dependency, observation client provider와 error mapping을 소유한다.
- VM action route module: `backend/app/api/v1/vm_actions.py`; Start/Shutdown application workflow와 post-create readiness facade를 HTTP에 mapping한다.
- Create VM route module: `backend/app/api/v1/vm_create_compat.py`; 기존 6개 path에 VMID 추천 GET을 추가하며 operator dependency, response/error mapping을 유지하고 `backend/app/vm_create/application.py`의 draft→preflight→plan→approval→preview/execute orchestration을 호출한다.
- success helper: `backend/app/api/v1/responses.py`.
- frontend consumer: `frontend/src/shared/api/apiV1.js`; 기존 `frontend/src/services/apiV1.js`는 compatibility export다.
- contract test: `backend/tests/contracts/test_api_v1_route_registry.py`, 나머지 `backend/tests/contracts/`, frontend `apiV1Client`, auth, navigation과 feature tests.
- `/api/v1`은 additive recovery observe를 포함한 40개 route이며 exact method/path/auth contract와 `/api/v1/drs` 부재를 test로 고정한다. recovery 구현은 기존 `operations`, `operation_events`, `operation_recovery_items`, `operation_locks`와 compatibility table을 사용하며 DB schema/data migration과 live Proxmox mutation을 추가하지 않았다. 이 문서의 route 수는 현재 source와 registry contract를 대조한 기준선이다. 과거 구현 Plan의 테스트 결과를 이번 문서 갱신의 실행 결과로 간주하지 않는다.

### Create evidence helper의 역사 결과 출처

아래는 `app.vm_create.evidence`의 독립 read-only helper/CLI 출력 계약이다. 별도 HTTP endpoint를 추가한 것은 아니다.

Create evidence summary는 succeeded Operation의 검증된 workload snapshot을 생성 당시 VM 결과로 반환한다. 해당 경로의 observed_after는 같은 job의 request/artifact에서 읽으며 현재 VM row를 사용하지 않는다. `vm_instance_source`는 `operation_history`, `legacy_workload`, `not_recorded` 중 하나다. `vm_instance_found`는 표시할 생성 결과가 존재한다는 뜻이며 현재 인프라의 VM 존재 여부가 아니다. 성공 history 손상 시 현재 row로 대체하지 않는다. succeeded Operation 없는 legacy 조회만 기존 workload evidence를 읽고, 동일 job의 복수 row 또는 request와 다른 target은 미기록으로 표시한다.

### Readiness 생성 작업 지정

`POST /nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence`의 선택적 `create_operation_id`는 succeeded Create의 exact identity다. 생략하면 Jobs-only 증거로 저장한다. 제출 identity의 최초 owner와 Job/artifact를 한 transaction으로 확정하며, 이미 저장된 동일 evidence identity에 다른 owner를 지정하면 `409 POST_CREATE_READINESS_OWNER_CONFLICT`다. 같은 owner 재요청은 원래 증거를 replay한다. Operation 연결 실패는 증거를 덮어쓰지 않고 `503 POST_CREATE_READINESS_OPERATION_LINK_UNAVAILABLE`로 반환하며 재요청으로 연결을 복구한다.

### VM 생성 식별 정보

`GET /api/v1/vm-create/suggested-vmid`는 operator/admin용 읽기 API이며 `{vmid: 정수}`를 기존 성공 envelope로 반환한다. 번호를 예약하지 않는다. 생성 payload의 선택적 `vmid`는 100–999999999의 정수 또는 십진 정수 문자열이고, boolean·소수·범위 밖 값은 `422 INVALID_VM_ID`다. 생략 시 기존 자동 선택을 유지한다.

선택적 `vm_name`은 1–63자의 영문·숫자·하이픈이며 양끝은 영문/숫자다. 잘못된 값은 `422 INVALID_VM_NAME`, 생략 시 기존 자동 이름을 사용한다. 입력한 VMID·이름은 검토·승인 intent에 포함한다. 검토 및 최초 mutation 직전 Proxmox 중복 검증을 수행하며, 승인한 VMID를 다른 추천값으로 변경하지 않는다.
