# Infra Explorer

평가일: 2026-05-13

검증 기준: coordinator가 backend `PYTHONPATH=backend backend/venv/bin/pytest -q backend/tests` -> 92 passed, frontend `for test_file in frontend/tests/*.mjs; do node "$test_file"; done` -> passed, `pnpm --dir frontend lint` -> passed, `pnpm --dir frontend build` -> passed를 기록했다.

## 구현 수준

현재 Infra Explorer는 read-only VM/node inventory와 VM detail evidence 화면이다. Proxmox inventory를 탐색하는 baseline은 구현되어 있지만, DRS identity/policy context나 action flow는 없다.

## 구현 API/endpoints

- `GET /api/v1/nodes`
- `GET /api/v1/vms`
- `GET /api/v1/vms/{vmid}`
- 보조 조회: `GET /api/v1/storage`, `GET /api/v1/networks`

## 관련 파일

- Frontend: [frontend/src/components/InstanceList.jsx](../../../../frontend/src/components/InstanceList.jsx), [frontend/src/utils/infraExplorerScreen.js](../../../../frontend/src/utils/infraExplorerScreen.js), [frontend/src/utils/apiV1ViewModels.js](../../../../frontend/src/utils/apiV1ViewModels.js), [frontend/src/services/apiV1.js](../../../../frontend/src/services/apiV1.js)
- Backend: [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py), [backend/app/proxmox/inventory.py](../../../../backend/app/proxmox/inventory.py), [backend/app/proxmox/models.py](../../../../backend/app/proxmox/models.py)
- Tests: [frontend/tests/infraExplorerScreen.test.mjs](../../../../frontend/tests/infraExplorerScreen.test.mjs), [frontend/tests/apiV1Client.test.mjs](../../../../frontend/tests/apiV1Client.test.mjs), [backend/tests/contracts/test_api_v1_inventory.py](../../../../backend/tests/contracts/test_api_v1_inventory.py), [backend/tests/proxmox/test_inventory_adapter.py](../../../../backend/tests/proxmox/test_inventory_adapter.py)

## 현재 구현

VM과 node inventory를 read-only로 보여주고, VMID 기반 detail을 조회한다. VM/node 상태, node 배치, IP/guest-agent 일부 evidence, storage/network 관찰값을 운영자가 확인할 수 있다.

legacy destructive lifecycle control은 active surface가 아니다. 현재 화면은 inventory 확인과 detail drill-down 중심이다.

## DRS Advisor 기준 gaps

[DRS Advisor data/identity 목표](../../prd/drs-advisor/03_DATA_DB_AND_IDENTITY.md) 대비 VM owner, profile, metadata completeness, migration policy, sensitivity, identity assertion, fingerprint match/mismatch 상태가 없다.

최근 DRS jobs, operation lock, active Proxmox task, HA 상태, route feasibility, final pre-check 결과와 연결되지 않는다. VM detail에서 Approve & Migrate나 Check Now 흐름도 없다.

## 리스크/메모

Infra Explorer의 live inventory는 Proxmox current state 확인에는 적합하지만, metadata 자동 재연결 기준으로 쓰면 안 된다. DRS PRD는 fingerprint match 기반 재연결과 same VMID/different fingerprint 차단을 요구한다.

## 다음 구현 slice

VM detail에 read-only DRS identity panel을 먼저 추가한다. backend에는 identity/fingerprint read model과 metadata completeness status를 만들고, action 없이 `confirmed`, `unclassified`, `identity_mismatch`를 표시하는 데서 시작한다.
