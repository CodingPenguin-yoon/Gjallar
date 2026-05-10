# Gjallar Frontend

React + Vite operator UI for Gjallar.

## Main Screens

- Dashboard
- Infra Explorer
- Networks
- Create VM
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
