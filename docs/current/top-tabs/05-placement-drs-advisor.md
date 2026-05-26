# Placement / DRS Advisor

평가일: 2026-05-13

검증 기준: coordinator가 backend `PYTHONPATH=backend backend/venv/bin/pytest -q backend/tests` -> 92 passed, frontend `for test_file in frontend/tests/*.mjs; do node "$test_file"; done` -> passed, `pnpm --dir frontend lint` -> passed, `pnpm --dir frontend build` -> passed를 기록했다.

## 구현 수준

현재 `/drs`는 read-only DRS Advisor Phase 1 recommendation seed다. Backend DRS read model은 구현되어 있지만 execution flow는 구현되어 있지 않다.

## 구현 API/endpoints

DRS Advisor Phase 1 backend endpoint는 다음 `/api/v1` 조회를 제공한다.

- `GET /api/v1/drs/summary`
- `GET /api/v1/drs/recommendations`
- `GET /api/v1/drs/recommendations/{recommendation_id}`
- `POST /api/v1/drs/recommendations/{recommendation_id}/check`

모든 recommendation은 `read_only=true`, `executable=false`다.

## 관련 파일

- Frontend: [frontend/src/components/DrsAdvisorScreen.jsx](../../../frontend/src/components/DrsAdvisorScreen.jsx), [frontend/src/utils/drsAdvisor.js](../../../frontend/src/utils/drsAdvisor.js), [frontend/src/services/apiV1.js](../../../frontend/src/services/apiV1.js), [frontend/src/App.jsx](../../../frontend/src/App.jsx)
- Backend: [backend/app/api/v1/router.py](../../../backend/app/api/v1/router.py), [backend/app/drs/advisor.py](../../../backend/app/drs/advisor.py), [backend/app/proxmox/inventory.py](../../../backend/app/proxmox/inventory.py), [backend/app/proxmox/models.py](../../../backend/app/proxmox/models.py)
- Tests: [frontend/tests/drsAdvisor.test.mjs](../../../frontend/tests/drsAdvisor.test.mjs), [frontend/tests/appNavigation.test.mjs](../../../frontend/tests/appNavigation.test.mjs), [backend/tests/contracts/test_api_v1_drs.py](../../../backend/tests/contracts/test_api_v1_drs.py)

## 현재 구현

`loadDrsAdvisorModel`은 DRS summary/recommendation endpoints를 읽고 backend에서 계산된 node pressure와 imbalance candidate를 표시한다. source pressure가 높고 target 여유가 있으면 candidate를 만든다.

현재 recommendation은 CPU/Memory current usage, bridge evidence, storage evidence, red risk exclusion을 사용한다. execution은 `available: false`, `readOnly: true`, `allowedActions: []`다.

화면은 review model only notice를 표시하고, migration 실행 버튼을 제공하지 않는다.

## DRS Advisor 기준 gaps

[DRS recommendation/execution 목표](../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md) 대비 backend recommendation authority가 없다. identity/fingerprint, metadata completeness, migration policy, VM mobility, route status, 15분 average/peak evidence가 없다.

Check Now, final pre-check, confirm modal, operation lock, Approve & Migrate, Proxmox live migration, UPID tracking, post-check, reconciliation이 없다. UI label도 DRS Advisor로 전환되지 않았다.

## 리스크/메모

현재 DRS recommendation은 seed일 뿐 실행 판단이 아니다. Phase 1은 identity mismatch, policy restriction, final pre-check를 authoritative하게 처리하지 않고 blocker로 표시한다.

## 다음 구현 slice

다음 slice는 identity/fingerprint/policy DB와 final pre-check contract를 추가하되, migration execution은 별도 승인/lock/UPID 흐름이 준비될 때까지 열지 않는 것이다.
