# Gjallar PRD

This folder preserves the shared PRD set inside the repo in numeric order.

## How to use this folder

- Use [`../status/current.md`](../status/current.md) for the current implemented-state summary.
- Use this `prd/` folder for shared product definition, rewrite planning, handoff material, and historical working decisions.
- Treat PRD files as design and planning context, not as a guarantee that every described endpoint or flow is live today.

## Product identity

Gjallar is a human-facing Proxmox Operations & Risk Console.
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

## Current vs historical

- Current repo-local state and verification belong under [`../status/`](../status/current.md) and [`../operations/`](../operations/runbook.md).
- Older repo docs under [`../../docs/`](../../docs/README.md) are retained as historical reference.
