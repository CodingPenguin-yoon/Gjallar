# Current API V1

Status source: [current product status](../../current/README.md). Top-tab status index: [top tabs](../../current/top-tabs/README.md).

This document describes the current `/api/v1` route surface implemented in
`backend/app/api/v1/router.py` plus auth/admin routers under `backend/app/auth/`,
and consumed by `frontend/src/services/apiV1.js`.

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
| Network readiness | Read-only frontend-composed selected-source migration pre-check evidence. No API write path, YAML persistence, DB migration, Proxmox network mutation, or DRS execution authority. |
| Jobs/artifacts | Create VM and VM start steps write job status and artifacts to `job_runs` and `job_artifacts` through `GJALLAR_DATABASE_URL`. |
| Auth/admin | Login/session endpoints are public as documented below. Local user management is admin-only and returns safe summaries only. |
| Native create | `proxmox-create` is the active live mutation path for Create VM. Default requests finish stopped; `boot_and_verify` starts the new VM and verifies guest-agent IP plus cloud-init completion. |
| Existing VM start | `POST /nodes/{node_id}/vms/{vmid}/actions/start` is the only existing-VM power action. It requires acknowledgement, idempotency, fresh inventory precheck, task polling, running post-check, and job/artifact evidence. |
| Terraform | Legacy plan/apply route surface, helper code, and Terraform-named state metadata are removed from active contracts. |
| DRS | `/api/v1/drs/summary`, recommendations, detail, and `/check` are read-only Phase 1. No migration execution. |

## Endpoint Table

