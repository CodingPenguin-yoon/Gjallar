# Create VM Stabilization Plan

Last updated: 2026-05-28

Status: completed for the intended stabilization slice. Approved live smoke is
recorded in
[`../operations/create-vm-live-smoke-2026-05-28.md`](../operations/create-vm-live-smoke-2026-05-28.md).

## Purpose

Create VM is already a strong supporting capability. This plan is not about
adding more Create VM features. It closes the current Create VM surface so it is
safe to keep as a production-shaped operator workflow before the next major DRS
Advisor phase begins.

The immediate decision is:

- Do not use a browser-stored mutation token as the main guard.
- Add Gjallar login, server-side sessions, and simple role-based authorization.
- Protect Proxmox mutation endpoints in the backend API, not only in the UI.

## Plain Terms

- Mutation: an operation that changes Proxmox or Gjallar state. In this project,
  VM create and VM start are mutations.
- Read-only API: an operation that only reads state, such as listing nodes, VMs,
  jobs, risks, and recommendations.
- Authentication: proving who the user is. In this plan, that means logging in.
- Authorization: deciding whether that user may perform a specific action.
- Role: a simple permission level such as `viewer`, `operator`, or `admin`.
- Session: the server-side record that says a browser is currently logged in.
- Cookie: the browser value that points to the session. The browser sends it
  with API requests.
- `HttpOnly` cookie: a cookie that frontend JavaScript cannot read directly.
  This is safer than storing API tokens in `localStorage`.
- CORS: a browser origin rule. It limits which frontend origins can call the API
  from a browser, but it is not login and not authorization. `curl`, scripts, or
  other servers can still call the API unless the backend checks auth.
- CSRF defense: protection against another site causing a logged-in browser to
  send an unwanted mutation request. Initial defense should use `SameSite=Lax`
  cookies and backend `Origin` checks for unsafe methods.

## Target Shape

Gjallar should behave like an operator console:

1. A user opens the web UI.
2. The app calls `GET /api/v1/auth/me`.
3. If there is no valid session, the app shows `/login`.
4. The user logs in with username and password.
5. The backend creates a server-side session and returns an `HttpOnly` cookie.
6. Read-only APIs require at least `viewer`.
7. VM create and VM start require at least `operator`.
8. The first admin can be created by CLI, and admins can manage local users
   through the admin-only UI/API.

## Roles

Keep the first role model deliberately small.

| Role | Can read inventory/jobs/risks | Can create/start VM | Can manage users |
|---|---:|---:|---:|
| `viewer` | yes | no | no |
| `operator` | yes | yes | no |
| `admin` | yes | yes | yes |

Rules:

- Backend API is the final authority. Frontend button hiding is only UX.
- Unauthenticated requests return `401`.
- Authenticated requests with insufficient role return `403`.
- `/health`, root health, and login should remain public.

## Backend Scope

Add the smallest auth foundation that can protect Create VM and VM Start.

Planned pieces:

- `users` table:
  - `user_id`
  - `username`
  - `password_hash`
  - `role`
  - `enabled`
  - `created_at`
  - `updated_at`
  - `last_login_at`
- `sessions` table:
  - `session_id`
  - `user_id`
  - `expires_at`
  - `created_at`
  - `revoked_at`
  - optional request metadata such as user agent or IP hash
- password hashing with a standard library. Do not hand-roll password hashing.
- CLI for the first admin:

```bash
cd backend
python -m app.auth.users create-admin --username yoon
```

- auth API:

```http
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET /api/v1/auth/me
```

- admin-only user management API:

```http
GET /api/v1/admin/users
POST /api/v1/admin/users
PATCH /api/v1/admin/users/{username}/role
POST /api/v1/admin/users/{username}/disable
POST /api/v1/admin/users/{username}/reset-password
```

- dependency helpers:

```python
require_user()
require_role("viewer")
require_role("operator")
require_role("admin")
```

- protect mutation endpoints:

```http
POST /api/v1/vm-create/{draft_id}/proxmox-create
POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start
```

- protect read-only operator APIs with `viewer` or above, except public health
  and login endpoints.
- add actor evidence to mutation job/request records where practical:
  - `actor_user_id`
  - `actor_username`
  - `actor_role`
- share local-account safety between CLI and API:
  - disabling the last enabled admin is rejected
  - demoting the last enabled admin away from `admin` is rejected
  - disabled admin rows do not count
  - password reset still revokes target sessions and is not blocked by the
    last-admin guard

