# Infra Explorer Architecture

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Infra Explorer](../../current/top-tabs/02-infra-explorer.md).

Infra Explorer is the `/infra` route. It is a VM and node inventory view backed by the current `/api/v1` inventory adapter, with one gated action for starting stopped non-template VMs.

## Current Route And Component

| Concern | Current implementation |
|---|---|
| Route | `/infra` |
| Component | `frontend/src/components/InstanceList.jsx` |
| Loader | `frontend/src/utils/infraExplorerScreen.js` |
| Shared view model | `buildInfraExplorerModel()` in `frontend/src/utils/apiV1ViewModels.js` |
| Mutation controls | Start only for stopped non-template VMs |

## APIs Used

| API | Used for |
|---|---|
| `GET /api/v1/nodes` | Node groups and node status. |
| `GET /api/v1/vms` | VM rows, VM detail evidence, guest-agent/IP/disk/tag/storage signals. |
| `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start` | Gated start action for eligible VM rows. |

The current screen does not call `GET /api/v1/vms/{vmid}`. VM detail evidence is already included in list payloads returned by the inventory adapter.

## Read-Only VM/Node Detail

The view model normalizes node identity, VMID/name, observed status, IP evidence, guest-agent signal, disk stack, tags, and storage signal. Rows are grouped by node. Unknown node ids are grouped into an "Unknown" bucket only if VM inventory references a node not present in the node list.

## Start Action Boundary

Start is separate from Create VM. The row action is visible only when the view model sees `status=stopped` and `template=false`; running, template, and unknown-status rows expose no action.

The UI shows an in-app confirmation panel with VM name, node, VMID, and current status, requires acknowledgement, calls `apiV1Client.startVm()`, then navigates to `/jobs?job=<job_id>`.

The backend route requires `vm_start_acknowledged=true` and a non-empty `idempotency_key`, rereads inventory for an exact `(node_id, vmid)` match, blocks missing/moved/template/non-stopped VMs, calls Proxmox QEMU start, polls the UPID, verifies observed-after `running`, and writes `vm_start_observed_after.json`.

Infra Explorer still has no buttons for stop, reboot, reset, delete, snapshot, rollback, migrate, clone, SSH, or Ansible. Create VM can optionally start and verify a newly created VM through `boot_and_verify`; existing-VM start remains this separate gated Infra Explorer action.

## Target Identity Panel

Target DRS Advisor requires an identity/fingerprint layer that does not exist yet. Future Infra Explorer may show Gjallar VM identity, identity confidence, last observed fingerprint, classification completeness, DRS eligibility/blockers, and last migration operation.

Until those exist, Infra Explorer remains primarily a Proxmox inventory browser plus the explicit stopped-VM start action.
