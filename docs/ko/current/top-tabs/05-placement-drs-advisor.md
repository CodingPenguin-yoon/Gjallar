# Placement / DRS Advisor

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Placement snapshot](../../../current/top-tabs/05-placement-drs-advisor.md), [영어 Placement/DRS architecture](../../../architecture/placement-drs-advisor/overview.md), [Target DRS API](../../../architecture/api/target-drs-api.md), [DRS product docs](../../../product/drs-advisor/README.md).

현재 `/drs`는 read-only DRS Advisor Phase 1 screen입니다. Backend DRS recommendation read model은 있지만 migration execution은 없습니다.

## 사용하는 API와 호출 위치

`loadDrsAdvisorModel()` in [frontend/src/utils/drsAdvisor.js](../../../../frontend/src/utils/drsAdvisor.js)는 다음 API를 조합합니다.

| API | 현재 사용 |
|---|---|
| `GET /api/v1/drs/summary` | thresholds, read-only summary, candidate counts |
| `GET /api/v1/drs/recommendations` | backend-owned read-only recommendation list |
| `GET /api/v1/drs/recommendations/{recommendation_id}` | detail evidence |
| `POST /api/v1/drs/recommendations/{recommendation_id}/check` | reference-only recalculation |

## 구현 방식

Backend는 current CPU/Memory usage로 node pressure와 imbalance를 계산합니다. Source가 hot이고 target이 online이며 delta가 충분하면 running non-template VM candidate를 만듭니다. Red-risk VM은 제외됩니다.

현재 execution은 `available: false`, `read_only: true`, `executable: false`, `allowed_actions: []`입니다.

## 현재 없는 것

- migration mutation routes.
- DB identity/fingerprint/metadata/policy.
- final pre-check, approval persistence.
- operation lock, Proxmox live migration, UPID tracking.
- post-check, reconciliation.

## Target gap

DRS Advisor target은 backend-owned recommendation, final pre-check, Allowed VM만 Approve & Migrate, Jobs/Runs `drs_migration`, Risks/Alerts DRS blockers입니다. Current Phase 1 candidate를 실행 허가로 해석하면 안 됩니다.
