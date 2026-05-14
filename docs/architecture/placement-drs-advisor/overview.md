# Placement / DRS Advisor Overview

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

The current `/placement` route is a read-only Placement screen. It is not a backend DRS Advisor implementation.

## Current Route And Component

| Concern | Current implementation |
|---|---|
| Route | `/placement` |
| Component | `frontend/src/components/PlacementScreen.jsx` |
| View model | `frontend/src/utils/placement.js` |
| Backend DRS routes | None |
| Mutation controls | None |

## APIs Used Now

`loadPlacementModel()` currently calls existing `/api/v1` APIs:

| API | Used for |
|---|---|
| `GET /api/v1/cluster/summary` | Cluster id and base summary. |
| `GET /api/v1/nodes` | Node load, status, storage/network evidence embedded on nodes. |
| `GET /api/v1/vms` | VM distribution, candidate VM list, storage/IP/guest-agent evidence. |
| `GET /api/v1/storage` | Target storage evidence. |
| `GET /api/v1/networks` | Target bridge evidence. |
| `GET /api/v1/risks` | Exclude/red-risk awareness and node/VM risk counts. |
| `GET /api/v1/jobs` | Placement history display if any job type includes `placement`. |

There is no current `GET /api/v1/drs/recommendations`.

## Current Read Model

The frontend builds cluster status, a node load table, VM distribution, and review-only movement candidates from current inventory. Recommendations are generated only when a source node is hot, another online node is cooler, and the imbalance delta is large enough. Candidate evidence checks for shared bridge ids and storage compatibility, but this is a read model, not an execution contract.

## Current Recommendation Boundaries

| Capability | Current status |
|---|---|
| Backend-owned recommendation ids | Not implemented. Frontend synthesizes ids. |
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

Target DRS Advisor should become a backend-owned recommendation and execution system with `/api/v1/drs/*` read models, DB-backed identity/fingerprint/policy state, exact evidence approval, final pre-check, operation locks, migration UPID tracking, post-check, reconciliation, DRS jobs, and DRS blockers in Risks/Alerts.

None of that is current.
