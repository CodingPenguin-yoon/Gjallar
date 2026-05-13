# Gjallar Docs

Gjallar is a human-facing Proxmox Operations & Risk Console.

This product tree is the active repo-local product documentation set. Use it for current product direction, implementation status, runbook guidance, and PRD navigation.

Current MVP product source of truth is [`prd/drs-advisor/`](prd/drs-advisor/README.md). If this document conflicts with that folder, `drs-advisor/` wins.

## Start here

- [Current status](status/current.md)
- [Operations runbook](operations/runbook.md)
- [PRD index](prd/README.md)
- [Historical docs refresh note](../history/status/refresh-2026-05-09.md)

## Current product framing

- Current MVP direction: DRS Advisor.
- Active frontend contract: `/api/v1`
- Safe live surface: read-only Proxmox inventory, with fallback data when live inventory is unavailable
- Current implementation: read-only inventory, read-only Placement, Jobs/Runs/Risks summaries, and approval-gated Create VM support
- Target gap: backend DRS recommendation, identity/fingerprint policy, final pre-check, approved live migration, Proxmox UPID tracking, and reconciliation are not implemented yet
- Create VM is a supporting existing capability, not the next MVP success line or implementation order
- Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.
- DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.
- PBS/Veeam references are backup evidence or future integration context only.
