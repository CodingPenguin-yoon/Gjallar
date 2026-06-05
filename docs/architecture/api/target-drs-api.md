# DRS API Boundary And Future Candidates

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

This document lists DRS Advisor APIs and separates the current implemented boundary from future execution/automation work.

Current `/drs` UI includes read/check recommendations and local approval packet/job intent creation. Manual VM policy configuration is surfaced under VM Instances / DRS Policies at `/instances/drs-policies`. Backend `/api/v1/drs/*` includes Proxmox-read-only recommendation/check routes, operator-only explicit test candidate check/approval helpers for a selected VM outside the normal top-3 shortlist, `vm_identity_id`-scoped manual policy management with local audit events, a local approval packet/job substrate, a narrow operator-only migration-job execute route with exact live-migration acknowledgement, a read-only reconcile preview route, and acknowledged stored-UPID local reconciliation follow-up. Approved VMID `140` live DRS smoke evidence exists. Live execute UI, corrective reconcile UI, corrective mutation, background automation, and automatic DRS remain deferred.

## Candidate Endpoints

| Candidate endpoint | Target purpose | Current status |
|---|---|---|
| `GET /api/v1/drs/summary` | DRS dashboard summary: blockers, candidates, policy gaps. | Implemented. Proxmox-read-only; may persist Gjallar-local identity observation evidence. |
| `GET /api/v1/drs/recommendations` | Backend-owned recommendation list from current Proxmox inventory and risk evidence. | Implemented. Proxmox-read-only; recommendations are `executable=false`, `allowed_actions=[]`. |
| `GET /api/v1/drs/recommendations/{recommendation_id}` | Detailed evidence bundle for one recommendation. | Implemented. Proxmox-read-only; 404 for unknown ids. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/check` | Reference final pre-check calculation. | Implemented. Computes `would_be_executable`, but response remains `executable=false`, `allowed_actions=[]`, and does not authorize migration. |
| `POST /api/v1/drs/explicit-test-candidates/check` | Operator-only final pre-check for one selected smoke/test VM outside the normal top-3 shortlist. | Implemented. Requires exact `explicit_test_vm_acknowledged=true` before inventory/advisor work; only bypasses the top-3 VM slice and keeps normal source/target, VM state, red-risk, route, storage, network, passthrough, target-threshold, identity, policy, and lock gates. |
| `POST /api/v1/drs/explicit-test-candidates/approval-packets` | Local approval packet/job intent creation for an explicit smoke/test candidate after the explicit check passes. | Implemented. Operator-only; rejects stale source/target/identity selection before approval creation, writes local rows/artifacts only, and does not call Proxmox mutation. |
| `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets` | Persist exact recommendation/final-precheck approval packet and pending job intent. | Implemented. Operator-only; writes local approval/job/artifact rows and does not start migration. |
| `POST /api/v1/drs/migration-jobs/{job_id}/execute` | Execute one stored approved DRS migration job after request acknowledgement and fresh gates. | Implemented. Operator-only; first requires exact `drs_live_migration_acknowledged=true`. Ack failure returns `409` / `DRS_EXECUTION_ACK_REQUIRED` before service/client/lock/migration work and does not mutate pending job state. After that it validates stored bindings/checksums, reruns fresh precheck, collects live Proxmox evidence, acquires operation locks, calls the dedicated DRS migration client, stores UPID/task/post-check evidence, and releases locks only after verified success. |
| `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview` | Read-only reconciliation evidence preview. | Implemented. Operator-only; no corrective mutation. |
| `GET /api/v1/drs/policies` | Read broader DRS policy coverage and blockers. | Implemented. Proxmox-read-only; current non-template VMs are listed, and uncertain identities are write-blocked. |
| `GET /api/v1/drs/policies/{vm_identity_id}` | Read one current VM policy item. | Implemented. Keyed by Gjallar `vm_identity_id`, not raw VMID/IP/name/node/tag/recommendation. |
| `PUT /api/v1/drs/policies/{vm_identity_id}` | Update DRS policy under policy/audit rules. | Implemented. Operator-only Gjallar-local write; requires expected observation guard, acknowledgement, trusted session actor, and audit event. |
| `GET /api/v1/drs/locks` | Inspect active/stale operation locks. | Not implemented as a public API. |

## Target Execution Rules

Current DRS execution is not "approve means migrate". The implemented sequence is:

1. Backend computes a recommendation and evidence version.
2. Operator may run `/check` for reference; this does not authorize execution.
3. Optional explicit test candidate check/approval can synthesize a deterministic recommendation id for one selected VM outside the normal top-3 shortlist, but only with exact `explicit_test_vm_acknowledged=true` and only if the normal DRS gates still pass.
4. Operator-only approval packet creation stores exact local approval/job/artifact evidence and does not start migration.
5. Operator-only `/migration-jobs/{job_id}/execute` first requires exact `drs_live_migration_acknowledged=true`; missing or malformed acknowledgement is request validation only and has no job-state side effects.
6. Backend validates approved job bindings/checksums.
7. Backend reruns a fresh final pre-check against current Proxmox and Gjallar identity/policy/lock state.
8. Backend collects live Proxmox DRS evidence for active tasks, HA, quorum, and migration preconditions.
9. Backend takes operation locks for VM identity, Proxmox locator, and route.
10. Backend starts Proxmox migration through the dedicated DRS migration client and records UPID.
11. Backend polls the Proxmox task to terminal or ambiguous state.
12. Backend post-checks VM target location, power state, fingerprint, and active task evidence.
13. Backend records `completed` only after verified post-check; otherwise it records `needs_reconciliation` and marks locks `reconciliation_required`.
14. Read-only reconcile preview can reread evidence. No corrective mutation or background automation exists.

## Explicit Non-Current Items

- Recommendation-level approve/migrate/live-migrate route aliases.
- Live execute UI, corrective reconcile UI, and broad approval-to-execute controls.
- Richer policy rule API beyond manual per-VM identity classification.
- Corrective reconciliation mutation.
- Background reconciliation automation or automatic DRS.
- Broad or repeated live DRS smoke/mutation evidence beyond the approved VMID
  `140` run.
- DRS blocker taxonomy integrated into `/api/v1/risks`.
