# Native Create Flow

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Create VM](../../current/top-tabs/04-create-vm.md).

This document covers the implemented native Proxmox Create VM path. It does not describe Terraform as active UI behavior.

## Native Preview

`POST /api/v1/vm-create/{draft_id}/proxmox-preview` is approval-gated and non-mutating.

| Step | Current behavior |
|---|---|
| Rebuild plan | Router rebuilds draft, preflight, and plan from current payload. |
| Validate approval | `validate_approval_request()` checks plan artifact id, review checksum, and yellow acknowledgement. |
| Build preview | `build_proxmox_create_preview()` builds clone/config/post-check payloads. |
| Write artifact | Writes `proxmox_create_preview.json` under the job run directory. |
| Return flags | `proxmox_create_enabled=false`, `proxmox_mutation_enabled=false`. |

## Approval Recheck

Native create repeats approval validation. `POST /api/v1/vm-create/{draft_id}/proxmox-create` rebuilds the plan from the submitted payload and requires exact `plan_artifact_id`, exact `review_summary_checksum`, yellow acknowledgement when needed, `proxmox_mutation_acknowledged=true`, and no red fresh risk.

If these gates fail, the route returns HTTP 409 and reports no live mutation side effect.

## Internal Preview

`proxmox-create` builds the same non-mutating preview artifact internally before it calls the Proxmox mutation client. The legacy `execute/archive` manifest routes are removed from the active API.

## Proxmox Operation Order

| Order | Operation | Proxmox endpoint | Success requirement |
|---:|---|---|---|
| 1 | Full clone from template | `POST /nodes/{template_node}/qemu/{template_vmid}/clone` | Returns a UPID. |
| 2 | Poll clone task | `GET /nodes/{template_node}/tasks/{upid}/status` | Task reaches `status=stopped` with `exitstatus=OK`. |
| 3 | Inspect cloned config | `GET /nodes/{target_node}/qemu/{vmid}/config` | Boot disk can be identified and current size can be read or resize is not needed. |
| 4 | Resize boot disk if needed | `PUT /nodes/{target_node}/qemu/{vmid}/resize` | Required only when requested disk is larger than observed cloned boot disk. |
| 5 | Apply VM config | `PUT /nodes/{target_node}/qemu/{vmid}/config` | CPU, memory, agent, onboot, net0, ciuser, optional sshkeys, ipconfig0 applied. |
| 6 | Read status | `GET /nodes/{target_node}/qemu/{vmid}/status/current` | VM is observable. |
| 7 | Read config | `GET /nodes/{target_node}/qemu/{vmid}/config` | Config is observable for fingerprint evidence. |
| 8 | Optional boot verification | `POST /status/start`, guest-agent network, guest exec | Only for `boot_and_verify`: VM runs, IP is observed, and `cloud-init status --wait` succeeds. |
| 9 | Write observed artifact | DB artifact write | `observed_after.json` exists. |

## Config Payload

`config_payload_from_plan()` builds `cores`, `memory`, `agent=enabled=1`, `onboot=0`, `net0=virtio,bridge=<bridge_id>`, reviewed access `ciuser`, optional transient `sshkeys`, and `ipconfig0`.

Raw SSH public key material is used only for the live Proxmox config call.
Preview/result payloads and artifacts redact `sshkeys` and expose only safe
access fingerprint evidence.

Static mode requires explicit `static_ip`, `prefix`, and `gateway`. The current code does not infer `/24` or `.1`.

## Disk Resize Decision

The runner selects the cloned boot disk in this order:

1. `scsi0`
2. disk named by `bootdisk` or `boot: order=...`
3. first non-CDROM disk sorted by bus/index

Resize happens only when requested `disk_gb` is larger than observed current boot disk size. Same-size or smaller requests skip resize as `not_needed`.

Unobservable boot disk or unknown current size returns `needs_reconciliation`, because Gjallar cannot safely claim the created VM matches the reviewed disk request.

## Observed After

`observed_after.json` is the current post-mutation evidence artifact. It includes operation identifiers, existence/power status, selected power policy, boot verification evidence when applicable, sanitized status/config evidence, and a fingerprint hash from `smbios1`, `vmgenid`, MAC addresses, and disk volume ids.

This artifact is not a DB identity record. It is current job evidence and a useful future input for identity work.

## Power-Policy Success

The default `stopped` policy succeeds only when Proxmox reports the new VM is
`stopped`. The optional `boot_and_verify` policy starts the new VM and succeeds
only when Proxmox reports it running, guest-agent IP discovery succeeds, and
`cloud-init status --wait` exits successfully. SSH login, Ansible verification,
app bootstrap, and DRS identity registration remain deferred and must not be
included in current success claims.
