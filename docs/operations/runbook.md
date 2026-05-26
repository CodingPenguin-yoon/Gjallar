# Current Runbook

This is the current concise verification runbook for the implemented repo state. Prefer this file over the legacy [`../archive/operations/RUNBOOK.md`](../archive/operations/RUNBOOK.md).

## Backend validation

From repo root:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
```

Latest consolidated backend validation baseline is recorded in
[`../current/README.md`](../current/README.md). This runbook intentionally does
not carry a separate backend pass count.

## Frontend validation

Run the frontend `.mjs` tests directly with Node.

From repo root:

```bash
for test_file in frontend/tests/*.mjs; do
  node "$test_file"
done
```

Lint and build from `frontend/`:

```bash
pnpm lint
pnpm build
```

Current recorded frontend baseline:

- Frontend tests passed.
- Frontend build passed.

## Auth And First Admin

Run migrations before starting the backend so auth tables exist:

```bash
cd backend
venv/bin/alembic upgrade head
PYTHONPATH=. venv/bin/python -m app.db.seed_create_vm_profiles
PYTHONPATH=. venv/bin/python -m app.auth.users create-admin --username yoon
```

The account CLIs prompt for a password unless `--password-env` is supplied. Use
`PYTHONPATH=. venv/bin/python -m app.auth.users create-user --username kim --role viewer`
or `--role operator` for non-admin accounts. The
backend stores a PBKDF2 password hash and server-side session records; the
browser receives only an opaque `HttpOnly`, `SameSite=Lax` session cookie.

Login/logout flow:

- UI route: `/login`
- API login: `POST /api/v1/auth/login`
- API logout: `POST /api/v1/auth/logout`
- Session bootstrap: `GET /api/v1/auth/me`

Role behavior:

- `viewer`: can read protected inventory/jobs/risks/DRS surfaces.
- `operator`: viewer permissions plus Create VM workflow writes, Create VM live
  create, and VM Start.
- `admin`: operator permissions; user-management UI is still not implemented.

Create VM draft/preflight/plan/approve/proxmox-preview all write Gjallar
job/artifact state, so they require `operator` or `admin`. Read-only GET APIs
require `viewer` or above. Public health, root health, login, logout, and
session status (`/api/v1/auth/me`, which returns `authenticated: false` when
anonymous) remain callable without a viewer role.

Unsafe browser requests with `Origin: null` or an unknown origin are rejected.
TestClient/curl-style requests without `Origin` are allowed.

## Diff hygiene

From repo root:

```bash
git diff --check
```

Use this to catch malformed whitespace or patch issues before any commit.

## Basic `/api/v1` smoke notes

The active frontend contract is `/api/v1`.

Current recorded smoke baseline:

- Frontend dev server convention is `http://127.0.0.1:5173`.
- Backend dev server convention is `http://127.0.0.1:8000`.
- Active API surface remains `/api/v1`.
- Browser access starts at `/login`; all frontend API fetches include session
  cookies.
- Jobs/Runs progress records are read from the DB configured by `GJALLAR_DATABASE_URL`.
- Create VM workflow and VM Start job evidence includes authenticated actor
  fields: `actor_user_id`, `actor_username`, and `actor_role`.
- Infra Explorer VM start uses `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start` and records `vm_start` jobs/artifacts in the DB-backed Jobs/Runs tables.

Auth-focused validation from repo root:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q \
  backend/tests/contracts/test_api_v1_auth.py \
  backend/tests/contracts/test_api_v1_vm_create.py \
  backend/tests/contracts/test_api_v1_vm_create_approval_execute.py
node --test frontend/tests/authFlow.test.mjs frontend/tests/apiV1Client.test.mjs frontend/tests/createVmFlow.test.mjs
```

## Safety notes

- Treat inventory as read-only.
- Create VM workflow writes and live actions require login with `operator` or
  `admin`, exact approval metadata, fresh red-risk checks, and explicit native
  Proxmox create acknowledgement.
- Create VM success remains stopped/powered-off and does not auto-start.
- Existing VM start requires an in-app acknowledgement, idempotency key, fresh inventory precheck, Proxmox task polling, and observed-after running evidence.
- Do not rely on destructive VM list controls; the current UI does not expose stop/reset/shutdown/reboot/delete/terminate.
- Live Proxmox Create VM smoke was not run during auth stabilization. Running
  the live smoke matrix still requires explicit approval.
