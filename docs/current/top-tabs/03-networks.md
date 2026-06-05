# VM Instances / Network Readiness

평가일: 2026-05-17

검증 기준: 이 문서는 현재 Networks 탭 구현 상태를 설명한다. 최신 통합 검증 baseline은 [current implemented state](../README.md)에 기록된 결과를 따른다.

## 구현 수준

현재 Network readiness는 canonical `/instances/networks` route의 read-only migration pre-check visualization 화면이며, legacy `/networks` deep link도 같은 화면을 렌더링한다. 프론트엔드가 기존 live inventory API를 조합해 migration source selector, selected-source target network comparison, CIDR-verified exact bridge match / CIDR remap evidence, selected-source VM impact를 보여준다. Target comparison UI는 한국어 중심의 3-column 표(`대상 노드`, `결과`, `네트워크 매핑`)로 단순화되어 있으며 별도 `Evidence` 컬럼은 없다.

이 화면은 Proxmox network를 변경하지 않고, API write path가 없으며, YAML persistence나 DB migration을 수행하지 않는다. 표시되는 readiness는 pre-check evidence일 뿐 DRS 실행 권한이 아니다.

## 구현 API/endpoints

- `GET /api/v1/nodes`
- `GET /api/v1/vms`
- `GET /api/v1/networks`

## 관련 파일

- Frontend: [frontend/src/components/NetworkReadinessScreen.jsx](../../../frontend/src/components/NetworkReadinessScreen.jsx), [frontend/src/utils/networkReadiness.js](../../../frontend/src/utils/networkReadiness.js), [frontend/src/services/apiV1.js](../../../frontend/src/services/apiV1.js)
- Backend: [backend/app/api/v1/router.py](../../../backend/app/api/v1/router.py), [backend/app/proxmox/inventory.py](../../../backend/app/proxmox/inventory.py)
- Tests: [frontend/tests/networkPolicy.test.mjs](../../../frontend/tests/networkPolicy.test.mjs), [backend/tests/contracts/test_api_v1_shape.py](../../../backend/tests/contracts/test_api_v1_shape.py), [backend/tests/contracts/test_api_v1_inventory.py](../../../backend/tests/contracts/test_api_v1_inventory.py)

## 현재 구현

`GET /nodes`, `GET /vms`, `GET /networks`는 live/read-only inventory를 반환한다. Network readiness screen은 이 세 응답을 프론트엔드에서 조합한다. Network inventory는 Proxmox bridge row에서 관찰한 `address`, `netmask`, `prefix`, `cidr`, `gateway`, `bridge_ports`, `vlan_aware`, `mtu`를 optional evidence로 포함할 수 있다.

- Migration source: source node를 하나 선택한다. source가 없거나 invalid하면 정렬된 첫 node가 deterministic default가 된다.
- Target network comparison: 선택한 source에서 다른 node로 가는 target row만 표시한다. Self-pair와 전체 source-target pair grid는 표시하지 않는다. Summary card는 `대상 노드`, `준비됨`, `검토 필요`, `차단`, `영향 VM` 중심이다. Target row status는 UI에서 `준비됨`, `검토 필요`, `차단`, `정보 부족`으로 표시한다. `차단`은 같은 target row 안의 `bridge_id_subnet_mismatch`, 매핑 없음, 비활성 같은 차단성 evidence가 있으면 `준비됨`보다 우선한다. `검토 필요`는 이름만 같거나 같은 CIDR의 다른 bridge ID remap 후보만 있는 경우다. `준비됨`은 source active bridge들이 차단/검토/정보부족 evidence 없이 CIDR-verified exact match로 확인될 때만 표시한다.
- 네트워크 매핑: 각 target row 안에서 source active bridge별 mapping row를 표시한다. Mapping status는 `일치`, `이름만 같음`, `remap 필요`, `CIDR 불일치`, `매핑 없음`, `비활성`, `정보 부족`으로 표시한다. 별도 Evidence 컬럼은 없고, 각 mapping row 아래에 `192.168.2.0/24 · GW 192.168.2.1`, `CIDR 근거 부족 · source: 없음 · target: 10.100.100.0/24`, `같은 CIDR 10.100.100.0/24 · bridge 이름 다름`, `source: 10.10.0.0/24 · target: 10.20.0.0/24`처럼 짧은 근거를 붙인다.
- Compatibility evidence: 내부 view model의 `bridgeMatrix`, `bridgeCoverageSummary`, `subnetCoverageSummary`는 호환 테스트/diagnostic data로 유지될 수 있지만, 사용자 화면에는 global Bridge ID matrix나 독립 subnet mapping table을 표시하지 않는다.
- 영향 VM: 선택한 source node의 VM만 표시한다. 현재 `VmInventory`에 NIC bridge field가 없으므로 per-VM migration readiness는 `준비됨`으로 표시하지 않고 `정보 부족` warning과 `vm_nic_bridge_evidence_missing` reason을 유지한다. 관찰된 IP/guest-agent evidence와 duplicate IP warning은 함께 보여준다.
- Duplicate IP warning은 `VmInventory.ip_evidence`의 structured evidence 중 `scope=primary` 성격이고 `duplicate_warning_eligible=true`인 항목만 사용한다. `docker0`, `br-*`, `veth*`, `cni*`, `flannel*`, `cali*`, `virbr*` 같은 guest-internal bridge/container interface 관측값은 evidence로 보존하고 IP 목록에는 표시하지만 duplicate warning 계산에서는 제외한다.

## Create VM target gap

Target Create VM networking은 Network readiness screen을 source of truth로 사용하지 않는다. Create wizard는 live bridge inventory를 로드하고, backend preflight는 명시적 `bridge_id`가 target node에서 active인지 확인한다. Static mode는 `static_ip`, `prefix`, `gateway`를 명시적으로 요구하고, native create는 static IP에서 `.1` gateway 또는 `/24` prefix를 추론하지 않는다.

## DRS Advisor 기준 gaps

[DRS recommendation/route 목표](../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md) 대비 route feasibility 판단에 필요한 shared storage 접근성, HA 상태, active task, config lock, passthrough, final pre-check, approval, operation lock, migration execution이 없다.

## 리스크/메모

Network readiness는 inventory evidence visualization이다. `준비됨`은 CIDR-verified exact active bridge match가 차단/검토 evidence 없이 관찰되었다는 뜻이며, migration 실행 가능이나 DRS approval을 의미하지 않는다. CIDR/gateway match는 observed config evidence일 뿐 actual same L2/VLAN/routed network나 migration feasibility의 proof가 아니다. `검토 필요`는 bridge name only 또는 CIDR remap evidence처럼 사람이 확인해야 하는 상태이고, `정보 부족`은 evidence가 부족하다는 뜻이며 execution authority가 아니다.

## 다음 구현 slice

DRS용 route evidence가 필요해지면 별도 read-only backend model을 추가한다. 이 slice에서는 backend readiness endpoint, YAML persistence, DB migration, Proxmox network mutation을 추가하지 않는다.
