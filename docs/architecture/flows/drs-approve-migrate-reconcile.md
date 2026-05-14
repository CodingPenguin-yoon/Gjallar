# Flow: Target DRS Approve, Migrate, Reconcile

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

This is a target-only DRS flow. It is not current implementation.

Current `/placement` does not call `/api/v1/drs/*`, does not approve recommendations, does not migrate VMs, does not track UPIDs, and does not reconcile operations.

## Target Flow Summary

| Step | Target frontend | Target backend/API | Target persisted state |
|---:|---|---|---|
| 1 | Load DRS Advisor. | `GET /api/v1/drs/summary` and `GET /api/v1/drs/recommendations`. | None or cached read model. |
| 2 | Operator opens recommendation. | `GET /api/v1/drs/recommendations/{recommendation_id}` returns evidence bundle. | Recommendation evidence/version. |
| 3 | Operator optionally refreshes route evidence for reference. | `POST /api/v1/drs/recommendations/{recommendation_id}/check-now`. | Check Now artifact/event; not execution authorization. |
| 4 | Operator reviews blockers and warnings. | Backend supplies red/yellow blocker taxonomy. | None. |
| 5 | Operator requests final pre-check. | `POST /api/v1/drs/recommendations/{recommendation_id}/precheck`. | Final pre-check job/artifact. |
| 6 | Final pre-check rereads Proxmox. | Verify locator, identity, fingerprint, status, source, target, storage, network, policy. | Final pre-check evidence. |
| 7 | Blocked or Unknown result is shown. | Backend returns blockers and does not create a migration job. | Final pre-check artifact only. |
| 8 | Operator confirms pass/warning result and acknowledges warnings. | `POST /api/v1/drs/recommendations/{recommendation_id}/approve-migrate`. | Approval record, lock record, `drs_migration` job, UPID/task state. |
| 9 | Backend acquires locks and starts migration. | Proxmox migration call returns UPID only after locks are acquired. | Operation lock records and UPID. |
| 10 | Operator opens job detail. | `GET /api/v1/drs/jobs/{job_id}`. | Read-only job detail. |
| 11 | Backend polls task. | Read Proxmox task until terminal or timeout. | Task poll artifact/status. |
| 12 | Backend post-checks and records terminal state. | Verify VM on expected target with expected identity/fingerprint/status. | Completed, failed, or `needs_reconciliation` job/risk state. |
| 13 | Operator reconciles uncertain state. | `POST /api/v1/drs/jobs/{job_id}/reconcile`. | Reconciliation artifact and updated job/lock state. |

## Target Final Pre-Check Requirements

| Requirement | Why it blocks |
|---|---|
| Recommendation evidence version still current | Avoid executing stale advice. |
| VM still at expected source locator | Avoid moving the wrong VM or an already moved VM. |
| Gjallar identity/fingerprint still matches | Avoid identity mismatch and VMID reuse hazards. |
| No conflicting Proxmox task | Avoid racing with backup, migration, clone, or manual operations. |
| Source and target nodes online | Migration requires available endpoints. |
| Target storage/network compatible | Avoid post-migration service failure. |
| DRS policy still permits move | Policy may change after recommendation. |
| Locks acquired | Avoid concurrent Gjallar operations. |
| No red DRS blocker | Red blockers stop execution. |

## Target Reconciliation

Reconciliation is required when backend cannot safely decide success or failure.

Examples:

- migration task times out
- Proxmox task status cannot be read
- VM is not found at source or target
- VM is found on target but fingerprint mismatches
- operation lock becomes stale
- post-check cannot read storage/network/status evidence
- backend crashes after starting a migration but before terminal state is recorded

The reconciler must reread Proxmox actual state and compare it to Gjallar operation records. It should not assume a task succeeded only because the migration call returned a UPID.

## Target Jobs And Risks

Target DRS operations should appear in Jobs/Runs with stages such as:

| Stage | Target meaning |
|---|---|
| `recommendation` | Evidence generated. |
| `approval` | Human approval recorded. |
| `final_precheck` | Current-state reread and locks. |
| `migration` | Proxmox migration call and UPID polling. |
| `post_check` | Target location/fingerprint/status verified. |
| `reconciliation` | Uncertain operation manually or automatically reconciled. |

Target Risks/Alerts should show red/yellow blockers and link to recommendation, final-precheck, migration, post-check, and reconciliation artifacts.

## Explicit Current Non-Implementation

Nothing in this target flow is currently wired in the active backend. The only current related screen is `/placement`, and it is read-only.
