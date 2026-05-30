# Goal 7: DRS UI And Operations Polish

Status: pending after Goal Check.

Prerequisite: complete the non-numbered Goal Check in
`docs/goal/goal-check-01-06-implementation-quality.md`. Goal 7 must not start
until that check verifies Goal 1 through Goal 6 are genuinely implemented,
production-quality, and not test-shaped or docs-only.

## Objective

Expose the DRS execution, post-check, and reconciliation lifecycle clearly
without weakening backend gates.

## Current DRS Baseline

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
- The read-only advisor final pre-check adapter still reports some active task,
  HA, and quorum evidence as explicit `not_collected`; the execution path
  collects live pre-mutation checks separately.
- Approval UI and broad execution UI polish are not implemented.
- A live DRS migration smoke run is still pending explicit user approval in a
  future active session.

## Standing Non-Negotiables

- no live Proxmox mutation/smoke without explicit active-session user approval
- 192.168.2.140-150/24 is candidate selection guard only
- VMID/IP/name/node/tag/Create VM history alone is not stable identity
- Proxmox task OK alone is not Gjallar success
- Do not broaden live migration execution beyond the Goal 5 narrow backend
  path unless a later goal explicitly scopes it.
- Do not call Proxmox mutation APIs from read-only foundation paths.
- Keep DRS execution authority separate from Create VM mutation authority.
- Proxmox current state remains the source of truth for VM/node/task/HA/storage
  state.
- Default migration policy remains `unknown` and execution-blocking.
- Low, medium, or unknown VM identity confidence remains execution-blocking.
- Do not store large raw Proxmox inventory or config blobs.
- Do not add broad policy UI or a complex rule engine unless a later goal
  explicitly scopes it.

## Live Smoke Guard

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
valid approval, operation lock, verified post-check contract, and explicit
active-session user approval.

## Scope

1. Show final pre-check details and blockers.
2. Show operation lock status.
3. Add approval/confirm UI only after backend approval and job substrate exist.
4. Show migration job progress and UPID/task evidence.
5. Show post-check and reconciliation state.
6. Keep action buttons disabled or absent unless backend says the action is
   available.

## Out Of Scope

- UI-only execution enablement.
- Client-side bypass of backend gates.
- Broad policy editor unless explicitly scoped.
- Corrective reconciliation mutation.
- Background reconciliation automation.
- Automatic DRS.

## Definition Of Done

- UI reflects backend authority, not local inference.
- No migration action bypasses backend gates.
- Operators can understand why a recommendation is blocked or safe to proceed.
- Operators can see migration job progress, UPID/task evidence, post-check
  evidence, and reconciliation state when those backend fields exist.

## Future Deferred Work

- Bulk policy classification.
- Tag-based policy defaults.
- Owner/team/environment metadata system.
- 15-minute average/peak metric storage and polling.
- Advanced placement scoring.
- Automatic DRS.
- Complex anti-affinity/rule engine.
- Corrective reconciliation mutation.
- Background reconciliation automation.

## Suggested Validation

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/jobs
node --test frontend/tests/drsAdvisor.test.mjs frontend/tests/*.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```
