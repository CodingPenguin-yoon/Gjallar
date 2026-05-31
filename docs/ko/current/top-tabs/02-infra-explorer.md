# Infra Explorer

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Infra Explorer snapshot](../../../current/top-tabs/02-infra-explorer.md), [영어 Infra Explorer architecture](../../../architecture/infra-explorer/overview.md), [Current implemented state](../../../current/README.md).

Infra Explorer는 `/infra` route의 read-only VM/node inventory 화면입니다. 목적은 Proxmox가 현재 보고하는 VM 배치와 evidence를 운영자가 확인하게 하는 것입니다. 현재 VM row는 `/drs/policies` coverage가 있으면 DRS migration policy 상태와 guarded local policy review action도 표시하지만, DRS migration action은 제공하지 않습니다.

## 사용하는 API와 호출 위치

| API | 하는 일 | Frontend 호출 |
|---|---|---|
| `GET /api/v1/nodes` | node group과 node status | [frontend/src/components/InstanceList.jsx](../../../../frontend/src/components/InstanceList.jsx), [frontend/src/utils/infraExplorerScreen.js](../../../../frontend/src/utils/infraExplorerScreen.js) |
| `GET /api/v1/vms` | VM row, status, IP/guest-agent/storage evidence | 같은 loader/view model |
| `GET /api/v1/vms/{vmid}` | VMID 단건 detail endpoint | API client helper로 존재하지만 current screen 정상 load의 주 경로는 list data입니다. |
| `GET /api/v1/drs/policies` | VM row의 current locator에 매칭되는 DRS policy coverage 보조 조회 | 같은 loader/view model |
| `PUT /api/v1/drs/policies/{vm_identity_id}` | guarded local policy update와 audit evidence | shared policy review modal |

Backend는 [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py)의 read-only inventory endpoint를 통해 [backend/app/proxmox/inventory.py](../../../../backend/app/proxmox/inventory.py)를 사용합니다.

## 구현 방식

Frontend view model은 node id, VMID/name, observed status, IP evidence, guest-agent signal, disk stack, tags, storage signal을 정규화합니다. VM은 node별로 grouping됩니다. VM inventory가 node list에 없는 node를 참조하면 Unknown group에 넣습니다.

## 현재 하지 않는 일

Infra Explorer에는 start, stop, reboot, reset, delete, snapshot, rollback, migrate, clone, SSH, Ansible 버튼이 없습니다. 기존 VM start는 이 화면의 별도 gated action입니다. 새 VM은 Create VM의 `boot_and_verify` 선택 시에만 부팅 후 IP/cloud-init 검증까지 수행합니다.

## Target gap

DRS Advisor에는 VM identity/fingerprint, metadata completeness, operation lock, last DRS job 같은 더 깊은 패널이 필요합니다. 현재 Infra Explorer는 compact DRS migration policy 상태와 guarded local policy update만 보조로 표시하고, full identity/blocker/job context나 migration action flow는 제공하지 않습니다.
