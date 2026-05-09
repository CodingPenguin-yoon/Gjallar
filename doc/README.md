# Gjallar Docs

Gjallar is a human-facing Proxmox Operations & Risk Console.

This `doc/` tree is the active repo-local documentation set for the current implemented state. Use it first. The older [`docs/`](../docs/README.md) tree is retained as historical reference and may describe superseded plans or endpoints.

## Start here

- [Current status](status/current.md)
- [Operations runbook](operations/runbook.md)
- [PRD index](prd/README.md)
- [Docs refresh note](status/refresh-2026-05-09.md)

## Current product framing

- Active frontend contract: `/api/v1`
- Safe live surface: read-only Proxmox inventory, with fallback data when live inventory is unavailable
- Mutations: lifecycle and provisioning flows remain approval-gated and fail closed
- UI baseline: Instances is a single read-only grouped and collapsible card with fixed columns and truncation
