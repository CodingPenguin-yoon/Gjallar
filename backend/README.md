# Gjallar Backend

FastAPI backend for the Gjallar Proxmox operations console.

## Active Surface

- Public API contract: `/api/v1`
- Inventory: read-only Proxmox nodes, VMs, templates, storage, and networks
- Create VM: draft, preflight, plan, approval, IaC manifest commit, Terraform plan/apply gates
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
