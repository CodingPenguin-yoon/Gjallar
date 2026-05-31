# Network Architecture

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Network architecture](../../../architecture/network/overview.md), [Networks snapshot](../../../current/top-tabs/03-networks.md), [Current API V1](../../../architecture/api/current-api-v1.md).

Networks tab은 `/networks` route입니다. 기존 live inventory API를 프론트엔드에서 조합하는 read-only Network Readiness / migration pre-check visualization입니다. UI는 하나의 selected migration source, 한국어 중심 3-column target comparison row(`대상 노드`, `결과`, `네트워크 매핑`), 각 mapping row 안에 흡수된 CIDR-verified exact bridge match / CIDR remap evidence, selected-source VM impact 중심으로 구성됩니다.

## Current route and implementation

| Concern | Current implementation |
|---|---|
| Route | `/networks` |
| Component | [NetworkReadinessScreen.jsx](../../../../frontend/src/components/NetworkReadinessScreen.jsx) |
| View model | [networkReadiness.js](../../../../frontend/src/utils/networkReadiness.js) |
| Backend helper | 없음 |
| Persistence | 없음 |

## APIs used

- `GET /api/v1/nodes`
- `GET /api/v1/vms`
- `GET /api/v1/networks`

`GET /api/v1/networks`는 Proxmox `/nodes/{node}/network` row에서 관찰한 `address`, `netmask`, `prefix`, `cidr`, `gateway`, `bridge_ports`, `vlan_aware`, `mtu`를 optional evidence로 포함할 수 있습니다. CIDR은 observed address와 netmask/prefix 또는 CIDR이 포함된 address에서만 계산합니다. Gateway만 있는 row에서 CIDR을 추론하지 않습니다.

Networks tab은 Proxmox network API mutation을 호출하지 않고, API write path, YAML persistence, DB migration, DRS execution authority도 없습니다.

## Readiness view

- All-pair source-target readiness model은 compatibility를 위해 유지하지만, 화면에는 selected source에서 다른 target node로 가는 target network comparison row만 표시합니다. 별도 Evidence 컬럼은 없습니다.
- Target row status는 UI에서 `준비됨`, `검토 필요`, `차단`, `정보 부족`으로 표시합니다. `차단`은 같은 target row 안의 `bridge_id_subnet_mismatch`, 매핑 없음, 비활성 같은 차단성 evidence가 있으면 `준비됨`보다 우선합니다.
- `준비됨`은 source active bridge들이 차단/검토/정보부족 evidence 없이 CIDR-verified exact match로 확인될 때만 표시합니다. 이름만 같거나 같은 CIDR의 다른 bridge ID remap 후보가 있으면 `검토 필요`입니다.
- Source-to-target comparison은 source active bridge별 `exact`, `bridge_name_unverified`, `bridge_id_subnet_mismatch`, `remap_candidate`, `missing`, `inactive`, `unknown` status를 가지며 UI label은 `일치`, `이름만 같음`, `CIDR 불일치`, `remap 필요`, `매핑 없음`, `비활성`, `정보 부족`입니다.
- 각 mapping row 아래에 짧은 근거를 표시합니다. 예: `192.168.2.0/24 · GW 192.168.2.1`, `CIDR 근거 부족 · source: 없음 · target: 10.100.100.0/24`, `같은 CIDR 10.100.100.0/24 · bridge 이름 다름`, `source: 10.10.0.0/24 · target: 10.20.0.0/24`.
- 내부 `bridgeMatrix`, `bridgeCoverageSummary`, `subnetCoverageSummary`는 호환 테스트/diagnostic data로 유지될 수 있지만, 사용자 화면에는 global Bridge ID matrix나 독립 subnet mapping table을 표시하지 않습니다.
- Selected source가 없거나 invalid하면 정렬된 첫 node를 deterministic default로 사용합니다.
- 영향 VM은 selected source node의 VM만 포함합니다. Current `VmInventory`에 NIC bridge field가 없으므로 per-VM migration readiness는 `준비됨`이 아니라 `정보 부족` / `vm_nic_bridge_evidence_missing`입니다.
- Duplicate IP와 guest-agent evidence는 read-only evidence로 보존합니다.

## Create VM boundary

Current Create VM은 selected target node, active live bridge, explicit `bridge_id`, IP mode, explicit static fields를 사용합니다. Networks readiness, `network_id`, `server-net`는 current Create VM source of truth가 아닙니다.

## DRS boundary

DRS route authorization은 current DRS recommendation/check evidence, final pre-check, policy, approval/job, live Proxmox evidence, and operation locks를 별도로 요구합니다. Networks readiness만으로 source/target route를 authorize할 수 없습니다. CIDR/gateway match는 observed config evidence일 뿐 actual same L2/VLAN/routed network나 migration feasibility의 proof가 아닙니다. `준비됨`도 visible target row에 차단/검토 evidence 없는 CIDR-verified exact active bridge mapping이 있다는 뜻일 뿐 실행 권한이 아닙니다.
