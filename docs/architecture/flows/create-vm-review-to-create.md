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
| 5 | Frontend creates draft. | `POST /api/v1/vm-create/drafts` builds draft with selected profile defaults/overrides and suggested VMID. | None from planner yet. | `vm_create`, status `in_progress`, stage `draft`. |
| 6 | Frontend runs preflight. | `POST /api/v1/vm-create/{draft_id}/preflight` checks profile, template, node, storage, bridge, IP, VMID/name, access, and read-only inventory scope. | None from planner yet. | `blocked` on red, otherwise `in_progress`, stage `preflight`, risks recorded. |
| 7 | Frontend builds plan. | `POST /api/v1/vm-create/{draft_id}/plan` builds plan from draft/preflight. | `preflight_report`, `plan`, `vm_instance_manifest`, `planned_git_diff`, `review_summary`. | `blocked` on red, otherwise `in_progress`, stage `plan`, artifacts and risks recorded. |
| 8 | UI renders review. | Frontend reads `review_confirm`, risk summary, artifact ids/checksum. | Existing artifacts displayed by metadata/path. | No new state. |
| 9 | Operator acknowledges yellow risks if needed. | Frontend stores local checkbox state. | None. | None. |
| 10 | Operator approves review. | `POST /approve` validates exact `plan_artifact_id`, `review_summary_checksum`, and yellow acknowledgement. | Approval evidence may be included in job details. | `in_progress` stage `approval` if valid; `blocked` if invalid. |
| 11 | Operator checks mutation acknowledgement. | UI requires final checkbox before enabling native create. | None. | None. |
| 12 | Operator clicks native create. | Frontend calls `POST /proxmox-create` with approval metadata and `proxmox_mutation_acknowledged=true`, then navigates to `/jobs?job=<job_id>`. | None immediately. | `running`, stage `create`, before Proxmox call. |
| 13 | Backend creates internal preview artifact. | `build_proxmox_create_preview()` records clone/config/post-check payload without mutation. | `proxmox_create_preview`. | Still `running`, stage `create`. |
| 14 | Backend runs native create. | Clone, poll UPID, inspect config, resize if needed, set config, run selected power-policy post-check. | `observed_after` on post-check path. | Updated after result. |
| 15 | UI reads Jobs/Runs. | `/jobs?job=<job_id>` polls selected live job. | Artifact metadata visible. | Operator sees step progress and artifacts. |

## Payload Boundary

The current frontend payload includes selected fields such as:

| Field | Current meaning |
|---|---|
| `operator_id` | Compatibility payload field. Current UI derives it from the authenticated session user; trusted actor evidence comes from the session, not this field. |
| `job_id` | UI-generated or operator-edited job id. |
| `profile_id` | One of current static-seed profiles. |
| `target_node_id` | Selected Proxmox node. |
| `storage_id` | Selected storage id. |
| `bridge_id` | Selected active live bridge on target node. |
| `static_ip`, `prefix`, `gateway` | Explicit static network fields. |
| `ip_mode` | `static` or `dhcp`. |
| `template_id`, `template_vmid`, `template_node_id` | Selected live template reference. |
| `hardware_overrides` | CPU, memory MB, disk GB. |
| `power_policy` | `stopped` by default, or `boot_and_verify` to start and verify the new VM. |

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
| `proxmox_mutation_acknowledged` | Explicit final acknowledgement for live Proxmox mutation. |

## Current Output Boundaries

| Endpoint | Current output boundary |
|---|---|
| `drafts` | Draft only, no live side effects. |
| `preflight` | Checks and risks only, no live side effects. |
| `plan` | Plan/review artifacts, no live side effects. |
| `approve` | Approval validation only, no manifest commit or Proxmox call. |
| `proxmox-preview` | Preview artifact only, no Proxmox call. |
| `proxmox-create` | Only current active VM creation path. |

## Success And Deferred Work

Success follows the selected power policy:

- `stopped`: Proxmox reports the new VM stopped after clone/config.
- `boot_and_verify`: Proxmox reports the new VM running, guest-agent IP is observed, and `cloud-init status --wait` succeeds.

The flow does not currently perform:

- SSH login
- Ansible verification
- app deployment
- DRS identity registration
