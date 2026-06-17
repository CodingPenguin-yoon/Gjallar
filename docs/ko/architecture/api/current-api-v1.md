# Current API V1

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Current API V1](../../../architecture/api/current-api-v1.md), [Current implemented state](../../../current/README.md), [VM provisioning contract](../../../architecture/VM_PROVISIONING_CONTRACT.md).

이 문서는 현재 `/api/v1` route가 무엇을 하는지, backend에서 어떻게 구현되는지, frontend의 어떤 함수가 호출하는지 설명합니다. Active route table은 [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py)와 [backend/app/main.py](../../../../backend/app/main.py)가 기준입니다.

## 응답 envelope와 client

성공 응답은 보통 다음 형태입니다.

```json
{
  "ok": true,
  "data": {},
  "meta": {}
}
```

Frontend client는 [frontend/src/services/apiV1.js](../../../../frontend/src/services/apiV1.js)의 `createApiV1Client()`입니다. 이 client는 `unwrapApiV1Envelope()`로 성공 envelope를 풀고, HTTP error에서는 FastAPI `detail` object와 error body를 모두 처리합니다.

## Auth/admin APIs

| Endpoint | Backend handler | 구현 방식 | Frontend client/caller | Side effect와 주의 |
|---|---|---|---|---|
| `POST /api/v1/auth/login` | auth router | Local user credential을 검증하고 server-side session을 생성합니다. | `login()`; `/login` | Public login endpoint. |
| `POST /api/v1/auth/logout` | auth router | Current session을 종료합니다. | `logout()` | Current session만 종료. |
| `GET /api/v1/auth/me` | auth router | Current session actor를 반환합니다. | `me()`; app bootstrap | Read-only. |
| `GET /api/v1/admin/users` | `admin_list_users()` | Local users list를 반환합니다. | `listAdminUsers()`; `/admin/users` | Admin-only. Password/session token material 반환 없음. |
| `POST /api/v1/admin/users` | `admin_create_user()` | Local user를 생성합니다. | `createAdminUser()` | Admin-only. Public signup 아님. |
| `PATCH /api/v1/admin/users/{username}/role` | `admin_set_user_role()` | Role을 변경합니다. | `setAdminUserRole()` | Admin-only. Last enabled admin demotion은 차단. Role change는 target sessions를 revoke하지 않음. |
| `POST /api/v1/admin/users/{username}/disable` | `admin_disable_user()` | User를 disable합니다. | `disableAdminUser()` | Admin-only. Target sessions를 revoke. Last enabled admin disable은 차단. |
| `POST /api/v1/admin/users/{username}/reset-password` | `admin_reset_password()` | Password를 reset합니다. | `resetAdminUserPassword()` | Admin-only. Target sessions를 revoke. Raw password/hash 반환 없음. |

## Root와 health

| Route | Backend 함수 | 하는 일 | Frontend 사용 |
|---|---|---|---|
| `GET /` | `root()` in [backend/app/main.py](../../../../backend/app/main.py) | 서비스 root metadata를 반환합니다. | Primary app data client가 쓰는 `/api/v1` 화면 API는 아닙니다. |
| `GET /health` | `health()` in [backend/app/main.py](../../../../backend/app/main.py) | health check 용도입니다. | 배포/운영 확인용입니다. |

## Inventory와 summary APIs

