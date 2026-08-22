# Gjallar

Gjallar is a Proxmox operations and risk console that combines live infrastructure visibility with guarded execution for a deliberately narrow set of VM workflows.

Proxmox remains the source of truth for nodes, virtual machines, and tasks. Gjallar records operation intent, action-specific acknowledgements or approval records, execution events, and post-checks. Operational insights are derived from current sources when requested and are not persisted.

## Current Status

Gjallar is under active development. The current application is a modular monolith in transition, built with a React SPA, FastAPI, PostgreSQL/Alembic, and the Proxmox API. Authentication, live inventory, selected VM operations, operation history, risks, and read-only insights are implemented, while some older workflows still use the previous internal structure.

The earlier DRS-centered product direction has been retired. Placement and capacity signals now appear in read-only Insights. Existing `/drs` and `/api/v1/drs/*` routes remain as maintenance compatibility surfaces for recommendations and checks, policies, approval packets, and a narrow migration and reconciliation workflow, but they are not the product's main feature or a claim of autonomous infrastructure control.

- [Product specification](project-docs/specifications/project-specification.md)
- [Current architecture](project-docs/architecture/overview.md)
- Architecture decisions: [ADR-001](project-docs/decisions/adr-001-proxmox-gjallar-authority-boundary.md), [ADR-002](project-docs/decisions/adr-002-modular-monolith-domain-boundaries.md), [ADR-003](project-docs/decisions/adr-003-production-inventory-connection-truth.md)
- [Transition plan](project-docs/plans/2026-07-20-verified-operations-control-plane-transition.md)

## Current Capabilities

- Local users and sessions with `viewer < operator < admin` role-based access control
- Live Proxmox inventory for nodes, VMs, templates, storage, and networks
- Native VM creation with exact-plan approval, risk acknowledgement when required, and a final mutation acknowledgement
- Guarded VM start with acknowledgement, idempotency, task polling, and an observed-state post-check
- Guided `qm unlock <vmid>` with a five-minute instruction, trusted-actor attestation, and Proxmox API verification; the backend does not execute the command
- A common operation projection and event history for VM creation, VM start, and guided unlock
- Jobs, artifacts, and operational risks for reviewing previous work
- Read-only readiness, capacity, placement, and stored-risk insights with source and freshness information
- A same-origin React SPA and FastAPI API packaged as a single production Docker image

## Connection Truth

The Proxmox connection is reported as `unconfigured`, `live`, or `degraded`. Production runtime never substitutes mock or demo inventory when the live connection is unavailable.

Inventory-dependent pages and mutation controls are available only in `live` mode. When the connection is not live, Insights retain stored risks but mark readiness, capacity, and placement data as unavailable. Jobs, Risks, Account, and Admin remain accessible.

## Operation Boundaries

- Create VM binds approval to the plan artifact and checksum. Yellow risk requires explicit acknowledgement, red risk blocks execution, and a final `proxmox_mutation_acknowledged=true` is required before dispatch. The current `operator` and `admin` roles can approve and execute; a separate four-eyes approver role is not implemented.
- VM Start requires an explicit acknowledgement and idempotency key before execution.
- Guided Unlock requires a risk acknowledgement and idempotency key, the node's `Sys.Audit` permission, no active task, and a supported current config lock before issuing a five-minute `qm unlock <vmid>` instruction. The backend does not execute the command. Operator attestation alone is not success; Gjallar must observe both the config lock and active task as absent through the Proxmox API.
- A timeout, missing task reference, or post-check mismatch remains a non-success or reconciliation state without an automatic mutation retry or fallback. Complete recovery from a hard process interruption is not yet implemented.
- Create VM, VM Start, and Guided Unlock share a target-scoped local file lock for the configured cluster. The current lock is designed for a single-container runtime, not multiple replicas.
- Insights are read-only. They do not expose an approval, operation, or mutation path.

## Current Limitations

- Supported mutations are intentionally narrow. Gjallar has no Stop, Shutdown, Reboot, Reset, Delete, Snapshot, or Rollback API surface; no arbitrary shell, SSH, or `qm` executor; and no autonomous remediation or automatic balancing.
- Inventory and inventory-dependent operations require a live Proxmox connection.
- Long-running operations do not yet have a durable runner, lease, or complete automatic restart recovery.
- Local target locks are not shared across replicas and may be lost when runtime storage is replaced.
- Existing DRS maintenance workflows use a separate lock and state model. They are not yet serialized with the common Create VM, VM Start, and Guided Unlock target lock.
- Not every backend workflow and frontend screen has moved to the target modular-monolith boundaries.

## Local Development

The supported local runtime matches the repository toolchain: Python 3.13, Node.js 24, pnpm 10, and PostgreSQL.

```bash
cp .env.example .env
nvm use
npm install --global pnpm@10.34.5
python3.13 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements-dev.lock
pnpm --dir frontend install --frozen-lockfile
```

Set `GJALLAR_DATABASE_URL` in `.env` to a PostgreSQL database, then initialize and start the application.

```bash
set -a
. ./.env
set +a
PYTHONPATH=backend backend/venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend backend/venv/bin/python -m app.db.seed_create_vm_profiles
PYTHONPATH=backend backend/venv/bin/python -m app.auth.users create-admin --username admin
pnpm run dev
```

- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/health`

`.python-version`, `.nvmrc`, package engines, `packageManager`, and lockfiles define the local toolchain. Generated virtual environments and `node_modules` are not committed. When changing direct Python dependencies, update both `requirements*.txt` and the corresponding Python 3.13/Linux `requirements*.lock` files.

## Docker

```bash
docker build -t gjallar:local .
docker run --rm --env-file .env -p 8000:8000 gjallar:local
```

Container startup applies Alembic migrations, seeds the Create VM profiles, optionally creates a bootstrap admin, and then starts Uvicorn. The bootstrap account is created only when both `GJALLAR_BOOTSTRAP_ADMIN_USERNAME` and `GJALLAR_BOOTSTRAP_ADMIN_PASSWORD` are set.

## Safety Rules

- Contributors must obtain explicit out-of-band authorization before running live Proxmox mutations or smoke tests against a real target.
- Gjallar does not silently fall back to `qm` or repeat a mutation when an API result is ambiguous.
- Arbitrary shell and SSH execution are outside the product scope.
- Secrets such as `.env` values, passwords, API tokens, session tokens, and private keys must not be committed or stored in logs and artifacts.
- Applied Alembic migrations must not be edited or deleted.

## Verification

```bash
git diff --check
pnpm run verify
pnpm run verify:container
```

`pnpm run verify` runs backend tests, frontend tests, frontend lint, and the frontend production build. `pnpm run verify:container` builds the production image with Python 3.13 backend tests and Node.js 24/pnpm 10 frontend verification stages.

## Documentation

`project-docs/` is the active source of truth for the project.

- [Project profile](project-docs/project-profile.md)
- [Current API](project-docs/api/current-api-v1.md)
- [Database schema and ownership](project-docs/database/current-schema-and-ownership.md)
- [Operation lifecycle](project-docs/flows/verified-operation-lifecycle.md)
- [Operations runbook](project-docs/operations/runbook.md)

Historical live-smoke records remain under `project-docs/evidence/legacy-live-smoke/`, and previous rewrite artifacts remain under `artifacts/rewrite-baseline/`. Neither directory defines the active product scope.
