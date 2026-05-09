# Current Implemented State

Last refreshed: 2026-05-09

Gjallar is a human-facing Proxmox Operations & Risk Console. Hermes, AI, and agent flows are control plumbing around the product, not the product identity.

## Active surface

- The active frontend contract remains `/api/v1`.
- Do not treat `/api/instances` or `/api/provision` as the active frontend surface.
- Inventory is live read-only Proxmox data with a fake fallback when live inventory is unavailable.
- Read-only inventory is the safe baseline.

## Implemented behavior

- Instances UI is a single read-only grouped and collapsible card.
- The card uses fixed columns and truncation.
- There are no destructive VM list controls.
- Lifecycle and provisioning mutations remain approval-gated and fail closed.

## Recent verification baseline

Development smoke and test results recorded for this refresh:

- Frontend `127.0.0.1:5174` returned status `200`.
- `/api/v1/nodes` returned `200` with count `3`.
- `/api/v1/vms` returned `200` with count `25`.
- Node ids returned: `yoonmanserver`, `yoonmanserver2`, `yoonserver3`.
- Backend `pytest` result: `46 passed`.
- Frontend tests: passed.
- Frontend build: passed.

## Practical reading

- Use [../operations/runbook.md](../operations/runbook.md) for current verification steps.
- Use [../prd/README.md](../prd/README.md) for shared PRD and working design material.
- Treat [`../../docs/`](../../docs/README.md) as historical context only.
