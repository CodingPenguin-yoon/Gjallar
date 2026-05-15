# Placement / DRS Advisor Overview

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Placement/DRS overview](../../../architecture/placement-drs-advisor/overview.md), [Placement snapshot](../../../current/top-tabs/05-placement-drs-advisor.md), [DRS product docs](../../../product/drs-advisor/README.md).

현재 `/placement` route는 read-only Placement screen입니다. Backend DRS Advisor 구현이 아닙니다.

## Current route and implementation

| Concern | Current implementation |
|---|---|
| Route | `/placement` |
| Component | [PlacementScreen.jsx](../../../../frontend/src/components/PlacementScreen.jsx) |
| View model | [placement.js](../../../../frontend/src/utils/placement.js) |
| Backend DRS routes | None |
| Mutation controls | None |

## APIs used now

`loadPlacementModel()`은 `cluster/summary`, `nodes`, `vms`, `storage`, `networks`, `risks`, `jobs`를 호출합니다. `GET /api/v1/drs/recommendations`는 현재 없습니다.

## Current read model

Frontend는 current node pressure와 imbalance를 계산하고, source가 hot이고 target이 cooler일 때 candidate를 만듭니다. Bridge/storage evidence와 red risk exclusion을 사용하지만, 이 결과는 execution contract가 아닙니다.

## Target direction

Target DRS Advisor는 backend-owned recommendation/execution system입니다. `/api/v1/drs/*`, DB-backed identity/fingerprint/policy, exact evidence approval, final pre-check, operation locks, migration UPID tracking, post-check, reconciliation, DRS jobs, DRS blockers가 필요합니다.
