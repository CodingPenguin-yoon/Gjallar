# Goal Guide: Remaining Gjallar Operations Work

## Role In The Goal Set

Use `docs/goal/README.md` as the canonical entrypoint before starting work.
This file is only the concise overall operations backlog, status, validation,
commit/push, and risk overview. Detailed goal scope lives in the Goal 1 through
Goal 11 documents, plus inserted Goal 7.5, linked below. Goal 10 safety
baseline and approved VMID `140` live DRS evidence are complete; the old Goal
11/12 split is superseded by the rewritten Goal 11 criteria/operations brief.

## Starting Point

- Session auth/RBAC was committed and pushed as `e7b4d13`.
- Local account operations were committed and pushed as `7b0a77c`.
- Operations-console stabilization instructions were committed as `99874b1`.
- Admin user management UI/API and legacy-doc cleanup were committed and
  pushed as `7b1ce8a`.
- Current local user management includes CLI commands `create-admin`,
  `create-user`, `list-users`, `set-role`, `disable-user`, and
  `reset-password`; UI route `/admin/users`; and API surface
  `/api/v1/admin/users*`.
- Admin local account/session operations support
  list/create/role/disable/reset-password, admin session inventory/revocation,
  self password change, and sanitized account/session audit metadata. Disable
  and reset-password revoke the target user's sessions; role changes do not
  revoke sessions.
- Create VM supports default `stopped` creation and optional
  `boot_and_verify`. Approved live Proxmox smoke completed on 2026-05-28 and
  is recorded in `docs/operations/create-vm-live-smoke-2026-05-28.md`.
- DRS identity/fingerprint, migration policy memory, identity/policy blockers,
  DB-backed operation lock lookup, config-lock evidence, and a read-only final
  pre-check model are implemented.
- DRS approval/job substrate, narrow live migration execution with UPID/task
  tracking, and post-check/reconciliation are implemented.
- Goal 7 DRS UI/operations polish completed the minimal safe UI slice.
- Goal 7.5 DRS VM policy configuration completed the manual policy UI/API and
  local audit evidence slice.
- Goal 8 Post-Create Readiness Evidence completed the minimal local-only
  recorder for opt-in sanitized evidence on already-created VMs. Create VM
  success is unchanged; future live readiness checks remain deferred and require
  explicit active-session approval.
- Goal 9 account/session polish is complete for the local auth/session model.
- Goal 10 DRS Live Migration Safety And Evidence is complete: the execute
  acknowledgement gate, optional live smoke readiness matrix, approved VMID `140`
  live migration, verified post-check, stored-UPID reconciliation follow-up, and
  lock release are recorded.
- Goal 11 DRS Criteria And Operations Productization is the rewritten follow-on,
  not mandatory or started work.
- Goal 12 is superseded and retained only as a historical pointer.

## Non-Negotiables

- no live Proxmox mutation, smoke, live readiness check, cleanup, corrective
  action, or reconciliation mutation without explicit active-session user
  approval for that specific run
- 192.168.2.140-150/24 is candidate selection guard only
- VMID/IP/name/node/tag/Create VM history alone is not stable identity
- Proxmox task OK alone is not Gjallar success
- Do not add public signup.
- Do not add OAuth, SSO, 2FA, email reset, or API tokens unless a later goal
  explicitly asks for them.
- Keep DRS execution authority separate from Create VM mutation authority.
- Follow `AGENTS.md`: main session coordinates; for non-trivial work delegate
  explorer, reviewer, docs_researcher, then worker; only worker edits code.
- Prefer small, cohesive, production-oriented changes over broad rewrites.

## Recommended Order

1. Goal 10 documentation/evidence close-out if the current worktree has not yet
   been committed and pushed.
2. Goal 11: DRS Criteria And Operations Productization, when the user selects
   the next goal-sized DRS slice.
3. Any hardening/decision-quality slice explicitly selected inside Goal 11 or a
   later newly defined goal.
4. Any other explicitly requested task from `docs/goal/README.md`.

## Completed Non-Goal Gate

