# Placement / DRS Advisor

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Placement snapshot](../../../current/top-tabs/05-placement-drs-advisor.md), [영어 Placement/DRS architecture](../../../architecture/placement-drs-advisor/overview.md), [Target DRS API](../../../architecture/api/target-drs-api.md), [DRS product docs](../../../product/drs-advisor/README.md).

현재 `/placement`는 read-only frontend Placement screen입니다. Target product direction은 이 route를 DRS Advisor로 확장하는 것이지만, 현재 backend DRS recommendation이나 migration execution은 없습니다.

## 사용하는 API와 호출 위치

`loadPlacementModel()` in [frontend/src/utils/placement.js](../../../../frontend/src/utils/placement.js)는 다음 API를 조합합니다.

| API | 현재 사용 |
|---|---|
| `GET /api/v1/cluster/summary` | cluster summary |
| `GET /api/v1/nodes` | node load/status |
| `GET /api/v1/vms` | VM distribution과 candidate list |
| `GET /api/v1/storage` | target storage evidence |
| `GET /api/v1/networks` | target bridge evidence |
| `GET /api/v1/risks` | red risk awareness |
| `GET /api/v1/jobs` | placement 관련 history 표시 seed |

## 구현 방식

Frontend는 current CPU/Memory usage로 node pressure와 imbalance를 계산합니다. Source pressure가 높고 target이 online이며 delta가 충분하면 candidate를 만듭니다. Bridge/storage evidence를 확인하지만, recommendation은 backend-owned execution contract가 아닙니다.

현재 execution은 `available: false`, `readOnly: true`, `allowedActions: []`입니다.

## 현재 없는 것

- `/api/v1/drs/*` routes.
- backend recommendation id/evidence version.
- DB identity/fingerprint/metadata/policy.
- Check Now, final pre-check, approval persistence.
- operation lock, Proxmox live migration, UPID tracking.
- post-check, reconciliation.

## Target gap

DRS Advisor target은 backend-owned recommendation, final pre-check, Allowed VM만 Approve & Migrate, Jobs/Runs `drs_migration`, Risks/Alerts DRS blockers입니다. Current Placement candidate를 실행 허가로 해석하면 안 됩니다.