| Endpoint | Backend handler | 구현 방식 | Frontend client/caller | Side effect와 주의 |
|---|---|---|---|---|
| `GET /api/v1/cluster/summary` | `cluster_summary()` | `_inventory_adapter()`로 adapter를 만들고 cluster/node/vm/template count와 mode metadata를 반환합니다. | `apiV1Client.clusterSummary()`; Dashboard | Read-only. DRS 15분 average/peak나 execution gate가 아닙니다. |
| `GET /api/v1/nodes` | `list_nodes()` | inventory adapter의 node snapshot을 envelope로 반환합니다. | `listNodes()`; Dashboard, Infra Explorer, Create VM options, Networks readiness | Read-only. node load는 실행 gate가 아니라 evidence입니다. |
| `GET /api/v1/vms` | `list_vms()` | template 제외 VM inventory를 반환합니다. | `listVms()`; Dashboard, Infra Explorer, Networks readiness | Read-only. DRS identity/fingerprint는 `/api/v1/drs/*` evidence/gates에서 별도로 다룹니다. |
| `GET /api/v1/vms/{vmid}` | `get_vm(vmid)` | inventory adapter lookup by VMID. 없으면 404입니다. | `getVm(vmid)` helper | VMID는 identity가 아니라 locator입니다. |
| `GET /api/v1/templates` | `list_templates()` | Proxmox template inventory를 반환합니다. | `listTemplates()`; Create VM options | Current active template selection source입니다. Missing readiness evidence는 ready가 아닙니다. |
| `GET /api/v1/storage` | `list_storage()` | storage candidates를 inventory에서 반환합니다. | `listStorage()`; Dashboard, Create VM | Read-only. Create VM UI는 selected node, `images` content, free capacity로 필터링합니다. |
| `GET /api/v1/networks` | `list_networks()` | bridge inventory를 반환합니다. | `listNetworks()`; Dashboard, Create VM, Networks readiness | Read-only. Create VM은 selected target node의 active bridge를 사용합니다. Networks는 nodes/vms/networks를 frontend에서 조합해 selected-source target network comparison, CIDR-verified exact bridge match evidence, bridge-name-only review evidence, CIDR remap candidate evidence를 표시합니다. |

## Create VM option APIs

| Endpoint | Backend handler | 구현 방식 | Frontend client/caller | Side effect와 주의 |
|---|---|---|---|---|
| `GET /api/v1/profiles` | `list_profiles()` | `GJALLAR_DATABASE_URL`의 active DB-seeded profile rows를 반환합니다. | `listProfiles()`; `CreateInstanceWizard` | Read-only. Current profiles는 `general-vm`, `runtime-server`, `development-vm`입니다. Disabled/archived rows는 숨깁니다. |

## Network readiness boundary

Networks는 별도 backend readiness endpoint 없이 `GET /api/v1/nodes`, `/vms`, `/networks`를 frontend에서 조합합니다. 화면은 selected migration source 기준 target network comparison, CIDR-verified exact bridge match / CIDR remap evidence, selected-source VM impact를 표시합니다. Proxmox network mutation, API write path, YAML persistence, DB migration, DRS execution authority는 없습니다.

`NetworkInventory`는 기존 `bridge_id`, `node_id`, `type`, `active`에 더해 `address`, `netmask`, `prefix`, `cidr`, `gateway`, `bridge_ports`, `vlan_aware`, `mtu`를 optional observed bridge config evidence로 포함할 수 있습니다. Live adapter는 Proxmox `/nodes/{node}/network` row에서 가능한 값을 채웁니다. CIDR은 observed address와 netmask/prefix 또는 CIDR이 포함된 address에서만 계산하고, gateway만 있는 row에서 CIDR을 추론하지 않습니다. CIDR/gateway match는 observed config evidence일 뿐 actual same L2/VLAN/routed network나 migration feasibility의 proof가 아닙니다.

## Jobs와 risks APIs

| Endpoint | Backend handler | 구현 방식 | Frontend client/caller | Side effect와 주의 |
|---|---|---|---|---|
| `GET /api/v1/jobs` | `list_jobs()` | `job_runs`를 latest-state summary로 읽습니다. | `listJobs()`; Dashboard, Jobs/Runs | Read-only. DB read 실패 시 fail-open `[]`입니다. |
| `GET /api/v1/jobs/{job_id}` | `get_job(job_id)` | `_job_entry_or_404()`로 DB job status를 읽습니다. | `getJob()`; `loadJobsScreenModel()` | Read-only. 없으면 404입니다. |
| `GET /api/v1/jobs/{job_id}/artifacts` | `list_job_artifacts(job_id)` | `job_artifacts` metadata list를 반환합니다. | `listJobArtifacts()`; `loadJobsScreenModel()` | File content와 로컬 path를 stream/expose하지 않습니다. |
| `GET /api/v1/risks` | `list_risks()` | DB job status의 `risks` 배열을 펼쳐 risk rows로 반환합니다. | `listRisks()`; Dashboard, Risks/Alerts | Current risks는 job-derived projection입니다. Standalone DRS blocker engine이 아닙니다. |

