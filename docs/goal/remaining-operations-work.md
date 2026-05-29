# Goal Guide: Remaining Gjallar Operations Work

## Starting Point

- Session auth/RBAC was committed and pushed as `e7b4d13`.
- Local account operations were committed and pushed as `7b0a77c`.
- Operations-console stabilization instructions were committed as `99874b1`.
- Admin user management UI/API and legacy-doc cleanup were committed and pushed as `7b1ce8a`.
- Current local user management includes:
  - CLI: `create-admin`, `create-user`, `list-users`, `set-role`, `disable-user`, `reset-password`
  - UI: `/admin/users`
  - API: `/api/v1/admin/users*`
  - Last enabled admin protection in shared service logic
- Create VM supports default `stopped` creation and optional `boot_and_verify`.
  Approved live Proxmox smoke completed on 2026-05-28 and is recorded in
  `docs/operations/create-vm-live-smoke-2026-05-28.md`.
- DRS Safe Execution Readiness Foundation is implemented. DRS now has
  DB-backed VM identity observations, migration policy memory, identity/policy
  blockers, DB-backed operation lock lookup, config-lock evidence, and a
  read-only final pre-check model. Live migration execution, operation lock
  acquisition/release, approval/job substrate, UPID tracking, and reconciliation
  are still deferred.

## Non-Negotiables

- Do not run live Proxmox mutation or smoke without explicit user approval in the active session.
- Do not add public signup.
- Do not add OAuth, SSO, 2FA, email reset, or API tokens unless a later goal explicitly asks for them.
- Keep DRS execution authority separate from Create VM mutation authority.
- Follow `AGENTS.md`: main session coordinates; for non-trivial work delegate explorer, reviewer, docs_researcher, then worker; only worker edits code.
- Prefer small, cohesive, production-oriented changes over broad rewrites.

## Recommended Goal Order

Next remaining goal:

1. DRS approval and migration job substrate. Detailed DRS slice guide:
   `docs/goal/drs-execution-goal-slices.md`.
2. DRS live migration execution and UPID tracking.
3. DRS post-check and reconciliation.
4. SSH/Ansible/app bootstrap readiness, if still desired after DRS safety work.
5. Account/session operations polish.

Completed:

- Create VM live smoke matrix and result recording.
- DRS Safe Execution Readiness Foundation:
  `docs/goal/drs-safe-execution-readiness-foundation.md`.
- DRS final pre-check and operation lock foundation:
  `docs/goal/drs-execution-goal-slices.md`.

## Goal 1: Create VM Live Smoke Matrix

Status: completed on 2026-05-28. Evidence is recorded in
`docs/operations/create-vm-live-smoke-2026-05-28.md`.

Primary objective: prove the current Create VM path against a real Proxmox target, record evidence, and update docs without expanding product scope.

### Scope

1. Read current runbook and Create VM docs:
   - `docs/operations/runbook.md`
   - `docs/current/README.md`
   - `docs/current/top-tabs/04-create-vm.md`
   - `docs/architecture/VM_PROVISIONING_CONTRACT.md`
   - `docs/engineering/NEXT_SESSION_HANDOFF.md`
2. Confirm target details with the user before mutation:
   - Proxmox cluster/API URL
   - target node
   - template VMID/node
   - storage
   - bridge
   - VMID/name range
   - static IP/DHCP choice
   - cleanup policy
3. Before live mutation, run non-live validation:
   - `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/contracts backend/tests/vm_create backend/tests/proxmox`
   - `node --test frontend/tests/createVmFlow.test.mjs`
   - `git diff --check`
4. With explicit approval, run and record:
   - default `stopped` creation
   - `boot_and_verify` creation with DHCP or approved network values
   - static IP creation with explicit `static_ip`, `prefix`, and `gateway`
   - one invalid target combination to verify operator-facing failure behavior
5. For each live run, record:
   - job id
   - request id
   - VMID/name
   - target node
   - power policy
   - actor fields
   - risk level
   - artifact ids
   - `observed_after`
   - guest-agent IP and cloud-init evidence when applicable
   - cleanup decision
6. Update docs with observed results and any remaining risks.

### Out Of Scope

- DRS migration execution.
- SSH/Ansible/app bootstrap.
- Background reconciliation worker.
- Automatic cleanup or delete unless separately approved.

### Definition Of Done

- Live smoke evidence is recorded in docs.
- Create VM runbook reflects actual observed behavior.
- No secrets, API tokens, SSH private keys, or raw sensitive payloads are committed.
- Required validation passes.
- Any live cleanup decision is explicit.

## Goal 2: DRS Identity And Final Pre-Check Preparation

Status: completed on 2026-05-28.

Detailed execution guide:
`docs/goal/drs-safe-execution-readiness-foundation.md`.

Primary objective: prepare the DRS Advisor path for safe future execution without enabling live migration by default.

### Scope

1. Design and implement DB-backed VM identity/fingerprint records.
2. Add policy boundaries for matching Proxmox VM identity to Gjallar records.
3. Add DRS final pre-check endpoint/model:
   - source/target node still valid
   - VM state still eligible
   - storage/network constraints still valid
   - recommendation not stale
   - no conflicting operation lock
4. Add read-only UI evidence for the final pre-check.
5. Keep recommendations non-executable unless explicitly approved by a later goal.
6. Add backend/frontend tests and docs.

### Definition Of Done

- DRS Advisor can show identity/fingerprint and final pre-check readiness.
- No live migration is executed.
- Tests prove stale/unsafe recommendations are blocked.
- Docs separate DRS readiness from DRS execution.

