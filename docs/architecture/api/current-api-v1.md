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
| Jobs/artifacts | Many Create VM steps write job status and artifacts under `GJALLAR_RUNS_ROOT`, including `approval.json` whenever approval validation runs with a run directory. |
| Manifest commit | `execute` commits desired-state manifest only. It does not create a VM. |
| Native create | `proxmox-create` is the active live mutation path for powered-off VM creation. |
| Terraform | Legacy plan/apply route surface, helper code, and Terraform-named state metadata are removed from active contracts. |
| DRS | No current `/api/v1/drs/*` routes or migration execution. |

## Endpoint Table

| Endpoint | Purpose | Data source | Side effects | Frontend use | Notes |
|---|---|---|---|---|---|
| `GET /api/v1/cluster/summary` | Cluster counts and high-level mode. | Inventory adapter snapshot. | None. | Dashboard, Placement. | Returns `cluster_id=gjallar-mvp`, node/vm/template counts, `risk_level=unknown`. |
| `GET /api/v1/nodes` | Read-only node inventory. | Inventory adapter. | None. | Dashboard, Infra Explorer, Create VM options, Placement. | Node rows include status, CPU/memory usage, storage, networks. |
| `GET /api/v1/vms` | Read-only VM inventory. | Inventory adapter. | None. | Dashboard, Infra Explorer, Placement. | Excludes templates; includes disks, tags, IP evidence, guest-agent evidence when available. |
| `GET /api/v1/vms/{vmid}` | Read-only single VM detail. | Inventory adapter lookup by VMID. | None. | API client helper; no primary current tab call observed. | 404 when VMID is not found. |
| `GET /api/v1/profiles` | Create VM profile options. | Transitional `static_seed` profiles. | None. | Create VM. | Current active profiles: `general-vm`, `runtime-server`, `development-vm`; all enabled/read-only. |
| `GET /api/v1/vm-create/readiness` | IaC readiness for Create VM. | `run_iac_readiness()`. | None. | Create VM review model. | Checks shared root, IaC root, write allowlist, and Git repo. |
| `GET /api/v1/templates` | Read-only Proxmox template inventory. | Inventory adapter. | None. | Create VM options. | Active template selection source. Missing cloud-init/guest-agent evidence is not ready. |
| `GET /api/v1/storage` | Read-only storage candidates. | Inventory adapter. | None. | Dashboard, Create VM options, Placement. | Create VM filters by selected node, `images` content, and free capacity. |
| `GET /api/v1/networks` | Read-only bridge inventory. | Inventory adapter. | None. | Dashboard, Create VM options, Placement. | Create VM uses active bridges on selected target node. |
| `GET /api/v1/networks/policy` | Live bridge inventory combined with IaC network policy state. | Inventory adapter plus `manifests/networks/network-profiles.yaml`. | None. | Networks tab. | Shows registered/unregistered bridges and missing policy bridges. Not the Create VM source of truth. |
| `PUT /api/v1/networks/policy` | Save normalized network policy. | Request payload, IaC root. | Writes policy file and may create local IaC Git commit. | Networks tab. | Path is constrained under IaC root. No Proxmox bridge mutation. |
| `GET /api/v1/jobs` | Read-only job summaries. | `GJALLAR_RUNS_ROOT/*/job_status.json`. | None. | Dashboard, Placement, Jobs/Runs. | Listing fails open to `[]` if runs root glob fails. |
| `GET /api/v1/jobs/{job_id}` | Read-only one job summary. | Job status file. | None. | Jobs/Runs selected detail. | 404 when absent. |
| `GET /api/v1/jobs/{job_id}/artifacts` | Read-only artifact metadata for one job. | Job status file artifact list. | None. | Jobs/Runs selected detail. | Returns metadata, not artifact file contents. |
| `GET /api/v1/risks` | Risk summaries derived from jobs. | `risks` arrays in job status files. | None. | Dashboard, Placement, Risks/Alerts. | Current risks are job-derived, not a standalone risk engine. |
| `POST /api/v1/vm-create/drafts` | Build a non-mutating Create VM draft. | Request payload, static profiles, inventory VMID suggestion. | Records draft job status. | Create VM review model. | Incoming `network_id`/`networkId` is ignored. Accepts nested `access` with `cloud_init_user`/`ssh_public_key` aliases; raw public key is not returned. |
| `POST /api/v1/vm-create/{draft_id}/preflight` | Run non-destructive checks. | Draft, read-only inventory, IaC readiness. | Records preflight job status and risks. | Create VM review model. | Red risk blocks approval/create; yellow can require acknowledgement. Access checks red-block missing/malformed required SSH public key and password login true. |
| `POST /api/v1/vm-create/{draft_id}/plan` | Build artifact-backed dry-run plan. | Draft plus preflight. | Writes preflight, plan, VMInstance manifest, planned diff, review summary artifacts; records job status. | Create VM review model. | No live Proxmox mutation. Plan/review artifacts include access fingerprint/source, selected template evidence, and selected bridge evidence. |
| `POST /api/v1/vm-create/{draft_id}/approve` | Validate review approval metadata. | Rebuilt plan artifacts and approval payload. | Writes or refreshes `approval.json`; records approval job status. | Create VM approval step. | Requires exact `plan_artifact_id`, `review_summary_checksum`, and yellow acknowledgement when needed. |
| `POST /api/v1/vm-create/{draft_id}/proxmox-preview` | Build native create preview. | Approved rebuilt plan. | Revalidates approval and may refresh `approval.json`; writes preview artifact; records job status. | Create VM final confirmation. | Approval-gated but non-mutating. Preview config redacts `sshkeys`. |
| `POST /api/v1/vm-create/{draft_id}/proxmox-create` | Active live native Proxmox VM creation. | Approved rebuilt plan, committed manifest, Proxmox mutation client. | Revalidates approval and may refresh `approval.json`; calls Proxmox clone/task/config/resize/post-check; updates manifest status; writes job/artifacts. | Create VM final mutation button. | Requires `manifest_commit_sha`, valid approval, no red fresh risk, and `proxmox_mutation_acknowledged=true`. Native config uses reviewed username and transient SSH public key; API/artifacts return only redacted/safe evidence. |
| `POST /api/v1/vm-create/{draft_id}/execute` | Commit approved VMInstance manifest. | Approved rebuilt plan and IaC root. | Revalidates approval and may refresh `approval.json`; writes and commits manifest if needed; records pending job status. | Create VM "save request" step. | Mode is `gitops_commit_only`. It does not create a VM or call Proxmox. |
| `POST /api/v1/vm-create/{draft_id}/archive` | Archive an unapplied VMInstance manifest. | Rebuilt plan and IaC root. | Moves manifest to `manifests/archive/vms/` and commits. | No primary current frontend call in `apiV1.js`. | Requires `archive_acknowledged=true`; refuses applied manifests. |

## Current Frontend Client Coverage

The frontend client does not expose Terraform plan/apply helpers, and the backend routes no longer exist. The active client covers inventory, network policy, jobs, risks, readiness, draft/preflight/plan/approve, native preview, manifest commit, and native create.