## DRS Advisor APIs

| Endpoint | Backend handler | 구현 방식 | Frontend client/caller | Side effect와 주의 |
|---|---|---|---|---|
| `GET /api/v1/drs/summary` | `get_drs_summary()` | `app.drs.advisor`가 current inventory, job-derived risks, identity/policy/lock evidence로 summary/recommendation model을 만듭니다. | `getDrsSummary()`; `loadDrsAdvisorModel()` | Proxmox-read-only. Local identity observation evidence를 저장할 수 있습니다. |
| `GET /api/v1/drs/recommendations` | `list_drs_recommendations()` | Running non-template VM 중 red-risk VM을 제외하고 current CPU/Memory threshold와 blocker evidence를 계산합니다. | `listDrsRecommendations()`; `loadDrsAdvisorModel()` | 모든 recommendation은 `executable=false`, `allowed_actions=[]`입니다. |
| `GET /api/v1/drs/recommendations/{recommendation_id}` | `get_drs_recommendation()` | 같은 model을 재계산해 id를 찾습니다. 없으면 404입니다. | `getDrsRecommendation()`; `loadDrsRecommendationDetail()` | Proxmox-read-only. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/check` | `check_drs_recommendation()` | Reference final-check 결과와 `would_be_executable`를 반환합니다. | `checkDrsRecommendation()` | Execution authorization이 아니며 `executable=false` 유지. |
| `GET /api/v1/drs/policies` | `list_drs_policies()` | Current VM identity/policy coverage와 blocker impact를 반환합니다. | `drsPolicies()`; InstanceList policy row | Read-only. |
| `GET /api/v1/drs/policies/{vm_identity_id}` | `get_drs_policy()` | One VM policy item을 반환합니다. | `drsPolicy()`; InstanceList policy review | Read-only. |
| `PUT /api/v1/drs/policies/{vm_identity_id}` | `put_drs_policy()` | Manual local VM migration policy를 update하고 audit evidence를 기록합니다. | `updateDrsPolicy()`; InstanceList review modal | Operator-only. Proxmox mutation 없음. `expected_observation`, `policy_change_acknowledged=true`, trusted actor audit를 사용합니다. Policy `allowed`는 migration approval이 아님. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets` | `create_drs_approval_packet()` | Exact recommendation/final-check evidence를 local approval/job/artifact로 저장합니다. | `createDrsApprovalPacket()`; `/drs` detail panel | Operator-only. Proxmox mutation 없음, migration 시작 안 함. |
| `POST /api/v1/drs/migration-jobs/{job_id}/execute` | `execute_drs_migration_job_route()` | Exact `drs_live_migration_acknowledged=true` payload gate 뒤 stored approval/job binding, fresh gates, live Proxmox evidence, operation locks를 확인하고 dedicated DRS migration client를 호출합니다. Ack 실패는 `409` / `DRS_EXECUTION_ACK_REQUIRED` request validation이며 service/client/lock/migration work 전에 `proxmox_mutation_enabled=false`, `side_effects=[]`로 차단하고 pending job을 `blocked`로 바꾸지 않습니다. | Frontend live execute UI/helper 없음 | Operator-only narrow execution. Broad UI는 아직 없음. Approved VMID `140` live DRS smoke evidence는 기록됐고, future live mutation은 별도 run-specific approval이 필요합니다. |
| `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview` | `preview_drs_migration_reconciliation_route()` | Stored job/UPID를 읽고 task/post-check evidence를 read-only로 다시 봅니다. | `reconcilePreviewDrsMigrationJob()` helper; broad UI 없음 | Operator-only read-only preview. Corrective mutation 없음. |

## VM action API

