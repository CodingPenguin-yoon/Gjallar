# Create VM Architecture

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Create VM](../../current/top-tabs/04-create-vm.md).

Create VM is the `/create` route. It is a guided operator-reviewed workflow for producing a Proxmox VM from a live template. The default request leaves the VM powered off; the optional `boot_and_verify` request starts the VM and verifies first-boot readiness. The active live mutation path is native Proxmox create, not Terraform.

Supporting references: [`../api/current-api-v1.md`](../api/current-api-v1.md), [`../flows/create-vm-review-to-create.md`](../flows/create-vm-review-to-create.md), [`../VM_PROVISIONING_CONTRACT.md`](../VM_PROVISIONING_CONTRACT.md), [`../CREATE_VM_NATIVE_ARCHITECTURE.md`](../CREATE_VM_NATIVE_ARCHITECTURE.md), and [`../CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md).

## Current Frontend Modules

| Concern | Current implementation |
|---|---|
| Route | `/create` |
| Component | `frontend/src/components/CreateInstanceWizard.jsx` |
| Defaults | `frontend/src/utils/createVmDefaults.js` |
| Flow helpers | `frontend/src/utils/createVmFlow.js` |
| API client | `frontend/src/services/apiV1.js` |
| Active live mutation button | `Proxmox native create` |

The current frontend loads options from live/read-only APIs, builds a review model, validates approval, then calls native Proxmox create after a final explicit acknowledgement. The former separate manifest commit/save-request button is not part of the primary UI flow.

## Current Backend Modules

| Module | Current role |
|---|---|
| `backend/app/api/v1/router.py` | Route orchestration, approval gates, job status recording, HTTP errors. |
| `backend/app/db/*` | SQLAlchemy/Alembic DB boundary plus manual Create VM profile seed/repository. |
| `backend/app/manifests/loader.py` | Initial seed-definition data for `general-vm`, `runtime-server`, `development-vm`. |
| `backend/app/vm_create/drafts.py` | Builds draft from request, selected profile defaults, selected target fields, and suggested VMID. |
| `backend/app/vm_create/preflight.py` | Read-only checks against profiles, templates, nodes, storage, bridges, and IPs. |
| `backend/app/vm_create/planner.py` | Writes preflight/plan/manifest/diff/review artifacts and returns review contract. |
| `backend/app/vm_create/approval.py` | Validates exact artifact/checksum approval metadata and yellow acknowledgement. |
| `backend/app/vm_create/proxmox_runner.py` | Builds native preview and performs clone/resize/config/post-check. |
| `backend/app/proxmox/client.py` | Separate Proxmox mutation client for native create only. |
| `backend/app/jobs/*` | Job status and artifact persistence. |

## Current Profiles

Current Create VM profiles are DB-seeded read-only records. The initial active seed is:

| Profile | Enabled | CPU default/min/max | Memory default/min/max MB | Disk default/min/max GB | Template requirements |
|---|---:|---|---|---|---|
| `general-vm` | true | 2 / 1 / 8 | 4096 / 1024 / 32768 | 50 / 50 / 500 | cloud-init and qemu guest agent required |
| `runtime-server` | true | 4 / 2 / 16 | 8192 / 4096 / 65536 | 100 / 80 / 1000 | cloud-init and qemu guest agent required |
| `development-vm` | true | 2 / 1 / 12 | 4096 / 2048 / 32768 | 50 / 50 / 500 | cloud-init and qemu guest agent required |

Disabled or archived profile rows are excluded from Create VM selection.

## Current Selection Sources

| Selection | Current source of truth | Notes |
|---|---|---|
| Profile | Active DB profile rows from backend. | Initial seed has three enabled choices. Local frontend defaults are display fallback only and do not allow review when the profile API fails or returns empty. |
| VMID | Inventory adapter suggestion. | UI does not supply VMID in normal flow. |
| Target node | `GET /api/v1/nodes`. | UI defaults once options load. |
| Template | `GET /api/v1/templates`. | Live/fake Proxmox inventory; failing templates are visible but disabled. |
| Storage | `GET /api/v1/storage`. | Filtered by target node, `images` content, and free capacity. |
| Bridge | `GET /api/v1/networks`. | Filtered to active bridges on selected target node. |
| Access | Wizard input plus backend default SSH public key env/file fallback. | Password login fixed disabled; raw public key is transient only. |
| Static networking | Operator input. | Static mode requires explicit `static_ip`, `prefix`, and `gateway`; no gateway inference. |
| Network policy | Networks tab IaC policy only. | Not Create VM source of truth. |

## Current Flow

| Step | Frontend helper | Backend endpoint | Current effect |
|---|---|---|---|
| Options load | Component `useEffect` | nodes/templates/storage/networks/profiles | Read-only options. |
| Review start | `loadCreateVmReviewModel()` | draft -> preflight -> plan | Writes job/artifacts, no live Proxmox mutation. |
| Approval | `approveCreateVmReview()` | `POST /approve` | Validates plan artifact/checksum and yellow acknowledgement. |
| Native preview | `previewCreateVmProxmox()` | `POST /proxmox-preview` | Optional helper that writes preview artifact, no mutation. Not a primary UI button. |
| Native create | `createVmWithProxmox()` | `POST /proxmox-create` | Builds internal preview artifact, then live Proxmox clone/resize/config/power-policy post-check after gates. |

The UI navigates to `/jobs?job=<job_id>` when native create starts so the operator can inspect job progress.

Access/SSH evidence is part of the current review model. The review displays
cloud-init username, password-login disabled, SSH key presence/source, and
fingerprint only. Request-supplied or backend-default raw public key material is
used transiently for Proxmox `sshkeys` config and is not persisted or returned.

## Current Approval And Mutation Gates

`proxmox-create` requires valid rebuilt plan approval metadata, exact plan artifact id, exact review checksum, yellow acknowledgement when needed, `proxmox_mutation_acknowledged=true`, and a fresh plan/preflight with no red risk. It no longer requires committed manifest verification.

Failure before live mutation returns a blocking HTTP error and does not call Proxmox.

## Current Success Criteria

Create VM success means the clone task completed with `exitstatus=OK`, requested disk resize was unnecessary or completed, config update completed, post-check read status/config from Proxmox, VM exists on the target node, `observed_after` artifact exists, and the selected power-policy checks passed. For `stopped`, Proxmox must report the VM stopped. For `boot_and_verify`, Proxmox must report the VM running and guest-agent IP discovery plus `cloud-init status --wait` must complete.

Create VM `boot_and_verify` covers first power-on, guest-agent IP discovery, and cloud-init completion. SSH login, Ansible verification, app bootstrap, and DRS identity registration remain deferred.

## Removed Terraform Boundary

Backend endpoints `terraform-plan` and `terraform-apply` have been removed. Old URLs are absent from FastAPI routes and naturally return 404. Terraform-named state metadata is also removed from active draft, preflight, plan, review, manifest, API, frontend, and artifact contracts.

## Removed GitOps Execute/Archive Boundary

Backend endpoints `execute` and `archive` have been removed from the active Create VM API. Old URLs are absent from FastAPI routes and naturally return 404. The primary create path stores review/preview/observed evidence in the DB-backed job/artifact tables and records native request/VM rows after Proxmox create.

## Current Gaps

| Gap | Current status |
|---|---|
| Profile management UI | Future. Current DB-seeded profiles are read-only in the UI. |
| Access section with SSH public key collection | Implemented for current profiles with safe fingerprint evidence; first-login SSH smoke remains deferred. |
| First power-on | Implemented only when the request uses `boot_and_verify`. Default `stopped` creation does not start the VM. |
| Guest-agent discovery and cloud-init smoke | Implemented only for `boot_and_verify`; SSH/Ansible smoke remains deferred. |
| SSH/Ansible verification | Deferred. |
| Background reconciliation service | Future. Current route can mark `needs_reconciliation`, but no worker resolves it. |
| DRS reuse of Create VM fingerprint | Future. Current fingerprint is artifact evidence, not DB identity. |
