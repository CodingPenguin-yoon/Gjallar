# Gjallar

Gjallar is a human-facing Proxmox Operations & Risk Console.

The active repo-local documentation lives under [`docs/`](docs/README.md). Start there for product docs, current engineering notes, and historical material.

## Current product direction

- Current MVP product source of truth is [`docs/product/prd/drs-advisor/`](docs/product/prd/drs-advisor/README.md). If this document conflicts with that folder, `drs-advisor/` wins.
- DRS Advisor is the next MVP success line: Proxmox-native migration recommendations, approval-gated live migration, Proxmox task tracking, audit, and reconciliation.
- DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.
- Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.
- PBS/Veeam references are backup evidence or future integration context only.

## Current state at a glance

- The active frontend contract remains `/api/v1`.
- Inventory is live read-only Proxmox data with a fake fallback when live inventory is unavailable.
- The current UI provides Dashboard, Infra Explorer, Networks, Create VM, read-only Placement, Jobs/Runs, and Risks/Alerts.
- Current code has read-only Placement and Create VM as supporting capabilities; it does not yet implement backend DRS recommendation, identity/fingerprint policy, approved migration execution, UPID tracking, or reconciliation.
- Create VM mutations remain approval-gated, Terraform-backed, and fail closed. Create VM is a supporting existing capability, not the next MVP success line.
- There are no destructive VM list controls in the current UI.

## Local Runtime Env

Copy `.env.example` to `.env` and adjust local paths or ports as needed. The root `pnpm run dev` scripts and the Vite dev proxy both read this file.

Key values:

- `FRONTEND_PORT`: Vite dev server port, default `5173`
- `BACKEND_PORT`: FastAPI backend port, default `8000`
- `VITE_BACKEND_URL`: frontend dev proxy target, default `http://127.0.0.1:8000`
- `GJALLAR_SHARED_ROOT`, `GJALLAR_IAC_ROOT`, `GJALLAR_RUNS_ROOT`: shared IaC and run-state paths

## Product framing

- Gjallar owns safe human-facing visibility and operational control for Proxmox.
- Hermes, AI, and agent workflows are supporting control plumbing, not the product identity.
- Read-only inventory is the safe baseline.

## Where to read next

- [Docs index](docs/README.md)
- [Current implemented state](docs/product/status/current.md)
- [Current runbook](docs/product/operations/runbook.md)
- [Product PRD index](docs/product/prd/README.md)
