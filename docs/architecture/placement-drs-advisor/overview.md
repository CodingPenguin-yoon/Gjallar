# Placement / DRS Advisor Overview

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

The current `/drs` route is a DRS Advisor screen with recommendation/check,
manual per-VM migration policy configuration, and local approval packet/job
intent creation. Backend DRS is backed by identity/policy evidence, read-only
final pre-check, local approval/job substrate, narrow approval-gated migration
execution, UPID tracking, verified post-check, and read-only reconciliation
preview. Live execute and corrective reconcile UI remain pending.

## Current Route And Component

| Concern | Current implementation |
|---|---|
| Route | `/drs` |
| Component | `frontend/src/components/DrsAdvisorScreen.jsx` |
| View model | `frontend/src/utils/drsAdvisor.js` |
| Backend DRS routes | `GET /api/v1/drs/summary`, `GET /api/v1/drs/recommendations`, detail, `POST /check`, `GET/PUT /drs/policies*`, `POST /approval-packets`, `POST /migration-jobs/{job_id}/execute`, `POST /migration-jobs/{job_id}/reconcile-preview` |
| Mutation controls | Current UI writes only local VM policy and local approval packet/job intent state. Live migration remains the narrow backend execute route after identity, policy, final pre-check, approval, lock, and live evidence gates; no live execute or corrective reconcile UI. |

## APIs Used Now

`loadDrsAdvisorModel()` currently calls backend DRS read, policy, and local
approval APIs and surfaces local readiness evidence:

| API | Used for |
|---|---|
| `GET /api/v1/drs/summary` | Thresholds, candidate counts, read-only execution boundary. |
| `GET /api/v1/drs/recommendations` | Recommendation list with stable blockers and evidence. |
| `GET /api/v1/drs/recommendations/{recommendation_id}` | Detail evidence for one recommendation. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/check` | Reference-only recalculation. |
| `GET /api/v1/drs/policies` | Current VM policy coverage and blocker impact. |
| `GET /api/v1/drs/policies/{vm_identity_id}` | Detail evidence for one VM policy item. |
| `PUT /api/v1/drs/policies/{vm_identity_id}` | Operator-only local VM policy update with audit evidence. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets` | Local approval packet and pending job intent creation after backend gates pass. |
| `POST /api/v1/drs/migration-jobs/{job_id}/execute` | Narrow operator-only live migration execution after stored approval, fresh final pre-check, live Proxmox evidence, and lock acquisition. |
| `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview` | Read-only reconciliation preview with no corrective mutation authority. |

## Current Read Model

The backend builds movement candidates from current inventory. Recommendations
are generated only when a source node is hot, another online node is cooler,
and the imbalance delta is large enough. Candidate evidence checks blockers,
but execution authority comes only from the stored approval/job path and the
narrow execution endpoint.

## Current Recommendation Boundaries

| Capability | Current status |
|---|---|
| Backend-owned recommendation ids | Implemented. |
| DB identity/fingerprint lookup | Implemented with curated fingerprint evidence and confidence. |
| Migration policy memory | Implemented; default `unknown` blocks execution. |
| Approval persistence | Implemented as local approval packets bound to recommendation and final-precheck checksums. |
| Final pre-check | Implemented as read-only `/check`; execution reruns fresh gates before mutation. |
| Proxmox migration | Implemented only through narrow approval-gated backend execution. |
| Operation locks | Implemented for DRS migration scopes. |
| UPID tracking | Implemented for accepted migration tasks. |
| Reconciliation | Verified post-check, `needs_reconciliation`, reconciliation events, and read-only Reconcile preview implemented. |

The screen shows a safety notice, compact identity/policy evidence, manual
policy configuration, and local approval packet/job intent creation. Live
migration execution UI remains pending; backend gates remain authoritative.

## Target DRS Advisor Direction

Target DRS Advisor remains a backend-owned recommendation and execution system
with DB-backed identity/fingerprint/policy state, exact evidence approval,
final pre-check, operation locks, migration UPID tracking, post-check,
reconciliation, DRS jobs, and DRS blockers in Risks/Alerts.

Goal 1-6 backend foundations are current. Before Goal 7 UI/operations polish,
the non-numbered Goal Check must verify that foundation is genuinely
implemented, production-quality, and not test-shaped or docs-only.
