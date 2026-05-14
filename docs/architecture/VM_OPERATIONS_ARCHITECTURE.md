# Gjallar VM Operations Architecture

Last reviewed against code: 2026-05-13

Current MVP product source of truth is [`docs/product/drs-advisor/`](../product/drs-advisor/README.md). If this document conflicts with that folder, `drs-advisor/` wins.

Gjallar is a human-facing Proxmox Operations & Risk Console. It presents live
read-only inventory, guided VM creation, placement evidence, job history, and
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
    -> IaC-backed network policy helpers
    -> Create VM draft/preflight/plan/approval helpers
    -> file-backed Jobs/Runs and risk summaries
    -> gated Proxmox native clone/resize/config/post-check helpers
```

The safe baseline is read-only. Any live Create VM side effect is behind
exact approval metadata, manifest commit verification, and Proxmox mutation acknowledgement gates.

## Frontend

The active frontend app is rooted at `frontend/src/App.jsx` and uses
`frontend/src/services/apiV1.js` for `/api/v1` calls.

Active routes:

| Route | Component | Purpose |
|---|---|---|
| `/` | `Dashboard` in `App.jsx` | Cluster summary from inventory, jobs, and risks. Uses partial-load behavior so NFS-backed job history failures do not blank the first screen. |
| `/infra` | `InstanceList` | Read-only grouped VM inventory and detail evidence. |
| `/networks` | `NetworkPolicyScreen` | Bridge inventory plus IaC network policy view and guarded policy write. |
| `/create` | `CreateInstanceWizard` | Guided VM create flow using draft, preflight, plan, approval, manifest commit, Proxmox native preview/create gates. |
| `/placement` | `PlacementScreen` | Read-only placement recommendations from inventory, storage, bridge, job, and risk evidence. |
| `/jobs` | `TaskBoard` | Read-only job/run progress and artifact metadata. |
| `/risks` | `OperationalRiskDashboard` | Read-only risk summaries derived from job records. |

Legacy frontend paths and components for `/api/provision`, app deployment,
destructive VM actions, and LLM chat are intentionally absent from active `src`.

## DRS Advisor Target Gap

Current `/placement` is a read-only Placement screen. It uses frontend view-model logic over existing `/api/v1` inventory/job/risk data and does not authorize or execute migration.

Target direction:

- Keep the `/placement` route if useful, but relabel the product flow as DRS Advisor.
- Add backend-owned `/api/v1/drs/*` recommendation read model.
- Add VM identity/fingerprint/metadata/policy state before any migration execution.
- Add DRS final pre-check that rereads current Proxmox state immediately before execution.
- Add approval-gated Proxmox live migration, UPID tracking, post-check, operation locks, and reconciliation.
- Show `drs_migration` jobs in Jobs/Runs and DRS blockers/warnings in Risks/Alerts.

Current gap:

- No `/api/v1/drs/*` routes.
- No DB-backed DRS identity/fingerprint/policy/lock/reconciliation tables.
- No Proxmox migration mutation client in the active DRS path.
- No UPID tracking or Reconcile Now flow.

## Backend

The backend entrypoint is `backend/app/main.py`. The active product API is
mounted by `backend/app/api/v1/router.py` under `/api/v1`.

Active backend modules:

| Module | Role |
|---|---|
| `app/api/v1/router.py` | API route composition, response envelopes, job progress recording, and gate orchestration. |
| `app/proxmox/inventory.py` | Live read-only Proxmox inventory with fake fallback and safe connection context redaction. This module must not gain mutation methods. |
| `app/proxmox/client.py` | Explicit native Proxmox mutation client for Create VM clone/resize/config/status calls. Reuses the inventory env but is imported only by gated mutation paths. |
| `app/proxmox/models.py` | Inventory dataclasses for nodes, VMs, templates, storage, and networks. |
| `app/manifests/*` | Built-in VM profile and manifest schema defaults. |
| `app/network_policy.py` | IaC-backed network policy load/save and bridge-policy view composition. |
| `app/vm_create/*` | Create VM draft, preflight, plan, approval, manifest, GitOps, IaC readiness, and native Proxmox runner helpers. |
| `app/jobs/*` | File-backed job status, artifacts, approval records, and risk source data. |
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
GET /api/v1/networks/policy
GET /api/v1/jobs
GET /api/v1/jobs/{job_id}
GET /api/v1/jobs/{job_id}/artifacts
GET /api/v1/risks
```

Create VM:

```text
GET  /api/v1/profiles
GET  /api/v1/vm-create/readiness
POST /api/v1/vm-create/drafts
POST /api/v1/vm-create/{draft_id}/preflight
POST /api/v1/vm-create/{draft_id}/plan
POST /api/v1/vm-create/{draft_id}/approve
POST /api/v1/vm-create/{draft_id}/proxmox-preview
POST /api/v1/vm-create/{draft_id}/proxmox-create
POST /api/v1/vm-create/{draft_id}/execute
POST /api/v1/vm-create/{draft_id}/archive
```

`PUT /api/v1/networks/policy` is the current policy write path. Create VM
execution writes artifacts/manifests only after the relevant approval gates pass.
`terraform-plan` and `terraform-apply` have been removed from the active API; the active UI uses `proxmox-preview` and `proxmox-create`.

Target DRS Advisor API candidates are documented in [`../product/drs-advisor/05_IMPLEMENTATION_PLAN.md`](../product/drs-advisor/05_IMPLEMENTATION_PLAN.md) and [`../product/legacy-prd/12_UI_API_CONTRACT.md`](../product/legacy-prd/12_UI_API_CONTRACT.md). They are not current implementation.

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
- Create success remains stopped/powered off by global create policy. VM start
  is future Infra Explorer row action work with Jobs/Runs audit.

Current implementation gap: profiles are transitional read-only `static_seed`
data rather than DB seed rows, and template requirement disabled-state/access
SSH key gates are still future slices. The active path now exposes the three
initial enabled profiles, records selected `profile_id` in plan/review evidence,
uses explicit `bridge_id` plus `static_ip`/`prefix`/`gateway`, and does not echo
incoming `network_id`/`networkId`.

## Main Data Flows

### Dashboard

```text
Dashboard
  -> cluster/nodes/vms/storage/networks/jobs/risks
  -> buildDashboardModel()
  -> operator summary and node table
```

The dashboard uses partial-load behavior. If `/jobs` or `/risks` cannot read an
NFS-backed `GJALLAR_RUNS_ROOT`, available inventory still renders and the UI
shows a yellow partial-failure notice.

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
Create VM route records job progress
  -> app.jobs.runs writes job_status.json under GJALLAR_RUNS_ROOT
  -> /jobs reads summaries
  -> /risks derives risk rows from stored job risks
```

If the runs root is unavailable, list reads fail open with an empty list so
read-only screens remain available.

### Native Create VM

```text
CreateInstanceWizard
  -> createVmFlow.loadCreateVmReviewModel()
  -> draft -> preflight -> plan -> approve
  -> execute_vm_draft() commits VMInstance manifest only
  -> preview_vm_draft_proxmox_create() writes non-mutating native preview artifact
  -> create_vm_draft_proxmox_native()
     -> run_proxmox_create()
        -> clone full VM from template
        -> poll clone UPID
        -> inspect cloned config and resize boot disk if requested disk_gb is larger
        -> set powered-off config
        -> read status/current and config
        -> write observed_after fingerprint artifact
```

Success requires Proxmox actual state, not planned state: requested disk resize must be unnecessary or completed, the VM must exist on the target node, `status/current` must report `stopped`, and an `observed_after` artifact with fingerprint hash must exist. Task failure, unknown cloned disk size, resize failure, VM missing, or powered-on observation marks the manifest `apply_failed` or `needs_reconciliation` and does not mark it `applied`.

### Network Policy

```text
Proxmox bridge inventory
  + IaC network-profiles.yaml
  -> NetworkPolicyScreen
```

Policy writes are scoped to the configured IaC root and are guarded against path
escape. Secret values are not returned by API responses.

For target Create VM, this Network tab policy is not the source of truth for
bridge selection. Create VM should use live Proxmox bridge inventory for the
selected target node. Network policy/subnet/gateway/range integration may be
added later as recommendations or validation evidence.

## Safety Boundaries

Current MVP exclusions:

- No legacy `/api/provision` active flow.
- No independent existing-VM power, stop, reset, delete, snapshot, or rollback controls.
- No app deploy, arbitrary package bootstrap, DB migration, or raw shell flow.
- No GitLab/staging registry writes.
- No LLM/chat product route.
- No first-power-on or post-creation smoke in the current native create slice.
- No profile-owned power policy.
- No Gjallar template catalog or template registration window in the target
  Create VM selection model.

The current Create VM policy is powered-off only. Native Proxmox create may clone/configure
the VM after explicit acknowledgement, but first power-on and Stage A smoke are
separate deferred stages.

## Runtime Configuration

Important environment variables:

| Variable | Role |
|---|---|
| `GJALLAR_INVENTORY_MODE` | Selects fake/live inventory behavior. Tests default to fake unless marked live. |
| `PROXMOX_API_URL` | Live Proxmox API base URL. |
| `PROXMOX_API_TOKEN_ID` | Live Proxmox token id. |
| `PROXMOX_API_TOKEN_SECRET` | Live Proxmox token secret. Must never be persisted or returned. |
| `PROXMOX_TLS_INSECURE` | Reused by live inventory and native mutation clients. |
| `PROXMOX_TASK_POLL_INTERVAL_SECONDS` / `GJALLAR_PROXMOX_TASK_POLL_INTERVAL_SECONDS` | Native Create VM clone task polling interval. |
| `PROXMOX_TASK_TIMEOUT_SECONDS` / `GJALLAR_PROXMOX_TASK_TIMEOUT_SECONDS` | Native Create VM clone task timeout. |
| `GJALLAR_SHARED_ROOT` | Shared root for IaC and state defaults. |
| `GJALLAR_IAC_ROOT` | Explicit IaC repo root override. |
| `GJALLAR_TF_STATE_ROOT` / `GJALLAR_TERRAFORM_STATE_ROOT` | Terraform state root override. |
| `GJALLAR_RUNS_ROOT` | File-backed Jobs/Runs status root. |

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