| Endpoint | Purpose | Data source | Side effects | Frontend use | Notes |
|---|---|---|---|---|---|
| `POST /api/v1/auth/login` | Create a browser session. | Local `users` table. | Writes a server-side session and sets an opaque `HttpOnly` cookie. | Login route. | Failed login returns `401`. No public signup exists. |
| `POST /api/v1/auth/logout` | Revoke the current browser session. | Local `sessions` table. | Revokes the session and clears the cookie. | Shell logout. | Safe to call when no session is present. |
| `GET /api/v1/auth/me` | Return session status. | Local `sessions` and `users` tables. | Clears stale cookies when needed. | App bootstrap and self-role refresh. | Anonymous callers receive `authenticated=false`. |
| `GET /api/v1/admin/users` | List local users. | Local `users` table. | None. | `/admin/users`. | Requires `admin`; returns username, role, enabled, timestamps only. |
| `POST /api/v1/admin/users` | Create a local user. | Request body and local `users` table. | Writes a user row with password hash. | `/admin/users`. | Body: `{username,password,role}`. Response never returns plaintext password or hash. Duplicate users return `409`. |
| `PATCH /api/v1/admin/users/{username}/role` | Change a local user's role. | Local `users` table. | Updates role/timestamp; does not revoke sessions. | `/admin/users`. | Last enabled admin cannot be demoted away from `admin`; that returns `409`. Unknown user returns `404`. |
| `POST /api/v1/admin/users/{username}/disable` | Disable a local user. | Local `users` and `sessions` tables. | Disables user and revokes active target sessions. | `/admin/users`. | Last enabled admin cannot be disabled; disabled admin rows do not count toward the guard. |
| `POST /api/v1/admin/users/{username}/reset-password` | Set an admin-supplied password. | Local `users` and `sessions` tables. | Updates password hash and revokes active target sessions. | `/admin/users`. | Not blocked by last-admin protection. Response includes only safe user summary and revoked session count. |
| `GET /api/v1/cluster/summary` | Cluster counts and high-level mode. | Inventory adapter snapshot. | None. | Dashboard. | Returns `cluster_id=gjallar-mvp`, node/vm/template counts, `risk_level=unknown`. |
| `GET /api/v1/nodes` | Read-only node inventory. | Inventory adapter. | None. | Dashboard, Infra Explorer, Create VM options. | Node rows include status, CPU/memory usage, storage, networks. |
| `GET /api/v1/vms` | Read-only VM inventory. | Inventory adapter. | None. | Dashboard, Infra Explorer, Networks readiness. | Excludes templates; includes disks, tags, legacy `ip_addresses`, structured `ip_evidence`, and guest-agent evidence when available. |
| `GET /api/v1/vms/{vmid}` | Read-only single VM detail. | Inventory adapter lookup by VMID. | None. | API client helper; no primary current tab call observed. | Same VM shape as list rows, including `ip_evidence`; 404 when VMID is not found. |
| `GET /api/v1/profiles` | Create VM profile options. | Active DB-seeded profiles through `GJALLAR_DATABASE_URL`. | None. | Create VM. | Initial seed profiles: `general-vm`, `runtime-server`, `development-vm`; disabled/archived rows are hidden. |
| `GET /api/v1/vm-create/readiness` | IaC readiness for Create VM. | `run_iac_readiness()`. | None. | Create VM review model. | Checks shared root, IaC root, write allowlist, and Git repo. |
| `GET /api/v1/templates` | Read-only Proxmox template inventory. | Inventory adapter. | None. | Create VM options. | Active template selection source. Missing cloud-init/guest-agent evidence is not ready. |
| `GET /api/v1/storage` | Read-only storage candidates. | Inventory adapter. | None. | Dashboard, Create VM options. | Create VM filters by selected node, `images` content, and free capacity. |
| `GET /api/v1/networks` | Read-only bridge inventory. | Inventory adapter. | None. | Dashboard, Create VM options, Networks readiness. | Create VM uses active bridges on selected target node. Networks tab combines this with nodes/VMs in the frontend for selected-source target network comparison, CIDR-verified exact bridge match evidence, bridge-name-only review evidence, and CIDR remap candidate evidence. |
| `GET /api/v1/jobs` | Read-only job summaries. | `job_runs` table. | None. | Dashboard, Jobs/Runs. | Listing fails open to `[]` if DB read fails. |
| `GET /api/v1/jobs/{job_id}` | Read-only one job summary. | `job_runs` table. | None. | Jobs/Runs selected detail. | 404 when absent. |
| `GET /api/v1/jobs/{job_id}/artifacts` | Read-only artifact metadata for one job. | `job_artifacts` table. | None. | Jobs/Runs selected detail. | Returns metadata, not artifact contents or local file paths. |
| `GET /api/v1/risks` | Risk summaries derived from jobs. | `risks` arrays in job records. | None. | Dashboard, Risks/Alerts. | Current risks are job-derived, not a standalone risk engine. |
| `GET /api/v1/drs/summary` | DRS Advisor Phase 1 summary and candidates. | Read-only inventory plus job-derived risks. | None. | DRS Advisor. | Advisory only; all recommendations are `executable=false`. |
| `GET /api/v1/drs/recommendations` | DRS Advisor Phase 1 recommendation list. | Read-only inventory plus job-derived risks. | None. | DRS Advisor. | Running non-template VMs only; red-risk VMs excluded. |
| `GET /api/v1/drs/recommendations/{recommendation_id}` | One DRS recommendation detail. | Recalculated read-only recommendation model. | None. | DRS Advisor detail. | 404 when recommendation id is unknown. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/check` | Reference-only DRS recalculation. | Recalculated read-only recommendation model. | None. | DRS Advisor check action. | Not execution authorization. |
| `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start` | Start a stopped non-template VM. | Fresh inventory adapter precheck plus Proxmox mutation client. | Calls `POST /nodes/{node}/qemu/{vmid}/status/start`, polls task, reads status/current, writes `vm_start` job/artifact evidence. | Infra Explorer. | Requires `vm_start_acknowledged=true` and non-empty `idempotency_key`; blocks missing/moved/template/non-stopped VMs. Duplicate idempotency returns the existing job/result without another Proxmox start. |
| `POST /api/v1/vm-create/drafts` | Build a non-mutating Create VM draft. | Request payload, DB-backed active profiles, inventory VMID suggestion. | Records draft job status. | Create VM review model. | Incoming `network_id`/`networkId` is ignored. Accepts nested `access` with `cloud_init_user`/`ssh_public_key` aliases; raw public key is not returned. |
| `POST /api/v1/vm-create/{draft_id}/preflight` | Run non-destructive checks. | Draft and read-only inventory. | Records preflight job status and risks. | Create VM review model. | Red risk blocks approval/create; yellow can require acknowledgement. Access checks red-block missing/malformed required SSH public key and password login true. IaC readiness may be reported separately but is not a primary native-create blocker. |
| `POST /api/v1/vm-create/{draft_id}/plan` | Build artifact-backed dry-run plan. | Draft plus preflight. | Writes preflight, plan, VMInstance manifest, planned diff, review summary artifacts; records job status. | Create VM review model. | No live Proxmox mutation. Plan/review artifacts include access fingerprint/source, selected template evidence, and selected bridge evidence. |
| `POST /api/v1/vm-create/{draft_id}/approve` | Validate review approval metadata. | Rebuilt plan artifacts and approval payload. | Writes or refreshes `approval.json`; records approval job status. | Create VM approval step. | Requires exact `plan_artifact_id`, `review_summary_checksum`, and yellow acknowledgement when needed. |
| `POST /api/v1/vm-create/{draft_id}/proxmox-preview` | Build native create preview. | Approved rebuilt plan. | Revalidates approval and may refresh `approval.json`; writes preview artifact; records job status. | API/helper only; no primary current UI button. | Approval-gated but non-mutating. Preview config redacts `sshkeys`. |
| `POST /api/v1/vm-create/{draft_id}/proxmox-create` | Active live native Proxmox VM creation. | Approved rebuilt plan and Proxmox mutation client. | Revalidates approval and may refresh `approval.json`; writes an internal preview artifact; calls Proxmox clone/task/config/resize/power-policy post-check; writes job/artifacts. | Create VM final mutation button. | Requires valid approval, no red fresh risk, and `proxmox_mutation_acknowledged=true`. It does not require `manifest_commit_sha`. Native config uses reviewed username and transient SSH public key; API/artifacts return only redacted/safe evidence. `boot_and_verify` starts the new VM and verifies guest-agent IP plus cloud-init completion. |
## Current Frontend Client Coverage

The frontend client does not expose Terraform plan/apply, legacy GitOps execute/archive helpers, or Networks write helpers, and the backend routes no longer exist. The active UI covers inventory, the explicit VM start action, read-only network readiness, DRS Advisor read-only recommendations, jobs, risks, Create VM readiness, draft/preflight/plan/approve, native preview, and native create.

## Network Inventory Shape

`NetworkInventory` remains read-only and additive. Existing fields are `bridge_id`, `node_id`, `type`, and `active`. Optional observed bridge config evidence may include `address`, `netmask`, `prefix`, `cidr`, `gateway`, `bridge_ports`, `vlan_aware`, and `mtu`.

Live inventory populates these fields from Proxmox `/nodes/{node}/network` rows when available. CIDR is derived from an observed address plus netmask/prefix, or from an address already containing CIDR. A gateway without an address does not infer CIDR. CIDR/gateway match is observed config evidence only, not proof of the actual same L2/VLAN/routed network or migration feasibility.
