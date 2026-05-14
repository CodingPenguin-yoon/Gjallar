# Gjallar PRD

This folder preserves the shared PRD set inside the repo in numeric order.

## How to use this folder

- Use [`../status/current.md`](../status/current.md) for the current implemented-state summary.
- Use this `prd/` folder for shared product definition, rewrite planning, handoff material, and historical working decisions.
- Treat PRD files as design and planning context, not as a guarantee that every described endpoint or flow is live today.

## Product identity

Current MVP product source of truth is [`drs-advisor/`](drs-advisor/README.md). If this document conflicts with that folder, `drs-advisor/` wins.

Gjallar is a human-facing Proxmox Enterprise Operations Platform.
The current MVP direction is [`drs-advisor/`](drs-advisor/README.md): observe Proxmox-native inventory/migration/HA state, recommend safe live migrations, require approval, execute through Proxmox, and track jobs/reconciliation.
Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.
DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.
Gjallar is not a backup product. PBS/Veeam references are backup evidence or future integration context only.
Terraform, Ansible, Hermes, AI, and agent flows are supporting control plumbing rather than the product identity.

## Navigation

| Document | Purpose |
|---|---|
| `01_MASTER_PRD.md` | Product identity, MVP scope, safety policy |
| `02_EXTERNAL_BOUNDARIES.md` | Boundaries with external systems |
| `03_MANIFEST_GITOPS.md` | Manifest and IaC storage direction |
| `04_SAFETY_PREFLIGHT.md` | Risk, approval, and preflight policy |
| `05_CREATE_VM_FLOW.md` | VM create flow design |
| `06_UI_SCREENS.md` | Human-facing screen definitions |
| `07_DB_JOBS_ARTIFACTS.md` | DB, job, and artifact roles |
| `08_IMPLEMENTATION_ROADMAP.md` | Planned implementation order |
| `09_OPEN_QUESTIONS.md` | Remaining product questions |
| `10_CODE_INVENTORY.md` | Legacy code inventory and reuse criteria |
| `11_KEEP_DROP_PARK.md` | Keep/drop/park decisions |
| `12_UI_API_CONTRACT.md` | UI-driven API contract |
| `13_MANIFEST_SCHEMA.md` | Manifest schema draft |
| `14_TDD_CONTRACT_PLAN.md` | Test-first implementation plan |
| `15_FIRST_IMPLEMENTATION_SLICE.md` | First slice handoff |
| `16_REVIEW_CHECKLIST.md` | Review checklist |
| `17_RELEASE_RUNBOOK.md` | Release and operations runbook |
| `18_PRD_AUDIT_CORRECTIONS.md` | PRD audit corrections |
| `19_MVP_DECISION_LOCK.md` | Locked MVP decisions |
| `20_REMAINING_DECISIONS.md` | Decisions still pending |
| `21_MVP_IMPLEMENTATION_HANDOFF.md` | MVP implementation handoff |
| `22_CODEBASE_REWRITE_EXECUTION_PLAN.md` | Rewrite execution plan |
| `23_PLACEMENT_PRD.md` | Placement screen and VM placement advisor product plan |
| `24_DRS_ADVISOR_MVP_PRD.md` | Numeric index for current DRS Advisor PRD folder |
| `drs-advisor/README.md` | Current DRS Advisor source of truth |

## Current vs historical

- Current MVP direction points to [`drs-advisor/`](drs-advisor/README.md); `24_DRS_ADVISOR_MVP_PRD.md` is only a numeric index.
- Current repo-local state and verification belong under [`../status/`](../status/current.md) and [`../operations/`](../operations/runbook.md).
- Create-first material is historical/supporting capability context only. It must not define the next MVP success line or implementation order.
- Current Create VM profile/template/network target design is [`../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md); status docs identify what is not implemented yet.
- Current engineering docs live under [`../../engineering/architecture/`](../../engineering/architecture/); historical feature, operations, and roadmap notes live under [`../../history/`](../../history/).
