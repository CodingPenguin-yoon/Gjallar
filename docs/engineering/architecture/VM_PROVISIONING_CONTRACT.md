# Gjallar Create VM Contract

Last reviewed against code: 2026-05-13

Current MVP product source of truth is [`docs/product/prd/drs-advisor/`](../../product/prd/drs-advisor/README.md). If this document conflicts with that folder, `drs-advisor/` wins.

The active VM creation contract is the `/api/v1/vm-create/*` flow. Legacy
`POST /api/provision` is not an active frontend or backend surface.

Create VM is a supporting existing capability. It is separate from DRS Advisor and must not define the next MVP success line or implementation order. DRS Advisor work should reuse approval/artifact/job lessons where useful, but migration recommendation/execution is a separate flow.

Target profile/template/network design is captured in
[`CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md).
That document is the source for the next Create VM profile, live template, and
live bridge model. Sections below call out where current code still differs.

## Contract Goal

Create VM is an operator-reviewed workflow for producing a powered-off Proxmox
VM from a known template. The active enterprise path is Proxmox API native. It is intentionally split into draft, preflight, plan, approval, manifest commit, native preview, and native create stages so the UI can show risk evidence before any live side effect. Terraform remains optional/deprecated legacy executor code.

```text
draft request
  -> preflight
  -> plan artifacts + Review & Confirm
  -> approval validation
  -> manifest commit through execute
  -> Proxmox native preview
  -> Proxmox native create after explicit acknowledgement
  -> optional archive path
```

## Active Endpoints

```text
GET  /api/v1/profiles
GET  /api/v1/vm-create/readiness
POST /api/v1/vm-create/drafts
POST /api/v1/vm-create/{draft_id}/preflight
POST /api/v1/vm-create/{draft_id}/plan
POST /api/v1/vm-create/{draft_id}/approve
POST /api/v1/vm-create/{draft_id}/proxmox-preview
POST /api/v1/vm-create/{draft_id}/proxmox-create
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
- `backend/app/proxmox/client.py`
- `backend/app/vm_create/proxmox_runner.py`
- `infra/terraform/main.tf`

## Draft Request

Current route handlers accept a compact payload and rebuild a server-side draft
from the locked `general-vm` profile defaults plus operator selections. This is
current implementation, not the full target design.

Current request fields:

```json
{
  "operator_id": "api-preview",
  "job_id": "job-api-preview",
  "target_node_id": "yoonmanserver2",
  "storage_id": "local-lvm",
  "bridge_id": "vmbr0",
  "static_ip": "192.168.2.150",
  "prefix": 24,
  "gateway": "192.168.2.1",
  "ip_mode": "static",
  "template_id": "ubuntu-template",
  "template_vmid": 9000,
  "template_node_id": "yoonmanserver2"
}
```

The backend resolves `proposed_vmid` from inventory via `suggest_next_vmid()`.
VMID is not operator-supplied in the active draft request.

Incoming `network_id`/`networkId` is ignored for transition compatibility and
is not echoed by active draft/plan/review/manifest/job output. Target requests
also carry the selected live template reference and editable access fields:

```json
{
  "profile_id": "runtime-server",
  "target_node_id": "yoonmanserver2",
  "storage_id": "local-lvm",
  "template": {
    "node_id": "yoonmanserver2",
    "vmid": 9000,
    "name": "ubuntu-template"
  },
  "hardware": {
    "cpu": 4,
    "memory_mb": 8192,
    "disk_gb": 100
  },
  "access": {
    "username": "yoon",
    "ssh_public_key": "ssh-ed25519 AAAA...",
    "password_login": false
  },
  "network": {
    "bridge": "vmbr0",
    "ip_mode": "static",
    "static_ip": "192.168.2.150",
    "prefix": 24,
    "gateway": "192.168.2.1"
  }
}
```

## Profile Defaults

Current implementation has `general-vm` as the only create-enabled profile.

Current default values:

| Field | Value |
|---|---|
| CPU | `2` |
| Memory | `4096 MB` |
| Disk | `50 GB` |
| Network source | explicit `bridge_id` selected from target-node active live bridge inventory |
| IP mode | `static` |
| Cloud-init user | `yoon` |
| Password login | `false` |
| Desired power state | `stopped` |
| First power-on included | `false` |

Target profile source of truth is Gjallar DB seed data, initially read-only in
the UI. Profile management UI is future. Initial seeded enabled profiles are:

| Profile ID | Display name | Korean label | CPU | Memory MB | Disk GB | Limits |
|---|---|---|---:|---:|---:|---|
| `general-vm` | General VM | 범용 VM | 2 | 4096 | 50 | CPU 1-8, memory 1024-32768, disk 50-500 |
| `runtime-server` | Runtime Server | 서비스 실행용 VM | 4 | 8192 | 100 | CPU 2-16, memory 4096-65536, disk 80-1000 |
| `development-vm` | Development VM | 개발/테스트용 VM | 2 | 4096 | 50 | CPU 1-12, memory 2048-32768, disk 50-500 |

All initial profiles require cloud-init and qemu guest agent capable templates.
All use access recommendations `default_user=yoon`,
`require_ssh_key=true`, `allow_password_login=false`, and
`allow_user_override=true`.

Profiles do not contain target node, storage, network/network_id, bridge,
static IP, template VMID/name, power policy, or profile version. Changing the
profile resets CPU/RAM/Disk to the new defaults, then the operator may edit
inside min/max.

## Template And Disk Floor

Target template source of truth is Proxmox live inventory. Gjallar should not
add a separate template catalog or registration window for this Create VM
target. The UI shows live Proxmox templates and disables templates that fail the
selected profile's cloud-init or qemu guest-agent requirements. Backend
preflight re-checks and red-blocks failing templates even if the UI already
disabled them.

Template inventory includes hardware evidence:

- `cpu`
- `memory_mb`
- `disk_gb`

The current Ubuntu template baseline is `50 GB`. Current preflight includes a
`template_disk_floor` check and returns a red
`template_disk_larger_than_requested` risk when the requested draft disk is
smaller than the selected template disk.

The frontend shows template disk size in the selector and raises the form disk
floor to the selected template minimum.

## Preflight Contract

Preflight is read-only. It checks the draft against inventory and IaC readiness
without creating, committing, pushing, applying, or mutating Proxmox state.

Current checks include:

- profile availability
- profile hardware min/max
- template availability and family match
- template cloud-init readiness
- template guest-agent readiness
- template disk floor
- target node online
- storage availability and capacity
- explicit bridge selection
- selected bridge active on the target node
- VMID uniqueness
- VM name uniqueness
- static field validity and observed static IP availability
- IaC root/state readiness
- Terraform state lock availability

Target checks remove `network_id` as the Create VM source of truth and add:

- selected profile exists in DB seed and is enabled
- selected live template satisfies selected profile requirements
- selected target node live bridge exists and is active
- static mode has `static_ip`, `prefix`, and `gateway`
- required SSH key is present through request or configured default
- password login remains disabled

Red risks block approval and execution. Yellow risks require explicit operator
acknowledgement where the approval contract allows it.

## Plan Contract

Plan builds artifact-backed review data from the draft and preflight result.
It does not perform live Proxmox mutation.

Plan output includes:

- draft and job identifiers
- manifest identifier
- selected profile id and resolved profile defaults/limits
- VM name and VMID
- target node, storage, live template, hardware, access, and network selections
- legacy Terraform state path retained in plan/review for compatibility
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

## Native Proxmox Preview And Create

`proxmox-preview` is approval-gated but non-mutating. It calls `build_proxmox_create_preview()` and writes a `proxmox_create_preview` artifact containing the clone endpoint, config payload, and post-check contract.

`proxmox-create` is the active live mutation route. It requires:

- approval metadata is valid
- `manifest_commit_sha`
- committed manifest verification through `verify_plan_manifest_commit()`
- `proxmox_mutation_acknowledged=true`
- a fresh preflight/plan immediately before mutation with no red risk

The native runner uses `backend/app/proxmox/client.py` and `backend/app/vm_create/proxmox_runner.py`:

1. `clone_vm()` calls `POST /nodes/{template_node}/qemu/{template_vmid}/clone` with `full=1`, `newid`, `name`, `target`, and `storage`.
2. `wait_for_task()` polls `/nodes/{node}/tasks/{upid}/status` until the clone task stops.
3. `get_vm_config()` reads the cloned config to choose the boot disk (`scsi0`, then boot order, then first non-CDROM disk) and compare observed size to requested `disk_gb`.
4. `resize_vm_disk()` calls `PUT /nodes/{node}/qemu/{vmid}/resize` with `disk=<device>` and `size=<N>G` only when requested `disk_gb` is larger than the observed cloned boot disk.
5. `set_vm_config()` applies CPU, memory, agent, onboot, network, and cloud-init defaults through `/nodes/{node}/qemu/{vmid}/config`.
6. `get_vm_status()` reads `/nodes/{node}/qemu/{vmid}/status/current`.
7. `get_vm_config()` reads `/nodes/{node}/qemu/{vmid}/config`.
8. `run_proxmox_create()` writes `observed_after.json` with a normalized fingerprint from `smbios1`, `vmgenid`, MAC addresses, and disk volume IDs.

Success requires clone task `exitstatus=OK`, requested disk resize to be unnecessary or completed, VM existence on the target node, observed `status=stopped`, and an `observed_after` artifact. If the task fails, the cloned disk size is unknown, resize fails, the VM is missing, or Proxmox reports it powered on, the route records failed/`needs_reconciliation` and does not mark the manifest `applied`.

## Legacy Terraform Plan And Apply

`terraform-plan`, `terraform-apply`, `backend/app/vm_create/terraform_runner.py`, and `infra/terraform/main.tf` remain for compatibility and emergency/legacy workflows. They are not the active UI default and should not be required for enterprise Create VM or DRS Advisor basics.

## Jobs, Artifacts, And Risks

Create VM route handlers record progress under `GJALLAR_RUNS_ROOT` through
`app.jobs.runs.record_job_run()`.

Artifacts are real files with checksums, and secret-bearing values are redacted
before persistence. `/api/v1/jobs` returns summaries, while `/api/v1/risks`
derives risk rows from recorded job risk data.

If the runs root is unavailable, listing jobs fails open with an empty list.
This keeps Dashboard and read-only operator screens available when NFS is down.

## Network Policy

Current Create VM implementation does not use NetworkPolicy or `server-net` as
the network source of truth. It uses explicit `bridge_id` selected from active
live bridge inventory on the selected target node. NetworkPolicy remains
current/legacy Networks-tab support and possible future advisory evidence.

Policy read combines:

- live Proxmox bridge inventory
- IaC `network-profiles.yaml`

Policy write is limited to the network policy path and guarded against escaping
the configured IaC root.

Target Create VM networking no longer uses `network_id`/`server-net`. The
operator selects target node, then an active live bridge on that node. Static
mode requires `static_ip`, `prefix`, and `gateway`; DHCP is allowed with a
warning and later guest-agent/inventory discovery. Network tab policy,
subnet/gateway/range integration is future and may remain as current/legacy
support until code changes.

## Current Implementation Gap

The current code still differs from the target profile/template/network design:

- profiles are built in/current manifest-backed behavior, not Gjallar DB seed
  source of truth
- only `general-vm` is create-enabled
- `runtime-server` and `development-vm` are target enabled profiles, not current
  active choices
- current Create VM uses explicit `bridge_id` selected from target-node active
  live bridge inventory; incoming `network_id`/`networkId` is ignored and is
  not echoed in active outputs
- current static networking requires explicit `static_ip`, `prefix`, and
  `gateway`
- profile management UI, template catalog UI, and VM start action are not part
  of the current implementation

## Explicit Non-Goals

The active Create VM contract does not include:

- legacy `POST /api/provision`
- profile management create/edit/delete UI in the initial target slice
- Gjallar template catalog or template registration window
- app deploy or arbitrary bootstrap package execution
- direct VM start/stop/reset/delete
- profile-owned power policy
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
