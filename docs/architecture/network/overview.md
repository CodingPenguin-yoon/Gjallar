# Network Architecture

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Networks](../../current/top-tabs/03-networks.md).

The Networks tab is the `/networks` route. It combines live Proxmox bridge inventory with an IaC-backed network policy file. It does not mutate Proxmox network configuration.

## Current Route And Component

| Concern | Current implementation |
|---|---|
| Route | `/networks` |
| Component | `frontend/src/components/NetworkPolicyScreen.jsx` |
| View model | `frontend/src/utils/networkPolicy.js` |
| Backend helper | `backend/app/network_policy.py` |
| Policy path | `manifests/networks/network-profiles.yaml` under the configured IaC root |

## APIs Used

| API | Purpose | Side effect |
|---|---|---|
| `GET /api/v1/networks/policy` | Build live bridge plus policy view. | None. |
| `PUT /api/v1/networks/policy` | Persist normalized policy. | Writes policy file and may create a local IaC Git commit. |

The Networks tab does not call Proxmox mutation APIs.

## Live Bridge Policy View

`GET /api/v1/networks/policy` performs:

1. Read live bridge inventory from the inventory adapter.
2. Load `manifests/networks/network-profiles.yaml` from IaC root.
3. Normalize the policy into a `NetworkPolicySet`.
4. Match policy nodes to observed `(node_id, bridge_id)` pairs.
5. Return observed bridges, registration state, missing policy bridges, policy path, and policy contents.

## PUT Network Policy Behavior

`PUT /api/v1/networks/policy` accepts either `{ "policy": ... }` or a policy object directly. The backend normalizes the policy, guards the path under IaC root, writes YAML, and commits the file if the IaC root is a Git repo and the file changed.

Side effects are limited to the IaC file and local Git commit. The route never creates, deletes, renames, or reconfigures Proxmox bridges.

## Create VM Boundary

Current Create VM uses:

- selected target node
- active live bridge on that node
- explicit `bridge_id`
- `ip_mode`
- explicit `static_ip`, `prefix`, and `gateway` for static mode

Current Create VM does not use `NetworkPolicy`, `network_id`, or `server-net` as its source of truth. Incoming `network_id`/`networkId` is transition-ignored by the draft builder and is not echoed in active draft, plan, review, manifest, or job output.

Network policy can become future advisory or validation evidence, but it is not a current Create VM gate.

## Non-Goals

- No Proxmox bridge creation.
- No Proxmox bridge deletion.
- No Proxmox network config edit.
- No current DRS route/policy enforcement.
- No Create VM gateway inference from policy or `.1` convention.
