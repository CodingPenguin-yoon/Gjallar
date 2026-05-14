# Gjallar Docs

This is the single repo-local documentation entrypoint for Gjallar.

## Current

Use this section for implemented behavior and current UI/API snapshots.

- [Current implemented state](current/README.md)
- [Current top-tab snapshots](current/top-tabs/README.md)

## Product

Use this section for active product direction and older PRD context.

- [Product docs](product/README.md)
- [DRS Advisor target direction](product/drs-advisor/README.md)
- [Legacy PRD index](product/legacy-prd/README.md)

## Architecture

Use this section for current and target architecture notes, implementation contracts, and known stale statements.

- [Architecture index](architecture/README.md)
- [VM operations architecture](architecture/VM_OPERATIONS_ARCHITECTURE.md)
- [Create VM contract](architecture/VM_PROVISIONING_CONTRACT.md)
- [Create VM native architecture](architecture/CREATE_VM_NATIVE_ARCHITECTURE.md)
- [Create VM profile/template/network target design](architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md)
- [Backend README](../backend/README.md)
- [Frontend README](../frontend/README.md)

## Operations

Use this section for current verification and operator safety notes.

- [Current runbook](operations/runbook.md)

## Engineering

Use this section for repo-local execution workflow and current work planning.

- [AI coding workflow principles](engineering/AI_CODING_WORKFLOW_PRINCIPLES.md)
- [Current work plan](engineering/GJALLAR_CURRENT_WORK_PLAN.md)

## Archive

Use this section for older implementation notes, planning records, refresh notes, and audit history. These files are background only.

- [Archived feature notes](archive/features/)
- [Archived operations notes](archive/operations/)
- [Archived roadmap notes](archive/roadmap/)
- [Archived status refreshes](archive/status/)

## Source Of Truth Order

Current implemented behavior:

1. Active code and tests.
2. [`docs/current/README.md`](current/README.md).
3. [`docs/current/top-tabs/`](current/top-tabs/README.md).
4. [`docs/architecture/`](architecture/README.md) current-architecture docs.
5. [`docs/product/drs-advisor/`](product/drs-advisor/README.md) only for target direction and planned gaps.
6. [`docs/product/legacy-prd/`](product/legacy-prd/README.md) and [`docs/archive/`](archive/) as context only.

Product target / MVP direction:

1. [`docs/product/drs-advisor/`](product/drs-advisor/README.md).
2. [`docs/architecture/`](architecture/README.md) target architecture docs.
3. [`docs/current/README.md`](current/README.md) and [`docs/current/top-tabs/`](current/top-tabs/README.md) for current gaps.
4. [`docs/product/legacy-prd/`](product/legacy-prd/README.md) as older design context only.
5. [`docs/archive/`](archive/) as historical notes only.

Workflow / execution:

1. [`AGENTS.md`](../AGENTS.md).
2. [`docs/engineering/AI_CODING_WORKFLOW_PRINCIPLES.md`](engineering/AI_CODING_WORKFLOW_PRINCIPLES.md).
3. [`docs/engineering/GJALLAR_CURRENT_WORK_PLAN.md`](engineering/GJALLAR_CURRENT_WORK_PLAN.md).

Operations:

1. [`docs/operations/runbook.md`](operations/runbook.md).
2. Current status verification notes in [`docs/current/README.md`](current/README.md).
3. Archived operations notes only as history.

## Active Contract Summary

- The active backend surface is `/api/v1`.
- Legacy `/api/instances`, `/api/provision`, task/log, deploy, and LLM surfaces are not active.
- Inventory is read-only and may use a fake fallback when live Proxmox inventory is unavailable.
- Create VM is a gated draft -> preflight -> plan -> approval -> manifest commit -> Proxmox native create path.
- Terraform remains optional/deprecated legacy executor code and is not the active UI default.
- Live native create remains explicit-acknowledgement only and creates/configures a powered-off VM after Proxmox post-check/`observed_after`.
- Target Create VM profile/template/network design uses DB-seeded profiles, Proxmox live templates, and selected target-node live bridges; current code still has known implementation gaps documented in status.
- Read-only Placement exists today; target direction is DRS Advisor.
- Dashboard and read-only screens should stay available when NFS-backed job history is unavailable.
