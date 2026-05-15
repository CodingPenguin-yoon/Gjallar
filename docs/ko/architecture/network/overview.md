# Network Architecture

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Network architecture](../../../architecture/network/overview.md), [Networks snapshot](../../../current/top-tabs/03-networks.md), [Current API V1](../../../architecture/api/current-api-v1.md).

Networks tab은 `/networks` route입니다. Live Proxmox bridge inventory와 IaC-backed network policy file을 합쳐 보여주고, policy file만 저장할 수 있습니다.

## Current route and implementation

| Concern | Current implementation |
|---|---|
| Route | `/networks` |
| Component | [NetworkPolicyScreen.jsx](../../../../frontend/src/components/NetworkPolicyScreen.jsx) |
| View model | [networkPolicy.js](../../../../frontend/src/utils/networkPolicy.js) |
| Backend helper | [backend/app/network_policy.py](../../../../backend/app/network_policy.py) |
| Policy path | IaC root `manifests/networks/network-profiles.yaml` |

## APIs used

`GET /api/v1/networks/policy`는 live bridge와 policy view를 반환합니다. `PUT /api/v1/networks/policy`는 normalized policy를 IaC root 아래에 씁니다. Proxmox network API mutation은 하지 않습니다.

## Create VM boundary

Current Create VM은 selected target node, active live bridge, explicit `bridge_id`, IP mode, explicit static fields를 사용합니다. NetworkPolicy, `network_id`, `server-net`는 current Create VM source of truth가 아닙니다.

## DRS boundary

DRS route feasibility는 future read-only model이 필요합니다. Network tab policy만으로 source/target route를 authorize할 수 없습니다.
