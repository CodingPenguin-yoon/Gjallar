# Target DRS Recommendation And Execution

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

This document describes target execution beyond the current read-only Phase 1 recommendation path.

## Current Baseline

Current `/drs` reads backend `/api/v1/drs/*` read-only endpoints; exposes no approval buttons; exposes no migration execution; and stores no DRS operation state.

## Target Recommendation Model

A target DRS recommendation should be a backend-owned record or read model.

| Field group | Target content |
|---|---|
| Recommendation identity | Stable recommendation id, generated time, evidence version/hash. |
| VM identity | Gjallar VM identity id, Proxmox VMID, source node, current fingerprint, identity confidence. |
| Candidate move | Source node, target node, intended migration mode, estimated effect. |
| Evidence | CPU/memory/load windows, storage compatibility, bridge/network compatibility, HA/lock/current task state. |
| Policy | Allowed target groups, exclusions, anti-affinity, maintenance windows, operator restrictions. |
| Blockers | Normalized red/yellow blockers with machine-readable codes. |
| Execution availability | False until red blockers are absent, approval exists, and final pre-check passes. |

## Target Approval And Final Pre-Check

Approval should record the exact recommendation evidence version. It should not start migration directly.

Immediately before migration, backend must reread current state and verify VM locator, Gjallar identity/fingerprint, task conflicts, power/status compatibility, source/target health, storage/network compatibility, policy permission, locks, and absence of red blockers.

If final pre-check fails, migration must not start.

## Target Migration Execution

The target execution path should create a DRS operation record, take locks, start Proxmox migration, record UPID, poll task state, post-check VM location/status/fingerprint, and then record completed, failed, or `needs_reconciliation`.

Locks should cover VM identity, Proxmox locator, source node, target node, and relevant storage/network resources when needed. Stale locks must block or require reconciliation.

## Target Jobs/Risks Integration

DRS execution should appear in Jobs/Runs as a first-class job type such as `drs_migration`. Risks/Alerts should include DRS blockers with source, blocked action, VM identity, evidence artifact, and required operator resolution.

## Explicitly Not Implemented

- Backend recommendation service.
- Target API routes.
- DB identity/fingerprint/policy/lock tables.
- Approval records for DRS recommendations.
- Final pre-check route.
- Migration mutation client.
- UPID tracking for DRS.
- DRS operation artifacts.
- Reconcile Now backend.
