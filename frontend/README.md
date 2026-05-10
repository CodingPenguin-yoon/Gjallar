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