## Goal 3: DRS Final Pre-Check And Operation Lock Foundation

Status: completed on 2026-05-28 as a read-only foundation.

Detailed execution guide:
`docs/goal/drs-execution-goal-slices.md`.

Primary objective: close the largest remaining pre-execution safety gap with
DB-backed operation locks and stronger read-only final pre-check evidence
without enabling live migration.

### Current Goal 3 Foundation

1. `operation_locks` schema/model exists for `drs_migration`.
2. DRS final pre-check queries active/stale/reconciliation-required locks for
   VM identity, Proxmox locator, and route scopes.
3. Released locks do not block; open locks block `would_be_executable`.
4. VM config-lock evidence is collected from curated inventory fields and
   blocks when present.
5. Active task, HA state, and quorum/cluster health remain explicit
   `not_collected` evidence in the current adapter.

### Out Of Scope

- Approval modal or approval endpoint.
- `drs_migration` job creation.
- Proxmox live migration mutation.
- UPID tracking.
- Operation lock acquisition/release flow.
- Reconciliation worker.

### Definition Of Done

- Operation lock state is no longer reported as `not_implemented`.
- Active or stale locks block `would_be_executable`.
- Final pre-check explains conflict evidence without mutating Proxmox.
- DRS recommendations and checks remain `executable=false`.

## Goal 4: DRS Approval And Migration Job Substrate

Detailed execution guide:
`docs/goal/drs-execution-goal-slices.md`.

Primary objective: add local approval evidence, warning acknowledgement, and
`drs_migration` job state before any live migration mutation exists.

### Scope

1. Add approval packet/checksum model.
2. Bind approval to exact recommendation and final pre-check evidence.
3. Add warning acknowledgement fields.
4. Add `drs_migration` job shape without invoking Proxmox migration.
5. Expose read-only readiness/job evidence in Jobs/Runs.

### Definition Of Done

- Approval/job state cannot bypass blockers.
- No Proxmox mutation API is called.
- Jobs/Runs can represent DRS migration intent safely.

## Goal 5: DRS Live Migration Execution And UPID Tracking

Detailed execution guide:
`docs/goal/drs-execution-goal-slices.md`.

Primary objective: add the first narrow live migration path only after identity,
policy, final pre-check, approval, operation lock, and job gates exist.

### Scope

1. Add a dedicated DRS Proxmox migration mutation client.
2. Require high-confidence identity, `allowed` policy, passing final pre-check,
   valid approval, and acquired lock.
3. Invoke Proxmox live migration only after all gates pass.
4. Store UPID and task metadata.
5. Poll enough task state to classify immediate result.
6. Mark ambiguous states as `needs_reconciliation`.

### Definition Of Done

- Blocked conditions do not call Proxmox mutation APIs.
- UPID is stored and visible in job evidence.
- Execution remains narrow and approval-gated.

## Goal 6: DRS Post-Check And Reconciliation

Detailed execution guide:
`docs/goal/drs-execution-goal-slices.md`.

Primary objective: detect and report drift between Proxmox actual state and Gjallar DB/job state.

### Scope

1. Post-check VM location, power state, and fingerprint after migration.
2. Define reconciliation records and job/artifact behavior.
3. Compare Proxmox actual VM/task state against DRS job and lock state.
4. Surface `needs_reconciliation` as operator-visible jobs/risks.
5. Add read-only Reconcile Now preview before any corrective mutation.
6. Add tests using fake inventory/adapters.

### Definition Of Done

- Drift can be detected and displayed without mutating Proxmox.
- Operators can see what Gjallar believes vs what Proxmox reports.
- Proxmox task success alone does not mark Gjallar migration success.
- Docs explain how to respond to drift manually.

## Goal 7: SSH/Ansible/App Bootstrap Readiness

Primary objective: optionally extend post-create confidence after Create VM live smoke is stable.

### Scope

1. Add SSH login smoke only after explicit approval.
2. Add Ansible verification only if target bootstrap requirements are clear.
3. Keep app bootstrap separate from Create VM success unless product direction changes.
4. Avoid storing private keys or raw secrets in DB/artifacts.

### Definition Of Done

- Bootstrap checks are explicit, opt-in, and safe.
- Create VM base success remains independent from app deploy success unless a later goal changes that contract.

## Goal 8: Account/Session Operations Polish

Primary objective: improve operational convenience without changing the auth model.

### Candidate Work

1. Re-enable disabled users.
2. Session list and force logout for admins.
3. Self password change.
4. Account operation audit log.
5. Better admin UI affordances for last-admin protection and disabled users.

### Out Of Scope Unless Explicitly Requested

- Public signup.
- Email password reset.
- OAuth/SSO/2FA.
- API tokens.

## Standard Validation

Run after code changes unless the goal explicitly narrows validation:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
node --test frontend/tests/*.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```

## Commit And Push

- Commit coherent finished work.
- Push to `origin/main`.
- Leave the working tree clean.

## Remaining Risk To Carry Forward

- Create VM live smoke is complete for the approved 2026-05-28 target, but any
  future live smoke or cleanup mutation still needs explicit active-session
  approval.
- DRS Advisor remains read-only. Identity/fingerprint policy, DB-backed
  operation lock lookup, config-lock evidence, and read-only final pre-check
  foundation exist, but operation lock acquisition/release, approval/job
  substrate, UPID tracking, live migration execution, and reconciliation are not
  implemented.
- SSH/Ansible/app bootstrap remains deferred.
