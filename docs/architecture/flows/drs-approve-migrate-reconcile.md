# Flow: DRS Approve, Execute, Reconcile Preview

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

This is the current DRS execution boundary.

Current `/drs` UI calls read/check and policy endpoints and exposes local approval packet/job intent creation. It does not expose live execute or corrective reconcile controls. Backend `/api/v1/drs/*` has local approval packet creation, a narrow operator-only migration-job execute route with exact acknowledgement, UPID/task/post-check tracking, and read-only reconcile preview.

## Current Flow Summary

| Step | Current frontend/API surface | Current backend/API | Current persisted state |
|---:|---|---|---|
| 1 | Load DRS Advisor. | `GET /api/v1/drs/summary` and `GET /api/v1/drs/recommendations`. | May persist Gjallar-local identity observation evidence; no Proxmox mutation. |
| 2 | Operator opens recommendation. | `GET /api/v1/drs/recommendations/{recommendation_id}` returns evidence bundle. | Same read-only/local-evidence boundary. |
| 3 | Operator refreshes recommendation evidence for reference. | `POST /api/v1/drs/recommendations/{recommendation_id}/check`. | Check result remains `read_only=true`, `executable=false`, `allowed_actions=[]`; not execution authorization. |
| 4 | Operator-only API creates approval packet/job intent. | `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets`. | Local approval packet, final-precheck artifact, recommendation artifact, and pending `drs_migration` job intent. No Proxmox mutation. |
| 5 | Operator-only API executes stored job. | `POST /api/v1/drs/migration-jobs/{job_id}/execute` with exact `drs_live_migration_acknowledged=true`. | Ack failure is request validation only: no DRS service call, client factory, live pre-check, lock, migration call, or job-state mutation. After ack, stored approval/job binding and artifact checksums are validated before any client factory or mutation. |
| 6 | Execute route reruns fresh gates. | Reread recommendation, identity/fingerprint, locator, policy, operation-lock, and config-lock evidence. | Blocked gate records blocked job evidence; no Proxmox mutation. |
| 7 | Execute route collects live Proxmox DRS evidence. | Dedicated DRS client checks active tasks, HA, quorum, and migration preconditions. | Blocked live evidence records blocked job evidence; no migration request. |
| 8 | Backend acquires operation locks. | VM identity, Proxmox locator, and route locks. | Active locks. If acquisition fails, no migration request. |
| 9 | Backend starts migration. | Dedicated DRS client calls Proxmox QEMU migrate. | UPID stored immediately when returned. Missing UPID/request uncertainty becomes `needs_reconciliation`. |
| 10 | Backend polls task. | Read Proxmox task until terminal, running, timeout, or ambiguous result. | Task result/status/log excerpt evidence. |
| 11 | Backend post-checks terminal OK task. | Direct target-node status/config/fingerprint and active-task evidence. | `completed` only after verified success; otherwise `needs_reconciliation`. |
| 12 | Operator-only API previews reconciliation. | `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview`. | Read-only preview only; no corrective mutation. |

## Execute Request Gate

`POST /api/v1/drs/migration-jobs/{job_id}/execute` must include exact
`{"drs_live_migration_acknowledged": true}`. Missing payload, missing field,
`false`, `null`, string `"true"`, number `1`, camelCase-only acknowledgement, or
Create VM acknowledgement return `409` with code `DRS_EXECUTION_ACK_REQUIRED`,
`required_acknowledgement="drs_live_migration_acknowledged"`,
`proxmox_mutation_enabled=false`, and `side_effects=[]`. This gate runs before
DRS execution service delegation, client factory selection, live pre-check,
operation locks, or migration calls, and it does not mark a pending job blocked.

## Final Pre-Check Requirements

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

## Reconciliation

Reconciliation is required when backend cannot safely decide success or failure.

Examples:

- migration task times out
- Proxmox task status cannot be read
- VM is not found at source or target
- VM is found on target but fingerprint mismatches
- operation lock becomes stale
- post-check cannot read storage/network/status evidence
- backend crashes after starting a migration but before terminal state is recorded

The read-only reconcile preview rereads Proxmox actual state and compares it to Gjallar operation records. It does not assume a task succeeded only because the migration call returned a UPID. Corrective reconciliation mutation and background automation are not implemented.

## Jobs And Risks

Current DRS operations appear in Jobs/Runs with stages such as:

| Stage | Current meaning |
|---|---|
| `recommendation` | Evidence generated. |
| `approval` | Human approval recorded. |
| `final_precheck` | Current-state reread and locks. |
| `migration` | Proxmox migration call and UPID polling. |
| `post_check` | Target location/fingerprint/status verified. |
| `reconciliation` | Uncertain operation requires reconciliation; preview remains read-only. |

Risks/Alerts remain job-derived and do not yet have a full DRS blocker taxonomy.

## Explicit Current Non-Implementation

- Live execute UI, corrective reconcile UI, and broad approval-to-execute controls.
- Corrective reconciliation mutation.
- Background reconciliation automation or automatic DRS.
- Recommendation-level approve/migrate/live-migrate aliases.
- Richer policy rule/full metadata editor beyond current per-VM policy configuration.
- Live DRS smoke evidence.
