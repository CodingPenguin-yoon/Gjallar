# Gjallar Backend

FastAPI backend for the Gjallar Proxmox operations console.

## Product Direction vs Current Backend

Current MVP product source of truth is `docs/product/drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.

The target direction is DRS Advisor. The current backend provides read-only Proxmox inventory, gated VM start from Infra Explorer, Jobs/Runs, Risks, and approval-gated Create VM support. Create VM's active mutation path is native Proxmox API clone/config/post-check; the legacy Terraform executor route surface and helper code are removed. The backend does not yet provide `/api/v1/drs/*`, DRS identity/fingerprint tables, backend recommendation generation, final pre-check, Proxmox live migration execution, operation locks, or reconciliation.

Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, Create VM request/VM records, audit, and reconciliation state.

DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.

## Active Surface

- Public API contract: `/api/v1`
- Inventory: read-only Proxmox nodes, VMs, templates, storage, and networks
- Infra Explorer VM start: acknowledgement/idempotency-gated QEMU start for stopped non-template VMs, with Proxmox task polling and `vm_start` job/artifact evidence
- Create VM: draft, preflight, plan, approval, Proxmox native preview/create for powered-off creation, and DB request/VM records
- Legacy Terraform Create VM executor: removed; old plan/apply URLs naturally 404
- Jobs/Runs and Risks: read-only MVP summaries

Legacy `/api` deploy/provision/task/log/LLM routes are not part of the active backend.

## Run

```bash
cp .env.example .env
cd backend
alembic upgrade head
python -m app.db.seed_create_vm_profiles
cd ..
pnpm run backend
```

The backend loads the repo root `.env`. `BACKEND_PORT` controls the local uvicorn port, and `FRONTEND_PORT` controls the CORS origin allowed for the Vite dev server.
`GJALLAR_DATABASE_URL` controls the SQLAlchemy/Alembic connection. Local SQLite is supported, and PostgreSQL can be used by changing the same URL.

## Validate

From the repo root:

```bash
PYTHONPATH=backend pytest -q backend/tests
```

## Notes

- The app loads the repo root `.env`.
- Create VM profiles are schema-managed by Alembic and seeded separately with `cd backend && python -m app.db.seed_create_vm_profiles`. The seed is idempotent and no-ops when any profile row already exists.
- Jobs/Runs progress and artifacts are stored through `GJALLAR_DATABASE_URL` in `job_runs` and `job_artifacts`.
- Do not commit `.env`, tokens, secrets, `data/`, or local runtime artifacts.
- Live VM creation remains gated behind exact approval metadata, fresh red-risk checks, and `proxmox_mutation_acknowledged=true`.
- Native creation and VM start reuse `PROXMOX_API_URL`, `PROXMOX_API_TOKEN_ID`, `PROXMOX_API_TOKEN_SECRET`, and `PROXMOX_TLS_INSECURE`; the mutation client is separate from the read-only inventory adapter.
