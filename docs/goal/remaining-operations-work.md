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
- Create VM supports default `stopped` creation and optional `boot_and_verify`, but live Proxmox smoke has not been run.

## Non-Negotiables

- Do not run live Proxmox mutation or smoke without explicit user approval in the active session.
- Do not add public signup.
- Do not add OAuth, SSO, 2FA, email reset, or API tokens unless a later goal explicitly asks for them.
- Keep DRS execution authority separate from Create VM mutation authority.
- Follow `AGENTS.md`: main session coordinates; for non-trivial work delegate explorer, reviewer, docs_researcher, then worker; only worker edits code.
- Prefer small, cohesive, production-oriented changes over broad rewrites.

## Recommended Goal Order

1. Create VM live smoke matrix and result recording.
2. DRS identity and final pre-check preparation.
3. Reconciliation worker for Proxmox/Gjallar state drift.
4. SSH/Ansible/app bootstrap readiness, if still desired after live smoke.
5. Account/session operations polish.

## Goal 1: Create VM Live Smoke Matrix

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

## Goal 3: Reconciliation Worker

Primary objective: detect and report drift between Proxmox actual state and Gjallar DB/job state.

### Scope

1. Define reconciliation records and job/artifact behavior.
2. Compare Proxmox actual VM state against:
   - `vm_instances`
   - `vm_create_requests`
   - latest job status/artifacts
3. Surface drift as operator-visible jobs/risks.
4. Keep reconciliation read-only at first.
5. Add tests using fake inventory/adapters.

### Definition Of Done

- Drift can be detected and displayed without mutating Proxmox.
- Operators can see what Gjallar believes vs what Proxmox reports.
- Docs explain how to respond to drift manually.

## Goal 4: SSH/Ansible/App Bootstrap Readiness

Primary objective: optionally extend post-create confidence after Create VM live smoke is stable.

### Scope

1. Add SSH login smoke only after explicit approval.
2. Add Ansible verification only if target bootstrap requirements are clear.
3. Keep app bootstrap separate from Create VM success unless product direction changes.
4. Avoid storing private keys or raw secrets in DB/artifacts.

### Definition Of Done

- Bootstrap checks are explicit, opt-in, and safe.
- Create VM base success remains independent from app deploy success unless a later goal changes that contract.

## Goal 5: Account/Session Operations Polish

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

- Live Proxmox Create VM smoke has not been run yet.
- DRS Advisor remains read-only and does not have identity/fingerprint policy, final pre-check, operation locks, UPID tracking, or execution.
- Reconciliation is not implemented.
- SSH/Ansible/app bootstrap remains deferred.
