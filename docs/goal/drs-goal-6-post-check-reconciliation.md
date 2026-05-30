# Goal 6: DRS Post-Check And Reconciliation

Status: completed on 2026-05-30. No live Proxmox DRS migration smoke was run
as part of Goal 6.

## Session Prompt Source

Use this file as the Goal 6 implementation brief and review reference. Reopen
it for implementation only if Goal 6 changes are missing from the current
checkout.

## Starting Point

Goal 5 added the first narrow backend path for approved DRS live migration
execution and Proxmox UPID/task tracking. The Goal 5 validation was automated
fake/mock validation. It did not run an actual live Proxmox migration smoke.

Goal 6 now makes the outcome trustworthy after task completion, timeout,
restart, or ambiguous evidence. DRS migration completion requires Proxmox task
`OK` plus direct target-node status/config post-check, expected power-state
evidence, matching DRS fingerprint, and no conflicting active task. Ambiguous
outcomes stay `needs_reconciliation`; locks release only after verified
post-check. A read-only Reconcile preview exists.

Use the current checkout as authoritative. If Goal 5 work is already present,
inspect it, verify it against `docs/goal/drs-goal-5-live-migration-upid.md`,
and continue from the actual current state instead of restarting.

## Controlling References

Read these first:

- `docs/goal/README.md`
- `docs/goal/drs-execution-goal-slices.md`
- `docs/goal/drs-goal-5-live-migration-upid.md`
- `docs/current/top-tabs/05-placement-drs-advisor.md`
- `docs/operations/create-vm-live-smoke-2026-05-28.md`
- `backend/app/drs/execution.py`
- `backend/app/drs/operation_locks.py`
- `backend/app/drs/approval.py`
- `backend/app/proxmox/drs_migration.py`
- `backend/app/jobs/runs.py`
- `backend/app/api/v1/router.py`
- `backend/app/db/models.py`
- `backend/tests/drs`
- `backend/tests/contracts/test_api_v1_drs.py`
- `backend/tests/jobs/test_runs.py`

## Objective

Make DRS migration completion trustworthy by requiring Proxmox actual-state
post-check evidence before Gjallar marks a migration successful or releases
safety state as complete.

## Live Migration Test Target Guard

The known test VM IP range from prior approved Create VM smoke is:

- `192.168.2.140-150/24`
- Gateway `192.168.2.1`
- Bridge `vmbr0`
- Recorded smoke VMs included VMIDs `137`, `138`, and `139` on
  `yoonserver3`, with final status `stopped` at the time of the
  2026-05-28 smoke.

For Goal 6, this range is only a candidate-selection guard for a future live
migration smoke. It must not be used as the authority to execute migration.

Before any live migration smoke:

1. Get explicit user approval in the active session.
2. Re-read Proxmox current state; do not rely on the 2026-05-28 snapshot.
3. Confirm the selected VM is test/disposable.
4. Confirm high-confidence DRS identity/fingerprint match.
5. Confirm current source node, target node, storage, network, HA, task, and
   quorum/pre-check evidence.
6. Confirm migration policy is `allowed` and final pre-check passes.
7. Confirm approval packet and operation lock are current.

IP range, VMID, name, node, tag, or Create VM history alone is not enough.

## Hard Constraints

- Do not run live Proxmox mutation or smoke without explicit user approval in
  the active session.
- Proxmox task `OK` alone is not Gjallar success.
- Release operation locks as completed only after a safe post-check terminal
  state.
- Preserve `needs_reconciliation` for timeout, missing UPID, missing task,
  worker restart ambiguity, post-check mismatch, fingerprint mismatch, or
  unknown Proxmox evidence.
- Keep DRS migration execution separate from Create VM mutation authority.
- Do not add automatic rollback, cleanup, delete, or corrective mutation.
- Do not store large raw Proxmox inventory/config/task blobs.

## Implemented Scope

1. Add a compact DRS migration post-check result model.
2. Read Proxmox actual state after a migration task reaches a terminal result.
3. Verify at minimum:
   - VM exists on expected target node
   - VM is in the expected running/power state
   - fingerprint still matches the expected DRS identity
   - no conflicting migration/task evidence remains
4. Persist expected vs observed post-check evidence in job output/artifacts.
5. Keep or set `needs_reconciliation` when evidence is missing, stale,
   conflicting, or ambiguous.
6. Release locks only when the job has a safe terminal state.
7. Add reconciliation records/events for ambiguous or drift states.
8. Add read-only Reconcile preview before any corrective mutation.
9. Surface post-check and reconciliation state in Jobs/Runs and DRS readiness
   output.
10. Add focused tests with fake Proxmox/task/inventory adapters.

## Out Of Scope

- Automatic DRS.
- Bulk migrations.
- Automatic rollback.
- Automatic cleanup or deletion.
- Corrective reconciliation mutation.
- Broad policy UI.
- Final UI polish beyond backend state needed for operators to understand the
  outcome.

## Implemented Result

- A migration job is successful only when Proxmox task evidence and
  actual-state post-check both pass.
- Task failure, timeout, missing UPID, restart ambiguity, wrong target,
  unexpected power state, fingerprint mismatch, or unknown evidence becomes
  `needs_reconciliation` or failed according to the documented contract.
- Operators can see expected vs observed state.
- Lock release is conservative and tied to verified terminal outcomes.
- DRS readiness surfaces reconciliation state through operation-lock evidence
  and `approval_readiness.reconciliation`.
- A future live smoke can use `192.168.2.140-150/24` to pick a test candidate,
  but still needs identity, policy, pre-check, approval, lock, and explicit
  user approval.
- No live DRS migration smoke was run for this implementation.

## Suggested Validation

Run focused validation first:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/db backend/tests/jobs
node --test frontend/tests/drsAdvisor.test.mjs
git diff --check
```

Before any future approved live smoke, also run the relevant full backend suite:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
```

If a live DRS migration smoke is approved and executed, record sanitized
evidence in a new file under `docs/operations/`, for example:

```text
docs/operations/drs-live-migration-smoke-YYYY-MM-DD.md
```
