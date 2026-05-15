# Flow: Target DRS Approve, Migrate, Reconcile

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 target DRS flow](../../../architecture/flows/drs-approve-migrate-reconcile.md), [Target DRS API](../../../architecture/api/target-drs-api.md), [DRS recommendation/execution product doc](../../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md).

이 문서는 target-only DRS flow입니다. 현재 구현이 아닙니다.

## Current non-implementation

Current `/placement`는 `/api/v1/drs/*`를 호출하지 않고, recommendation approval, VM migration, UPID tracking, reconciliation을 수행하지 않습니다. 현재는 frontend-only read model입니다.

## Target flow summary

| Step | Target frontend | Target backend/API | Persisted state |
|---:|---|---|---|
| 1 | DRS Advisor load | `GET /api/v1/drs/summary`, `GET /api/v1/drs/recommendations` | recommendation snapshot/cache |
| 2 | Open recommendation | `GET /api/v1/drs/recommendations/{recommendation_id}` | evidence version |
| 3 | Optional Check Now | `POST /check-now` | reference artifact, not authorization |
| 4 | Review blockers/warnings | backend blocker taxonomy | none |
| 5 | Request final pre-check | `POST /precheck` | final precheck artifact |
| 6 | Backend rereads Proxmox | identity/fingerprint/status/source/target/storage/network/policy/locks | final evidence |
| 7 | Blocked/Unknown | no migration job | precheck artifact only |
| 8 | Confirm pass/warning | `POST /approve-migrate` | approval, locks, `drs_migration` job |
| 9 | Start migration | Proxmox live migration returns UPID | operation lock and UPID |
| 10 | Poll/read job | `GET /api/v1/drs/jobs/{job_id}` | task status |
| 11 | Post-check | target node/running/fingerprint | completed/failed/needs_reconciliation |
| 12 | Reconcile if needed | `POST /api/v1/drs/jobs/{job_id}/reconcile` | reconciliation artifact and lock update |

## Final pre-check requirements

Final pre-check must verify recommendation evidence version, VM still at source locator, identity/fingerprint match, no conflicting task, source/target online, target storage/network compatibility, policy allowed, locks acquired, and no red blocker.

Blocked or Unknown must not create a migration job.

## Reconciliation

Reconciliation is required when success/failure cannot be safely decided: timeout, unreadable Proxmox task, VM not found, fingerprint mismatch, stale lock, backend crash after UPID, unreadable post-check evidence. The reconciler rereads Proxmox actual state and compares it to Gjallar operation records.
