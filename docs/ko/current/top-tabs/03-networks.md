# VM Instances / Network Readiness

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Network readiness snapshot](../../../current/top-tabs/03-networks.md), [영어 Network architecture](../../../architecture/network/overview.md), [Current implemented state](../../../current/README.md).

Network readiness는 canonical `/instances/networks` route의 read-only migration pre-check visualization이며 legacy `/networks` deep link도 같은 화면을 렌더링합니다. 기존 live inventory API를 프론트엔드에서 조합해 migration source selector, selected-source target network comparison, CIDR-verified exact bridge match / CIDR remap evidence, selected-source VM impact를 보여줍니다. Target comparison UI는 한국어 중심 3-column 표(`대상 노드`, `결과`, `네트워크 매핑`)이며 별도 `Evidence` 컬럼은 없습니다.

Proxmox network mutation, API write path, YAML persistence, DB migration, DRS execution authority는 없습니다.

## 사용하는 API와 호출 위치

| API | 하는 일 | Frontend 호출 |
|---|---|---|
| `GET /api/v1/nodes` | node inventory와 embedded network evidence | Network readiness, Dashboard, Create VM, Placement |
| `GET /api/v1/vms` | VM IP와 guest-agent evidence | Network readiness, Dashboard, VM Instances, Placement |
| `GET /api/v1/networks` | live/read-only bridge inventory와 optional observed bridge config evidence | Network readiness, Dashboard, Create VM, Placement |

Frontend 구현은 [NetworkReadinessScreen.jsx](../../../../frontend/src/components/NetworkReadinessScreen.jsx)와 [networkReadiness.js](../../../../frontend/src/utils/networkReadiness.js)에 있습니다.

## 구현 방식

- Migration source: source node를 하나 선택합니다. source가 없거나 invalid하면 정렬된 첫 node를 deterministic default로 사용합니다.
- Target network comparison: 선택한 source에서 다른 node로 가는 target row만 표시합니다. Self-pair와 전체 source-target pair grid는 표시하지 않습니다. Summary card는 `대상 노드`, `준비됨`, `검토 필요`, `차단`, `영향 VM` 중심입니다. Target row status는 UI에서 `준비됨`, `검토 필요`, `차단`, `정보 부족`으로 표시합니다. `차단`은 같은 target row 안의 `bridge_id_subnet_mismatch`, 매핑 없음, 비활성 같은 차단성 evidence가 있으면 `준비됨`보다 우선합니다. `검토 필요`는 이름만 같거나 같은 CIDR의 다른 bridge ID remap 후보만 있는 경우입니다. `준비됨`은 source active bridge들이 차단/검토/정보부족 evidence 없이 CIDR-verified exact match로 확인될 때만 표시합니다.
- 네트워크 매핑: 각 target row 안에서 source active bridge별 mapping row를 표시합니다. Mapping status는 `일치`, `이름만 같음`, `remap 필요`, `CIDR 불일치`, `매핑 없음`, `비활성`, `정보 부족`으로 표시합니다. 별도 Evidence 컬럼은 없고, 각 mapping row 아래에 `192.168.2.0/24 · GW 192.168.2.1`, `CIDR 근거 부족 · source: 없음 · target: 10.100.100.0/24`, `같은 CIDR 10.100.100.0/24 · bridge 이름 다름`, `source: 10.10.0.0/24 · target: 10.20.0.0/24`처럼 짧은 근거를 붙입니다.
- Compatibility evidence: 내부 view model의 `bridgeMatrix`, `bridgeCoverageSummary`, `subnetCoverageSummary`는 호환 테스트/diagnostic data로 유지될 수 있지만, 사용자 화면에는 global Bridge ID matrix나 독립 subnet mapping table을 표시하지 않습니다.
- 영향 VM: 선택한 source node의 VM만 표시합니다. Current `VmInventory`에 NIC bridge field가 없으므로 per-VM migration readiness는 `준비됨`으로 표시하지 않고 `정보 부족`과 `vm_nic_bridge_evidence_missing` reason을 유지합니다.
- 관찰된 IP, guest-agent evidence, duplicate IP warning은 함께 보여줍니다.

`NetworkInventory`는 `address`, `netmask`, `prefix`, `cidr`, `gateway`, `bridge_ports`, `vlan_aware`, `mtu`를 optional observed bridge config evidence로 포함할 수 있습니다. CIDR은 observed address와 netmask/prefix 또는 CIDR이 포함된 address에서만 계산합니다. Gateway만 있는 row에서 CIDR을 추론하지 않습니다.

## Create VM과의 경계

Create VM의 current network source of truth는 Network readiness가 아닙니다. Create VM은 selected target node의 active live bridge와 explicit `bridge_id`, `static_ip`, `prefix`, `gateway`를 사용합니다. `network_id`/`networkId`는 transition compatibility로 무시되고 active output에 echo되지 않습니다.

## Target gap

DRS route feasibility에는 shared storage, HA, active task, config lock, passthrough, final pre-check, approval, operation lock, migration execution이 별도로 필요합니다. Network readiness는 pre-check evidence이며 final gate가 아닙니다. `준비됨`은 CIDR-verified exact active bridge match가 차단/검토 evidence 없이 관찰되었다는 뜻입니다. `검토 필요`는 bridge name only 또는 CIDR remap evidence처럼 사람이 확인해야 하는 상태입니다. CIDR/gateway match는 observed config evidence일 뿐 actual same L2/VLAN/routed network나 migration feasibility의 proof가 아닙니다.
