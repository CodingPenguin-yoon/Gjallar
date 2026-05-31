# Placement / DRS Advisor Overview

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Placement/DRS overview](../../../architecture/placement-drs-advisor/overview.md), [Placement snapshot](../../../current/top-tabs/05-placement-drs-advisor.md), [DRS product docs](../../../product/drs-advisor/README.md).

현재 `/drs` route는 DRS Advisor recommendation/check, manual VM policy configuration, local approval packet/job intent creation screen입니다. Frontend에는 live execute/corrective reconcile controls가 없지만, backend에는 identity/policy evidence, operation locks, local approval/job substrate, narrow operator-only execute route, UPID/task tracking, verified post-check, read-only reconcile preview가 있습니다.

## Current route and implementation

| Concern | Current implementation |
|---|---|
| Route | `/drs` |
| Component | [DrsAdvisorScreen.jsx](../../../../frontend/src/components/DrsAdvisorScreen.jsx) |
| View model | [drsAdvisor.js](../../../../frontend/src/utils/drsAdvisor.js) |
| Backend DRS routes | `GET /api/v1/drs/summary`, `GET /api/v1/drs/recommendations`, `GET /api/v1/drs/recommendations/{recommendation_id}`, `POST /api/v1/drs/recommendations/{recommendation_id}/check`, `GET/PUT /api/v1/drs/policies*`, `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets`, `POST /api/v1/drs/migration-jobs/{job_id}/execute`, `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview` |
| Mutation controls | Local VM policy update and local approval packet/job intent creation only. No live execute or corrective reconcile UI. |

## APIs used now

`loadDrsAdvisorModel()`은 `GET /api/v1/drs/summary`와 `GET /api/v1/drs/recommendations`를 호출합니다. Detail은 `GET /api/v1/drs/recommendations/{recommendation_id}`, reference check는 `POST /api/v1/drs/recommendations/{recommendation_id}/check`를 사용합니다. Policy coverage/update는 `GET/PUT /api/v1/drs/policies*`, local approval packet creation은 `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets`를 사용합니다.

## Current read model

Backend는 current CPU/Memory threshold와 source-target delta로 candidate를 만들고, running non-template VM만 대상으로 삼으며 red-risk VM은 제외합니다. Blocker에는 identity/policy/final-check, route/local storage/passthrough/target pressure blocker가 포함될 수 있습니다. 모든 recommendation/check result는 `executable=false`, `allowed_actions=[]`입니다.

## Target direction

남은 target gap은 broad live execution UI, corrective reconcile UI, richer policy rule/full metadata editor, corrective mutation, background automation, automatic DRS, live DRS smoke, recommendation-level migrate aliases, Risks/Alerts DRS blocker taxonomy integration입니다.
