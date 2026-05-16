# Current API V1

Status source: [current product status](../../current/README.md). Top-tab status index: [top tabs](../../current/top-tabs/README.md).

This document describes the current `/api/v1` route surface implemented in `backend/app/api/v1/router.py` and consumed by `frontend/src/services/apiV1.js`.

## Response Envelope

Successful current `/api/v1` responses use:

```json
{
  "ok": true,
  "data": {},
  "meta": {}
}
```

`meta` is optional. Inventory responses usually include source/mode metadata such as `source=fake_read_only` or `source=live_read_only`.

Current error responses are not fully normalized. Many failures raise FastAPI `HTTPException` with a `detail` object. The frontend client handles both successful envelopes and HTTP error detail objects.

## Write/Read Boundaries

| Boundary | Current rule |
|---|---|
| Inventory | Read-only only. `app.proxmox.inventory` must not mutate Proxmox. |
| Network policy | May write IaC network policy file; does not mutate Proxmox network config. |
| Jobs/artifacts | Create VM and VM start steps write job status and artifacts to `job_runs` and `job_artifacts` through `GJALLAR_DATABASE_URL`. |
| Native create | `proxmox-create` is the active live mutation path for Create VM. Default requests finish stopped; `boot_and_verify` starts the new VM and verifies guest-agent IP plus cloud-init completion. |
| Existing VM start | `POST /nodes/{node_id}/vms/{vmid}/actions/start` is the only existing-VM power action. It requires acknowledgement, idempotency, fresh inventory precheck, task polling, running post-check, and job/artifact evidence. |
| Terraform | Legacy plan/apply route surface, helper code, and Terraform-named state metadata are removed from active contracts. |
| DRS | No current `/api/v1/drs/*` routes or migration execution. |

## Endpoint Table

