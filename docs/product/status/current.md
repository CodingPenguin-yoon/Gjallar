# Current Implemented State

Last refreshed: 2026-05-11

Gjallar is a human-facing Proxmox Operations & Risk Console. Hermes, AI, and agent flows are control plumbing around the product, not the product identity.

Current MVP product source of truth is [`../prd/drs-advisor/`](../prd/drs-advisor/README.md). If this document conflicts with that folder, `drs-advisor/` wins.

## Product direction vs implemented state

- Product direction: DRS Advisor is the next MVP success line.
- Current implementation: read-only Proxmox inventory, Dashboard, Infra Explorer, Networks, read-only Placement, Jobs/Runs, Risks/Alerts, and Create VM supporting capability.
- Current gap: backend DRS recommendation API, VM identity/fingerprint policy, DRS final pre-check, approval-gated live migration, Proxmox UPID tracking, operation locks, and reconciliation are not implemented yet.
- Create VM is a supporting existing capability. It must not define the next MVP success line or implementation order.
- Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.
- DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.
- PBS/Veeam references are backup evidence or future integration context only.

## Active surface

- The active frontend contract remains `/api/v1`.
- Do not treat `/api/instances` or `/api/provision` as the active frontend surface.
- Inventory is live read-only Proxmox data with a fake fallback when live inventory is unavailable.
- Create VM uses `/api/v1` draft/preflight/plan/approval endpoints, explicit node/template/storage/network/IP selections, and gated IaC/Terraform actions.
- Current Create VM apply policy is powered-off only: Terraform may clone/configure the VM after explicit apply acknowledgement, but first power-on and Stage A smoke are separate deferred stages.
- Read-only inventory is the safe baseline.
- `/placement` is currently a read-only Placement screen. The target product direction is to relabel and expand this route into DRS Advisor.

## Implemented behavior

- Instances UI is a single read-only grouped and collapsible card.
- Create VM review stores request manifests under the configured IaC root and publishes request progress to Jobs/Runs through `GJALLAR_RUNS_ROOT`.
- Create VM plan/review records `first_power_on_included=false`; the generated VMInstance manifest requests `desired_power_state: stopped`.
- `general-vm` currently defaults to 2 CPU / 4096 MB RAM / 50 GB disk to match the live Ubuntu template size; preflight blocks requests smaller than the selected template disk.
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
- Use [`../../engineering/architecture/`](../../engineering/architecture/) for current code-oriented architecture notes; treat [`../../history/features/`](../../history/features/), [`../../history/operations/`](../../history/operations/), and [`../../history/roadmap/`](../../history/roadmap/) as historical context unless a file says otherwise.
