# Next Session Handoff

Last updated: 2026-05-31

> Historical/stale handoff note: this file preserves the 2026-05-28 Create VM
> smoke and session context, but it is no longer the source of current goal
> sequencing. Use [`docs/goal/README.md`](../goal/README.md) for the active
> sequence. Goal Check 01-06, Goal 7, Goal 7.5, the minimal local-only
> Goal 8 recorder, Goal 9 local account/session polish, and Goal 10 are
> complete. Goal 10 includes approved VMID `140` live DRS evidence and
> stored-UPID local reconciliation completion. Future live mutation still
> requires explicit active-session approval for that specific run.

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
- Admin-only local user/session management is implemented at `/admin/users`,
  `/api/v1/admin/users*`, and `/api/v1/admin/sessions*`; self password change
  is implemented at `/account` and `POST /api/v1/auth/change-password`.
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
- Approved Proxmox Create VM live smoke completed on 2026-05-28. Results are in
  [`../operations/create-vm-live-smoke-2026-05-28.md`](../operations/create-vm-live-smoke-2026-05-28.md).
  Future live smoke or cleanup mutations still require explicit active-session
  approval.
- Current goal sequencing has moved to
  [`docs/goal/README.md`](../goal/README.md). Goal 7.5, the minimal local-only
  Goal 8 recorder, and Goal 9 local account/session polish are complete; do not
  restart them as next work.

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

## Completed Work: Create VM Live Smoke Matrix

Goal completed: verify the auth-protected Create VM behavior against live
Proxmox after explicit approval.

Recorded on 2026-05-28:

1. Negative bridge gate: red blocked with `side_effects=[]`.
2. `stopped` creation: VMID 137, final stopped.
3. `boot_and_verify`: VMID 138, guest-agent IP and cloud-init verified, then
   stopped by approved cleanup.
4. Static IP creation: VMID 139, final stopped.

Jobs/Runs evidence checked:

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

## Current Goal Pointer

The "next work" sections previously in this handoff are historical and stale.
Use [`docs/goal/README.md`](../goal/README.md) for current sequencing. Goal 7.5
DRS VM Policy Configuration, the minimal local-only Goal 8 recorder, and Goal 9
local account/session polish are complete; Goal 10 is complete with approved
VMID `140` live DRS evidence. The old Goal 11/12 split is superseded by the
rewritten Goal 11 DRS Criteria And Operations Productization.

## First Commands In A New Session

```bash
git status --short --branch
git pull --ff-only
nl -ba docs/goal/README.md | sed -n '1,120p'
nl -ba docs/goal/goal-07-5-drs-vm-policy-management.md | sed -n '1,260p'
nl -ba docs/engineering/GJALLAR_CURRENT_WORK_PLAN.md | sed -n '1,270p'
nl -ba docs/engineering/GJALLAR_IMPLEMENTATION_ROADMAP.md | sed -n '1,260p'
nl -ba docs/engineering/CREATE_VM_STABILIZATION_PLAN.md | sed -n '1,260p'
nl -ba docs/engineering/NEXT_SESSION_HANDOFF.md | sed -n '1,220p'
```
