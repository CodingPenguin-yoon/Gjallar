# Infra Explorer Architecture

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Infra Explorer](../../current/top-tabs/02-infra-explorer.md).

Infra Explorer is the `/infra` route. It is a read-only VM and node inventory view backed by the current `/api/v1` inventory adapter.

## Current Route And Component

| Concern | Current implementation |
|---|---|
| Route | `/infra` |
| Component | `frontend/src/components/InstanceList.jsx` |
| Loader | `frontend/src/utils/infraExplorerScreen.js` |
| Shared view model | `buildInfraExplorerModel()` in `frontend/src/utils/apiV1ViewModels.js` |
| Mutation controls | None |

## APIs Used

| API | Used for |
|---|---|
| `GET /api/v1/nodes` | Node groups and node status. |
| `GET /api/v1/vms` | VM rows, VM detail evidence, guest-agent/IP/disk/tag/storage signals. |

The current screen does not call `GET /api/v1/vms/{vmid}`. VM detail evidence is already included in list payloads returned by the inventory adapter.

## Read-Only VM/Node Detail

The view model normalizes node identity, VMID/name, observed status, IP evidence, guest-agent signal, disk stack, tags, and storage signal. Rows are grouped by node. Unknown node ids are grouped into an "Unknown" bucket only if VM inventory references a node not present in the node list.

## No Destructive Controls

Infra Explorer currently has no buttons for start, stop, reboot, reset, delete, snapshot, rollback, migrate, clone, SSH, or Ansible.

Starting a newly created VM is explicitly deferred. Create VM success is powered-off/stopped only.

## Target Identity Panel

Target DRS Advisor requires an identity/fingerprint layer that does not exist yet. Future Infra Explorer may show Gjallar VM identity, identity confidence, last observed fingerprint, classification completeness, DRS eligibility/blockers, and last migration operation.

Until those exist, Infra Explorer remains a read-only Proxmox inventory browser.
