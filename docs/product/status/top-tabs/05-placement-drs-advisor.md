# Placement / DRS Advisor

평가일: 2026-05-13

검증 기준: coordinator가 backend `PYTHONPATH=backend backend/venv/bin/pytest -q backend/tests` -> 92 passed, frontend `for test_file in frontend/tests/*.mjs; do node "$test_file"; done` -> passed, `pnpm --dir frontend lint` -> passed, `pnpm --dir frontend build` -> passed를 기록했다.

## 구현 수준

현재 `/placement`는 read-only frontend recommendation seed다. UI label도 아직 `Placement`이며, DRS Advisor backend read model이나 execution flow는 구현되어 있지 않다.

## 구현 API/endpoints

Placement 전용 backend endpoint는 없다. 화면은 다음 기존 `/api/v1` 조회를 조합한다.

- `GET /api/v1/cluster/summary`
- `GET /api/v1/nodes`
- `GET /api/v1/vms`
- `GET /api/v1/storage`
- `GET /api/v1/networks`
- `GET /api/v1/risks`
- `GET /api/v1/jobs`

`/api/v1/drs/*`는 존재하지 않는다.

## 관련 파일

- Frontend: [frontend/src/components/PlacementScreen.jsx](../../../../frontend/src/components/PlacementScreen.jsx), [frontend/src/utils/placement.js](../../../../frontend/src/utils/placement.js), [frontend/src/services/apiV1.js](../../../../frontend/src/services/apiV1.js), [frontend/src/App.jsx](../../../../frontend/src/App.jsx)
- Backend: [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py), [backend/app/proxmox/inventory.py](../../../../backend/app/proxmox/inventory.py), [backend/app/proxmox/models.py](../../../../backend/app/proxmox/models.py)
- Tests: [frontend/tests/placement.test.mjs](../../../../frontend/tests/placement.test.mjs), [frontend/tests/appNavigation.test.mjs](../../../../frontend/tests/appNavigation.test.mjs), [backend/tests/contracts/test_api_v1_inventory.py](../../../../backend/tests/contracts/test_api_v1_inventory.py)

## 현재 구현

`loadPlacementModel`은 cluster/nodes/vms/storage/networks/risks/jobs를 읽고 frontend에서 node pressure와 imbalance를 계산한다. source pressure가 높고 target 여유가 있으면 candidate를 만든다.

현재 recommendation은 CPU/Memory current usage, bridge evidence, storage evidence, red risk exclusion을 사용한다. execution은 `available: false`, `readOnly: true`, `allowedActions: []`다.

화면은 review model only notice를 표시하고, migration 실행 버튼을 제공하지 않는다.

## DRS Advisor 기준 gaps

[DRS recommendation/execution 목표](../../prd/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md) 대비 backend recommendation authority가 없다. identity/fingerprint, metadata completeness, migration policy, VM mobility, route status, 15분 average/peak evidence가 없다.

Check Now, final pre-check, confirm modal, operation lock, Approve & Migrate, Proxmox live migration, UPID tracking, post-check, reconciliation이 없다. UI label도 DRS Advisor로 전환되지 않았다.

## 리스크/메모

현재 Placement recommendation은 seed일 뿐 실행 판단이 아니다. frontend-only 계산은 stale/live evidence 재구성, identity mismatch, policy restriction, route unknown 같은 blocker를 authoritative하게 처리할 수 없다.

## 다음 구현 slice

첫 slice는 route label을 `DRS Advisor`로 바꾸되 실행 기능 없이 backend read-only recommendation contract를 추가하는 것이다. `/api/v1/drs/recommendations` 같은 target endpoint는 계약 테스트부터 만들고, Allowed/Restricted/Blocked/Unclassified/Identity Mismatch를 실행 없이 표시한다.
