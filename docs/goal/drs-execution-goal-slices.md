# DRS Execution Goal Slices

## Purpose

This document is the DRS execution sub-index for Goal 3 through Goal 7.
Use `docs/goal/README.md` first for the canonical Goal 1 through Goal 9 map,
then use this file for DRS execution details.

Do not treat this file as a separate top-level backlog. It intentionally does
not define Goal 1, Goal 2, Goal 8, or Goal 9.

Before starting any new DRS goal, read this file together with:

- `docs/goal/drs-safe-execution-readiness-foundation.md`
- `docs/current/top-tabs/05-placement-drs-advisor.md`
- `docs/product/drs-advisor/03_DATA_DB_AND_IDENTITY.md`
- `docs/product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md`
- `docs/engineering/drs-safe-execution-readiness-foundation-implementation.md`

## Current Baseline

Completed foundation:

- DB-backed VM identity records, identity observations, and migration policy.
- Read-only identity resolver from curated Proxmox inventory evidence.
- Identity and policy blockers in DRS recommendation output.
- Read-only final pre-check output on
  `POST /api/v1/drs/recommendations/{recommendation_id}/check`.
- Goal 3 operation lock foundation:
  - `operation_locks` schema/model exists for `drs_migration`.
  - Final pre-check performs read-only lock lookup for VM identity, Proxmox
    locator (`cluster_id + vmid`), and route scopes.
  - `active`, `stale`, and `reconciliation_required` locks block
    `would_be_executable`; `released` locks do not block.
- Config-lock evidence is collected from curated VM config fields and blocks
  final pre-check when present.
- Active task, HA state, and cluster quorum/health are explicit
  `not_collected` read-only evidence in the current adapter.
- Local DRS approval packet and pending `drs_migration` job intent substrate
  exist for passing final pre-checks, bound to compact recommendation and
  final-precheck checksums. These records are local evidence only:
  `runnable=false`, `proxmox_mutation_enabled=false`, and `side_effects=[]`.
- Goal 5 live migration execution and UPID tracking exists as a narrow backend
  path:
  - dedicated DRS migration client separate from Create VM mutation authority
  - approval/final-pre-check/lock gates before mutation
  - UPID/task metadata storage
  - conservative `needs_reconciliation` handling for ambiguous outcomes
- Goal 6 post-check and reconciliation exists:
  - completion requires Proxmox task `OK` plus direct target-node status/config
    post-check, matching fingerprint, expected power state, and no conflicting
    active task
  - operation locks release only after verified post-check
  - ambiguous outcomes stay `needs_reconciliation` and locks become
    `reconciliation_required`
  - read-only Reconcile preview exists before any corrective mutation
- DRS UI shows compact identity and policy evidence.
- Goal 5 and Goal 6 validation used automated fake/mock tests. No live Proxmox
  DRS migration smoke has been run yet.

Known remaining gaps:

- Corrective reconciliation mutation and background reconciliation automation
  remain deferred.
- The read-only advisor final pre-check adapter still reports some active
  task, HA, and quorum evidence as explicit `not_collected`; the execution path
  collects live pre-mutation checks separately.
- Approval UI and broad execution UI polish are not implemented.
- A live DRS migration smoke run is still pending explicit user approval in a
  future active session.

## Standing Non-Negotiables

- Do not broaden live migration execution beyond the Goal 5 narrow backend
  path unless a later goal explicitly scopes it.
- Do not run live Proxmox mutation or smoke without explicit user approval in
  the active session.
- Do not call Proxmox mutation APIs from read-only foundation goals.
- Keep DRS execution authority separate from Create VM mutation authority.
- Proxmox current state remains the source of truth for VM/node/task/HA/storage
  state.
- Default migration policy remains `unknown` and execution-blocking.
- Low, medium, or unknown VM identity confidence remains execution-blocking.
- Do not treat VMID, node, name, tag, IP, or Create VM records alone as stable
  identity.
- Do not store large raw Proxmox inventory or config blobs.
- Do not add broad policy UI or a complex rule engine unless a later goal
  explicitly scopes it.

## Recommended Order

Completed:

- Goal 3 DRS Final Pre-Check And Operation Lock Foundation.
- Goal 4 DRS Approval And Migration Job Substrate as local-only substrate.
- Goal 5 DRS Live Migration Execution And UPID Tracking.
- Goal 6 DRS Post-Check And Reconciliation.

Next remaining goals:

1. Goal 7: DRS UI And Operations Polish.
2. Optional approved live DRS migration smoke evidence recording.

The order matters. Goal 5 opened only the narrow execution path with UPID
tracking, and Goal 6 made completion dependent on verified post-check evidence.
Goal 7 should expose that lifecycle clearly without weakening backend gates.

## Live Migration Smoke Target Guard

The approved Create VM smoke range remains the candidate range for a future DRS
live migration smoke:

- Static network: `192.168.2.140-150/24`
- Gateway: `192.168.2.1`
- Bridge used in the recorded smoke: `vmbr0`
- Evidence source:
  `docs/operations/create-vm-live-smoke-2026-05-28.md`

Use this range only to narrow test VM candidates. It is not execution
authority. A live migration still requires high-confidence identity/fingerprint,
current Proxmox locator, migration policy `allowed`, passing final pre-check,
valid approval, operation lock, and explicit active-session user approval.

## Goal 3: DRS Final Pre-Check And Operation Lock Foundation

Status: completed as a read-only foundation. Operation lock schema/model,
read-only lock lookup, config-lock evidence, and explicit `not_collected`
active task/HA/quorum evidence are implemented. At Goal 3 completion, lock
acquisition/release, live migration, UPID tracking, post-check, and
reconciliation were future goals. Goal 5 later added the narrow mutation and
UPID path; Goal 6 later added verified post-check and reconciliation state.

### Objective

Close the largest remaining pre-execution safety gap by adding DB-backed
operation locks and stronger read-only final pre-check evidence. This goal still
must not execute migration.

### Scope

1. Add a small `operation_locks` DB model and Alembic migration.
2. Define lock scopes:
   - VM identity lock
   - Proxmox VM locator lock: cluster + VMID
   - optional route lock: source node + target node
3. Define lock states:
   - `active`
   - `released`
   - `stale`
   - `reconciliation_required`
4. Extend DRS final pre-check to replace `operation_lock: not_implemented`
   with real Gjallar-local lock checks.
5. Add read-only Proxmox conflict evidence where current inventory supports it:
   - active task signal if available
   - config lock signal if available
   - HA state if available
   - cluster health/quorum if available
6. Keep unsupported Proxmox evidence explicit as `not_collected` or
   `not_implemented`; do not fake a healthy signal.
7. Add blockers for active/stale locks and known conflict evidence.
8. Add focused backend tests and docs.

### Out Of Scope

- Approval modal or approval endpoint.
- `drs_migration` job creation.
- Proxmox live migration mutation.
- UPID tracking.
- Reconciliation worker.
- Bulk policy UI.

### Definition Of Done

- Operation lock schema and model exist.
- Final pre-check reports operation lock state from DB.
- Active, stale, or reconciliation-required locks block
  `would_be_executable`.
- Released locks do not block final pre-check.
- Config-lock evidence is collected and blocks when present.
- Current Proxmox conflict evidence is represented as read-only checks.
- Unknown/uncollected conflict evidence is explicit and not treated as healthy.
- For this goal, `executable` remains false and no Proxmox mutation path is
  added.
- Focused backend tests and docs pass/update.

