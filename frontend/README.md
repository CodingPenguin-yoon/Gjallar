# Gjallar Frontend

React + Vite operator UI for Gjallar.

## Product Direction vs Current UI

Current MVP product source of truth is `docs/product/drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.

The target direction is DRS Advisor. The current frontend exposes a read-only `/drs` DRS Advisor Phase 1 screen and a Create VM wizard as supporting capability. It does not yet provide identity/fingerprint status, final pre-check, Approve & Migrate, UPID tracking, or Reconcile Now UI.

DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.

## Main Screens

- Dashboard
- Infra Explorer
- Networks
- Create VM
- DRS Advisor
- Jobs/Runs
- Risks/Alerts

The frontend talks to the backend through `/api/v1` only.

## Run

```bash
cd frontend
pnpm dev -- --host 0.0.0.0 --port 5173
```

The Vite proxy reads runtime values from the repo root `.env` and optional `frontend/.env`.

```bash
FRONTEND_PORT=5173
BACKEND_PORT=8000
VITE_BACKEND_URL=http://127.0.0.1:8000
```

## Validate

```bash
pnpm lint
pnpm build
```

From the repo root, the contract tests can be run with:

```bash
for test_file in frontend/tests/*.mjs; do
  node "$test_file"
done
```
