# Gjallar

Gjallar is a human-facing Proxmox Operations & Risk Console.

The active repo-local documentation now lives under [`doc/`](doc/README.md). Start there for current state, runbook guidance, and PRD navigation. The older [`docs/`](docs/README.md) tree is preserved as historical reference only.

## Current state at a glance

- The active frontend contract remains `/api/v1`.
- Inventory is live read-only Proxmox data with a fake fallback when live inventory is unavailable.
- The current Instances UI is a single read-only grouped and collapsible card with fixed columns and truncation.
- Lifecycle and provisioning mutations remain approval-gated and fail closed.
- There are no destructive VM list controls in the current UI.

## Local Runtime Env

Copy `.env.example` to `.env` and adjust local paths or ports as needed. The root `pnpm run dev` scripts and the Vite dev proxy both read this file.

Key values:

- `FRONTEND_PORT`: Vite dev server port, default `5173`
- `BACKEND_PORT`: FastAPI backend port, default `8000`
- `VITE_BACKEND_URL`: frontend dev proxy target, default `http://127.0.0.1:8000`
- `REMOTE_IAC_REPO`: shared IaC Git checkout path, for example `/Users/yoon/mnt/nfs/IaC`
- `GJALLAR_SHARED_ROOT`, `GJALLAR_IAC_ROOT`, `GJALLAR_RUNS_ROOT`: shared IaC and run-state paths

## Product framing

- Gjallar owns safe human-facing visibility and operational control for Proxmox.
- Hermes, AI, and agent workflows are supporting control plumbing, not the product identity.
- Read-only inventory is the safe baseline.

## Where to read next

- [doc/README.md](doc/README.md)
- [doc/status/current.md](doc/status/current.md)
- [doc/operations/runbook.md](doc/operations/runbook.md)
- [doc/prd/README.md](doc/prd/README.md)
