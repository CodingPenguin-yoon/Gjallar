# Gjallar Create VM Contract

Last reviewed against code: 2026-05-11

Current MVP product source of truth is [`docs/product/prd/drs-advisor/`](../../product/prd/drs-advisor/README.md). If this document conflicts with that folder, `drs-advisor/` wins.

The active VM creation contract is the `/api/v1/vm-create/*` flow. Legacy
`POST /api/provision` is not an active frontend or backend surface.

Create VM is a supporting existing capability. It is separate from DRS Advisor and must not define the next MVP success line or implementation order. DRS Advisor work should reuse approval/artifact/job lessons where useful, but migration recommendation/execution is a separate flow.

## Contract Goal

Create VM is an operator-reviewed workflow for producing a powered-off Proxmox
VM from a known template. It is intentionally split into draft, preflight, plan,
approval, workspace, and apply stages so the UI can show risk evidence before
any live side effect.

```text
draft request
  -> preflight
  -> plan artifacts + Review & Confirm
  -> approval validation
  -> Terraform workspace/plan
  -> optional Terraform apply after explicit acknowledgement
  -> optional manifest archive/execute paths
```

## Active Endpoints

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

The frontend implementation lives in:

- `frontend/src/components/CreateInstanceWizard.jsx`
- `frontend/src/utils/createVmDefaults.js`
- `frontend/src/utils/createVmFlow.js`

The backend implementation lives in:

- `backend/app/api/v1/router.py`
- `backend/app/vm_create/*`
- `backend/app/manifests/*`
- `backend/app/network_policy.py`
- `backend/app/jobs/*`
- `infra/terraform/main.tf`

## Draft Request

Current route handlers accept a compact payload and rebuild a server-side draft
from the locked `general-vm` profile defaults plus operator selections.

Common request fields:

```json
{
  "operator_id": "api-preview",
  "job_id": "job-api-preview",
  "target_node_id": "yoonmanserver2",
  "storage_id": "local-lvm",
  "network_id": "server-net",
  "bridge_id": "vmbr0",
  "static_ip": "192.168.2.150",
  "ip_mode": "static",
  "template_id": "ubuntu-template",
  "template_vmid": 9000,
  "template_node_id": "yoonmanserver2"
}
```

The backend resolves `proposed_vmid` from inventory via `suggest_next_vmid()`.
VMID is not operator-supplied in the active draft request.

## Profile Defaults

The active create-enabled profile is `general-vm`.

Current default values:

| Field | Value |
|---|---|
| CPU | `2` |
| Memory | `4096 MB` |
| Disk | `50 GB` |
| Network profile | `server-net` |
| IP mode | `static` |
| Cloud-init user | `yoon` |
| Password login | `false` |
| Desired power state | `stopped` |
| First power-on included | `false` |

Future profiles may exist in manifests but are not create-enabled.

## Template And Disk Floor

Template inventory includes hardware evidence:

- `cpu`
- `memory_mb`
- `disk_gb`

The current Ubuntu template baseline is `50 GB`. Preflight includes a
`template_disk_floor` check and returns a red
`template_disk_larger_than_requested` risk when the requested draft disk is
smaller than the selected template disk.

The frontend shows template disk size in the selector and raises the form disk
floor to the selected template minimum.

## Preflight Contract

Preflight is read-only. It checks the draft against inventory, network policy,
and IaC readiness without creating, committing, pushing, applying, or mutating
Proxmox state.

Current checks include:

- profile availability
- template availability and family match
- template cloud-init readiness
- template guest-agent readiness
- template disk floor
- target node online
- storage availability and capacity
- bridge mapping
- observed bridge availability
- VMID uniqueness
- VM name uniqueness
- static IP policy and availability
- IaC root/state readiness
- Terraform state lock availability

Red risks block approval and execution. Yellow risks require explicit operator
acknowledgement where the approval contract allows it.

## Plan Contract

Plan builds artifact-backed review data from the draft and preflight result.
It does not perform live Proxmox mutation.

Plan output includes:

- draft and job identifiers
- manifest identifier
- VM name and VMID
- target node, storage, template, hardware, and network selections
- Terraform state path
- risk summary
- Review & Confirm payload
- generated artifacts
- `first_power_on_included=false`

The generated `VMInstance` manifest requests `desired_power_state: stopped`.

## Approval Contract

Approval validates the exact plan artifact metadata supplied by the frontend:

- `plan_artifact_id`
- `review_summary_checksum`
- `yellow_risk_acknowledged`

Approval is validation-only. It records job progress but does not itself apply
Terraform or create a VM.

## Terraform Plan And Apply

Terraform workspace creation is gated by approval and IaC readiness.

`terraform-plan` may either prepare a workspace or run `terraform plan` when:

- approval metadata is valid
- IaC is ready for planning
- `run_terraform_plan=true`
- `terraform_plan_acknowledged=true`

`terraform-apply` is stricter. It requires:

- approval metadata is valid
- IaC plan/apply readiness passes
- apply acknowledgement is explicit
- a plan file exists where required by the runner

Current apply policy creates/configures the VM as powered-off. First power-on,
guest smoke, and post-create readiness are deferred.

## Jobs, Artifacts, And Risks

Create VM route handlers record progress under `GJALLAR_RUNS_ROOT` through
`app.jobs.runs.record_job_run()`.

Artifacts are real files with checksums, and secret-bearing values are redacted
before persistence. `/api/v1/jobs` returns summaries, while `/api/v1/risks`
derives risk rows from recorded job risk data.

If the runs root is unavailable, listing jobs fails open with an empty list.
This keeps Dashboard and read-only operator screens available when NFS is down.

## Network Policy

Static IP and bridge checks use the configured network policy under the IaC
root. The active MVP network profile is `server-net`.

Policy read combines:

- live Proxmox bridge inventory
- IaC `network-profiles.yaml`

Policy write is limited to the network policy path and guarded against escaping
the configured IaC root.

## Explicit Non-Goals

The active Create VM contract does not include:

- legacy `POST /api/provision`
- app deploy or arbitrary bootstrap package execution
- direct VM start/stop/reset/delete
- snapshot/rollback
- raw shell execution
- DB migration orchestration
- Heimdall runtime registry writes
- GitLab environment/staging host registration
- LLM/agent product behavior

## Verification

Relevant backend tests:

```bash
PYTHONPATH=backend python3 -m pytest -q \
  backend/tests/vm_create \
  backend/tests/contracts/test_api_v1_vm_create.py \
  backend/tests/contracts/test_api_v1_vm_create_approval_execute.py \
  backend/tests/proxmox/test_inventory_adapter.py \
  backend/tests/manifests/test_profile_schema.py
```

Relevant frontend tests:

```bash
node frontend/tests/createVmDefaults.test.mjs
node frontend/tests/createVmFlow.test.mjs
node frontend/tests/apiV1Client.test.mjs
```
