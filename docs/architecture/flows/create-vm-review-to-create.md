# Flow: Create VM Review To Native Create

Status source: [current product status](../../current/README.md). Relevant top-tab statuses: [Create VM](../../current/top-tabs/04-create-vm.md), [Jobs/Runs](../../current/top-tabs/06-jobs-runs.md).

This is the current implemented frontend/API/backend flow from options load through native `proxmox-create`.

## Actors And Modules

| Layer | Current module |
|---|---|
| UI | `frontend/src/components/CreateInstanceWizard.jsx` |
| Frontend flow helpers | `frontend/src/utils/createVmFlow.js` |
| Frontend defaults | `frontend/src/utils/createVmDefaults.js` |
| API client | `frontend/src/services/apiV1.js` |
| Backend router | `backend/app/api/v1/router.py` |
| Backend Create VM | `backend/app/vm_create/*` |
| Proxmox mutation | `backend/app/proxmox/client.py`, `backend/app/vm_create/proxmox_runner.py` |
| Jobs/artifacts | `backend/app/jobs/*` |

## Step-By-Step Flow

| Step | Frontend action | API/backend action | Artifacts | Job state |
|---:|---|---|---|---|
| 1 | Component mounts and loads options. | Calls nodes, templates, storage, networks, profiles in parallel. | None. | None. |
| 2 | UI normalizes options and picks defaults. | Frontend filters storage/bridge by selected node and templates by selected profile requirements. | None. | None. |
| 3 | Operator edits profile, hardware, node, template, storage, bridge, IP mode, static fields. | No backend call until review. | None. | None. |
| 4 | Operator clicks review. | `loadCreateVmReviewModel()` builds payload. | None yet. | None yet. |
| 5 | Frontend gets readiness. | `GET /api/v1/vm-create/readiness` runs read-only IaC readiness. | None. | None. |
| 6 | Frontend creates draft. | `POST /api/v1/vm-create/drafts` builds draft with selected profile defaults/overrides and suggested VMID. | None from planner yet. | `vm_create`, status `in_progress`, stage `draft`. |
| 7 | Frontend runs preflight. | `POST /api/v1/vm-create/{draft_id}/preflight` checks profile, template, node, storage, bridge, IP, VMID/name, IaC readiness, read-only inventory scope. | None from planner yet. | `blocked` on red, otherwise `in_progress`, stage `preflight`, risks recorded. |
| 8 | Frontend builds plan. | `POST /api/v1/vm-create/{draft_id}/plan` builds plan from draft/preflight. | `preflight_report`, `plan`, `vm_instance_manifest`, `planned_git_diff`, `review_summary`. | `blocked` on red, otherwise `in_progress`, stage `plan`, artifacts and risks recorded. |
| 9 | UI renders review. | Frontend reads `review_confirm`, risk summary, readiness, artifact ids/checksum. | Existing artifacts displayed by metadata/path. | No new state. |
| 10 | Operator acknowledges yellow risks if needed. | Frontend stores local checkbox state. | None. | None. |
| 11 | Operator approves review. | `POST /approve` validates exact `plan_artifact_id`, `review_summary_checksum`, and yellow acknowledgement. | Approval evidence may be included in job details. | `in_progress` stage `approval` if valid; `blocked` if invalid. |
| 12 | Operator requests final native preview. | `POST /proxmox-preview` revalidates approval and builds non-mutating Proxmox preview. | `proxmox_create_preview`. | `in_progress`, stage `workspace`, preview details recorded. |
| 13 | Operator saves request. | `POST /execute` validates approval, writes/commits VMInstance manifest. | Manifest was already planned; commit result recorded in job details. | `pending`, stage `commit`. |
| 14 | Operator checks mutation acknowledgement. | UI requires final checkbox before enabling native create. | None. | None. |
| 15 | Operator clicks native create. | Frontend calls `POST /proxmox-create` with approval metadata, `manifest_commit_sha`, and `proxmox_mutation_acknowledged=true`, then navigates to `/jobs?job=<job_id>`. | None immediately. | `running`, stage `create`, before Proxmox call. |
| 16 | Backend verifies manifest commit. | `verify_plan_manifest_commit()` checks commit and manifest path. | None. | Blocks at `commit` if invalid. |
| 17 | Backend marks applying. | `update_plan_manifest_status(plan, "applying")`. | IaC manifest status commit. | Still `running`, stage `create`. |
| 18 | Backend runs native create. | Clone, poll UPID, inspect config, resize if needed, set config, post-check status/config. | `observed_after` on post-check path. | Updated after result. |
| 19 | Backend marks terminal manifest state. | `applied`, `apply_failed`, or `needs_reconciliation`. | IaC status commit. | `completed` on success, `failed` on failure/uncertain. |
| 20 | UI reads Jobs/Runs. | `/jobs?job=<job_id>` polls selected live job. | Artifact metadata visible. | Operator sees step progress and artifacts. |

## Payload Boundary

The current frontend payload includes selected fields such as:

| Field | Current meaning |
|---|---|
| `operator_id` | Operator identifier, default `ui-operator`. |
| `job_id` | UI-generated or operator-edited job id. |
| `profile_id` | One of current static-seed profiles. |
| `target_node_id` | Selected Proxmox node. |
| `storage_id` | Selected storage id. |
| `bridge_id` | Selected active live bridge on target node. |
| `static_ip`, `prefix`, `gateway` | Explicit static network fields. |
| `ip_mode` | `static` or `dhcp`. |
| `template_id`, `template_vmid`, `template_node_id` | Selected live template reference. |
| `hardware_overrides` | CPU, memory MB, disk GB. |

Current Create VM does not use incoming `network_id`/`networkId` as source of truth.

## Approval Packet

The approval and subsequent preview/commit/create calls reuse:

| Field | Purpose |
|---|---|
| `plan_artifact_id` | Proves operator is approving the current plan artifact. |
| `review_summary_checksum` | Proves the review summary matches current artifact contents. |
| `yellow_risk_acknowledged` | Confirms operator reviewed non-red risks when required. |

`proxmox-create` additionally requires:

| Field | Purpose |
|---|---|
| `manifest_commit_sha` | Proves desired-state manifest was committed before live mutation. |
| `proxmox_mutation_acknowledged` | Explicit final acknowledgement for live Proxmox mutation. |

## Current Output Boundaries

| Endpoint | Current output boundary |
|---|---|
| `drafts` | Draft only, no live side effects. |
| `preflight` | Checks and risks only, no live side effects. |
| `plan` | Plan/review artifacts, no live side effects. |
| `approve` | Approval validation only, no manifest commit or Proxmox call. |
| `proxmox-preview` | Preview artifact only, no Proxmox call. |
| `execute` | Manifest commit only, no VM creation. |
| `proxmox-create` | Only current active VM creation path. |

## Success And Deferred Work

Success is powered-off/stopped only. The flow does not currently perform:

- first power-on
- cloud-init completion check
- guest-agent IP discovery after first boot
- SSH login
- Ansible verification
- app deployment
- DRS identity registration
