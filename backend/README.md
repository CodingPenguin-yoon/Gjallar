# Gjallar Backend

FastAPI backend for the Gjallar Proxmox operations console.

## Product Direction vs Current Backend

Current MVP product source of truth is `docs/product/prd/drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.

The target direction is DRS Advisor. The current backend provides read-only Proxmox inventory, Jobs/Runs, Risks, and approval-gated Create VM support. It does not yet provide `/api/v1/drs/*`, DRS identity/fingerprint tables, backend recommendation generation, final pre-check, Proxmox live migration execution, UPID tracking, operation locks, or reconciliation.

Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.

DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.

## Active Surface

- Public API contract: `/api/v1`
- Inventory: read-only Proxmox nodes, VMs, templates, storage, and networks
- Create VM: draft, preflight, plan, approval, IaC manifest commit, Terraform plan/apply gates for powered-off creation
- Jobs/Runs and Risks: read-only MVP summaries

Legacy `/api` deploy/provision/task/log/LLM routes are not part of the active backend.

## Run

```bash
cp .env.example .env
pnpm run backend
```

The backend loads the repo root `.env`. `BACKEND_PORT` controls the local uvicorn port, and `FRONTEND_PORT` controls the CORS origin allowed for the Vite dev server.

## Validate

From the repo root:

```bash
PYTHONPATH=backend pytest -q backend/tests
```

## Notes

- The app loads the repo root `.env`.
- `GJALLAR_RUNS_ROOT` controls where Jobs/Runs progress records are stored.
- Do not commit `.env`, tokens, secrets, `data/`, or local runtime artifacts.
- Live VM creation remains gated behind explicit approval and Terraform apply acknowledgement.
