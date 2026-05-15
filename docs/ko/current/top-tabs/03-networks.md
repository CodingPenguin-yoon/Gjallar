# Networks

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Networks snapshot](../../../current/top-tabs/03-networks.md), [영어 Network architecture](../../../architecture/network/overview.md), [Current implemented state](../../../current/README.md).

Networks는 `/networks` route의 bridge inventory와 IaC-backed NetworkPolicy 화면입니다. 목적은 운영자가 live bridge와 policy file 상태를 비교하고 policy를 저장하는 것입니다. Proxmox bridge를 직접 변경하지 않습니다.

## 사용하는 API와 호출 위치

| API | 하는 일 | Frontend 호출 |
|---|---|---|
| `GET /api/v1/networks` | live/read-only bridge inventory | Dashboard, Create VM, Placement에서도 사용 |
| `GET /api/v1/networks/policy` | live bridge + IaC policy view | [frontend/src/components/NetworkPolicyScreen.jsx](../../../../frontend/src/components/NetworkPolicyScreen.jsx) |
| `PUT /api/v1/networks/policy` | normalized policy 저장 | 같은 screen과 [frontend/src/utils/networkPolicy.js](../../../../frontend/src/utils/networkPolicy.js) |

Backend 구현은 [backend/app/network_policy.py](../../../../backend/app/network_policy.py)와 [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py)에 있습니다.

## 구현 방식

`GET /networks/policy`는 Proxmox inventory adapter에서 bridge를 읽고, IaC root 아래 `manifests/networks/network-profiles.yaml`을 읽어 policy와 observed bridge를 매칭합니다. 결과에는 registered/unregistered bridge, missing policy bridge, policy path, policy contents가 들어갑니다.

`PUT /networks/policy`는 `{ "policy": ... }` 또는 policy object를 받아 정규화하고, path가 IaC root 아래인지 확인한 뒤 YAML을 씁니다. IaC root가 Git repo이고 변경이 있으면 local commit을 시도할 수 있습니다.

## Create VM과의 경계

Create VM의 current network source of truth는 NetworkPolicy가 아닙니다. Create VM은 selected target node의 active live bridge와 explicit `bridge_id`, `static_ip`, `prefix`, `gateway`를 사용합니다. `network_id`/`networkId`는 transition compatibility로 무시되고 active output에 echo되지 않습니다.

## Target gap

DRS route feasibility에는 shared storage, HA, active task, config lock, passthrough, source/target bridge evidence 같은 별도 read-only model이 필요합니다. Networks tab policy는 그 자체로 DRS final gate가 아닙니다.
