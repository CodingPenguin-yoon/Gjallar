# API 계약: 현재 `/api/v1` 기준선

- 상태: `APPROVED`
- 최종 검토일: `2026-07-20`
- 소비자: `frontend/src/services/apiV1.js`, React SPA, 승인된 외부 consumer
- 관련 요구사항·ADR: [`Project Specification`](../specifications/project-specification.md), [`ADR-001`](../decisions/adr-001-proxmox-gjallar-authority-boundary.md), [`ADR-003`](../decisions/adr-003-production-inventory-connection-truth.md)

이 문서는 active route의 보존용 기준선이다. 세부 payload와 error code는 코드와 contract test가 우선한다. 공통 Operation 조회와 첫 Guided Manual mutation은 additive public contract로 추가됐고 기존 endpoint는 유지된다.

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
- authoritative snapshot 성공: `live`, `source=live_read_only`, `freshness=fresh`.
- 설정됐지만 TLS·timeout·network·authentication·API read 실패: `degraded`와 redacted reason code.
- `cluster/summary`, nodes, VMs, templates, storage, networks와 inventory-dependent Create/DRS path는 non-live에서 `503`을 반환한다.
- `503 detail.code`는 `PROXMOX_INVENTORY_UNCONFIGURED` 또는 `PROXMOX_INVENTORY_DEGRADED`이며 mutation을 호출하지 않는다.
- inventory endpoint meta에는 기존 `source`, `mode`와 함께 `observed_at`, `freshness`, nested `connection`을 additive field로 제공한다.
- `profiles`, Jobs, Risks, auth/account/admin은 Proxmox inventory가 non-live여도 자체 책임 범위에서 계속 사용할 수 있다.

### Jobs·artifacts·risks

| Method | Path | 권한 | 현재 책임 |
|---|---|---|---|
| `GET` | `/api/v1/jobs` | viewer | latest job projection 목록 |
| `GET` | `/api/v1/jobs/{job_id}` | viewer | job 상세 |
| `GET` | `/api/v1/jobs/{job_id}/artifacts` | viewer | artifact metadata 목록 |
| `GET` | `/api/v1/risks` | viewer | job record에서 파생한 risk 목록 |

`job_runs`/`job_artifacts`는 목표 append-only operation/evidence 계약이 아니다. DB error를 empty list로 숨기는 현재 경로는 보존할 제품 behavior가 아니라 수정 대상이다.

### VM action

| Method | Path | 권한 | side effect | 현재 gate |
|---|---|---|---|---|
| `POST` | `/api/v1/nodes/{node_id}/vms/{vmid}/actions/start` | operator | Proxmox VM start | acknowledgement, idempotency key, fresh pre-check, lock, task poll, post-check |
| `POST` | `/api/v1/nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence` | operator | local evidence only | sanitized payload, live check/command/secret field 거부 |

VM Start는 구현된 `managed_api` Operations vertical slice다. 현재 구현은 같은 node/VMID/idempotency key와 같은 intent를 기존 결과로 replay하고, 그 operation identity에서 expected context가 다른 intent는 `409` conflict로 거부한다. 현재 한 개의 configured Proxmox cluster를 전제로 `vmid` 단위 target file lock을 잡으며, POST timeout·missing UPID·task unknown·post-check mismatch는 mutation을 재호출하지 않고 `needs_reconciliation`과 retained lock으로 보존한다.

VM Start는 기존 job/artifact 계약과 함께 공통 `operations` projection과 `operation_events`를 기록한다. 기존 response envelope과 job payload는 바꾸지 않는다.

### Operations·Guided `qm`

| Method | Path | 권한 | side effect | 현재 책임 |
|---|---|---|---|---|
| `POST` | `/api/v1/operations/guided-qm/vm-unlock` | operator | 없음; instruction 발급만 | fixed `qm unlock` plan, pre-check, target lock, 5분 bundle |
| `GET` | `/api/v1/operations/{operation_id}` | viewer | 없음 | current projection, checksum-linked event timeline 조회 |
| `POST` | `/api/v1/operations/{operation_id}/operator-attestation` | operator | local state only | 외부 command 실행 사실의 trusted actor attestation |
| `POST` | `/api/v1/operations/{operation_id}/verification` | operator | Proxmox read only | config lock·active task after-state 검증 |

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

이 다단계 endpoint는 standardized Create VM operation으로 통합하되 전환 동안 호환 facade로 유지한다. final create는 같은 job/intent의 완료 결과를 mutation 없이 replay하고, 같은 job의 다른 intent와 같은 VMID를 소유한 다른 active/reconciliation/completed request를 `409`로 차단한다. VM Start와 같은 VMID target file lock을 사용하며, 명확한 side-effect-free 거절만 `failed`로 종료·해제하고 partial/unknown result는 `apply_failed` 또는 `needs_reconciliation`과 retained lock으로 남긴다.

