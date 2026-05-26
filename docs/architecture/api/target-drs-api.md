# Target DRS API

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

This document lists DRS Advisor APIs and separates current Phase 1 read-only implementation from future execution work.

Current `/drs` is a read-only DRS Advisor Phase 1 screen backed by `/api/v1/drs/*` summary/recommendation/detail/check endpoints. It has no approval persistence, migration execution, locks, UPID tracking, or reconciliation backend.

## Candidate Endpoints

| Candidate endpoint | Target purpose | Current status |
|---|---|---|
| `GET /api/v1/drs/summary` | DRS dashboard summary: blockers, candidates, policy gaps. | Phase 1 read-only implemented. |
| `GET /api/v1/drs/recommendations` | Backend-owned recommendation list from current Proxmox inventory and risk evidence. | Phase 1 read-only implemented. |
| `GET /api/v1/drs/recommendations/{recommendation_id}` | Detailed evidence bundle for one recommendation. | Phase 1 read-only implemented. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/check` | Reference-only recalculation. This does not authorize migration. | Phase 1 read-only implemented. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/precheck` | Final pre-check immediately before migration: reread Proxmox, verify identity/fingerprint/policy/locks/target. | Not implemented. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/approve-migrate` | Persist warning acknowledgement, acquire locks, create a `drs_migration` job, and start migration only after final pre-check allows it. | Not implemented. |
| `GET /api/v1/drs/jobs/{job_id}` | Read DRS migration job state, UPID, task polling, and post-check status. | Not implemented. |
| `POST /api/v1/drs/jobs/{job_id}/reconcile` | Reconcile uncertain job state against Proxmox actual state. | Not implemented. |
| `GET /api/v1/drs/policies` | Read DRS policy coverage and blockers. | Not implemented. |
| `PUT /api/v1/drs/policies/{policy_id}` | Update DRS policy under future policy/audit rules. | Not implemented. |
| `GET /api/v1/drs/locks` | Inspect active/stale operation locks. | Not implemented. |

## Target Execution Rules

Target DRS execution must not be "approve means migrate". The minimum target sequence is:

1. Backend computes a recommendation and evidence version.
2. Operator may run Check Now for reference; this does not authorize execution.
3. Backend performs final pre-check against current Proxmox and Gjallar identity/policy state.
4. Operator acknowledges warnings and requests approve-migrate for the exact evidence version.
5. Backend takes operation locks for VM, source node, and target node.
6. Backend starts Proxmox migration and records UPID.
7. Backend polls the Proxmox task to terminal state.
8. Backend post-checks VM location, status, fingerprint, network, and storage evidence.
9. Backend records completed, failed, or `needs_reconciliation`.
10. Jobs/Runs and Risks/Alerts expose the operation and blockers.

## Explicit Non-Current Items

- DRS mutation route surface.
- DRS DB identity, fingerprint, metadata, policy, approval, lock, operation, or reconciliation tables.
- Migration execution client in a DRS path.
- UPID tracking for DRS migration.
- DRS final pre-check backend.
- DRS reconciliation worker or job reconciliation route.
- DRS blocker taxonomy integrated into `/api/v1/risks`.
