# Current Implemented State

Last refreshed: 2026-05-11

Gjallar is a human-facing Proxmox Operations & Risk Console. Hermes, AI, and agent flows are control plumbing around the product, not the product identity.

## Active surface

- The active frontend contract remains `/api/v1`.
- Do not treat `/api/instances` or `/api/provision` as the active frontend surface.
- Inventory is live read-only Proxmox data with a fake fallback when live inventory is unavailable.
- Create VM uses `/api/v1` draft/preflight/plan/approval endpoints, explicit node/template/storage/network/IP selections, and gated IaC/Terraform actions.
- Current Create VM apply policy is powered-off only: Terraform may clone/configure the VM after explicit apply acknowledgement, but first power-on and Stage A smoke are separate deferred stages.
- Read-only inventory is the safe baseline.

## Implemented behavior

- Instances UI is a single read-only grouped and collapsible card.
- Create VM review stores request manifests under the configured IaC root and publishes request progress to Jobs/Runs through `GJALLAR_RUNS_ROOT`.
- Create VM plan/review records `first_power_on_included=false`; the generated VMInstance manifest requests `desired_power_state: stopped`.
- There are no destructive VM list controls.
- Legacy `/api` deploy/provision/task/log/LLM routes and legacy helper code are removed from the active tree.
- Live Terraform apply remains approval-gated and fail closed.

## Recent verification baseline

Development smoke and test results recorded for this refresh:

- Backend `pytest` result: `89 passed`.
- Frontend `.mjs` contract tests: passed.
- Frontend lint: passed.
- Frontend build: passed.

## Practical reading

- Use [../operations/runbook.md](../operations/runbook.md) for current verification steps.
- Use [../prd/README.md](../prd/README.md) for shared PRD and working design material.
- Treat [`../../docs/`](../../docs/README.md) as historical context only.
