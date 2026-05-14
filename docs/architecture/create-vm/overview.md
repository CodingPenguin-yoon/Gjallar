# Create VM Architecture

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Create VM](../../current/top-tabs/04-create-vm.md).

Create VM is the `/create` route. It is a guided operator-reviewed workflow for producing a powered-off Proxmox VM from a live template. The active live mutation path is native Proxmox create, not Terraform.

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

The current frontend loads options from live/read-only APIs, builds a review model, validates approval, commits a manifest, then calls native Proxmox create after a final explicit acknowledgement.

## Current Backend Modules

| Module | Current role |
|---|---|
| `backend/app/api/v1/router.py` | Route orchestration, approval gates, job status recording, HTTP errors. |
| `backend/app/manifests/loader.py` | Transitional static profile seed for `general-vm`, `runtime-server`, `development-vm`. |
| `backend/app/vm_create/drafts.py` | Builds draft from request, selected profile defaults, selected target fields, and suggested VMID. |
| `backend/app/vm_create/preflight.py` | Read-only checks against profiles, templates, nodes, storage, bridges, IPs, IaC readiness. |
| `backend/app/vm_create/planner.py` | Writes preflight/plan/manifest/diff/review artifacts and returns review contract. |
| `backend/app/vm_create/approval.py` | Validates exact artifact/checksum approval metadata and yellow acknowledgement. |
| `backend/app/vm_create/gitops.py` | Writes/commits VMInstance manifest, verifies commit, updates manifest status, archives unapplied manifests. |
| `backend/app/vm_create/proxmox_runner.py` | Builds native preview and performs clone/resize/config/post-check. |
| `backend/app/proxmox/client.py` | Separate Proxmox mutation client for native create only. |
| `backend/app/jobs/*` | Job status and artifact persistence. |

## Current Profiles

Current Create VM profiles are exactly these transitional read-only `static_seed` records:

| Profile | Enabled | CPU default/min/max | Memory default/min/max MB | Disk default/min/max GB | Template requirements |
|---|---:|---|---|---|---|
| `general-vm` | true | 2 / 1 / 8 | 4096 / 1024 / 32768 | 50 / 50 / 500 | cloud-init and qemu guest agent required |
| `runtime-server` | true | 4 / 2 / 16 | 8192 / 4096 / 65536 | 100 / 80 / 1000 | cloud-init and qemu guest agent required |
| `development-vm` | true | 2 / 1 / 12 | 4096 / 2048 / 32768 | 50 / 50 / 500 | cloud-init and qemu guest agent required |

DB-seeded profiles remain future work. Do not describe DB seed as current.

## Current Selection Sources

| Selection | Current source of truth | Notes |
|---|---|---|
| Profile | Static seed from backend, with local frontend fallback. | Active profile list has three enabled choices. |
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
| Native preview | `previewCreateVmProxmox()` | `POST /proxmox-preview` | Writes preview artifact, no mutation. |
| Manifest commit | `commitCreateVmManifest()` | `POST /execute` | Commits VMInstance manifest only. |
| Native create | `createVmWithProxmox()` | `POST /proxmox-create` | Live Proxmox clone/resize/config/post-check after gates. |

The UI navigates to `/jobs?job=<job_id>` when native create starts so the operator can inspect job progress.

Access/SSH evidence is part of the current review model. The review displays
cloud-init username, password-login disabled, SSH key presence/source, and
fingerprint only. Request-supplied or backend-default raw public key material is
used transiently for Proxmox `sshkeys` config and is not persisted or returned.

## Current Approval And Mutation Gates

`proxmox-create` requires valid rebuilt plan approval metadata, exact plan artifact id, exact review checksum, yellow acknowledgement when needed, committed manifest verification, `proxmox_mutation_acknowledged=true`, and a fresh plan/preflight with no red risk.

Failure before live mutation returns a blocking HTTP error and does not call Proxmox.

## Current Success Criteria

Create VM success means the clone task completed with `exitstatus=OK`, requested disk resize was unnecessary or completed, config update completed, post-check read status/config from Proxmox, VM exists on the target node, observed power status is `stopped`, `observed_after` artifact exists, manifest status is updated to `applied`, and the job is recorded as `completed`.

Create VM success does not include first power-on, cloud-init smoke, guest-agent IP discovery, SSH, or Ansible verification. Those are deferred.

## Removed Terraform Boundary

Backend endpoints `terraform-plan` and `terraform-apply` have been removed. Old URLs are absent from FastAPI routes and naturally return 404. Terraform-named state metadata is also removed from active draft, preflight, plan, review, manifest, API, frontend, and artifact contracts.

## Current Gaps

| Gap | Current status |
|---|---|
| DB-seeded profiles | Future. Current profiles are `static_seed`. |
| Profile management UI | Future. Current profiles are read-only. |
| Access section with SSH public key collection | Implemented for current profiles with safe fingerprint evidence; first-login SSH smoke remains deferred. |
| First power-on | Deferred. |
| Guest-agent discovery and smoke | Deferred. |
| SSH/Ansible verification | Deferred. |
| Background reconciliation service | Future. Current route can mark `needs_reconciliation`, but no worker resolves it. |
| DRS reuse of Create VM fingerprint | Future. Current fingerprint is artifact evidence, not DB identity. |
