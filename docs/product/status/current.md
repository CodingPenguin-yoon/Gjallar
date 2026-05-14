# Current Implemented State

Last refreshed: 2026-05-14

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
- Create VM uses `/api/v1` draft/preflight/plan/approval endpoints, explicit node/template/storage/network/IP selections, manifest commit, and gated Proxmox native create.
- Create VM profile/template/network target design is documented in [`../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md), but it is not fully implemented yet.
- Current Create VM create policy is powered-off only: native Proxmox clone, boot disk resize when needed, and config may run after exact approval metadata, manifest commit verification, and `proxmox_mutation_acknowledged=true`; first power-on and Stage A smoke are separate deferred stages.
- Terraform plan/apply routes remain optional/deprecated legacy executor paths and are not used by the active UI.
- Read-only inventory is the safe baseline.
- `/placement` is currently a read-only Placement screen. The target product direction is to relabel and expand this route into DRS Advisor.

## Implemented behavior

- Instances UI is a single read-only grouped and collapsible card.
- Create VM review stores request manifests under the configured IaC root and publishes request progress to Jobs/Runs through `GJALLAR_RUNS_ROOT`.
- Create VM plan/review records `first_power_on_included=false`; the generated VMInstance manifest requests `desired_power_state: stopped`.
- `general-vm` currently defaults to 2 CPU / 4096 MB RAM / 50 GB disk to match the live Ubuntu template size; preflight blocks requests smaller than the selected template disk.
- There are no destructive VM list controls.
- Legacy `/api` deploy/provision/task/log/LLM routes and legacy helper code are removed from the active tree.
- Native Create VM polls the clone UPID, inspects cloned config for boot disk resize, applies config, reads `/status/current` and `/config`, writes `observed_after`, and marks applied only when the requested disk resize is unnecessary or completed and the VM exists on the target node and is still stopped.
- Task failure, unknown cloned disk size, resize failure, VM missing, or observed powered-on state records failed/`needs_reconciliation` and does not mark the manifest applied.

## Create VM target gap

The target design is not current implementation yet:

- Profiles should become Gjallar DB-seeded read-only presets with enabled
  `general-vm`, `runtime-server`, and `development-vm`.
- Current code still uses current built-in/profile paths and only `general-vm`
  is create-enabled.
- Target templates come from Proxmox live inventory with no Gjallar template
  catalog or registration window.
- Target Create VM networking should select target node, then an active live
  bridge on that node.
- Current code now uses explicit `bridge_id` from active live bridge inventory
  as the Create VM network source of truth. Incoming `network_id`/`networkId`
  is ignored for transition compatibility and is not echoed in active draft,
  plan, review, manifest, or job output.
- NetworkPolicy remains Networks-tab legacy/future policy UI and is not a
  red-gate source for Create VM static range membership.
- Static mode now requires explicit `static_ip`, `prefix`, and `gateway`
  across draft, preflight, plan/review, manifest, and native create
  preview/create.
- Native create no longer infers a `.1` gateway or `/24` prefix from
  `static_ip`.
- Profile has no power policy; create remains stopped/powered off. VM start is
  future Infra Explorer row action work with Jobs/Runs audit.

## Recent verification baseline

Development smoke and test results recorded for this refresh:

- Backend `PYTHONPATH=backend python3 -m pytest -q backend/tests`: `112 passed`.
- Frontend `node --test frontend/tests/*.mjs`: `11 passed`.
- Frontend `pnpm --dir frontend build`: passed.
- `git diff --check`: passed.

## Practical reading

- Use [`../../engineering/AI_CODING_WORKFLOW_PRINCIPLES.md`](../../engineering/AI_CODING_WORKFLOW_PRINCIPLES.md) for repo-local AI coding workflow rules.
- Use [`../../engineering/GJALLAR_CURRENT_WORK_PLAN.md`](../../engineering/GJALLAR_CURRENT_WORK_PLAN.md) for the living current-work checklist.
- Use [../operations/runbook.md](../operations/runbook.md) for current verification steps.
- Use [../prd/README.md](../prd/README.md) for shared PRD and working design material.
- Use [`../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md) for the Create VM target profile/template/network model.
- Use [`../../engineering/architecture/`](../../engineering/architecture/) for current code-oriented architecture notes; treat [`../../history/features/`](../../history/features/), [`../../history/operations/`](../../history/operations/), and [`../../history/roadmap/`](../../history/roadmap/) as historical context unless a file says otherwise.
