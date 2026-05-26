# Placement / DRS Advisor Overview

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Placement/DRS overview](../../../architecture/placement-drs-advisor/overview.md), [Placement snapshot](../../../current/top-tabs/05-placement-drs-advisor.md), [DRS product docs](../../../product/drs-advisor/README.md).

현재 `/drs` route는 read-only DRS Advisor Phase 1 screen입니다. Backend DRS recommendation read model은 구현되어 있지만 migration 실행은 없습니다.

## Current route and implementation

| Concern | Current implementation |
|---|---|
| Route | `/drs` |
| Component | [DrsAdvisorScreen.jsx](../../../../frontend/src/components/DrsAdvisorScreen.jsx) |
| View model | [drsAdvisor.js](../../../../frontend/src/utils/drsAdvisor.js) |
| Backend DRS routes | `GET /api/v1/drs/summary`, `GET /api/v1/drs/recommendations`, `GET /api/v1/drs/recommendations/{recommendation_id}`, `POST /api/v1/drs/recommendations/{recommendation_id}/check` |
| Mutation controls | None |

## APIs used now

`loadDrsAdvisorModel()`은 `GET /api/v1/drs/summary`와 `GET /api/v1/drs/recommendations`를 호출합니다. Detail은 `GET /api/v1/drs/recommendations/{recommendation_id}`, reference check는 `POST /api/v1/drs/recommendations/{recommendation_id}/check`를 사용합니다.

## Current read model

Backend는 current CPU/Memory threshold와 source-target delta로 candidate를 만들고, running non-template VM만 대상으로 삼으며 red-risk VM은 제외합니다. Phase 1 blocker에는 `identity_unknown`, `metadata_missing`, `policy_unknown`, `final_precheck_not_run`, route/local storage/passthrough/target pressure blocker가 포함될 수 있습니다. 모든 recommendation은 `executable=false`입니다.

## Target direction

Target DRS Advisor는 backend-owned recommendation/execution system입니다. Phase 1 이후 DB-backed identity/fingerprint/policy, exact evidence approval, final pre-check, operation locks, migration UPID tracking, post-check, reconciliation, DRS jobs, DRS blockers integration이 필요합니다.
