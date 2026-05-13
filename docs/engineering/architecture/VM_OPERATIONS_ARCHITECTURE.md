# Gjallar VM Operations Architecture

Last reviewed against code: 2026-05-11

Current MVP product source of truth is [`docs/product/prd/drs-advisor/`](../../product/prd/drs-advisor/README.md). If this document conflicts with that folder, `drs-advisor/` wins.

Gjallar is a human-facing Proxmox Operations & Risk Console. It presents live
read-only inventory, guided VM creation, placement evidence, job history, and
risk summaries. It is not a CI/CD system, source deployment tool, GitLab
environment controller, or LLM assistant product.

Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.
DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.

## Active System Shape

```text
React operator UI
  -> /api/v1 FastAPI router
    -> read-only Proxmox inventory adapter
    -> IaC-backed network policy helpers
    -> Create VM draft/preflight/plan/approval helpers
    -> file-backed Jobs/Runs and risk summaries
    -> gated Terraform workspace/plan/apply helpers
```

The safe baseline is read-only. Any live Create VM side effect is behind
explicit approval and Terraform acknowledgement gates.

## Frontend

The active frontend app is rooted at `frontend/src/App.jsx` and uses
`frontend/src/services/apiV1.js` for `/api/v1` calls.

Active routes:

| Route | Component | Purpose |
|---|---|---|
| `/` | `Dashboard` in `App.jsx` | Cluster summary from inventory, jobs, and risks. Uses partial-load behavior so NFS-backed job history failures do not blank the first screen. |
| `/infra` | `InstanceList` | Read-only grouped VM inventory and detail evidence. |
| `/networks` | `NetworkPolicyScreen` | Bridge inventory plus IaC network policy view and guarded policy write. |
| `/create` | `CreateInstanceWizard` | Guided VM create flow using draft, preflight, plan, approval, and Terraform gates. |
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
| `app/proxmox/inventory.py` | Live read-only Proxmox inventory with fake fallback and safe connection context redaction. |
| `app/proxmox/models.py` | Inventory dataclasses for nodes, VMs, templates, storage, and networks. |
| `app/manifests/*` | Built-in VM profile and manifest schema defaults. |
| `app/network_policy.py` | IaC-backed network policy load/save and bridge-policy view composition. |
| `app/vm_create/*` | Create VM draft, preflight, plan, approval, manifest, GitOps, IaC readiness, and Terraform runner helpers. |
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
POST /api/v1/vm-create/{draft_id}/terraform-plan
POST /api/v1/vm-create/{draft_id}/terraform-apply
POST /api/v1/vm-create/{draft_id}/execute
POST /api/v1/vm-create/{draft_id}/archive
```

`PUT /api/v1/networks/policy` is the only current policy write path. Create VM
execution writes artifacts/manifests only after the relevant approval gates pass.

Target DRS Advisor API candidates are documented in [`../../product/prd/drs-advisor/05_IMPLEMENTATION_PLAN.md`](../../product/prd/drs-advisor/05_IMPLEMENTATION_PLAN.md) and [`../../product/prd/12_UI_API_CONTRACT.md`](../../product/prd/12_UI_API_CONTRACT.md). They are not current implementation.

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

### Network Policy

```text
Proxmox bridge inventory
  + IaC network-profiles.yaml
  -> NetworkPolicyScreen
```

Policy writes are scoped to the configured IaC root and are guarded against path
escape. Secret values are not returned by API responses.

## Safety Boundaries

Current MVP exclusions:

- No legacy `/api/provision` active flow.
- No independent existing-VM power, stop, reset, delete, snapshot, or rollback controls.
- No app deploy, arbitrary package bootstrap, DB migration, or raw shell flow.
- No GitLab/staging registry writes.
- No LLM/chat product route.
- No first-power-on or post-creation smoke in the current Terraform apply slice.

The current Create VM policy is powered-off only. Terraform may clone/configure
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
