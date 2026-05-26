# Placement / DRS Advisor Overview

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

The current `/drs` route is a read-only DRS Advisor Phase 1 screen. It is not a migration execution implementation.

## Current Route And Component

| Concern | Current implementation |
|---|---|
| Route | `/drs` |
| Component | `frontend/src/components/DrsAdvisorScreen.jsx` |
| View model | `frontend/src/utils/drsAdvisor.js` |
| Backend DRS routes | `GET /api/v1/drs/summary`, `GET /api/v1/drs/recommendations`, detail, `POST /check` |
| Mutation controls | None |

## APIs Used Now

`loadDrsAdvisorModel()` currently calls backend DRS read-only APIs:

| API | Used for |
|---|---|
| `GET /api/v1/drs/summary` | Thresholds, candidate counts, read-only execution boundary. |
| `GET /api/v1/drs/recommendations` | Recommendation list with stable blockers and evidence. |
| `GET /api/v1/drs/recommendations/{recommendation_id}` | Detail evidence for one recommendation. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/check` | Reference-only recalculation. |

## Current Read Model

The backend builds review-only movement candidates from current inventory. Recommendations are generated only when a source node is hot, another online node is cooler, and the imbalance delta is large enough. Candidate evidence checks blockers, but this is a read model, not an execution contract.

## Current Recommendation Boundaries

| Capability | Current status |
|---|---|
| Backend-owned recommendation ids | Implemented for Phase 1 read-only recommendations. |
| DB identity/fingerprint lookup | Not implemented. |
| Policy engine | Not implemented. Rules panel is display-only. |
| Approval persistence | Not implemented. |
| Final pre-check | Not implemented. |
| Proxmox migration | Not implemented. |
| Operation locks | Not implemented. |
| UPID tracking | Not implemented. |
| Reconciliation | Not implemented. |

The screen shows a read-only safety notice and exposes no migration buttons.

## Target DRS Advisor Direction

Target DRS Advisor should become a backend-owned recommendation and execution system with DB-backed identity/fingerprint/policy state, exact evidence approval, final pre-check, operation locks, migration UPID tracking, post-check, reconciliation, DRS jobs, and DRS blockers in Risks/Alerts.

None of that is current.
