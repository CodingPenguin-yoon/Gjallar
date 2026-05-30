# Goal 4: DRS Approval And Migration Job Substrate

Status: completed. This file is retained as the Goal 4 implementation brief
and review reference. The next active DRS goal is tracked from
`docs/goal/README.md`.

## Session Prompt Source

Use this file as the detailed task brief only when reviewing or repairing Goal
4 work. Do not use it as the next active DRS goal unless Goal 4 changes are
missing from the worktree.

## Controlling References

Read these first:

- `docs/goal/drs-execution-goal-slices.md`
- `docs/goal/drs-safe-execution-readiness-foundation.md`
- `docs/current/top-tabs/05-placement-drs-advisor.md`
- `backend/app/drs/advisor.py`
- `backend/app/drs/identity.py`
- `backend/app/drs/operation_locks.py`
- `backend/app/db/models.py`
- `backend/alembic/versions/20260528_0019_drs_identity_policy.py`
- `backend/alembic/versions/20260528_0020_drs_operation_locks.py`
- `backend/tests/drs`
- `backend/tests/contracts/test_api_v1_drs.py`
- `backend/tests/db/test_drs_identity_schema.py`

Use the current worktree as authoritative. If Goal 4 work is already present,
inspect it, verify it against this brief, and continue from the actual current
state instead of restarting.

## Objective

Add the local approval and job state needed before a future DRS live migration
mutation can be safely started.

This goal must still avoid live migration execution.

## Hard Constraints

- Do not implement live migration execution.
- Do not call Proxmox migration mutation APIs.
- Keep DRS execution authority separate from Create VM mutation authority.
- Preserve Goal 2 and Goal 3 safety gates:
  - high-confidence VM identity required
  - default unknown migration policy remains blocking
  - low, medium, or unknown VM identity confidence remains blocking
  - operation locks block when `active`, `stale`, or
    `reconciliation_required`
  - unsupported Proxmox conflict evidence stays explicit and is not treated as
    healthy
- Do not add UPID tracking, task polling, post-check, reconciliation worker, or
  live migration UI.
- Do not store large raw Proxmox inventory/config blobs.
- Keep recommendation/check output execution closed unless a later goal opens
  it: `executable=false`, `allowed_actions=[]`.

## Expected Result

- Local approval packet/checksum model or table for DRS recommendations.
- Approval evidence is bound to exact recommendation and final pre-check
  evidence.
- Warning acknowledgement fields are represented.
- A `drs_migration` job state shape exists without starting Proxmox migration.
- Read-only job/readiness output includes:
  - recommendation id
  - VM identity id
  - source node
  - target node
  - approved actor
  - final pre-check summary
  - relevant lock ids/evidence
- Tests prove blocked or unknown states do not create runnable jobs and do not
  call Proxmox mutation APIs.
- Focused backend tests and docs are updated.

## Out Of Scope

- Proxmox live migration mutation.
- UPID tracking.
- Task polling.
- Post-check.
- Reconciliation worker.
- Live migration button or execution UI.

## Suggested Validation

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/db backend/tests/jobs
node --test frontend/tests/drsAdvisor.test.mjs
git diff --check
```
