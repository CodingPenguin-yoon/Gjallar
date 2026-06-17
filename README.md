# Gjallar

Gjallar is a human-facing Proxmox Operations & Risk Console.

The active repo-local documentation lives under [`docs/`](docs/README.md). Start there for product docs, current engineering notes, and historical material.

## Current product direction

- Current MVP product source of truth is [`docs/product/drs-advisor/`](docs/product/drs-advisor/README.md). If this document conflicts with that folder, `drs-advisor/` wins.
- DRS Advisor is the next MVP success line: Proxmox-native migration recommendations, approval-gated live migration, Proxmox task tracking, audit, and reconciliation.
- DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.
- Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, Create VM request/VM records, audit, and reconciliation state.
- PBS/Veeam references are backup evidence or future integration context only.

## Current state at a glance

- The active frontend contract remains `/api/v1`.
- Inventory is live read-only Proxmox data with a fake fallback when live inventory is unavailable.
- The current primary UI nav is Overview, VM Instances, DRS Advisor, Operations, and Settings. VM Instances contains inventory, DRS Policies, Create VM, and Network readiness; Operations contains Jobs and Risks; Settings contains Account and admin-only Users.
- Current code has DRS identity/fingerprint policy, read-only final pre-check,
  local approval/job substrate, narrow approval-gated migration execution, UPID
  tracking, verified post-check, read-only reconciliation preview, and approved
  VMID `140` live DRS migration evidence. Live execute/corrective reconcile UI
  remains pending.
- Create VM mutations are approval-gated Proxmox API native. The legacy Terraform executor route surface and helper code have been removed.
- Native Create VM creates/configures a VM, polls the Proxmox clone UPID, records request/VM DB rows, and requires post-check `observed_after` evidence before marking the create applied. The default policy leaves the VM stopped; the optional `boot_and_verify` policy starts it and verifies guest-agent IP plus cloud-init completion.
- VM Instances inventory exposes only a gated Start action for stopped non-template VMs; stop/reset/shutdown/reboot/delete/terminate controls are absent.

## Local Runtime Env

Copy `.env.example` to `.env` and adjust local paths or ports as needed. The root `pnpm run dev` scripts and the Vite dev proxy both read this file.

Key values:

- `FRONTEND_PORT`: Vite dev server port, default `5173`
- `BACKEND_PORT`: FastAPI backend port, default `8000`
- `VITE_BACKEND_URL`: frontend dev proxy target, default `http://127.0.0.1:8000`
- `GJALLAR_DEFAULT_SSH_PUBLIC_KEY_B64`: optional base64-encoded OpenSSH public key for Create VM cloud-init access defaults; use this for Docker env files when the raw public key's spaces would be awkward
- `GJALLAR_DATABASE_URL`: PostgreSQL SQLAlchemy/Alembic database URL for profiles, jobs, artifacts, Create VM requests, and created VM records; `.env.example` uses the `postgresql+psycopg://` driver URL

For Heimdall-managed PostgreSQL, bind the managed project database URL to
`GJALLAR_DATABASE_URL`. The Docker entrypoint uses that same URL for startup
migrations and initial profile seeding. Gjallar normalizes `postgresql://` and
`postgres://` URLs to `postgresql+psycopg://` at runtime. SQLite is not a runtime
database; it is allowed only for tests with `GJALLAR_ALLOW_SQLITE_FOR_TESTS=1`.

Initialize the PostgreSQL-backed backend DB before first local Create VM use:

```bash
cd backend
alembic upgrade head
python -m app.db.seed_create_vm_profiles
```

## Docker Runtime

Build the single runtime image from the repo root:

```bash
docker build -t gjallar:local .
```

Run FastAPI/Uvicorn on port `8000`; the backend serves the built React app from
the same origin:

```bash
docker run --rm --env-file .env -p 8000:8000 -v "$PWD/data:/app/data" gjallar:local
```

The image does not bake in `.env`, local databases, virtualenvs, `node_modules`,
or docs. On container startup, the entrypoint runs Alembic migrations and the
idempotent Create VM profile seed, then creates a bootstrap admin only when
`GJALLAR_BOOTSTRAP_ADMIN_USERNAME` and `GJALLAR_BOOTSTRAP_ADMIN_PASSWORD` are
both set, before starting Uvicorn. Existing enabled admin users are left
unchanged. Set `GJALLAR_SKIP_STARTUP_INIT=1` only for special one-off/debug runs
that must skip startup database initialization.

You can still create the initial admin account as an explicit one-off command:

```bash
docker run --rm -it --env-file .env -v "$PWD/data:/app/data" gjallar:local python -m app.auth.users create-admin --username yoon
```

## Product framing

- Gjallar owns safe human-facing visibility and operational control for Proxmox.
- Hermes, AI, and agent workflows are supporting control plumbing, not the product identity.
- Read-only inventory is the safe baseline.

## Where to read next

- [Docs index](docs/README.md)
- [Goal map and next gate](docs/goal/README.md)
- [Current implemented state](docs/current/README.md)
- [Create VM native architecture](docs/architecture/CREATE_VM_NATIVE_ARCHITECTURE.md)
- [Current runbook](docs/operations/runbook.md)
- [Product docs](docs/product/README.md)