The non-numbered Goal Check verified that Goal 1 through Goal 6 were genuinely
implemented, production-quality, and not test-shaped or docs-only before Goal 7
UI/operations polish started. Goal 7 is now complete as a minimal safe UI slice.

## Goal Table

| Goal | Status | Detailed document |
| --- | --- | --- |
| Goal 1: Create VM Live Smoke Matrix | Completed | `docs/goal/goal-01-create-vm-live-smoke-matrix.md` |
| Goal 2: DRS Identity And Final Pre-Check Preparation | Completed | `docs/goal/goal-02-drs-identity-final-precheck-preparation.md` |
| Goal 3: DRS Final Pre-Check And Operation Lock Foundation | Completed | `docs/goal/goal-03-drs-final-precheck-operation-lock-foundation.md` |
| Goal 4: DRS Approval And Migration Job Substrate | Completed | `docs/goal/goal-04-drs-approval-migration-job-substrate.md` |
| Goal 5: DRS Live Migration Execution And UPID Tracking | Completed | `docs/goal/goal-05-drs-live-migration-upid-tracking.md` |
| Goal 6: DRS Post-Check And Reconciliation | Completed | `docs/goal/goal-06-drs-post-check-reconciliation.md` |
| Goal Check: Goal 1-6 Implementation Verification And Quality Audit | Completed | `docs/goal/goal-check-01-06-implementation-quality.md` |
| Goal 7: DRS UI And Operations Polish | Completed | `docs/goal/goal-07-drs-ui-operations-polish.md` |
| Goal 7.5: DRS VM Policy Configuration | Completed | `docs/goal/goal-07-5-drs-vm-policy-management.md` |
| Goal 8: Post-Create Readiness Evidence | Completed: minimal local-only recorder slice | `docs/goal/goal-08-post-create-readiness-evidence.md` |
| Goal Check: Current Implementation Validation Before Goal 9 | Completed: pass-with-risk | `docs/goal/goal-check-current-implementation-validation.md` |
| Goal 9: Account/Session Operations Polish | Completed | `docs/goal/goal-09-account-session-operations-polish.md` |
| Goal 10: DRS Live Migration Safety And Evidence | Completed with approved VMID `140` live evidence | `docs/goal/goal-10-drs-live-migration-safety-evidence.md` |
| Goal 11: DRS Criteria And Operations Productization | Rewritten follow-on / not started | `docs/goal/goal-11-drs-operations-productization.md` |
| Goal 12: Superseded Platform Hardening And Decision Quality Brief | Superseded | `docs/goal/goal-12-platform-hardening-decision-quality.md` |

## Standard Validation

Run after code changes unless the goal explicitly narrows validation:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
node --test frontend/tests/*.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```

For docs-only restructuring, run the requested document checks and
`git diff --check`.

## Commit And Push

- Commit coherent finished work after review.
- Push to `origin/main` only when the main session or user asks for it.
- Leave the working tree clean after the commit/push step.

## Remaining Risks

- Any future live Create VM smoke, cleanup, DRS migration smoke, live readiness
  check, corrective action, or reconciliation mutation still needs explicit
  active-session approval for that specific run.
- Background reconciliation automation and corrective reconciliation mutation
  remain deferred. VMID `140` cleanup, reverse migration, retry, or deletion also
  remains separate approval-gated live mutation work.
- The DRS advisor read-only final pre-check adapter still reports some active
  task, HA, and quorum evidence as explicit `not_collected`; execution collects
  live pre-mutation checks separately.
- Future live post-create readiness checks remain deferred, approval-gated, and
  separate from Create VM success.
- Account/session audit browsing UI/API remains deferred; Goal 9 records and
  returns sanitized audit metadata on the implemented mutation responses.
- Broad live DRS execute UI, corrective reconcile UI, richer policy rule/full
  metadata editor, 15-minute metrics, deeper read-only task/HA/quorum collection,
  and backend-owned blocker taxonomy remain gaps for the rewritten Goal 11 or
  later hardening slices.