### DRS

| Method | Path | 권한 | side effect | 현재 책임 |
|---|---|---|---|---|
| `GET` | `/api/v1/drs/summary` | viewer | 없음 | advisor summary |
| `GET` | `/api/v1/drs/recommendations` | viewer | 없음 | recommendation 목록 |
| `GET` | `/api/v1/drs/recommendations/{recommendation_id}` | viewer | 없음 | recommendation 상세 |
| `POST` | `/api/v1/drs/recommendations/{recommendation_id}/check` | viewer | 없음 | execution-closed check |
| `POST` | `/api/v1/drs/explicit-test-candidates/check` | viewer | 없음 | explicit candidate check |
| `GET` | `/api/v1/drs/policies` | viewer | 없음 | policy 목록 |
| `GET` | `/api/v1/drs/policies/{vm_identity_id}` | viewer | 없음 | policy 상세 |
| `PUT` | `/api/v1/drs/policies/{vm_identity_id}` | operator | local DB | ack와 observation guard를 포함한 policy 변경 |
| `POST` | `/api/v1/drs/recommendations/{recommendation_id}/approval-packets` | operator | local DB | approval packet와 job intent 생성 |
| `POST` | `/api/v1/drs/explicit-test-candidates/approval-packets` | operator | local DB | explicit candidate packet/job 생성 |
| `POST` | `/api/v1/drs/migration-jobs/{job_id}/execute` | operator | Proxmox migration | exact binding, final pre-check, lock, task/post-check |
| `POST` | `/api/v1/drs/migration-jobs/{job_id}/reconcile` | operator | local/Proxmox read | ack 후 reconciliation |
| `POST` | `/api/v1/drs/migration-jobs/{job_id}/reconcile-preview` | operator | 없음 | read-only reconciliation preview |

DRS recommendation은 향후 Insights로 이동한다. 기존 live execution/history의 유지·폐기는 별도 승인 전 변경하지 않는다. migration execute는 Proxmox POST 전에 DB에 `running`과 `dispatch_attempt.state=prepared`, active operation lock을 저장하고, UPID를 받으면 `accepted` evidence로 전환한다. prepared 이후 UPID 저장이 확인되지 않는 crash window에서 execute 재진입은 second mutation 없이 `needs_reconciliation`으로 전환한다. 해당 no-UPID reconcile은 direct read-only post-check만 허용하며 UPID 없이 자동 완료하거나 lock을 해제하지 않는다.

## 공통 mutation 계약 기준선

- actor는 server-side session에서 얻고 request payload actor를 신뢰하지 않는다.
- action별 exact acknowledgement field와 `operator+` role을 요구한다.
- Create VM, VM Start, Guided `qm unlock`은 현재 한 configured cluster의 VMID를 `proxmox_vm/vmid:{vmid}`로 표현하는 동일한 single-container file lock namespace를 사용한다.
- DRS는 별도 DB `operation_locks`를 사용하므로 Create/Start와 공통 lock 또는 공통 operation resource를 아직 공유하지 않는다.
- 네 mutation slice는 서로 다른 idempotency/approval/error contract를 일부 유지하지만, covered ambiguity를 terminal failure로 축소하거나 자동 재호출하지 않는다.
- VM Start와 Guided `qm`은 공통 operation resource/event를 기록한다. Create VM과 DRS는 아직 자체 projection/evidence를 유지한다.
- secret, token, password와 unsafe evidence field를 저장·응답하지 않아야 한다.

## 호환성 정책

- additive endpoint와 optional response field를 우선한다.
- 기존 endpoint를 application use case facade로 바꾸더라도 status, response/error shape, actor, acknowledgement, job/artifact 의미를 characterization test로 먼저 고정한다.
- frontend canonical route와 legacy alias는 별도 폐기 결정 전 유지한다.
- operation API가 확장되고 모든 internal consumer가 전환된 뒤에만 기존 workflow endpoint deprecation을 제안한다.

## 구현과 검증

- 진입점: `backend/app/auth/api.py`, `backend/app/auth/admin_api.py`, `backend/app/api/v1/router.py`.
- success helper: `backend/app/api/v1/responses.py`.
- frontend consumer: `frontend/src/services/apiV1.js`.
- contract test: `backend/tests/contracts/`, frontend `apiV1Client`, auth, navigation과 feature tests.
- 2026-07-20 현재 Python 3.13 container backend 전체 suite는 `425 passed`다. Node 24/pnpm 10 production build의 기존 기준선은 frontend test 15개, lint, build와 최종 image build 통과다. 이번 additive backend API slice에서는 frontend를 변경하거나 재실행하지 않았다.
