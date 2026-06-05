# Gjallar Backend

FastAPI backend for the Gjallar Proxmox operations console.

## Product Direction vs Current Backend

Current MVP product source of truth is `docs/product/drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.

The target direction is DRS Advisor. The current backend provides Gjallar login,
server-side sessions, role-based API protection, read-only Proxmox inventory,
admin-only local user management, gated VM start from Infra Explorer,
Jobs/Runs, Risks, read-only DRS Advisor surfaces, and approval-gated Create VM
support. Create VM's active mutation path is native Proxmox API
clone/config/post-check; the legacy Terraform executor route surface and helper
code are removed. The backend also provides the first DRS live migration
execution slice: DB-backed identity/fingerprint and migration policy evidence,
approval packet/job intent records, DRS operation locks, a dedicated DRS
Proxmox migration client, exact live migration acknowledgement, UPID/task
evidence persistence, and conservative `needs_reconciliation` handling. DRS
post-check/reconciliation is implemented
for the narrow execution path: completion requires Proxmox task `OK` plus
direct target-node status/config evidence, expected power state, matching DRS
fingerprint, and no conflicting active task; locks release only after verified
post-check, ambiguous outcomes stay `needs_reconciliation`, and a read-only
Reconcile preview exists. Corrective reconciliation mutation, automatic DRS,
bulk migration, and live DRS smoke evidence remain out of scope.

Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, Create VM request/VM records, audit, and reconciliation state.

DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.

## Active Surface

- Public API contract: `/api/v1`
- Auth: `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, and
  `GET /api/v1/auth/me`
- Admin user management: `GET/POST /api/v1/admin/users`,
  `PATCH /api/v1/admin/users/{username}/role`,
  `POST /api/v1/admin/users/{username}/disable`, and
  `POST /api/v1/admin/users/{username}/reset-password`
- Inventory: read-only Proxmox nodes, VMs, templates, storage, and networks
- Infra Explorer VM start: acknowledgement/idempotency-gated QEMU start for stopped non-template VMs, with Proxmox task polling and `vm_start` job/artifact evidence
- Create VM: draft, preflight, plan, approval, Proxmox native preview/create, optional boot-and-verify, and DB request/VM records
- DRS Advisor: read-only recommendations/final pre-check, local approval packets, one narrow operator-only `POST /api/v1/drs/migration-jobs/{job_id}/execute` path for approved live migration jobs with exact `drs_live_migration_acknowledged=true`, and read-only `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview`
- Legacy Terraform Create VM executor: removed; old plan/apply URLs naturally 404
- Jobs/Runs and Risks: read-only MVP summaries

Legacy `/api` deploy/provision/task/log/LLM routes are not part of the active backend.

## Run

```bash
cp .env.example .env
cd backend
set -a
. ../.env
set +a
venv/bin/alembic upgrade head
PYTHONPATH=. venv/bin/python -m app.db.seed_create_vm_profiles
PYTHONPATH=. venv/bin/python -m app.auth.users create-admin --username yoon
cd ..
pnpm run backend
```

The backend loads the repo root `.env`. `BACKEND_PORT` controls the local uvicorn port, and `FRONTEND_PORT` controls the CORS origin allowed for the Vite dev server.
`GJALLAR_DATABASE_URL` controls the SQLAlchemy/Alembic connection. Local SQLite is supported, and PostgreSQL can be used by changing the same URL.
There is no public signup flow. Local accounts are managed with the backend CLI,
which prompts for passwords unless `--password-env` is used.

For one-off backend CLI commands, load the repo root `.env` in the backend shell
first:

```bash
cd backend
set -a
. ../.env
set +a
```

## Docker

The root Dockerfile builds the Vite frontend, copies the built `dist` into the
Python runtime image, and sets `GJALLAR_FRONTEND_DIST=/app/frontend-dist`.
FastAPI serves `/health` and `/api/v1/*` as backend routes and serves the React
SPA for extensionless frontend routes from the same origin.

```bash
docker build -t gjallar:local .
docker run --rm --env-file .env -p 8000:8000 -v "$PWD/data:/app/data" gjallar:local
```

The Docker CMD only starts Uvicorn. Run migrations, seed data, and admin user
creation explicitly:

```bash
docker run --rm --env-file .env -v "$PWD/data:/app/data" gjallar:local alembic -c /app/backend/alembic.ini upgrade head
docker run --rm --env-file .env -v "$PWD/data:/app/data" gjallar:local python -m app.db.seed_create_vm_profiles
docker run --rm -it --env-file .env -v "$PWD/data:/app/data" gjallar:local python -m app.auth.users create-admin --username yoon
```

Do not bake secrets into the image. Pass runtime values with `--env-file` or
orchestrator secrets, and mount any host data/IaC paths referenced by `.env`.

Account operations:

```bash
PYTHONPATH=. venv/bin/python -m app.auth.users create-admin --username yoon
PYTHONPATH=. venv/bin/python -m app.auth.users create-user --username kim --role viewer
PYTHONPATH=. venv/bin/python -m app.auth.users create-user --username park --role operator
PYTHONPATH=. venv/bin/python -m app.auth.users list-users
PYTHONPATH=. venv/bin/python -m app.auth.users set-role --username kim --role operator
PYTHONPATH=. venv/bin/python -m app.auth.users disable-user --username kim
PYTHONPATH=. venv/bin/python -m app.auth.users reset-password --username park
```

`disable-user` and `reset-password` revoke existing sessions for the target user.
`set-role` does not revoke sessions; existing sessions pick up the role on their
next request. `disable-user` rejects disabling the last enabled admin, and
`set-role` rejects demoting the last enabled admin away from `admin`. Disabled
admin rows do not count toward that protection. `reset-password` is not blocked
by last-admin protection.

Admins can also use the browser UI at `/admin/users` or the admin API endpoints
listed above. Admin API responses return only safe user summaries and revoked
session counts; they never return password hashes, session token hashes, raw
secrets, or plaintext passwords.

## Validate

From the repo root:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
```

## Notes

- The app loads the repo root `.env`.
- Successful login creates a server-side session row and sends an opaque
  `HttpOnly`, `SameSite=Lax` cookie. Only a hash of the cookie token is stored.
- Roles are ordered `viewer < operator < admin`.
- Read-only `/api/v1` APIs require `viewer` or above. Create VM workflow POSTs,
  Create VM live create, and VM Start require `operator` or `admin`. Admin user
  management requires `admin`.
- Create VM profiles are schema-managed by Alembic and seeded separately with `cd backend && PYTHONPATH=. venv/bin/python -m app.db.seed_create_vm_profiles`. The seed is idempotent and no-ops when any profile row already exists.
- Jobs/Runs progress and artifacts are stored through `GJALLAR_DATABASE_URL` in `job_runs` and `job_artifacts`.
- Do not commit `.env`, tokens, secrets, `data/`, or local runtime artifacts.
- Live VM creation remains gated behind exact approval metadata, fresh red-risk checks, and `proxmox_mutation_acknowledged=true`. The default power policy leaves the new VM stopped; `boot_and_verify` starts it and verifies guest-agent IP plus cloud-init completion.
- Create VM and VM Start job/request evidence records authenticated actor fields
  from the session, not payload `operator_id`.
- Native creation and VM start reuse `PROXMOX_API_URL`, `PROXMOX_API_TOKEN_ID`, `PROXMOX_API_TOKEN_SECRET`, and `PROXMOX_TLS_INSECURE`; the mutation client is separate from the read-only inventory adapter.
- DRS live migration does not reuse the Create VM/VM Start mutation client. It requires `PROXMOX_DRS_API_URL`, `PROXMOX_DRS_API_TOKEN_ID`, `PROXMOX_DRS_API_TOKEN_SECRET`, and optional `PROXMOX_DRS_TLS_INSECURE`, `PROXMOX_DRS_TASK_POLL_INTERVAL_SECONDS`, `PROXMOX_DRS_TASK_TIMEOUT_SECONDS`.
- DRS live migration execute rejects missing or malformed `drs_live_migration_acknowledged=true` before DRS service/client/lock/migration work; ack failures return `409` / `DRS_EXECUTION_ACK_REQUIRED`, `proxmox_mutation_enabled=false`, and `side_effects=[]`.
