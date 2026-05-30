# Goal: Stabilize Gjallar Operations Console And Remove Legacy Code

## Current Role

This is a completed historical goal brief. It is retained for traceability of
the operations-console stabilization work that preceded the current Goal 1
through Goal 9 backlog.

Use `docs/goal/README.md` as the active entry point. Do not treat this file as
the next goal unless the user explicitly reopens this workstream.

## Starting Point

- Session auth/RBAC was committed and pushed as `e7b4d13`.
- Local account operations were committed and pushed as `7b0a77c`.
- The local account CLI supports `create-admin`, `create-user`, `list-users`, `set-role`, `disable-user`, and `reset-password`.
- Do not add public signup.
- Do not run live Proxmox mutation or smoke without explicit user approval.
- Keep changes clean, minimal, and production-oriented.
- Remove legacy/dead code only when current tests/docs prove it is no longer part of the active surface.

## Operating Mode

Follow `AGENTS.md`:

- Main session coordinates.
- For non-trivial work, use explorer, reviewer, docs_researcher, then worker.
- Only worker edits code.
- Use default agents with model `gpt-5.5` and `reasoning_effort: xhigh` when model control is needed.
- Prefer focused summaries and explicit validation.

## Primary Objective

Bring Gjallar closer to an operator-ready console by adding admin user management UI/API, hardening local account operations, closing Create VM stabilization gaps that do not require live mutation, and removing legacy code paths that are no longer part of the active product.

## Workstream A: Admin User Management UI/API

1. Add admin-only backend APIs for local user management:
   - `GET /api/v1/admin/users`
   - `POST /api/v1/admin/users`
   - `PATCH /api/v1/admin/users/{username}/role`
   - `POST /api/v1/admin/users/{username}/disable`
   - `POST /api/v1/admin/users/{username}/reset-password`
2. Reuse `backend/app/auth/users.py` service logic.
3. Require `admin` role for all admin user-management APIs.
4. Never return password hashes, session token hashes, raw secrets, or plaintext passwords.
5. Add frontend admin route, preferably `/admin/users`.
6. Show user list, role, enabled state, created/updated/last login timestamps.
7. Allow admin to create user, change role, disable user, and reset password.
8. Make the route invisible or inaccessible to non-admin users.
9. Handle 401/403 and validation errors clearly.

## Workstream B: Account Safety Hardening

1. Prevent disabling the last enabled admin.
2. Prevent demoting the last enabled admin away from admin.
3. Keep `reset-password` behavior: revoke existing sessions for the target user.
4. Keep `disable-user` behavior: revoke existing sessions for the target user.
5. Add tests for last-admin protection through CLI and API if both surfaces share the same service logic.

## Workstream C: Create VM Stabilization Closure

1. Review current Create VM flow end to end:
   - draft
   - preflight
   - plan
   - approve
   - proxmox-preview
   - proxmox-create
   - job/artifact/status surfaces
   - actor evidence
   - RBAC behavior
2. Fix any obvious non-live gaps, stale UI copy, inconsistent error handling, or missing tests.
3. Do not run live Proxmox create/smoke unless the user explicitly approves during the goal.
4. Prepare the exact live smoke checklist/runbook section so it can be run later with approval.

## Workstream D: Legacy/Dead Code Cleanup

1. Identify legacy routes, frontend services, components, tests, docs, or comments that are no longer part of the active Gjallar surface.
2. Remove only code that is demonstrably unused or superseded.
3. Do not delete compatibility paths unless tests/docs prove they are outside the active contract.
4. Keep the active surface centered on `/api/v1`, auth/RBAC, inventory/jobs/DRS/Create VM, and admin user management.
5. Remove stale docs that mislead operators.

## Workstream E: Code Quality

1. Keep implementation small and cohesive.
2. Prefer existing patterns over new abstractions.
3. Avoid broad rewrites.
4. Factor shared account logic into service helpers where it reduces duplication.
5. Keep UI utilitarian and operator-focused, not marketing-style.
6. Do not introduce public signup, OAuth, SSO, email reset, or API tokens in this goal.

## Tests

1. Add backend contract tests for admin user APIs:
   - admin can list/create/change-role/disable/reset-password
   - viewer/operator cannot access admin APIs
   - unauthenticated receives 401
   - last enabled admin cannot be disabled or demoted
   - password hashes/secrets are never returned
2. Extend CLI tests for last-admin protection.
3. Add frontend tests for:
   - admin user-management screen rendering
   - non-admin access handling
   - create user / role change / disable / reset password interactions
4. Keep existing Create VM, auth, jobs, inventory, DRS, and frontend tests passing.

## Docs

1. Update `backend/README.md`.
2. Update `docs/operations/runbook.md`.
3. Update `docs/engineering/NEXT_SESSION_HANDOFF.md`.
4. Document:
   - admin UI route
   - account CLI commands
   - admin API behavior
   - last-admin protection
   - Create VM live smoke checklist, gated behind explicit approval

## Validation

Run, or explain why unable:

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

## Definition Of Done

- Admin can manage local users from the UI without public signup.
- CLI and API share safe account behavior.
- Last enabled admin cannot be accidentally removed.
- Create VM non-live stabilization gaps are closed.
- Legacy/dead code that is clearly outside the active surface is removed.
- Docs match the actual operator workflow.
- Required validation passes.
- Remaining risk is explicit, especially anything requiring live Proxmox approval.