| Endpoint | Purpose | Data source | Side effects | Frontend use | Notes |
|---|---|---|---|---|---|
| `GET /api/v1/cluster/summary` | Cluster counts and high-level mode. | Inventory adapter snapshot. | None. | Dashboard, Placement. | Returns `cluster_id=gjallar-mvp`, node/vm/template counts, `risk_level=unknown`. |
| `GET /api/v1/nodes` | Read-only node inventory. | Inventory adapter. | None. | Dashboard, Infra Explorer, Create VM options, Placement. | Node rows include status, CPU/memory usage, storage, networks. |
| `GET /api/v1/vms` | Read-only VM inventory. | Inventory adapter. | None. | Dashboard, Infra Explorer, Placement. | Excludes templates; includes disks, tags, IP evidence, guest-agent evidence when available. |
| `GET /api/v1/vms/{vmid}` | Read-only single VM detail. | Inventory adapter lookup by VMID. | None. | API client helper; no primary current tab call observed. | 404 when VMID is not found. |
| `GET /api/v1/profiles` | Create VM profile options. | Active DB-seeded profiles through `GJALLAR_DATABASE_URL`. | None. | Create VM. | Initial seed profiles: `general-vm`, `runtime-server`, `development-vm`; disabled/archived rows are hidden. |
| `GET /api/v1/vm-create/readiness` | IaC readiness for Create VM. | `run_iac_readiness()`. | None. | Create VM review model. | Checks shared root, IaC root, write allowlist, and Git repo. |
| `GET /api/v1/templates` | Read-only Proxmox template inventory. | Inventory adapter. | None. | Create VM options. | Active template selection source. Missing cloud-init/guest-agent evidence is not ready. |
| `GET /api/v1/storage` | Read-only storage candidates. | Inventory adapter. | None. | Dashboard, Create VM options, Placement. | Create VM filters by selected node, `images` content, and free capacity. |
| `GET /api/v1/networks` | Read-only bridge inventory. | Inventory adapter. | None. | Dashboard, Create VM options, Placement. | Create VM uses active bridges on selected target node. |
| `GET /api/v1/networks/policy` | Live bridge inventory combined with IaC network policy state. | Inventory adapter plus `manifests/networks/network-profiles.yaml`. | None. | Networks tab. | Shows registered/unregistered bridges and missing policy bridges. Not the Create VM source of truth. |
| `PUT /api/v1/networks/policy` | Save normalized network policy. | Request payload, IaC root. | Writes policy file and may create local IaC Git commit. | Networks tab. | Path is constrained under IaC root. No Proxmox bridge mutation. |
| `GET /api/v1/jobs` | Read-only job summaries. | `job_runs` table. | None. | Dashboard, Placement, Jobs/Runs. | Listing fails open to `[]` if DB read fails. |
| `GET /api/v1/jobs/{job_id}` | Read-only one job summary. | `job_runs` table. | None. | Jobs/Runs selected detail. | 404 when absent. |
| `GET /api/v1/jobs/{job_id}/artifacts` | Read-only artifact metadata for one job. | `job_artifacts` table. | None. | Jobs/Runs selected detail. | Returns metadata, not artifact contents or local file paths. |
| `GET /api/v1/risks` | Risk summaries derived from jobs. | `risks` arrays in job records. | None. | Dashboard, Placement, Risks/Alerts. | Current risks are job-derived, not a standalone risk engine. |
| `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start` | Start a stopped non-template VM. | Fresh inventory adapter precheck plus Proxmox mutation client. | Calls `POST /nodes/{node}/qemu/{vmid}/status/start`, polls task, reads status/current, writes `vm_start` job/artifact evidence. | Infra Explorer. | Requires `vm_start_acknowledged=true` and non-empty `idempotency_key`; blocks missing/moved/template/non-stopped VMs. Duplicate idempotency returns the existing job/result without another Proxmox start. |
| `POST /api/v1/vm-create/drafts` | Build a non-mutating Create VM draft. | Request payload, DB-backed active profiles, inventory VMID suggestion. | Records draft job status. | Create VM review model. | Incoming `network_id`/`networkId` is ignored. Accepts nested `access` with `cloud_init_user`/`ssh_public_key` aliases; raw public key is not returned. |
| `POST /api/v1/vm-create/{draft_id}/preflight` | Run non-destructive checks. | Draft and read-only inventory. | Records preflight job status and risks. | Create VM review model. | Red risk blocks approval/create; yellow can require acknowledgement. Access checks red-block missing/malformed required SSH public key and password login true. IaC readiness may be reported separately but is not a primary native-create blocker. |
| `POST /api/v1/vm-create/{draft_id}/plan` | Build artifact-backed dry-run plan. | Draft plus preflight. | Writes preflight, plan, VMInstance manifest, planned diff, review summary artifacts; records job status. | Create VM review model. | No live Proxmox mutation. Plan/review artifacts include access fingerprint/source, selected template evidence, and selected bridge evidence. |
| `POST /api/v1/vm-create/{draft_id}/approve` | Validate review approval metadata. | Rebuilt plan artifacts and approval payload. | Writes or refreshes `approval.json`; records approval job status. | Create VM approval step. | Requires exact `plan_artifact_id`, `review_summary_checksum`, and yellow acknowledgement when needed. |
| `POST /api/v1/vm-create/{draft_id}/proxmox-preview` | Build native create preview. | Approved rebuilt plan. | Revalidates approval and may refresh `approval.json`; writes preview artifact; records job status. | API/helper only; no primary current UI button. | Approval-gated but non-mutating. Preview config redacts `sshkeys`. |
| `POST /api/v1/vm-create/{draft_id}/proxmox-create` | Active live native Proxmox VM creation. | Approved rebuilt plan and Proxmox mutation client. | Revalidates approval and may refresh `approval.json`; writes an internal preview artifact; calls Proxmox clone/task/config/resize/power-policy post-check; writes job/artifacts. | Create VM final mutation button. | Requires valid approval, no red fresh risk, and `proxmox_mutation_acknowledged=true`. It does not require `manifest_commit_sha`. Native config uses reviewed username and transient SSH public key; API/artifacts return only redacted/safe evidence. `boot_and_verify` starts the new VM and verifies guest-agent IP plus cloud-init completion. |
## Current Frontend Client Coverage

The frontend client does not expose Terraform plan/apply or legacy GitOps execute/archive helpers, and the backend routes no longer exist. The active UI covers inventory, the explicit VM start action, network policy, jobs, risks, readiness, draft/preflight/plan/approve, native preview, and native create.
