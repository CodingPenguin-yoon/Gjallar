# Goal 10: DRS Live Migration Safety And Evidence

Status: candidate follow-on goal; not started. Start only if the user
explicitly selects this goal for the active session.

## Objective

Harden the narrow backend DRS migration execution path and define the evidence
contract for an optional approved live DRS smoke run.

This goal does not make live DRS migration mandatory. It prepares the safety
baseline that must exist before any broader execute UI or productized operator
flow is considered.

## Starting Point

- DRS identity/fingerprint, migration policy memory, identity/policy blockers,
  DB-backed operation lock lookup/acquisition/release, config-lock evidence,
  and read-only final pre-check are implemented.
- Local approval packet/job intent creation is implemented.
- A narrow operator-only backend execution route exists at
  `POST /api/v1/drs/migration-jobs/{job_id}/execute`.
- DRS execution stores UPID/task evidence and marks completion only after
  verified target-node status/config post-check, expected power-state evidence,
  matching DRS fingerprint, and no conflicting active task.
- Read-only Reconcile preview exists.
- Broad live execute UI, corrective reconcile UI, live DRS smoke evidence,
  richer policy rule/full metadata editor, 15-minute metrics, and deeper
  read-only task/HA/quorum collection remain gaps.

## Controlling References

Read these before starting:

- `docs/goal/README.md`
- `docs/goal/goal-05-drs-live-migration-upid-tracking.md`
- `docs/goal/goal-06-drs-post-check-reconciliation.md`
- `docs/current/README.md`
- `docs/current/top-tabs/05-placement-drs-advisor.md`
- `docs/current/top-tabs/06-jobs-runs.md`
- `docs/architecture/flows/drs-approve-migrate-reconcile.md`
- `docs/product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md`

Use the current checkout as authoritative. If implementation and this candidate
brief disagree, inspect code/tests first and keep this goal limited to the
smallest correction needed.

## Hard Constraints

- No live Proxmox mutation, smoke, live readiness check, cleanup, corrective
  action, or reconciliation mutation without explicit active-session approval
  for that specific run.
- Do not create `docs/operations/drs-live-migration-smoke-YYYY-MM-DD.md` during
  planning or dry-run work. Create it only during an actual approved live run.
- `192.168.2.140-150/24` is candidate selection guard only. It is not
  execution authority.
- VMID, IP, name, node, tag, and Create VM history are not stable identity.
- Proxmox task `OK` alone is not Gjallar success.
- Keep DRS execution authority separate from Create VM mutation authority.
- Unknown, stale, missing, conflicting, not-collected, or ambiguous evidence
  remains blocking before mutation.
- This goal must not add automatic DRS, bulk migration, recommendation-level
  migrate aliases, broad execute UI, corrective mutation, or background
  reconciliation automation.

## Scope

1. Harden the execute acknowledgement gate.
   - Require an explicit payload field such as
     `drs_live_migration_acknowledged=true` before mutation.
   - The payload must not be ignored; missing, false, malformed, or unexpected
     acknowledgement input must block before any Proxmox mutation call.
   - Tests must prove blocked acknowledgement states do not call the DRS
     migration client.
2. Define a runbook/checklist/evidence matrix for live DRS smoke readiness.
   - Cover candidate VM identity, policy, locator, source/target route,
     storage/network evidence, final pre-check, approval packet checksum,
     operation locks, live Proxmox evidence, UPID, task polling, post-check,
     and reconciliation state.
   - Make skipped, unavailable, stale, or unapproved evidence explicit.
3. Define the pre-mutation evidence packet contract.
   - The packet must be reviewable before mutation and must include the exact
     candidate, actor, requested move, recommendation/pre-check versions,
     approval binding, blockers, warnings, acknowledgement state, and lock
     intent.
4. Add dry-run/non-live validation for the hardened gates.
   - Fake/mock Proxmox validation is acceptable and expected before any live
     operation.
5. Optionally run one live DRS smoke only after explicit active-session
   approval for that exact run.
   - The live smoke remains optional. If not approved, Goal 10 can still close
     as safety baseline and dry-run evidence only.

## Candidate And Approval Protocol

- Candidate selection starts with a VM deliberately classified for DRS movement.
- The `192.168.2.140-150/24` range can narrow live-smoke candidates but cannot
  authorize execution.
