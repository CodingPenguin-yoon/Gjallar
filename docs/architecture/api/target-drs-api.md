# DRS API Boundary And Future Candidates

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

This document lists DRS Advisor APIs and separates the current Goals 1-6 backend boundary from future UI/policy/automation work.

Current `/drs` UI remains read/check only. Backend `/api/v1/drs/*` includes Proxmox-read-only recommendation/check routes, a local approval packet/job substrate, a narrow operator-only migration-job execute route, and a read-only reconcile preview route. Broad execution UI, policy editor, corrective mutation, background automation, automatic DRS, and live DRS smoke evidence remain deferred.

## Candidate Endpoints

| Candidate endpoint | Target purpose | Current status |
|---|---|---|
| `GET /api/v1/drs/summary` | DRS dashboard summary: blockers, candidates, policy gaps. | Implemented. Proxmox-read-only; may persist Gjallar-local identity observation evidence. |
| `GET /api/v1/drs/recommendations` | Backend-owned recommendation list from current Proxmox inventory and risk evidence. | Implemented. Proxmox-read-only; recommendations are `executable=false`, `allowed_actions=[]`. |
| `GET /api/v1/drs/recommendations/{recommendation_id}` | Detailed evidence bundle for one recommendation. | Implemented. Proxmox-read-only; 404 for unknown ids. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/check` | Reference final pre-check calculation. | Implemented. Computes `would_be_executable`, but response remains `executable=false`, `allowed_actions=[]`, and does not authorize migration. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets` | Persist exact recommendation/final-precheck approval packet and pending job intent. | Implemented. Operator-only; writes local approval/job/artifact rows and does not start migration. |
| `POST /api/v1/drs/migration-jobs/{job_id}/execute` | Execute one stored approved DRS migration job after fresh gates. | Implemented. Operator-only; validates stored bindings/checksums, reruns fresh precheck, collects live Proxmox evidence, acquires operation locks, calls the dedicated DRS migration client, stores UPID/task/post-check evidence, and releases locks only after verified success. |
| `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview` | Read-only reconciliation evidence preview. | Implemented. Operator-only; no corrective mutation. |
| `GET /api/v1/drs/policies` | Read broader DRS policy coverage and blockers. | Not implemented as a public API. |
| `PUT /api/v1/drs/policies/{policy_id}` | Update DRS policy under future policy/audit rules. | Not implemented. |
| `GET /api/v1/drs/locks` | Inspect active/stale operation locks. | Not implemented as a public API. |

## Target Execution Rules

Current DRS execution is not "approve means migrate". The implemented sequence is:

1. Backend computes a recommendation and evidence version.
2. Operator may run `/check` for reference; this does not authorize execution.
3. Operator-only approval packet creation stores exact local approval/job/artifact evidence and does not start migration.
4. Operator-only `/migration-jobs/{job_id}/execute` validates approved job bindings/checksums.
5. Backend reruns a fresh final pre-check against current Proxmox and Gjallar identity/policy/lock state.
6. Backend collects live Proxmox DRS evidence for active tasks, HA, quorum, and migration preconditions.
7. Backend takes operation locks for VM identity, Proxmox locator, and route.
8. Backend starts Proxmox migration through the dedicated DRS migration client and records UPID.
9. Backend polls the Proxmox task to terminal or ambiguous state.
10. Backend post-checks VM target location, power state, fingerprint, and active task evidence.
11. Backend records `completed` only after verified post-check; otherwise it records `needs_reconciliation` and marks locks `reconciliation_required`.
12. Read-only reconcile preview can reread evidence. No corrective mutation or background automation exists.

## Explicit Non-Current Items

- Recommendation-level approve/migrate/live-migrate route aliases.
- Broad DRS execution UI controls.
- DRS policy editor or richer policy rule API.
- Corrective reconciliation mutation.
- Background reconciliation automation or automatic DRS.
- Live DRS smoke/mutation evidence.
- DRS blocker taxonomy integrated into `/api/v1/risks`.
