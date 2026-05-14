# Current Runbook

This is the current concise verification runbook for the implemented repo state. Prefer this file over the legacy [`../archive/operations/RUNBOOK.md`](../archive/operations/RUNBOOK.md).

## Backend validation

From `backend/`:

```bash
pytest
```

Latest consolidated backend validation baseline is recorded in
[`../current/README.md`](../current/README.md): `127 passed`. This runbook does
not claim that backend tests were rerun for this docs-only reorganization.

## Frontend validation

Run the frontend `.mjs` tests directly with Node.

From repo root:

```bash
for test_file in frontend/tests/*.mjs; do
  node "$test_file"
done
```

Lint and build from `frontend/`:

```bash
pnpm lint
pnpm build
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

- Frontend dev server convention is `http://127.0.0.1:5173`.
- Backend dev server convention is `http://127.0.0.1:8000`.
- Active API surface remains `/api/v1`.
- Jobs/Runs progress records are read from `GJALLAR_RUNS_ROOT`.

## Safety notes

- Treat inventory as read-only.
- Create VM live actions require approval, manifest commit verification, and explicit native Proxmox create acknowledgement.
- Do not rely on destructive VM list controls; the current UI does not expose them.