## Frontend Scope

Add only the UI needed for operator login and role-aware controls.

Planned pieces:

- `/login` route.
- app startup call to `GET /api/v1/auth/me`.
- redirect unauthenticated users to `/login`.
- `POST /api/v1/auth/login` form.
- logout button using `POST /api/v1/auth/logout`.
- show current user and role in the shell.
- disable or hide Create VM live execution and VM Start for `viewer`.
- keep backend error handling clear for `401` and `403`.
- all API calls should include cookies:

```js
fetch(url, { credentials: 'include' })
```
- `/admin/users` route visible only to admins, with route-level guard for direct
  access.

## Security Defaults

Initial defaults:

- session cookie is `HttpOnly`.
- session cookie uses `SameSite=Lax`.
- production HTTPS should set `Secure`.
- sessions expire.
- logout revokes the session.
- unsafe methods should reject unexpected `Origin` values.
- CORS stays narrow, but it is treated only as browser-origin defense, not auth.
- backend should not trust frontend-only state for authorization.

## Work Slices

### Slice 1: Backend Auth Foundation

Goal: login/session/role model exists and is tested.

- Add Alembic migration for `users` and `sessions`.
- Add password hash and session helper module.
- Add first-admin CLI.
- Add `/api/v1/auth/login`, `/logout`, `/me`.
- Add contract tests for login, logout, session expiry, disabled users, and bad
  password.

### Slice 2: Protect API Surface

Goal: no Create VM or VM Start mutation can run without an `operator` session.

- Add `require_role("operator")` to `proxmox-create`.
- Add `require_role("operator")` to VM Start.
- Add `viewer` or above to read-only operator APIs.
- Add `401`/`403` tests.
- Add actor evidence to Create VM and VM Start job/request details.

### Slice 3: Frontend Login

Goal: the UI has a real login flow and handles permissions clearly.

- Add `/login`.
- Add auth state provider or equivalent app-level state.
- Add `auth/me` boot check.
- Add logout.
- Add role-aware Create VM and VM Start controls.
- Add frontend tests for unauthenticated, viewer, and operator behavior.

### Slice 4: Operational Hardening

Goal: make the auth-protected Create VM flow reproducible and understandable.

- Add root validation scripts for backend tests, frontend tests, lint, and build.
- Update runbook with first-admin creation and login steps.
- Run and record Create VM live smoke:
  - `stopped`
  - `boot_and_verify`
  - static IP with explicit `static_ip`, `prefix`, and `gateway`
  - expected blocked cases
- Confirm artifacts do not expose raw SSH key material.

## Non-Goals For This Stabilization

Do not include these in the Create VM stabilization slice:

- OAuth, SSO, or 2FA.
- self-service signup.
- password reset email flow.
- fine-grained per-project permissions.
- API token automation.
- SSH smoke, Ansible, or app bootstrap.
- full background reconciliation worker.
- DRS identity registration.
- DRS migration execution.

These can be added later when the DRS execution path requires them.

## Completion Criteria

Create VM stabilization is complete when:

- unauthenticated users cannot access operator APIs except public health/login.
- `viewer` can read but cannot create/start VMs.
- `operator` and `admin` can create/start VMs.
- Create VM and VM Start record the authenticated actor in job/request evidence.
- session cookies are `HttpOnly` and expire.
- unsafe mutation requests without a valid session return `401`.
- mutation requests with insufficient role return `403`.
- backend tests, frontend tests, lint, build, and `git diff --check` pass.
- Create VM live smoke is recorded for `stopped`, `boot_and_verify`, static IP,
  and a negative pre-mutation gate.
- docs/runbook explain first-admin creation, login, logout, and role behavior.
- admins can list, create, role-change, disable, and reset local users without a
  public signup flow.

## Next After This Plan

This plan is historical. Current goal sequencing is tracked in
[`docs/goal/README.md`](../goal/README.md).

Create VM stabilization, DRS identity/fingerprint, operation locks,
approval/job substrate, narrow DRS live migration execution with UPID tracking,
and post-check/reconciliation were completed later. The next active gate is the
non-numbered Goal Check:
[`docs/goal/goal-check-01-06-implementation-quality.md`](../goal/goal-check-01-06-implementation-quality.md).
Goal 7 remains DRS UI And Operations Polish and is pending after that check:
[`docs/goal/goal-07-drs-ui-operations-polish.md`](../goal/goal-07-drs-ui-operations-polish.md).
