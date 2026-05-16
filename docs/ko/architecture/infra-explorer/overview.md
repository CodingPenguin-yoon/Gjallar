# Infra Explorer Architecture

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Infra Explorer architecture](../../../architecture/infra-explorer/overview.md), [Infra Explorer snapshot](../../../current/top-tabs/02-infra-explorer.md), [Current implemented state](../../../current/README.md).

Infra Explorer는 `/infra` route의 VM/node inventory view이며, stopped non-template VM에 한해 gated Start action을 제공합니다. 목적은 Proxmox current inventory evidence를 operator가 탐색하고, 명시적으로 확인한 VM만 시작하게 하는 것입니다.

## Current route and implementation

| Concern | Current implementation |
|---|---|
| Route | `/infra` |
| Component | [InstanceList.jsx](../../../../frontend/src/components/InstanceList.jsx) |
| Loader | [infraExplorerScreen.js](../../../../frontend/src/utils/infraExplorerScreen.js) |
| Shared view model | [apiV1ViewModels.js](../../../../frontend/src/utils/apiV1ViewModels.js) |
| Mutation controls | Start only for stopped non-template VMs |

## APIs used

Current screen은 `GET /api/v1/nodes`와 `GET /api/v1/vms`를 사용합니다. Backend에는 `GET /api/v1/vms/{vmid}`도 있지만 current screen normal load의 primary path는 list payload입니다. Start action은 `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start`를 사용합니다.

## Current detail boundary

View model은 node identity, VMID/name, observed status, IP evidence, guest-agent signal, disk stack, tags, storage signal을 normalize합니다. 이 정보는 운영 관찰용이며 DRS identity/policy authority가 아닙니다.

## No destructive controls

현재 stop, reboot, reset, delete, snapshot, rollback, migrate, clone, SSH, Ansible control이 없습니다. Start는 stopped non-template VM row에서만 노출되며 acknowledgement, idempotency key, fresh inventory precheck, Proxmox task polling, observed-after running evidence를 요구합니다. Create VM success는 자동 start하지 않습니다.

## Target identity panel

DRS target에서는 Gjallar VM identity, identity confidence, fingerprint match/mismatch, metadata completeness, DRS eligibility/blockers, last migration operation이 필요합니다. Current implementation에는 없습니다.
