# Create VM Native Architecture

Last reviewed against code: 2026-05-14

This document describes the current implemented Create VM path. The active enterprise direction is Proxmox API native create. The legacy Terraform executor route surface and helper code are removed.

The target profile/template/network model is documented in
[`CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md).
This architecture document remains current-code oriented, so target items below
are called out separately when the implementation has not caught up.

## Active Direction

- Primary create path: Proxmox API native clone/resize-if-needed/config/post-check.
- Legacy Terraform executor: removed from the active tree.
- Powered-off policy: create/config only; first power-on and smoke are deferred.
- Source of truth: Proxmox actual state. A create is not successful unless post-check reads Proxmox state and writes `observed_after`.
- Inventory boundary: `backend/app/proxmox/inventory.py` remains read-only. Mutation code lives in `backend/app/proxmox/client.py`.

## Target Design Overlay

The next Create VM design keeps the native create gates but changes selection
sources:

- Profiles are Gjallar DB-seeded creation presets, initially read-only in the UI.
- Initial enabled profiles are `general-vm`, `runtime-server`, and
  `development-vm`.
- Profiles set hardware defaults/min/max, template requirements, and access
  recommendations. They do not include target node, storage, network,
  `network_id`, bridge, static IP, template VMID/name, power policy, or profile
  version.
- Templates are selected from Proxmox live inventory. There is no target Gjallar
  template catalog or registration window.
- Target networking selects an active live bridge after target node selection.
  `network_id`/`server-net` is not the target Create VM source of truth.
- Static mode requires `static_ip`, `prefix`, and `gateway`; DHCP is allowed
  with a warning and later discovery.
- Access/SSH uses reviewed cloud-init username plus a request-supplied or
  backend env/file default SSH public key. Raw public key material is transient
  only; artifacts and API responses contain presence/source/fingerprint.
- Create success remains powered off/stopped by global create policy.
- Starting a VM is future Infra Explorer row action work with Jobs/Runs audit,
  not part of profile policy.

## Frontend Flow

Entry point:

- `frontend/src/components/CreateInstanceWizard.jsx`

Utility flow:

- `buildCreateVmInputFromConfig()` builds form input.
- `loadCreateVmReviewModel()` calls draft, preflight, and plan.
- `approveCreateVmReview()` validates exact plan/review metadata.
- `previewCreateVmProxmox()` calls the non-mutating native preview endpoint.
- `commitCreateVmManifest()` calls `execute` to commit the manifest only.
- `createVmWithProxmox()` calls native create after final acknowledgement.

API client functions in `frontend/src/services/apiV1.js`:

- `createVmDraft()`
- `preflightVmDraft()`
- `planVmDraft()`
- `approveVmDraft()`
- `commitVmDraftManifest()`
- `previewVmDraftProxmox()`
- `createVmDraftProxmox()`

The active frontend does not call Terraform plan/apply helpers, and the backend routes are absent.

## Backend Endpoint Flow

All routes are mounted in `backend/app/api/v1/router.py`.

1. `POST /api/v1/vm-create/drafts`
   - Handler: `create_vm_draft()`
   - Builds a server-side draft through `_api_draft_from_payload()` and `build_default_vm_draft()`.
   - Records draft job progress with `_record_draft_job()`.

2. `POST /api/v1/vm-create/{draft_id}/preflight`
   - Handler: `preflight_vm_draft()`
   - Calls `run_preflight()` using the read-only inventory adapter.
   - Records preflight checks/risks.

3. `POST /api/v1/vm-create/{draft_id}/plan`
   - Handler: `plan_vm_draft()`
   - Calls `build_vm_create_plan()`.
   - Writes preflight, plan, manifest, planned diff, and review summary artifacts.

4. `POST /api/v1/vm-create/{draft_id}/approve`
   - Handler: `approve_vm_draft()`
   - Calls `validate_approval_request()`.
   - Validates `plan_artifact_id`, `review_summary_checksum`, and yellow risk acknowledgement.

5. `POST /api/v1/vm-create/{draft_id}/execute`
   - Handler: `execute_vm_draft()`
   - Calls `commit_plan_manifest()`.
   - Writes and commits `IaC/manifests/vms/<manifest_id>.yaml`.
   - Does not call Proxmox.

6. `POST /api/v1/vm-create/{draft_id}/proxmox-preview`
   - Handler: `preview_vm_draft_proxmox_create()`
   - Revalidates approval.
   - Calls `build_proxmox_create_preview()`.
   - Writes `proxmox_create_preview.json`.
   - Does not call Proxmox.

7. `POST /api/v1/vm-create/{draft_id}/proxmox-create`
   - Handler: `create_vm_draft_proxmox_native()`
   - Revalidates approval.
   - Requires `manifest_commit_sha`.
   - Requires `proxmox_mutation_acknowledged=true`.
   - Rebuilds plan/preflight immediately before mutation and blocks red risk.
   - Calls `verify_plan_manifest_commit()`.
   - Calls `update_plan_manifest_status(plan, "applying")`.
   - Calls `get_default_proxmox_mutation_client()`.
   - Calls `run_proxmox_create()`.
   - Marks manifest `applied` only if native runner success includes `observed_after_artifact`.

## Backend Responsibilities

`backend/app/vm_create/drafts.py`

- Current `build_default_vm_draft()` builds the locked `general-vm` draft.
- VMID is suggested from inventory before draft construction.
- `first_power_on_included=False`.
- Target draft construction should load the selected DB-seeded profile, reset
  hardware to profile defaults on profile change, enforce min/max, use live
  template selection, use live target-node bridge selection, and reject
  `network_id` as the target Create VM contract.

`backend/app/vm_create/preflight.py`

- `run_preflight()` checks template, node, storage, network, VMID/name, IP, IaC readiness, and read-only adapter scope.
- It must use the read-only inventory adapter only.
- Current preflight also red-blocks selected templates that fail
  `require_cloud_init` or `require_qemu_guest_agent`, static network requests
  missing `prefix`/`gateway`, missing required SSH public key, malformed or
  private-key-looking SSH input, and password login true.

`backend/app/vm_create/planner.py`

- `build_vm_create_plan()` writes artifact-backed review evidence.
- It builds the `VMInstance` manifest artifact through `build_vm_instance_manifest()`.
- Current plan evidence includes selected profile defaults/limits, live
  template evidence, live bridge evidence, static prefix/gateway when used, and
  access username/key presence/source/fingerprint without raw key material.

`backend/app/vm_create/approval.py`

- `validate_approval_request()` validates exact artifact IDs/checksums and yellow risk acknowledgement.
- Approval does not mutate Proxmox or commit manifests.

`backend/app/vm_create/gitops.py`

- `commit_plan_manifest()` writes the manifest and local Git commit.
- `verify_plan_manifest_commit()` checks that the supplied commit contains the expected manifest.
- `update_plan_manifest_status()` records `applying`, `applied`, `apply_failed`, or `needs_reconciliation`.

`backend/app/proxmox/client.py`

- `ProxmoxMutationClient.from_env()` reads `PROXMOX_API_URL`, `PROXMOX_API_TOKEN_ID`, `PROXMOX_API_TOKEN_SECRET`, and `PROXMOX_TLS_INSECURE`.
- `clone_vm()` calls the Proxmox clone endpoint.
- `wait_for_task()` polls task status by UPID.
- `set_vm_config()`, `get_vm_status()`, and `get_vm_config()` perform the native config and post-check calls.

`backend/app/vm_create/proxmox_runner.py`

- `build_proxmox_create_preview()` writes the non-mutating preview artifact.
- `clone_payload_from_plan()` builds full-clone parameters.
- `config_payload_from_plan()` builds CPU/memory/agent/onboot/network/cloud-init config.
- It uses the reviewed access username for `ciuser` and the transient public
  key for Proxmox `sshkeys`; preview/result artifacts redact `sshkeys`.
- `run_proxmox_create()` performs clone, polling, boot disk resize when needed, config, post-check, and observed artifact creation.

`backend/app/jobs/runs.py` and `backend/app/jobs/artifacts.py`

- `record_job_run()` writes current job state under `GJALLAR_RUNS_ROOT`.
- `write_json_artifact()` writes checksummed artifacts with secret redaction.

## Proxmox API Order

Native create uses this order:

1. Clone:
   - `POST /nodes/{template_node}/qemu/{template_vmid}/clone`
   - Payload: `full=1`, `newid`, `name`, `target`, `storage`
   - Returns UPID.

2. Task polling:
   - `GET /nodes/{template_node}/tasks/{upid}/status`
   - Success requires stopped task with `exitstatus=OK`.

3. Boot disk resize:
   - `GET /nodes/{target_node}/qemu/{vmid}/config`
   - Selects `scsi0` first, then `bootdisk`/`boot: order=...`, then the first non-CDROM disk.
   - If requested `disk_gb` is larger than the observed cloned boot disk size, calls `PUT /nodes/{target_node}/qemu/{vmid}/resize` with `disk=<device>` and `size=<N>G`.
   - Same-size or smaller requests do not call resize.
   - Unknown cloned disk size or resize failure returns `needs_reconciliation` before config.

4. Config:
   - `PUT /nodes/{target_node}/qemu/{vmid}/config`
   - Applies `cores`, `memory`, `agent=enabled=1`, `onboot=0`, `net0`, `ciuser`, optional `sshkeys`, and `ipconfig0`.

5. Post-check:
   - `GET /nodes/{target_node}/qemu/{vmid}/status/current`
   - `GET /nodes/{target_node}/qemu/{vmid}/config`
   - Success requires VM exists on target node and `status=stopped`.

6. Artifact:
   - `observed_after.json`
   - Contains observed status/config and a fingerprint hash from `smbios1`, `vmgenid`, MAC list, and disk volume ID list.
   - Observed config redacts `sshkeys` and public key material.

## Success And Failure Criteria

Success:

- Approval metadata is exact.
- Manifest commit is verified.
- Red risk is absent in the fresh pre-mutation plan.
- Clone task exits `OK`.
- Requested boot disk resize is either unnecessary or completed.
- Config call completes.
- Post-check reads the VM on the target node.
- Observed status is `stopped`.
- `observed_after_artifact` exists.
- Router marks manifest `applied`.

Failure:

- Approval mismatch, missing acknowledgement, red risk, or missing commit blocks before mutation.
- Clone task failure returns failed and does not configure.
- Unknown cloned boot disk size or resize failure after clone returns `needs_reconciliation`.
- Config failure after clone returns `needs_reconciliation`.
- VM missing during post-check returns `needs_reconciliation`.
- Observed powered-on state returns `needs_reconciliation`.
- Missing `observed_after_artifact` prevents `applied`.

## Status Recording

Job status:

- Draft/preflight/plan/approval use `_record_draft_job()`, `_record_preflight_job()`, and `_record_plan_job()`.
- Native create records `running` at stage `create`.
- Success records job `completed`.
- Failed or uncertain post-check records job `failed` with step status `apply_failed` or `needs_reconciliation`.

Manifest status:

- `execute` creates manifest with `pending`.
- `proxmox-create` sets `applying` before mutation.
- Success sets `applied`.
- Task failure sets `apply_failed`.
- Missing/powered-on/uncertain observed state sets `needs_reconciliation`.

Artifacts:

- Plan stage writes `preflight_report`, `plan`, `vm_instance_manifest`, `planned_git_diff`, and `review_summary`.
- Approval may write `approval`.
- Preview writes `proxmox_create_preview`.
- Create writes `observed_after`.

## Current Implementation Gap

As of 2026-05-14, the current native create path is ahead of the old Terraform
flow but still has selection-model gaps:

- Profiles are transitional read-only `static_seed` data rather than Gjallar DB
  seed source of truth.
- `general-vm`, `runtime-server`, and `development-vm` are active enabled
  choices with hardware default/min/max validation.
- Current Create VM networking uses explicit `bridge_id` selected from active
  live bridge inventory on the target node. Incoming `network_id`/`networkId`
  is ignored during transition compatibility and is not echoed in active
  draft/plan/review/manifest/job output.
- Current static network handling requires explicit `static_ip`, `prefix`, and
  `gateway`.
- Current Access/SSH handling accepts nested access payload aliases, requires a
  valid SSH public key from request or backend default for current profiles,
  keeps password login disabled, records safe fingerprint evidence, and uses
  raw key material only transiently for native Proxmox config.
- Network tab policy remains current/legacy support; it is not the target Create
  VM network source of truth.

## Remaining Risk

- There is no DRS DB identity/fingerprint table yet; Create VM fingerprint is artifact evidence, not a reusable DRS identity substrate.
- Restart reconciliation for native create is not implemented as a background service.
- First power-on, cloud-init readiness, guest-agent/IP discovery, SSH smoke, and Ansible verification are deferred.
- Terraform-named state path/root fields remain compatibility metadata until a separate cleanup.
- DB profile seed source remains future work.
- DRS Advisor migration will need its own final pre-check, operation lock, migration UPID tracking, and reconciliation flow; Create VM native runner is not a DRS migration executor.