### Suggested Validation

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/db backend/tests/proxmox
node --test frontend/tests/drsAdvisor.test.mjs
git diff --check
```

## Goal 4: DRS Approval And Migration Job Substrate

Status: completed as local-only substrate. Live migration remained closed for
Goal 4 and was later opened only through the narrow Goal 5 backend path.

### Objective

Add the local approval and job state needed before a future migration mutation
can be safely started. This goal should still avoid live migration execution.

### Scope

1. Add approval packet model or table for DRS recommendations.
2. Record exact recommendation/pre-check evidence version or checksum.
3. Add warning acknowledgement fields.
4. Add `drs_migration` job state shape without starting Proxmox migration.
5. Add job/risk output fields:
   - recommendation id
   - VM identity id
   - source node
   - target node
   - approved actor
   - final pre-check summary
   - lock ids
6. Add read-only API output for approval readiness.
7. Add tests proving blocker/unknown states do not create runnable jobs.

### Out Of Scope

- Proxmox live migration mutation.
- UPID tracking.
- Task polling.
- Post-check.
- Corrective reconciliation action.

### Definition Of Done

- Approval packet cannot be created or treated as runnable unless identity,
  policy, locks, and final pre-check pass.
- Approval evidence is bound to current recommendation/pre-check evidence.
- Jobs/Runs can represent a pending DRS migration intent without mutation.
- No Proxmox mutation API is called.

## Goal 5: DRS Live Migration Execution And UPID Tracking

Status: completed on 2026-05-30. Standalone brief:
`docs/goal/drs-goal-5-live-migration-upid.md`.

### Objective

Open the first narrow live migration execution path after identity, policy,
final pre-check, approval, operation locks, and job state are in place.

### Scope

1. Add a dedicated DRS Proxmox migration mutation client separate from read-only
   inventory.
2. Require:
   - high-confidence identity
   - migration policy `allowed`
   - passing final pre-check
   - valid approval packet
   - acquired active operation lock
3. Start Proxmox live migration only after all gates pass.
4. Store Proxmox UPID and task metadata.
5. Poll task status/log enough to classify immediate result.
6. Mark ambiguous results as `needs_reconciliation`.
7. Keep Create VM mutation authority separate.

### Out Of Scope

- Automatic DRS.
- Bulk migrations.
- Complex placement rules.
- Full reconciliation UI beyond the minimum state needed to avoid false
  success.

### Definition Of Done

- Migration cannot start without final pre-check, approval, and lock.
- Proxmox mutation is limited to the migration API path.
- UPID is stored and visible in job evidence.
- Failure, timeout, or ambiguity does not release safety state as success.
- Tests prove blocked conditions do not call Proxmox mutation APIs.

## Goal 6: DRS Post-Check And Reconciliation

Status: completed on 2026-05-30. Standalone brief:
`docs/goal/drs-goal-6-post-check-reconciliation.md`.

### Objective

Make migration outcomes trustworthy after task completion, timeout, or worker
restart.

### Implemented Scope

1. Post-check VM on target node after Proxmox task result.
2. Verify:
   - VM found on expected target
   - VM running or expected power state
   - fingerprint still matches expected identity
   - no conflicting task remains
3. Release locks only after safe terminal states.
4. Add reconciliation records/events.
5. Add `needs_reconciliation` behavior for:
   - task timeout
   - missing UPID
   - worker restart during migration
   - Proxmox task success but post-check mismatch
   - fingerprint mismatch
6. Add read-only Reconcile preview before any corrective mutation.
7. Keep `192.168.2.140-150/24` only as the candidate guard for a future
   approved live smoke. No live DRS migration smoke was run for Goal 6.

### Out Of Scope

- Automatic cleanup or deletion.
- Automatic rollback.
- Broad remediation automation.
- Live smoke without explicit active-session approval.

### Definition Of Done

- Proxmox task success alone is not enough for Gjallar success.
- Post-check must pass before job success and lock release.
- Ambiguous states become `needs_reconciliation`.
- Operators can see expected vs observed state.
- Read-only Reconcile preview exists and performs no corrective mutation.
- No live smoke evidence was recorded because no live smoke was run.

## Goal 7: DRS UI And Operations Polish

### Objective

Expose the DRS execution lifecycle clearly without weakening backend gates.

### Scope

1. Show final pre-check details and blockers.
2. Show operation lock status.
3. Add approval/confirm UI only after backend approval and job substrate exist.
4. Show migration job progress and UPID/task evidence.
5. Show post-check and reconciliation state.
6. Keep action buttons disabled or absent unless backend says the action is
   available.

### Out Of Scope

- UI-only execution enablement.
- Client-side bypass of backend gates.
- Broad policy editor unless explicitly scoped.

### Definition Of Done

- UI reflects backend authority, not local inference.
- No migration action appears before backend gates are implemented.
- Operators can understand why a recommendation is blocked or safe to proceed.

## Future Deferred Work

- Bulk policy classification.
- Tag-based policy defaults.
- Owner/team/environment metadata system.
- 15-minute average/peak metric storage and polling.
- Advanced placement scoring.
- Automatic DRS.
- Complex anti-affinity/rule engine.
