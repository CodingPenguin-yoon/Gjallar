# Placement / DRS Advisor

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Placement snapshot](../../../current/top-tabs/05-placement-drs-advisor.md), [영어 Placement/DRS architecture](../../../architecture/placement-drs-advisor/overview.md), [Target DRS API](../../../architecture/api/target-drs-api.md), [DRS product docs](../../../product/drs-advisor/README.md).

현재 `/drs`는 DRS Advisor recommendation/check, manual VM policy configuration, local approval packet/job intent creation screen입니다. Frontend에는 live execute/corrective reconcile controls가 없습니다. Backend에는 compact identity/fingerprint와 policy evidence, operation locks, local approval/job substrate, narrow operator-only migration-job execute route, UPID/task tracking, verified post-check, read-only reconcile preview, stored-UPID local reconciliation follow-up이 있습니다. Approved VMID `140` live DRS smoke evidence는 기록됐습니다.

## 사용하는 API와 호출 위치

`loadDrsAdvisorModel()` in [frontend/src/utils/drsAdvisor.js](../../../../frontend/src/utils/drsAdvisor.js)는 다음 API를 조합합니다.

| API | 현재 사용 |
|---|---|
| `GET /api/v1/drs/summary` | thresholds, read-only summary, candidate counts |
| `GET /api/v1/drs/recommendations` | backend-owned read-only recommendation list |
| `GET /api/v1/drs/recommendations/{recommendation_id}` | detail evidence |
| `POST /api/v1/drs/recommendations/{recommendation_id}/check` | reference-only recalculation |
| `GET /api/v1/drs/policies` | current VM policy coverage와 blocker impact |
| `GET /api/v1/drs/policies/{vm_identity_id}` | one VM policy item |
| `PUT /api/v1/drs/policies/{vm_identity_id}` | operator-only local policy update와 audit evidence |
| `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets` | operator-only local approval/job/artifact write; migration 시작 안 함 |
| `POST /api/v1/drs/migration-jobs/{job_id}/execute` | operator-only narrow backend execution after fresh gates |
| `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview` | read-only reconciliation preview |
| `POST /api/v1/drs/migration-jobs/{job_id}/reconcile` | stored-UPID local reconciliation follow-up; corrective mutation 아님 |

## 구현 방식

Backend는 current CPU/Memory usage로 node pressure와 imbalance를 계산합니다. Source가 hot이고 target이 online이며 delta가 충분하면 running non-template VM candidate를 만듭니다. Red-risk VM은 제외됩니다.

현재 execution은 `available: false`, `read_only: true`, `executable: false`, `allowed_actions: []`입니다.

## 현재 없는 것

- live execute/corrective reconcile controls and broad approval-to-execute UI.
- richer policy/rule controls와 full metadata/classification UI.
- recommendation-level approve/migrate/live-migrate alias routes.
- corrective reconciliation mutation, background automation, automatic DRS.
- broad/repeated live DRS smoke evidence beyond the approved VMID `140` run.

## Target gap

DRS recommendation/check result는 실행 허가가 아닙니다. Live migration은 stored approval/job, fresh final pre-check, live Proxmox evidence, operation locks를 통과한 dedicated execute route에서만 가능합니다. Risks/Alerts DRS blocker taxonomy 통합과 broad UI는 future work입니다.
