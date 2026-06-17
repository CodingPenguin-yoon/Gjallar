# Gjallar VM Operations Architecture

Last reviewed against code: 2026-05-30

Current MVP product source of truth is [`docs/product/drs-advisor/`](../product/drs-advisor/README.md). If this document conflicts with that folder, `drs-advisor/` wins.

Gjallar is a human-facing Proxmox Operations & Risk Console. It presents live
read-only inventory, guided VM creation, DRS Advisor recommendation/check,
manual VM migration policy and local approval evidence, job history, and
risk summaries. It is not a CI/CD system, source deployment tool, GitLab
environment controller, or LLM assistant product.

Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.
DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.

Create VM profile/template/network target design is documented in
[`CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md).
That design is the target for the Create VM supporting capability, while this
document primarily describes current architecture and target gaps.

## Active System Shape

```text
React operator UI
  -> /api/v1 FastAPI router
    -> read-only Proxmox inventory adapter
    -> read-only network readiness and migration pre-check evidence
    -> Create VM draft/preflight/plan/approval helpers
    -> DRS identity/policy/final-precheck/approval/job helpers
    -> DB-backed Operations/Jobs and risk summaries
    -> gated Proxmox native clone/resize/config/post-check helpers
    -> gated existing-VM start helper
    -> narrow approval-gated DRS migration execution helper
```

The safe baseline is read-only. Any live Create VM side effect is behind
exact approval metadata and Proxmox mutation acknowledgement gates. Existing-VM start is separate from Create VM and is gated by explicit acknowledgement, idempotency, fresh inventory precheck, Proxmox task polling, and running post-check.

## Frontend

The active frontend app is rooted at `frontend/src/App.jsx` and uses
`frontend/src/services/apiV1.js` for `/api/v1` calls.

Active routes:

| Route | Component | Purpose |
|---|---|---|
| `/` | `Dashboard` in `App.jsx` | Overview cluster summary from inventory, jobs, and risks. Uses partial-load behavior so job/risk read failures do not blank the first screen. |
| `/instances` | `InstanceList` | VM Instances inventory, detail evidence, and Start action for stopped non-template VMs. |
| `/instances/drs-policies` | `DrsPoliciesScreen` | Dedicated DRS VM migration policy coverage and guarded manual policy review/update. |
| `/instances/networks` | `NetworkReadinessScreen` | Read-only Network Readiness / migration pre-check visualization. |
| `/instances/create` | `CreateInstanceWizard` | Guided VM create flow using draft, preflight, plan, approval, and Proxmox native preview/create gates. |
| `/drs` | `DrsAdvisorScreen` | DRS Advisor recommendations, identity/policy evidence, final pre-check, approval/job substrate, and reconciliation state; broad execution UI polish remains pending. |
| `/operations/jobs` | `TaskBoard` | Read-only job/run progress and artifact metadata. |
| `/operations/risks` | `OperationalRiskDashboard` | Read-only risk summaries derived from job records. |
| `/settings/account` | `AccountSettingsScreen` in `App.jsx` | Authenticated self password change. |
| `/settings/admin/users` | `AdminUsersScreen` with `AdminGuard` | Admin-only local user and session operations. |

Legacy frontend aliases `/infra`, `/networks`, `/create`, `/jobs`,
`/risks`, `/account`, and `/admin/users` render the same screens to preserve
deep links. They are not the canonical paths for new UI navigation.

Legacy frontend paths and components for `/api/provision`, app deployment,
destructive VM actions, and LLM chat are intentionally absent from active `src`.

## DRS Advisor Current Baseline And Gaps

Current `/drs` uses backend `/api/v1/drs/*` read models and local approval
packet/job intent creation plus backend execution,
post-check, and read-only reconciliation routes. Backend gates are
authoritative; live execute and corrective reconcile UI remain absent. Manual
policy routes are surfaced under `/instances/drs-policies`.

Implemented baseline:

- DB-backed VM identity/fingerprint observations and migration policy memory.
- Identity and policy blockers in recommendation output.
- Read-only final pre-check on
  `POST /api/v1/drs/recommendations/{recommendation_id}/check`.
- DB-backed operation lock lookup/acquisition/release for DRS migration.
- Local approval packet and `drs_migration` job substrate.
- Narrow approval-gated live migration execution route with dedicated DRS
  Proxmox migration client and UPID/task metadata.
- Verified post-check and conservative `needs_reconciliation` handling.
- Read-only Reconcile preview before any corrective mutation.
- `drs_migration` jobs and artifacts in Operations/Jobs.

Current gap:

- Goal Check must verify Goal 1-6 implementation quality before Goal 7 starts.
- Approved VMID `140` live DRS migration evidence has been recorded; broad DRS
  execute UI remains pending.
- Broad DRS execution UI polish remains pending.
- Corrective reconciliation mutation, background reconciliation automation, and
  automatic DRS remain deferred.
- 15-minute average/peak metrics and deeper read-only advisor task/HA/quorum
  collection remain future work.

## Backend

The backend entrypoint is `backend/app/main.py`. The active product API is
mounted by `backend/app/api/v1/router.py` under `/api/v1`.

Active backend modules:

| Module | Role |
|---|---|
| `app/api/v1/router.py` | API route composition, response envelopes, job progress recording, and gate orchestration. |
| `app/proxmox/inventory.py` | Live read-only Proxmox inventory with fake fallback and safe connection context redaction. This module must not gain mutation methods. |
| `app/proxmox/client.py` | Explicit native Proxmox mutation client for Create VM clone/resize/config/status and VM start calls. Reuses the inventory env but is imported only by gated mutation paths. |
| `app/proxmox/models.py` | Inventory dataclasses for nodes, VMs, templates, storage, and networks. |
| `app/manifests/*` | Built-in VM profile and manifest schema defaults. |
| `app/vm_create/*` | Create VM draft, preflight, plan, approval, manifest evidence, and native Proxmox runner helpers. |
| `app/vm_actions/*` | Existing-VM action helpers that remain separate from Create VM and read-only inventory. |
| `app/jobs/*` | DB-backed job status, artifacts, approval records, and risk source data. |
| `app/core/redaction.py` | Secret redaction for responses, artifacts, and persisted job details. |

## API Surface

Inventory and read-only screens:

```text
GET /api/v1/cluster/summary
GET /api/v1/nodes
GET /api/v1/vms
GET /api/v1/vms/{vmid}
GET /api/v1/templates
GET /api/v1/storage
GET /api/v1/networks
GET /api/v1/jobs
GET /api/v1/jobs/{job_id}
GET /api/v1/jobs/{job_id}/artifacts
GET /api/v1/risks
POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start
```

Create VM:

```text
GET  /api/v1/profiles
POST /api/v1/vm-create/drafts
POST /api/v1/vm-create/{draft_id}/preflight
POST /api/v1/vm-create/{draft_id}/plan
POST /api/v1/vm-create/{draft_id}/approve
POST /api/v1/vm-create/{draft_id}/proxmox-preview
POST /api/v1/vm-create/{draft_id}/proxmox-create
```

Networks has no API write path. Create VM execution writes DB-backed artifacts
and request/VM records after the relevant approval gates pass.
`terraform-plan` and `terraform-apply` have been removed from the active API; the active UI uses `proxmox-preview` and `proxmox-create`.

DRS Advisor API boundaries are documented in [`api/target-drs-api.md`](api/target-drs-api.md). Current DRS includes read/check routes, manual per-VM migration policy API/UI, local approval/job substrate, narrow operator-only execution, and read-only reconcile preview; live execute UI, corrective reconcile UI, richer policy rule/full metadata editing, corrective mutation, background automation, and automatic DRS remain deferred.

## Create VM Target Selection Model

The current Create VM implementation is a supporting capability. Its target
selection model is being updated as follows:

- Profiles become Gjallar DB-seeded creation presets, initially read-only in the
  UI. Initial enabled profiles are `general-vm`, `runtime-server`, and
  `development-vm`.
- Profiles define hardware defaults/min/max, template requirements, and access
  recommendations only. They do not define target node, storage, network,
  `network_id`, bridge, static IP, template VMID/name, power policy, or profile
  version.
- Template source of truth is Proxmox live inventory. There is no target
  Gjallar template catalog or registration window.
- The UI shows live Proxmox templates and disables templates that fail the
  selected profile's cloud-init or qemu guest-agent requirements. Backend
  preflight still red-blocks failing templates.
- Create VM target networking removes `network_id`/`server-net`. The operator
  selects target node, then an active live bridge on that node.
- Static mode requires `static_ip`, `prefix`, and `gateway`. DHCP is allowed
  with a warning and later guest-agent/inventory discovery.
- Gateway is explicit operator input. Create VM must not infer a `.1` gateway
  from the requested static IP.
- Create success follows the reviewed request power policy: `stopped` leaves the
  VM powered off, while `boot_and_verify` starts the VM and verifies
  guest-agent IP plus cloud-init completion. Existing-VM start remains a
  separate VM Instances row action with Operations/Jobs audit.

Current implementation note: profiles are DB-seeded read-only rows with no
profile management UI yet. The active path exposes the three initial enabled
profiles, records selected `profile_id` in plan/review evidence, enforces
template requirements and access SSH key gates, uses explicit `bridge_id` plus
`static_ip`/`prefix`/`gateway`, and does not echo incoming
`network_id`/`networkId`.

## Main Data Flows

### Overview / Dashboard

```text
Dashboard
  -> cluster/nodes/vms/storage/networks/jobs/risks
  -> buildDashboardModel()
  -> operator summary and node table
```

The dashboard uses partial-load behavior. If `/api/v1/jobs` or `/api/v1/risks` cannot read
job/risk data, available inventory still renders and the UI shows a yellow
partial-failure notice.

### Read-Only Inventory

```text
Frontend screen
  -> apiV1Client inventory call
    -> get_default_inventory_adapter()
      -> live Proxmox adapter when configured
      -> fake adapter fallback when live inventory is unavailable or disabled
```

Inventory calls must not mutate Proxmox. Tests guard against exposing mutating
adapter methods in the active inventory path.

### Jobs And Risks

```text
Create VM and VM start routes record job progress
  -> app.jobs.runs writes latest state to job_runs
  -> app.jobs.artifacts writes payloads/metadata to job_artifacts
  -> /operations/jobs reads summaries
  -> /operations/risks derives risk rows from stored job risks
```

If the job DB read is unavailable, list reads fail open with an empty list so
read-only screens remain available.

### Native Create VM

```text
CreateInstanceWizard
  -> createVmFlow.loadCreateVmReviewModel()
  -> draft -> preflight -> plan -> approve
  -> preview_vm_draft_proxmox_create() writes non-mutating native preview artifact
  -> create_vm_draft_proxmox_native()
     -> run_proxmox_create()
        -> clone full VM from template
        -> poll clone UPID
        -> inspect cloned config and resize boot disk if requested disk_gb is larger
        -> set reviewed config
        -> read status/current and config
        -> if boot_and_verify: start VM, wait for guest-agent IP, verify cloud-init
        -> write observed_after fingerprint artifact
        -> record vm_create_requests and vm_instances rows
```

Success requires Proxmox actual state, not planned state: requested disk resize must be unnecessary or completed, the VM must exist on the target node, and an `observed_after` artifact with fingerprint hash must exist. The `stopped` policy requires `status/current=stopped`; `boot_and_verify` requires `status/current=running`, guest-agent IP discovery, and cloud-init completion. Task failure, unknown cloned disk size, resize failure, VM missing, or failed power-policy verification marks the manifest `apply_failed` or `needs_reconciliation` and does not mark it `applied`.

### VM Instances VM Start

```text
InstanceList
  -> apiV1Client.startVm(node_id, vmid, acknowledgement/idempotency/context)
  -> start_vm_action()
     -> fresh inventory precheck for exact node/vmid stopped non-template VM
     -> ProxmoxMutationClient.start_vm()
     -> wait_for_task()
     -> get_vm_status()
     -> write vm_start_observed_after DB artifact
     -> record vm_start job stages
```

Success requires Proxmox task `exitstatus=OK` and observed-after `status=running`. Missing/moved/template/non-stopped inventory blocks before mutation. Duplicate idempotency keys return the existing job/result without issuing another Proxmox start.

### Network Readiness

```text
GET /api/v1/nodes
GET /api/v1/vms
GET /api/v1/networks
  -> frontend Network Readiness model
  -> NetworkReadinessScreen
```

Network readiness is read-only. It has no Proxmox network mutation, API write
path, YAML persistence, DB migration, or DRS execution authority.

For target Create VM, the Network readiness screen is not the source of truth for bridge
selection. Create VM uses live Proxmox bridge inventory for the selected target
node.

## Safety Boundaries

Current MVP exclusions:

- No legacy `/api/provision` active flow.
- No existing-VM stop, reset, delete, snapshot, rollback, or broad power controls. Start is the only current existing-VM action and is gated to stopped non-template VMs.
- No app deploy, arbitrary package bootstrap, DB migration, or raw shell flow.
- No GitLab/staging registry writes.
- No LLM/chat product route.
- No SSH/Ansible/app bootstrap smoke in the current native create slice.
- No profile-owned power policy.
- No Gjallar template catalog or template registration window in the target
  Create VM selection model.

The current Create VM power policy is explicit per request. Native Proxmox create
may clone/configure the VM after explicit acknowledgement. `stopped` leaves the
VM powered off; `boot_and_verify` starts the new VM and verifies guest-agent IP
plus cloud-init completion. Existing-VM start remains the separate Infra
Explorer action, and SSH/Ansible/app bootstrap smoke remains deferred.

## Runtime Configuration

Important environment variables:

| Variable | Role |
|---|---|
| `GJALLAR_INVENTORY_MODE` | Selects fake/live inventory behavior. Tests default to fake unless marked live. |
| `PROXMOX_API_URL` | Live Proxmox API base URL. |
| `PROXMOX_API_TOKEN_ID` | Live Proxmox token id. |
| `PROXMOX_API_TOKEN_SECRET` | Live Proxmox token secret. Must never be persisted or returned. |
| `PROXMOX_TLS_INSECURE` | Reused by live inventory and native mutation clients. |
| `PROXMOX_TASK_POLL_INTERVAL_SECONDS` / `GJALLAR_PROXMOX_TASK_POLL_INTERVAL_SECONDS` | Native Proxmox task polling interval for Create VM and VM start. |
| `PROXMOX_TASK_TIMEOUT_SECONDS` / `GJALLAR_PROXMOX_TASK_TIMEOUT_SECONDS` | Native Proxmox task timeout for Create VM and VM start. |
| `GJALLAR_DATABASE_URL` | SQLAlchemy/Alembic DB URL for profiles, jobs, artifacts, Create VM requests, and created VM records. |

## Verification

From repo root:

```bash
PYTHONPATH=backend python3 -m pytest -q backend/tests
node --test frontend/tests/*.mjs
```

From `frontend/`:

```bash
pnpm lint
pnpm build
```
