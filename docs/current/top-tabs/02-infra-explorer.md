# Infra Explorer

평가일: 2026-05-15

검증 기준: 2026-05-27에 backend `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests` -> 182 passed, 33 warnings, 29 subtests passed, frontend `node --test frontend/tests/*.mjs` -> 13 passed, `pnpm --dir frontend lint` -> passed, `pnpm --dir frontend build` -> passed, `git diff --check` -> passed를 기록했다.

## 구현 수준

현재 Infra Explorer는 VM/node inventory와 VM detail evidence 화면이며, stopped non-template VM에 한해 gated Start action을 제공한다. DRS identity/policy context나 migration action flow는 없다.

## 구현 API/endpoints

- `GET /api/v1/nodes`
- `GET /api/v1/vms`
- `GET /api/v1/vms/{vmid}`
- `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start`
- 보조 조회: `GET /api/v1/storage`, `GET /api/v1/networks`

## 관련 파일

- Frontend: [frontend/src/components/InstanceList.jsx](../../../frontend/src/components/InstanceList.jsx), [frontend/src/utils/infraExplorerScreen.js](../../../frontend/src/utils/infraExplorerScreen.js), [frontend/src/utils/apiV1ViewModels.js](../../../frontend/src/utils/apiV1ViewModels.js), [frontend/src/services/apiV1.js](../../../frontend/src/services/apiV1.js)
- Backend: [backend/app/api/v1/router.py](../../../backend/app/api/v1/router.py), [backend/app/proxmox/inventory.py](../../../backend/app/proxmox/inventory.py), [backend/app/proxmox/models.py](../../../backend/app/proxmox/models.py), [backend/app/proxmox/client.py](../../../backend/app/proxmox/client.py), [backend/app/vm_actions/start.py](../../../backend/app/vm_actions/start.py)
- Tests: [frontend/tests/infraExplorerScreen.test.mjs](../../../frontend/tests/infraExplorerScreen.test.mjs), [frontend/tests/apiV1Client.test.mjs](../../../frontend/tests/apiV1Client.test.mjs), [frontend/tests/apiV1ViewModels.test.mjs](../../../frontend/tests/apiV1ViewModels.test.mjs), [backend/tests/contracts/test_api_v1_inventory.py](../../../backend/tests/contracts/test_api_v1_inventory.py), [backend/tests/contracts/test_api_v1_vm_actions.py](../../../backend/tests/contracts/test_api_v1_vm_actions.py), [backend/tests/proxmox/test_inventory_adapter.py](../../../backend/tests/proxmox/test_inventory_adapter.py)

## 현재 구현

VM과 node inventory를 read-only로 보여주고, VMID 기반 detail을 조회한다. VM/node 상태, node 배치, IP/guest-agent 일부 evidence, storage/network 관찰값을 운영자가 확인할 수 있다.

Start action은 Create VM과 분리되어 있다. UI는 VM name, node, VMID, current status를 확인시키고 acknowledgement checkbox를 요구한 뒤 `/jobs?job=<job_id>`로 이동한다. Backend는 fresh inventory에서 `(node_id, vmid)` exact match를 확인하고 missing/moved/template/non-stopped VM을 차단한다.

성공/실패 모두 `vm_start` job status를 기록한다. 성공은 Proxmox start UPID, task poll `exitstatus=OK`, observed-after `running`, `vm_start_observed_after.json` artifact가 있어야 completed가 된다.

legacy destructive lifecycle control은 active surface가 아니다. stop/reset/shutdown/reboot/delete/terminate는 노출하지 않는다.

## DRS Advisor 기준 gaps

[DRS Advisor data/identity 목표](../../product/drs-advisor/03_DATA_DB_AND_IDENTITY.md) 대비 VM owner, profile, metadata completeness, migration policy, sensitivity, identity assertion, fingerprint match/mismatch 상태가 없다.

최근 DRS jobs, operation lock, active Proxmox task, HA 상태, route feasibility, final pre-check 결과와 연결되지 않는다. VM detail에서 Approve & Migrate나 Check Now 흐름도 없다.

## 리스크/메모

Infra Explorer의 live inventory는 Proxmox current state 확인에는 적합하지만, metadata 자동 재연결 기준으로 쓰면 안 된다. DRS PRD는 fingerprint match 기반 재연결과 same VMID/different fingerprint 차단을 요구한다.

## 다음 구현 slice

VM detail에 read-only DRS identity panel을 먼저 추가한다. backend에는 identity/fingerprint read model과 metadata completeness status를 만들고, action 없이 `confirmed`, `unclassified`, `identity_mismatch`를 표시하는 데서 시작한다.
