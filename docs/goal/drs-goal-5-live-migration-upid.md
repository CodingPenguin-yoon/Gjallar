# Goal 5: DRS Live Migration Execution And UPID Tracking

## Session Prompt Source

Use this file as the detailed task brief for the next DRS goal session.
The short goal prompt can point here instead of embedding the full instructions.

## Controlling References

Read these first:

- `docs/goal/drs-execution-goal-slices.md`
- `docs/goal/drs-goal-4-approval-job-substrate.md`
- `docs/goal/drs-safe-execution-readiness-foundation.md`
- `docs/current/top-tabs/05-placement-drs-advisor.md`
- `backend/app/drs/advisor.py`
- `backend/app/drs/approval.py`
- `backend/app/drs/identity.py`
- `backend/app/drs/operation_locks.py`
- `backend/app/jobs/runs.py`
- `backend/app/db/models.py`
- `backend/tests/drs`
- `backend/tests/contracts/test_api_v1_drs.py`
- `backend/tests/jobs/test_runs.py`

Use the current worktree as authoritative. If Goal 5 work is already present,
inspect it, verify it against this brief, and continue from the actual current
state instead of restarting.

## Objective

Open the first narrow live migration execution path after identity, policy,
final pre-check, approval, operation locks, and job state are in place.

## Hard Constraints

- Add a dedicated DRS Proxmox migration mutation path separate from read-only
  inventory and separate from Create VM mutation authority.
- Do not reuse Create VM mutation clients, permissions, endpoints, or job
  semantics for DRS migration execution.
- Migration execution must require all gates before any Proxmox mutation call:
  - high-confidence VM identity
  - migration policy `allowed`
  - passing final pre-check
  - valid approval packet bound to the recommendation and pre-check evidence
  - acquired active operation lock
- Preserve Goal 2, Goal 3, and Goal 4 blockers. Unknown, stale, conflicting,
  missing, or not-collected evidence must remain blocking.
- Store Proxmox UPID and task metadata once the mutation is accepted.
- Poll task status/log only enough to classify the immediate result.
- Mark failure, timeout, missing UPID, or ambiguity as `needs_reconciliation`;
  do not represent it as success.
- Do not add automatic DRS, bulk migration, rollback, remediation automation, or
  broad UI.
- Do not store large raw Proxmox inventory/config/task blobs.

## Expected Result

- A narrow backend execution path can start one approved DRS migration.
- Blocked recommendations cannot reach the Proxmox mutation client.
- Proxmox live migration mutation is limited to the migration API path.
- UPID and task evidence are visible in job/readiness output.
- Job state distinguishes accepted, running, failed, timed out, ambiguous, and
  needs-reconciliation outcomes.
- Operation lock behavior remains conservative and never releases safety state
  as success on ambiguous evidence.
- Focused tests prove missing gates and blocked states do not call mutation
  APIs.

## Out Of Scope

- Automatic DRS.
- Bulk migrations.
- Complex placement rules.
- Full post-check and reconciliation workflow beyond the minimum state needed
  to avoid false success.
- Reconcile Now or corrective mutation.
- Broad execution UI polish.

## Suggested Validation

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/db backend/tests/jobs
node --test frontend/tests/drsAdvisor.test.mjs
git diff --check
```
