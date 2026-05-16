# Gjallar Architecture Docs

Status source: [current product status](../current/README.md). Top-tab status index: [top tabs](../current/top-tabs/README.md).

This folder describes Gjallar by domain. It separates current implementation, target DRS Advisor architecture, and stale or superseded statements from older PRDs.

## Source Of Truth Order

Use this order when current-implementation documents conflict:

1. Active code for current behavior: `frontend/src`, `backend/app`, and current tests.
2. Current product status: [`docs/current/README.md`](../current/README.md).
3. Top-tab status pages under [`docs/current/top-tabs/`](../current/top-tabs/README.md).
4. Current architecture files in this folder.
5. [`docs/product/drs-advisor/`](../product/drs-advisor/README.md) only for target direction and planned gaps.
6. [`docs/product/legacy-prd/`](../product/legacy-prd/README.md) and [`docs/archive/`](../archive/) as context only.

Use this order when product-target documents conflict:

1. [`docs/product/drs-advisor/`](../product/drs-advisor/README.md).
2. Target architecture files in this folder.
3. [`docs/current/README.md`](../current/README.md) and [`docs/current/top-tabs/`](../current/top-tabs/README.md) for current gaps.
4. [`docs/product/legacy-prd/`](../product/legacy-prd/README.md) as older design context only.
5. [`docs/archive/`](../archive/) as historical notes only.

Do not copy old PRD statements blindly. Several early PRD slices describe single-profile Create VM, `server-net` as a Create VM gate, Terraform as the active UI path, or DRS execution as if it were already implemented. Those statements are superseded unless a current status page and active code both confirm them.

## Current Vs Target Convention

| Term | Meaning |
|---|---|
| Current | Implemented in the active app as of 2026-05-14 and reachable through current routes or API handlers. |
| Target | Product or architecture direction that is not implemented yet. |
| Legacy/deprecated | Historical or compatibility behavior that may be documented for context; do not assume it exists in current code. |
| Deferred | Known follow-up work with no current implementation. |

Important boundaries:

- Current `/placement` is a frontend read-only Placement read model, not backend DRS Advisor execution.
- Current Create VM live mutation is `POST /api/v1/vm-create/{draft_id}/proxmox-create`.
- Legacy `POST /api/v1/vm-create/{draft_id}/execute` has been removed; current live VM creation is `proxmox-create`.
- Current Create VM networking uses selected target-node active live bridge plus explicit `bridge_id`, `static_ip`, `prefix`, and `gateway`.
- Terraform plan/apply endpoints are removed; the active frontend uses native Proxmox preview/create.
- Jobs/Runs and Risks/Alerts are read-only UI surfaces. Jobs are DB-backed through `job_runs`/`job_artifacts`; risks are derived from recorded job risks. Current job producers include Create VM and the Infra Explorer VM start action.

## Domain Index

| Domain | File |
|---|---|
| System overview | [`system/overview.md`](system/overview.md) |
| Current `/api/v1` contract | [`api/current-api-v1.md`](api/current-api-v1.md) |
| Target DRS API candidates | [`api/target-drs-api.md`](api/target-drs-api.md) |
| Dashboard | [`dashboard/overview.md`](dashboard/overview.md) |
| Infra Explorer | [`infra-explorer/overview.md`](infra-explorer/overview.md) |
| Networks | [`network/overview.md`](network/overview.md) |
| Create VM overview | [`create-vm/overview.md`](create-vm/overview.md) |
| Native Create VM flow | [`create-vm/native-create-flow.md`](create-vm/native-create-flow.md) |
| Create VM profile/template/network model | [`create-vm/profile-template-network.md`](create-vm/profile-template-network.md) |
| Placement and target DRS Advisor | [`placement-drs-advisor/overview.md`](placement-drs-advisor/overview.md) |
| Target DRS recommendation/execution | [`placement-drs-advisor/recommendation-and-execution.md`](placement-drs-advisor/recommendation-and-execution.md) |
| Data identity | [`data-identity/overview.md`](data-identity/overview.md) |
| Jobs/Runs | [`jobs-runs/overview.md`](jobs-runs/overview.md) |
| Risks/Alerts | [`risks-alerts/overview.md`](risks-alerts/overview.md) |
| Create VM review-to-create flow | [`flows/create-vm-review-to-create.md`](flows/create-vm-review-to-create.md) |
| Target DRS approve/migrate/reconcile flow | [`flows/drs-approve-migrate-reconcile.md`](flows/drs-approve-migrate-reconcile.md) |
| Stale and superseded statements | [`appendices/stale-and-superseded.md`](appendices/stale-and-superseded.md) |

## Existing Architecture Notes

Use these supporting references:

- [`VM_OPERATIONS_ARCHITECTURE.md`](VM_OPERATIONS_ARCHITECTURE.md): broad current system shape and DRS target gap.
- [`VM_PROVISIONING_CONTRACT.md`](VM_PROVISIONING_CONTRACT.md): detailed Create VM endpoint contract.
- [`CREATE_VM_NATIVE_ARCHITECTURE.md`](CREATE_VM_NATIVE_ARCHITECTURE.md): native Proxmox create internals.
- [`CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md): target profile/template/network design with current gaps.
