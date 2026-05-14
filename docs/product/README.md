# Gjallar Product Docs

Gjallar is a human-facing Proxmox Operations & Risk Console / operations platform.

This product tree is focused on product direction. Current implemented status, operational runbooks, and architecture docs live outside this folder.

## Start Here

- [DRS Advisor target direction](drs-advisor/README.md)
- [Legacy PRD index](legacy-prd/README.md)
- [Current implemented state](../current/README.md)
- [Architecture index](../architecture/README.md)

## Product Framing

- DRS Advisor is the next MVP success line.
- Create VM is a supporting capability, not the MVP success line.
- Proxmox is the source of truth for actual VM/node/task/HA/storage state.
- Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.
- DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, automatic DRS for Proxmox, or a backup product.
- PBS/Veeam references are backup evidence or future integration context only.

## Current Boundaries

- The active contract is `/api/v1`.
- Old `/api/instances`, `/api/provision`, deploy/task/log/LLM surfaces are not active.
- Current `/placement` is a read-only Placement seed; the target direction is DRS Advisor.
- There is no `/api/v1/drs/*`, identity/fingerprint DB, final pre-check, live migration, operation locks, UPID tracking, or reconciliation yet.
- The active Create VM path is native Proxmox preview/create, not Terraform.
- Terraform remains an optional/deprecated legacy executor until removed.
- Create VM success is powered-off/stopped only after Proxmox post-check and `observed_after`.
- Inventory is read-only with fake fallback.
- Dashboard and read-only screens should remain usable when NFS-backed job history is unavailable.