| Endpoint | Backend handler와 주요 함수 | Frontend caller | 현재 의미 |
|---|---|---|---|
| `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start` | `start_vm_action()` -> `run_vm_start()` -> fresh inventory precheck -> `ProxmoxMutationClient.start_vm()` -> task poll/post-check | `startVm()`; `InstanceList` | Stopped non-template VM만 start합니다. `vm_start_acknowledged=true`, non-empty `idempotency_key`, expected name/status context, observed-after `running`, `vm_start` job/artifact evidence가 필요합니다. Stop/reset/delete 같은 destructive action은 없습니다. |
| `POST /api/v1/nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence` | `post_create_readiness_evidence_route()` -> `record_post_create_readiness_evidence()` | `recordPostCreateReadinessEvidence()` | Already-created VM에 대해 local-only operator-supplied readiness evidence를 기록합니다. Inventory, Proxmox, DRS, SSH, Ansible, guest-agent, shell, network checks를 호출하지 않습니다. |

## Create VM mutation-adjacent APIs

아래 API는 Create VM job/artifact/manifests를 쓰거나, 마지막 단계에서 Proxmox를 mutate할 수 있습니다. 모든 handler는 [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py)에 있습니다.

| Endpoint | Backend handler와 주요 함수 | Frontend caller | 현재 의미 |
|---|---|---|---|
| `POST /api/v1/vm-create/drafts` | `create_vm_draft()` -> `_api_draft_from_payload()` -> `build_default_vm_draft()` -> `resolve_ssh_public_key()`, `adapter.suggest_next_vmid()`, `record_job_run()` | `createVmDraft()` via `loadCreateVmReviewModel()` | Request payload를 정규화하고 server-side draft를 만듭니다. Draft job status를 기록하지만 Proxmox mutation은 없습니다. |
| `POST /api/v1/vm-create/{draft_id}/preflight` | `preflight_vm_draft()` -> `_api_draft_from_payload()` -> `run_preflight()` -> inventory adapter | `preflightVmDraft()` | Profile/template/node/storage/bridge/IP/access checks를 실행합니다. Red risk는 approval/create를 막습니다. |
| `POST /api/v1/vm-create/{draft_id}/plan` | `plan_vm_draft()` -> `build_vm_create_plan()` | `planVmDraft()` | `preflight_report`, `plan`, `vm_instance_manifest`, `planned_git_diff`, `review_summary` artifacts를 씁니다. Live Proxmox mutation 없음. |
| `POST /api/v1/vm-create/{draft_id}/approve` | `approve_vm_draft()` -> `validate_approval_request()` | `approveVmDraft()` via `approveCreateVmReview()` | Exact `plan_artifact_id`, `review_summary_checksum`, yellow acknowledgement를 검증합니다. Approval validation only입니다. |
| `POST /api/v1/vm-create/{draft_id}/proxmox-preview` | `preview_vm_draft_proxmox_create()` -> `validate_approval_request()` -> `build_proxmox_create_preview()` -> `clone_payload_from_plan()`, `config_payload_from_plan()` | `previewVmDraftProxmox()` via `previewCreateVmProxmox()` | Approval-gated non-mutating native create preview입니다. Preview artifact를 씁니다. |
| `POST /api/v1/vm-create/{draft_id}/proxmox-create` | `create_vm_draft_proxmox_native()` -> approval gate -> red risk gate -> internal preview -> `run_proxmox_create()` | `createVmDraftProxmox()` via `createVmWithProxmox()` | 현재 active live Proxmox VM creation path입니다. `proxmox_mutation_acknowledged=true`가 필요합니다. |

## Frontend API client coverage

[frontend/src/services/apiV1.js](../../../../frontend/src/services/apiV1.js)는 auth/admin users, inventory, VM start, post-create readiness evidence, network readiness, jobs, risks, DRS Advisor recommendation/check, DRS policy read/update, DRS local approval packet creation, DRS reconcile-preview helper, Create VM draft/preflight/plan/approve, native preview, native create를 expose합니다. DRS live execute helper/UI는 아직 없습니다. Legacy GitOps execute/archive helper와 route는 active API에서 제거됐습니다.

## 현재 없는 DRS API/UI

Recommendation-level approve/migrate/live-migrate alias route, richer policy rule/full metadata editor, corrective reconciliation mutation, background automation, automatic DRS, live execute UI, corrective reconcile UI는 없습니다. Current boundary와 future 후보는 [target-drs-api.md](target-drs-api.md)에 정리되어 있습니다.
