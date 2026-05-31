# Flow: DRS Approve, Execute, Reconcile Preview

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 DRS flow](../../../architecture/flows/drs-approve-migrate-reconcile.md), [Target DRS API](../../../architecture/api/target-drs-api.md), [DRS recommendation/execution product doc](../../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md).

이 문서는 Goal 1-6 이후 현재 backend DRS execution boundary입니다.

## Current boundary

Current `/drs` frontend는 recommendation/check, manual policy configuration, local approval packet creation을 제공합니다. Backend는 local approval/job substrate, narrow operator-only migration-job execute route, UPID/task tracking, verified post-check, read-only reconcile preview를 제공합니다. Live execute UI, corrective reconcile UI, background automation, automatic DRS는 없습니다.

## Current flow summary

| Step | Current frontend/API surface | Current backend/API | Persisted state |
|---:|---|---|---|
| 1 | DRS Advisor load | `GET /api/v1/drs/summary`, `GET /api/v1/drs/recommendations` | local identity evidence may be observed |
| 2 | Open recommendation | `GET /api/v1/drs/recommendations/{recommendation_id}` | evidence version |
| 3 | Optional Check | `POST /api/v1/drs/recommendations/{recommendation_id}/check` | reference result; `executable=false` 유지 |
| 4 | Create approval packet | `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets` | local approval/job/artifact only; migration 시작 안 함 |
| 5 | Execute stored job | `POST /api/v1/drs/migration-jobs/{job_id}/execute` | validates approval/job binding and checksums |
| 6 | Backend rereads gates | identity/fingerprint/status/source/target/storage/network/policy/locks | blocked evidence or execution evidence |
| 7 | Live DRS evidence | active tasks, HA, quorum, migration preconditions | blocks before mutation if unsafe |
| 8 | Acquire locks | VM identity, locator, route locks | active locks |
| 9 | Start migration | Dedicated DRS Proxmox client returns UPID | operation locks and UPID/task evidence |
| 10 | Poll task | Proxmox task terminal/running/ambiguous result | task status/log excerpt |
| 11 | Post-check | target node/status/config/fingerprint/active tasks | completed or needs_reconciliation |
| 12 | Reconcile preview | `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview` | read-only preview only |

## Final pre-check requirements

Final pre-check must verify recommendation evidence version, VM still at source locator, identity/fingerprint match, no conflicting task, source/target online, target storage/network compatibility, policy allowed, locks acquired, and no red blocker.

Blocked or Unknown gates must not call Proxmox migration.

## Reconciliation

Reconciliation is required when success/failure cannot be safely decided: timeout, unreadable Proxmox task, VM not found, fingerprint mismatch, stale lock, backend crash after UPID, unreadable post-check evidence. Current reconcile preview rereads Proxmox actual state and compares it to Gjallar operation records, but it does not run corrective mutation.
