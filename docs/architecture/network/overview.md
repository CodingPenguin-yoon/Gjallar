# Network Architecture

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Networks](../../current/top-tabs/03-networks.md).

The Networks tab is the `/networks` route. It is a read-only Network Readiness / migration pre-check visualization composed in the frontend from existing live inventory APIs. The UI is organized around one selected migration source, simplified three-column Korean target comparison rows (`대상 노드`, `결과`, `네트워크 매핑`), CIDR-verified exact bridge match / CIDR remap evidence folded into each mapping row, and VM impact on the selected source. It does not mutate Proxmox network configuration, write configuration, persist YAML, migrate data to DB, or grant DRS execution authority.

## Current Route And Component

| Concern | Current implementation |
|---|---|
| Route | `/networks` |
| Component | `frontend/src/components/NetworkReadinessScreen.jsx` |
| View model | `frontend/src/utils/networkReadiness.js` |
| Backend helper | None for readiness in this slice |
| Persistence | None |

## APIs Used

| API | Purpose | Side effect |
|---|---|---|
| `GET /api/v1/nodes` | Node inventory and embedded network evidence. | None. |
| `GET /api/v1/vms` | VM inventory, IP evidence, and guest-agent evidence. | None. |
| `GET /api/v1/networks` | Bridge inventory by node. | None. |

`GET /api/v1/networks` is additive and may include observed bridge config evidence from Proxmox network rows: `address`, `netmask`, `prefix`, `cidr`, `gateway`, `bridge_ports`, `vlan_aware`, and `mtu`. CIDR is derived only from an observed address plus netmask/prefix, or from an address that already includes CIDR. Gateway-only rows do not infer CIDR.

The Networks tab does not call Proxmox mutation APIs.

## Readiness Model

The frontend readiness model performs:

1. Read nodes, VMs, and networks through existing `/api/v1` inventory endpoints.
2. Normalize bridge inventory from `/networks` plus embedded node network evidence without letting sparse rows erase richer CIDR/gateway evidence.
3. Build bridge/subnet coverage summaries for compatibility and diagnostics. The user-facing screen does not show a global Bridge ID matrix or standalone subnet mapping table.
4. Build all-pair source-target node pre-check evidence from active bridge inventory for compatibility, then derive the visible selected-source target network comparison table. Row labels are Korean in the UI:
   - `준비됨`: every active source bridge in the target row is covered by CIDR-verified exact mapping, with no blocked, name-only, remap, or unknown evidence.
   - `검토 필요`: the row has only review-grade evidence such as same bridge name with missing/partial/unverified CIDR evidence, or same-CIDR/different-bridge-ID remap candidates.
   - `차단`: same-bridge-ID CIDR mismatch, missing target mapping, or inactive target bridge evidence exists. This takes priority over any exact mapping in the same target row.
   - `정보 부족`: required inventory evidence is missing.
5. Build source-to-target comparison rows for each active source bridge. Mapping labels are Korean in the UI: `일치`, `이름만 같음`, `remap 필요`, `CIDR 불일치`, `매핑 없음`, `비활성`, or `정보 부족`.
6. Fold observed config evidence into each mapping row instead of rendering a separate Evidence column. Examples: `192.168.2.0/24 · GW 192.168.2.1`, `CIDR 근거 부족 · source: 없음 · target: 10.100.100.0/24`, `같은 CIDR 10.100.100.0/24 · bridge 이름 다름`, and `source: 10.10.0.0/24 · target: 10.20.0.0/24`.
7. Attach source-target subnet overlap evidence when both sides have active bridges with the same CIDR but different bridge IDs and the same-CIDR active bridge ID sets are not identical. This is shown only as `remap 필요` and does not become `준비됨`. For example, source `vmbr2 10.100.100.0/24` to target `vmbr1 10.100.100.0/24` remains `검토 필요` with remap evidence.
8. Default the selected source deterministically to the first sorted node when the requested source is missing or invalid. The visible target table excludes self-pairs and does not show reverse/all pairs outside the selected source.
9. Build selected-source VM impact rows as `정보 부족` with reason `vm_nic_bridge_evidence_missing`, because current `VmInventory` does not include a NIC bridge field. Per-VM migration readiness is not marked `준비됨` until NIC bridge evidence exists.
10. Show observed IP and guest-agent evidence. When structured `VmInventory.ip_evidence` is present, duplicate IP warnings use only primary-eligible evidence with `duplicate_warning_eligible=true`.

CIDR/gateway match is observed config evidence only. It is not proof of the actual same L2 segment, VLAN membership, routed network, or migration feasibility. `준비됨` therefore means only that CIDR-verified exact active bridge mappings exist without blocked/review evidence in the visible target row; it is not execution authority.

Guest-internal bridge/container observations such as `docker0`, `br-*`, `veth*`, `cni*`, `flannel*`, `cali*`, and `virbr*` are retained as evidence and displayed as observed IPs, but they are excluded from duplicate IP warnings. The `br-*` internal rule does not classify `vmbr*` names as internal.

There is no network readiness backend endpoint yet. There is no API write path for Networks.

## Create VM Boundary

Current Create VM uses:

- selected target node
- active live bridge on that node
- explicit `bridge_id`
- `ip_mode`
- explicit `static_ip`, `prefix`, and `gateway` for static mode

Current Create VM does not use Networks readiness, `network_id`, or `server-net` as its source of truth. Incoming `network_id`/`networkId` is transition-ignored by the draft builder and is not echoed in active draft, plan, review, manifest, or job output.

## Non-Goals

- No Proxmox bridge creation.
- No Proxmox bridge deletion.
- No Proxmox network config edit.
- No current DRS route enforcement or execution authority.
- No Create VM gateway inference from policy or `.1` convention.
- No YAML persistence or DB migration for Networks in this slice.
