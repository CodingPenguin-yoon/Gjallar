# Current Runbook

This is the current concise verification runbook for the implemented repo state. Prefer this file over the legacy [`../archive/operations/RUNBOOK.md`](../archive/operations/RUNBOOK.md).

## Backend validation

From `backend/`:

```bash
pytest
```

Latest consolidated backend validation baseline is recorded in
[`../current/README.md`](../current/README.md). This runbook intentionally does
not carry a separate backend pass count.

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
- Jobs/Runs progress records are read from the DB configured by `GJALLAR_DATABASE_URL`.
- Infra Explorer VM start uses `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start` and records `vm_start` jobs/artifacts in the DB-backed Jobs/Runs tables.

## Safety notes

- Treat inventory as read-only.
- Create VM live actions require approval, manifest commit verification, and explicit native Proxmox create acknowledgement.
- Create VM success remains stopped/powered-off and does not auto-start.
- Existing VM start requires an in-app acknowledgement, idempotency key, fresh inventory precheck, Proxmox task polling, and observed-after running evidence.
- Do not rely on destructive VM list controls; the current UI does not expose stop/reset/shutdown/reboot/delete/terminate.
