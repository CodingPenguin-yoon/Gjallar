# Goal 3: DRS Final Pre-Check And Operation Lock Foundation

Status: completed as a read-only foundation.

## Objective

Close the largest remaining pre-execution safety gap by adding DB-backed
operation locks and stronger read-only final pre-check evidence without
enabling live migration.

## Current Foundation

1. `operation_locks` schema/model exists for `drs_migration`.
2. DRS final pre-check queries active/stale/reconciliation-required locks for
   VM identity, Proxmox locator, and route scopes.
3. Released locks do not block; open locks block `would_be_executable`.
4. VM config-lock evidence is collected from curated inventory fields and
   blocks when present.
5. Active task, HA state, and quorum/cluster health remain explicit
   `not_collected` evidence in the current adapter.
6. Goal 5 later added the narrow mutation and UPID path.
7. Goal 6 later added verified post-check and reconciliation state.

## Non-Negotiables

- no live Proxmox mutation/smoke without explicit active-session user approval
- Do not call Proxmox mutation APIs from read-only foundation goals.
- Keep DRS execution authority separate from Create VM mutation authority.
- Proxmox current state remains the source of truth for VM/node/task/HA/storage
  state.
- Default migration policy remains `unknown` and execution-blocking.
- Low, medium, or unknown VM identity confidence remains execution-blocking.
- VMID/IP/name/node/tag/Create VM history alone is not stable identity
- Do not store large raw Proxmox inventory or config blobs.
- Do not add broad policy UI or a complex rule engine unless a later goal
  explicitly scopes it.

## Scope

1. Add a small `operation_locks` DB model and Alembic migration.
2. Define lock scopes:
   - VM identity lock
   - Proxmox VM locator lock: cluster + VMID
   - optional route lock: source node + target node
3. Define lock states:
   - `active`
   - `released`
   - `stale`
   - `reconciliation_required`
4. Extend DRS final pre-check to replace `operation_lock: not_implemented`
   with real Gjallar-local lock checks.
5. Add read-only Proxmox conflict evidence where current inventory supports it:
   - active task signal if available
   - config lock signal if available
   - HA state if available
   - cluster health/quorum if available
6. Keep unsupported Proxmox evidence explicit as `not_collected` or
   `not_implemented`; do not fake a healthy signal.
7. Add blockers for active/stale locks and known conflict evidence.
8. Add focused backend tests and docs.

## Out Of Scope

- Approval modal or approval endpoint.
- `drs_migration` job creation.
- Proxmox live migration mutation.
- UPID tracking.
- Operation lock acquisition/release flow.
- Reconciliation worker.
- Bulk policy UI.

## Definition Of Done

- Operation lock schema and model exist.
- Final pre-check reports operation lock state from DB.
- Active, stale, or reconciliation-required locks block
  `would_be_executable`.
- Released locks do not block final pre-check.
- Config-lock evidence is collected and blocks when present.
- Current Proxmox conflict evidence is represented as read-only checks.
- Unknown/uncollected conflict evidence is explicit and not treated as healthy.
- For this goal, `executable` remains false and no Proxmox mutation path is
  added.
- Focused backend tests and docs pass/update.

## Suggested Validation

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/db backend/tests/proxmox
node --test frontend/tests/drsAdvisor.test.mjs
git diff --check
```
