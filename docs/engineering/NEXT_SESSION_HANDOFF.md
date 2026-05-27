# Next Session Handoff

Last updated: 2026-05-27

## Current State

- Base commit before auth stabilization: `b753b06 feat: add drs advisor readiness surface`.
- Create VM is now the strongest supporting capability, not the DRS MVP success line.
- Active Create VM mutation path is `POST /api/v1/vm-create/{draft_id}/proxmox-create`.
- Terraform plan/apply and legacy GitOps `execute/archive` routes are removed from the active API.
- Profiles, Jobs/Runs, artifacts, Create VM requests, and created VM records are DB-backed.
- Gjallar auth is implemented with local users, server-side sessions, and roles:
  `viewer`, `operator`, and `admin`.
- Read APIs require `viewer` or above. Create VM workflow writes, Create VM
  live create, and VM Start require `operator` or `admin`.
- Admin-only local user management is implemented at `/admin/users` and
  `/api/v1/admin/users*`.
- First admin is created with
  `cd backend && python -m app.auth.users create-admin --username yoon`.
- Auth endpoints are active:
  `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, and
  `GET /api/v1/auth/me`.
- `/networks` is now read-only Network Readiness / migration pre-check visualization composed from existing live inventory APIs. There is no Proxmox network mutation, Networks API write path, YAML persistence, DB migration, or DRS execution authority.
- Create VM power policy is request-level:
  - `stopped`: default, clone/config and stopped post-check.
  - `boot_and_verify`: start the new VM, observe guest-agent IP, and verify `cloud-init status --wait`.
- Create VM displays the authenticated session user as actor evidence instead
  of exposing editable payload `operator_id`.
- Last enabled admin protection is shared by CLI and API: the last enabled
  admin cannot be disabled or demoted; disabled admins do not count. Password
  reset still revokes target sessions and is not blocked by that guard.
- SSH login, Ansible verification, app bootstrap, background reconciliation, and DRS identity registration are not implemented.
- Live Proxmox Create VM smoke was not run during auth stabilization and still
  requires explicit approval.
- Next immediate implementation work is the Create VM live smoke matrix plus
  docs/risk follow-up from the auth stabilization review.

## Validation Baseline

Most recent operations-console stabilization validation:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
node --test frontend/tests/*.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```

Recorded backend result after operations-console stabilization:
`182 passed, 33 warnings, 29 subtests passed`.

## Next Work 1: Create VM Live Smoke Matrix

Goal: verify the auth-protected Create VM behavior against live Proxmox after
explicit approval.

Start by reading:

- `docs/operations/runbook.md`
- `backend/app/api/v1/router.py`
- `backend/app/main.py`
- `backend/app/db/models.py`
- `frontend/src/App.jsx`
- `frontend/src/services/apiV1.js`
- `frontend/src/components/CreateInstanceWizard.jsx`
- `frontend/src/components/InstanceList.jsx`

Run and record:

1. `stopped` creation with default settings.
2. `boot_and_verify` with DHCP and guest-agent IP display.
3. Static IP creation with explicit `static_ip`, `prefix`, and `gateway`.
4. Invalid target combination, such as template/node/storage mismatch, to confirm the error is understandable.

Check Jobs/Runs after each run:

- authenticated actor evidence
- job status and stage
- generated VM summary
- IP display and meaning
- `observed_after`
- `cloud_init`
- `boot_verification`

Keep out of scope for this smoke:

- OAuth/SSO/2FA.
- API token automation.
- SSH smoke, Ansible, app bootstrap, full reconciliation worker, or DRS identity
  registration.

## Next Work 2: Docs And Risk Follow-Up

Goal: close documentation drift and explicitly capture remaining auth/Create VM
risks before DRS Phase 2.

Targets:

- Update `docs/current/README.md` and any top-tab status docs that still imply
  Create VM is unauthenticated.
- Keep password reset email flows, OAuth/SSO/2FA, API tokens, and live smoke
  clearly separated from the completed auth/admin foundation.
- Keep DRS execution authority separate from Create VM mutation authority.

## Next Work 3: DRS Advisor Identity And Execution Prep

Goal: extend the implemented read-only DRS Phase 1 without adding migration mutation yet.

Start by reading:

- `docs/engineering/GJALLAR_IMPLEMENTATION_ROADMAP.md`
- `docs/product/drs-advisor/README.md`
- `docs/product/drs-advisor/05_IMPLEMENTATION_PLAN.md`
- `frontend/src/components/DrsAdvisorScreen.jsx`
- `frontend/src/utils/drsAdvisor.js`
- `backend/app/drs/advisor.py`
- `backend/app/api/v1/router.py`
- `backend/app/proxmox/inventory.py`

Implemented backend endpoints are read-only:

```http
GET /api/v1/drs/summary
GET /api/v1/drs/recommendations
GET /api/v1/drs/recommendations/{recommendation_id}
POST /api/v1/drs/recommendations/{recommendation_id}/check
```

Phase 1 rules:

- No live migration endpoint yet.
- No Proxmox mutation yet.
- Recommendations are non-executable until identity, metadata, final pre-check, locks, and reconciliation exist.
- Reuse Create VM's approval/artifact/job lessons, but do not reuse Create VM success criteria as DRS migration criteria.

## First Commands In A New Session

```bash
git status --short --branch
git pull --ff-only
nl -ba docs/engineering/GJALLAR_CURRENT_WORK_PLAN.md | sed -n '1,270p'
nl -ba docs/engineering/GJALLAR_IMPLEMENTATION_ROADMAP.md | sed -n '1,260p'
nl -ba docs/engineering/CREATE_VM_STABILIZATION_PLAN.md | sed -n '1,260p'
nl -ba docs/engineering/NEXT_SESSION_HANDOFF.md | sed -n '1,220p'
```
