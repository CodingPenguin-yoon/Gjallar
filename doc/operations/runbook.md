# Current Runbook

This is the current concise verification runbook for the implemented repo state. Prefer this file over the legacy [`docs/operations/RUNBOOK.md`](../../docs/operations/RUNBOOK.md).

## Backend validation

From `backend/`:

```bash
pytest
```

Current recorded result for this docs refresh: `46 passed`.

## Frontend validation

Run the frontend `.mjs` tests directly with Node.

From repo root:

```bash
for test_file in frontend/tests/*.mjs; do
  node "$test_file"
done
```

Build from `frontend/`:

```bash
npm run build
```

Current recorded result for this docs refresh:

- Frontend tests passed.
- Frontend build passed.

## Diff hygiene

From repo root:

```bash
git diff --check
```

Use this to catch malformed whitespace or patch issues before any commit.

## Basic `/api/v1` smoke notes

The active frontend contract is `/api/v1`.

Current recorded smoke baseline:

- Frontend on `http://127.0.0.1:5174` returned `200`.
- `GET /api/v1/nodes` returned `200` with `3` nodes.
- `GET /api/v1/vms` returned `200` with `25` VMs.
- Expected node ids in the recorded smoke were `yoonmanserver`, `yoonmanserver2`, and `yoonserver3`.

## Safety notes

- Treat inventory as read-only.
- Mutating lifecycle and provisioning flows require approval and fail closed.
- Do not rely on destructive VM list controls; the current UI does not expose them.
