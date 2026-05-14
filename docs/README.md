# Gjallar Docs

This is the single repo-local documentation entrypoint for Gjallar.

## Product

Use this section for product direction, current implemented state, operational guidance, and PRD navigation.

- [Product docs](product/README.md)
- [Current implemented state](product/status/current.md)
- [Current runbook](product/operations/runbook.md)
- [Product PRD index](product/prd/README.md)
- [DRS Advisor source of truth](product/prd/drs-advisor/README.md)

## Engineering

Use this section for current code-oriented architecture notes and implementation contracts.

- [Engineering architecture](engineering/architecture/)
- [VM operations architecture](engineering/architecture/VM_OPERATIONS_ARCHITECTURE.md)
- [Create VM contract](engineering/architecture/VM_PROVISIONING_CONTRACT.md)
- [Create VM native architecture](engineering/architecture/CREATE_VM_NATIVE_ARCHITECTURE.md)
- [Create VM profile/template/network target design](engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md)
- [Backend README](../backend/README.md)
- [Frontend README](../frontend/README.md)

## History

Use this section for older implementation notes, planning records, refresh notes, and audit history. These files are background only and do not override the current product source of truth.

- [Historical feature notes](history/features/)
- [Historical operations notes](history/operations/)
- [Historical roadmap notes](history/roadmap/)
- [Historical status refreshes](history/status/)

Current MVP product source of truth is [`docs/product/prd/drs-advisor/`](product/prd/drs-advisor/README.md). If another document conflicts with that folder, `drs-advisor/` wins.

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
