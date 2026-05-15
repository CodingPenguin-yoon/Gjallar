# Target DRS API

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Target DRS API](../../../architecture/api/target-drs-api.md), [Placement / DRS snapshot](../../../current/top-tabs/05-placement-drs-advisor.md), [DRS product direction](../../../product/drs-advisor/README.md), [DRS recommendation/execution](../../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md).

이 문서는 future-only DRS Advisor API 후보를 설명합니다. 2026-05-14 기준 현재 `/api/v1/drs/*` route는 구현되어 있지 않습니다.

## 현재 baseline

현재 `/placement`는 [frontend/src/utils/placement.js](../../../../frontend/src/utils/placement.js)가 기존 `/api/v1` inventory/jobs/risks API를 조합해 만드는 frontend-only read model입니다. Backend recommendation engine, approval persistence, migration execution, operation locks, UPID tracking, reconciliation backend가 없습니다.

## Target candidate endpoints

| Candidate endpoint | 목표 | 현재 상태 |
|---|---|---|
| `GET /api/v1/drs/summary` | blockers, candidates, recent migrations, policy coverage summary | Not implemented |
| `GET /api/v1/drs/recommendations` | identity/policy/current Proxmox inventory/risk evidence 기반 backend-owned recommendation list | Not implemented |
| `GET /api/v1/drs/recommendations/{recommendation_id}` | recommendation 하나의 evidence bundle | Not implemented |
| `POST /api/v1/drs/recommendations/{recommendation_id}/check-now` | operator 참고용 route evidence refresh. 실행 허가는 아님 | Not implemented |
| `POST /api/v1/drs/recommendations/{recommendation_id}/precheck` | migration 직전 final pre-check | Not implemented |
| `POST /api/v1/drs/recommendations/{recommendation_id}/approve-migrate` | warning ack, lock, `drs_migration` job, migration start | Not implemented |
| `GET /api/v1/drs/jobs/{job_id}` | DRS migration job state, UPID, task polling, post-check | Not implemented |
| `POST /api/v1/drs/jobs/{job_id}/reconcile` | uncertain job state를 Proxmox actual state로 정리 | Not implemented |
| `GET /api/v1/drs/policies` | DRS policy coverage/blockers view | Not implemented |
| `PUT /api/v1/drs/policies/{policy_id}` | future policy/audit rule 아래 policy update | Not implemented |
| `GET /api/v1/drs/locks` | active/stale operation lock inspection | Not implemented |

## Target execution rule

Target DRS는 "approve means migrate"가 아닙니다. 최소 순서는 recommendation evidence version 생성, optional Check Now, final pre-check, warning acknowledgement, operation lock, Proxmox migration, UPID polling, post-check, completed/failed/`needs_reconciliation` 기록입니다.

Check Now와 stale recommendation snapshot은 실행 허가가 아닙니다. Final pre-check가 execution 직전 Proxmox current state와 Gjallar identity/policy/lock state를 다시 읽어야 합니다.

## Explicit non-current items

- `/api/v1/drs/*` route surface.
- DRS DB identity/fingerprint/metadata/policy/approval/lock/operation/reconciliation tables.
- DRS migration mutation client.
- DRS UPID tracking.
- DRS final pre-check backend.
- DRS reconciliation worker or route.
- DRS blocker taxonomy integrated into `/api/v1/risks`.