- The operator must review high-confidence DRS identity/fingerprint evidence,
  current Proxmox locator, migration policy `allowed`, source/target route,
  storage/network evidence, final pre-check result, approval binding, and lock
  state.
- Approval must be active-session, run-specific, and recorded with actor,
  timestamp, target VM identity, source node, target node, and acknowledged
  risk.
- Cleanup, corrective action, reverse migration, or retry after ambiguity needs
  separate active-session approval for that specific operation.

## Pre-Mutation Evidence Packet

The packet should be compact and operator-readable. At minimum it must include:

- job id and approval packet id
- actor username/id/role from trusted session state
- `vm_identity_id`, confidence, and curated fingerprint summary
- supporting locator fields: node, VMID, name, IP, tags, and observation time
- source node and target node
- migration policy and policy audit reference
- recommendation id/version and final pre-check id/version/checksum
- blocker and warning lists with explicit stale/not-collected states
- expected Proxmox mutation path and request shape
- operation lock scopes to be acquired
- acknowledgement field and value
- side-effect summary

## Dry-Run/Non-Live Validation

Dry-run validation should prove:

- missing/false acknowledgement blocks before mutation
- blocked identity, policy, final pre-check, approval, stale job, cancelled job,
  existing lock, stale locator, and live evidence failures block before mutation
- successful fake execution stores UPID/task evidence and still requires
  verified post-check before completion
- task `OK` without verified post-check remains `needs_reconciliation`
- read-only Reconcile preview does not perform corrective mutation

## Live Smoke Procedure

Do not run this procedure unless the user explicitly approves the specific live
run in the active session.

If approved, the run should:

1. Select one candidate VM that is safe to move and deliberately classified for
   DRS movement.
2. Capture the pre-mutation evidence packet and operator approval.
3. Confirm `drs_live_migration_acknowledged=true` or the final implemented
   acknowledgement field.
4. Execute only the stored approved migration job through the narrow backend
   route.
5. Record UPID and task status/log evidence immediately.
6. Verify target-node status/config, expected power state, matching DRS
   fingerprint, and absence of conflicting active task.
7. Classify failure, ambiguity, timeout, wrong target, unexpected power state,
   fingerprint mismatch, or missing evidence as `needs_reconciliation`.
8. Write the operations evidence file only for the actual approved run.

## Evidence Record Contract

Evidence must be sanitized, compact, and durable enough for later review:

- no secrets, tokens, raw credentials, private keys, raw session data, or large
  unredacted Proxmox payloads
- explicit actor, timestamp, route, target, policy, approval, lock, task, and
  post-check evidence
- explicit result classification: blocked, accepted, running, completed,
  failed, timed out, ambiguous, or needs reconciliation
- explicit statement that Proxmox task `OK` alone is not success
- explicit statement of any cleanup or corrective action that was not approved
  and therefore not performed

## Reconciliation And Failure Handling

- Keep ambiguous outcomes conservative.
- Do not release operation locks as success unless verified post-check passes.
- `needs_reconciliation` and `reconciliation_required` must remain visible to
  Jobs/Runs and DRS readiness surfaces.
- Reconcile preview remains read-only.
- Corrective mutation, cleanup, retry, rollback, or reverse migration requires
  separate active-session approval for that exact operation.

## Out Of Scope

- Broad live execute UI.
- Corrective reconcile UI.
- Corrective reconciliation mutation.
- Background reconciliation automation.
- Automatic DRS or scheduled balancing.
- Bulk migrations.
- Richer policy rule/full metadata editor.
- 15-minute average/peak metrics.
- Deeper read-only task/HA/quorum collection beyond what is needed to preserve
  existing execute safety.

## Definition Of Done

- Goal 10 is still documented as candidate/not started until selected and
  implemented.
- The execute route requires an explicit DRS live migration acknowledgement
  payload before mutation.
- A runbook/checklist/evidence matrix exists for optional live DRS smoke.
- Pre-mutation evidence packet shape is documented and validated.
- Focused tests prove the acknowledgement and safety gates block before
  Proxmox mutation.
- If no live run is approved, docs clearly state that no live DRS smoke was run.
- If a live run is approved and performed, evidence is recorded in the
  operations file for that actual run only.

## Suggested Validation

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/jobs backend/tests/db
node --test frontend/tests/drsAdvisor.test.mjs frontend/tests/apiV1Client.test.mjs
git diff --check
```

For a docs-only Goal 10 planning update, run the requested document checks and
`git diff --check`.
