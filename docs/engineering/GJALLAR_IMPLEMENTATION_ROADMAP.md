# Gjallar Implementation Roadmap

Last updated: 2026-05-30

## Purpose

This is historical implementation roadmap context for Gjallar slices. It
connects the implemented-state docs, DRS product target, architecture notes,
and validation commands into one execution-oriented view.

This document does not replace detailed requirements. It tells the next engineer
what is implemented, what remains, and which source documents to read for the
detailed contract. For current implementation order and the next gate, use
[`docs/goal/README.md`](../goal/README.md).

## Source Of Truth

Use this order when documents disagree:

1. Active code and tests.
2. Goal sequencing and next gate: [`docs/goal/README.md`](../goal/README.md).
3. Current implemented state: [`docs/current/README.md`](../current/README.md).
4. Top-tab snapshots: [`docs/current/top-tabs/`](../current/top-tabs/README.md).
5. Current and target architecture: [`docs/architecture/`](../architecture/README.md).
6. DRS product target: [`docs/product/drs-advisor/`](../product/drs-advisor/README.md).
7. Legacy PRDs and archive docs only as historical context.

For implementation order, read `docs/goal/README.md` first, then use this file
as phase background when it is still relevant.

## Current Baseline

Gjallar is currently a Proxmox Operations & Risk Console with these active
surfaces:

| Area | Current implementation | Current status |
|---|---|---|
| Dashboard | Proxmox inventory, Jobs/Runs, Risks aggregation. | Implemented read-only overview. |
| Infra Explorer | VM/node inventory, VM detail, gated stopped-VM Start action. | Implemented; no DRS identity panel yet. |
| Networks | Selected-source read-only network readiness and migration pre-check visualization. | Implemented; no mutation or DRS authority. |
| Create VM | DB profile seed, draft/preflight/plan/approval, native Proxmox create, jobs/artifacts, request/VM records. | Implemented supporting capability. |
| DRS Advisor | `/drs` UI with identity/policy evidence, manual VM policy configuration, read-only final pre-check, approval/job substrate, narrow execution route, UPID tracking, verified post-check, and read-only Reconcile preview. | Goal Check, Goal 7 minimal UI polish, and Goal 7.5 VM policy configuration are complete. |
| Jobs/Runs | DB-backed latest job state and artifact metadata. | Implemented for Create VM, VM start, and DRS migration jobs. |
| Risks/Alerts | Job-derived risk summaries. | Implemented; not yet a DRS blocker engine. |
| Auth/Admin | Local login, server-side sessions, RBAC, and admin local-user management. | Implemented; no public signup/OAuth/API tokens. |

Implemented DB tables:

- `create_vm_profiles`
- `job_runs`
- `job_artifacts`
- `vm_create_requests`
- `vm_instances`
- `vm_identities`
- `vm_identity_observations`
- `vm_migration_policies`
- `vm_migration_policy_events`
- `operation_locks`
- `drs_approval_packets`
- `drs_migration_jobs`
- `drs_reconciliation_events`
- `users`
- `sessions`

Remaining or deferred:

- DRS observed VM/node history
- 15-minute average/peak metric substrate
- broader DRS execution UI beyond the safe slice
- live DRS migration smoke evidence
- corrective reconciliation mutation
- background reconciliation automation
- automatic DRS

## Current Product Direction

DRS Advisor is the next MVP success line. Create VM is a strong supporting
capability, but it must not define DRS execution semantics.

Keep the Create VM supporting capability closed under login/session/role-based
authorization and admin-managed local accounts. The stabilization plan is
[`CREATE_VM_STABILIZATION_PLAN.md`](CREATE_VM_STABILIZATION_PLAN.md).

DRS execution authority remains gated by VM identity, fingerprint, policy,
final pre-check, operation locks, approval, UPID tracking, post-check, and
reconciliation contracts. Goal 7.5 DRS VM Policy Configuration is complete; no
live DRS smoke was run.

## Feature Matrix

| Feature | Implemented | Remaining | Next action | Key docs |
|---|---|---|---|---|
| `/drs` Advisor | Backend endpoints and UI route exist with compact identity/policy evidence plus manual VM policy configuration. | Broader execution UI and live DRS smoke evidence. | Follow `docs/goal/README.md` for the next user-selected task. | [`docs/goal/README.md`](../goal/README.md) |
| Create VM auth/session hardening | Login/session/RBAC, actor evidence, admin local-user management, and approved 2026-05-28 live smoke are implemented. | Future live smoke or cleanup still needs explicit approval. | Keep as supporting capability. | [`CREATE_VM_STABILIZATION_PLAN.md`](CREATE_VM_STABILIZATION_PLAN.md) |
| Recommendation calculation | Uses current CPU/memory pressure, imbalance, bridge/storage evidence, red-risk exclusion, identity/policy blockers, operation-lock evidence, config-lock evidence, and final pre-check readiness. | 15m average/peak metrics and deeper read-only HA/quorum/task collection. | Keep as backend-owned evidence. | [`04_DRS_RECOMMENDATION_AND_EXECUTION.md`](../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md) |
| VM identity/fingerprint | DB-backed DRS identities, observations, curated fingerprints, confidence, migration policy memory, and manual VM policy configuration exist. | Future operations polish. | Keep identity policy keyed to `vm_identity_id`. | [`docs/goal/goal-07-5-drs-vm-policy-management.md`](../goal/goal-07-5-drs-vm-policy-management.md) |
| Metadata/policy | Migration policy memory exists with default `unknown` blocking execution, manual UI/API updates, and audit evidence. | Richer future policy metadata/rule engine remains deferred. | Preserve `allowed` as prerequisite only. | [`docs/goal/goal-07-5-drs-vm-policy-management.md`](../goal/goal-07-5-drs-vm-policy-management.md) |
| Final pre-check | Read-only final pre-check exists with identity, policy, operation-lock, and config-lock blockers. | Advisor adapter still marks some task/HA/quorum evidence as explicit `not_collected`; execution collects live pre-mutation evidence separately. | Verify in Goal Check. | [`docs/goal/goal-check-01-06-implementation-quality.md`](../goal/goal-check-01-06-implementation-quality.md) |
| Migration execution | Narrow approval-gated backend execution route exists with dedicated DRS migration client, operation locks, and UPID tracking. | Live DRS smoke evidence remains pending explicit approval. | Do not broaden execution without a new explicit goal. | [`drs-approve-migrate-reconcile.md`](../architecture/flows/drs-approve-migrate-reconcile.md) |
| Reconciliation/restart safety | Verified post-check, `needs_reconciliation`, reconciliation events, and read-only Reconcile preview exist. | Corrective mutation and background reconciliation automation remain deferred. | Keep deferred without a new explicit goal. | [`05_IMPLEMENTATION_PLAN.md`](../product/drs-advisor/05_IMPLEMENTATION_PLAN.md) |

## DRS Implementation Phases

The phase sections below preserve the original roadmap shape. Current goal
status and sequencing are superseded by [`docs/goal/README.md`](../goal/README.md).

### Phase 1: Read-Only DRS Advisor

Status: implemented.

Implemented:

- active route: `/drs`
- active backend read endpoints:
  - `GET /api/v1/drs/summary`
  - `GET /api/v1/drs/recommendations`
  - `GET /api/v1/drs/recommendations/{recommendation_id}`
  - `POST /api/v1/drs/recommendations/{recommendation_id}/check`
- server-side recommendation calculator in `backend/app/drs/advisor.py`
- recommendations are always read-only and `executable=false`
- default blockers include identity, metadata, policy, and final-precheck gaps
- route/local-storage/passthrough/target-pressure blockers are represented
- no approve/migrate/live-migrate route exists

Exit criteria:

- DRS route and backend endpoints pass contract tests.
- Frontend test and production build pass.
- Current docs no longer refer to active `/placement`.

### Phase 2: Identity, Fingerprint, Metadata, And Policy

Status: next major implementation phase.

Goal:

Build the persistent identity layer needed before any DRS execution can be
considered.

Scope:

- collect explicit fingerprint evidence from Proxmox inventory:
  - SMBIOS UUID
  - `vmgenid`
  - MAC address list
  - disk volume id list
- add DB-backed identity and metadata concepts:
  - `vm_identity_assertions`
  - `vm_metadata`
  - likely `observed_vms`
  - possibly `observed_nodes` or metric samples if the metrics slice is bundled
- build a read-only resolver that maps live inventory VMs to DB identity state:
  - `confirmed`
  - `unknown`
  - `mismatch`
  - `retired_candidate`
- enforce these rules:
  - VMID alone is only a locator
  - same VMID plus same fingerprint can attach metadata
  - same VMID plus different fingerprint becomes Identity Mismatch
  - unknown fingerprint blocks migration
  - name, tag, IP, owner, and profile cannot confirm identity by themselves
- add metadata/policy fields:
  - owner
  - environment
  - sensitivity
  - migration_policy: `allowed | restricted | blocked`

Non-goals:

- no migration execution
- no approval mutation
- no operation lock enforcement
- no automatic DRS

Expected contracts/tests:

- same VMID with different primary fingerprint creates mismatch
- unknown fingerprint produces identity blocker
- metadata incomplete produces metadata blocker
- restricted/blocked policies disable migration availability
- allowed plus confirmed plus complete metadata can remove identity/policy
  blockers, but still cannot execute until final pre-check exists

Primary docs:

- [`03_DATA_DB_AND_IDENTITY.md`](../product/drs-advisor/03_DATA_DB_AND_IDENTITY.md)
- [`data-identity/overview.md`](../architecture/data-identity/overview.md)
- [`05_IMPLEMENTATION_PLAN.md`](../product/drs-advisor/05_IMPLEMENTATION_PLAN.md)

### Phase 3: DRS Advisor UI And Recommendation Integration

Status: planned.

Goal:

Wire Phase 2 identity and policy state into DRS recommendations and the UI.

Scope:

- recommendation rows show identity status, metadata completeness, policy, VM
  mobility, and route status
- DRS details show fingerprint assertion summary and policy evidence
- Dashboard can show top DRS recommendations without implying execution
- `/check` remains reference-only until final pre-check exists

Exit criteria:

- `identity_unknown`, `metadata_missing`, and `policy_unknown` are calculated
  from DB resolver state, not only static Phase 1 blockers
- frontend shows blockers and policy state clearly
- no migration mutation endpoint is exposed

### Phase 4: Final Pre-Check And Operation Locks

Status: planned.

Goal:

Add the authoritative final gate that rereads Proxmox current state and Gjallar
identity/policy/lock state immediately before any migration.

Scope:

- final pre-check endpoint or approve-migrate preflight packet
- checks current source node, VM running state, target health, route, policy,
  identity/fingerprint, active tasks, and locks
- operation lock table and stale/reconciliation-required states
- warning acknowledgement contract

Non-goals:

- Proxmox migration mutation can still remain disabled until Phase 5.

### Phase 5: Approved Proxmox Migration Execution

Status: planned.

Goal:

Execute manual, operator-approved live migration through Proxmox.

Scope:

- narrow DRS mutation client separate from read-only inventory adapter
- migration approval record
- DRS migration job
- Proxmox UPID capture and polling
- task log artifact
- post-check VM target node, running state, and fingerprint
- release locks only after clear success/failure

Success must require Proxmox current state and fingerprint match, not only a
successful Proxmox task response.

### Phase 6: Reconciliation And Restart Safety

Status: planned.

Goal:

Make Gjallar restart and uncertain migration outcomes safe.

Scope:

- startup reconciliation scan
- reattach running/unknown DRS jobs by UPID and Proxmox current state
- Reconcile Now endpoint/action
- reconciliation event records
- timeout handling
- stale lock handling

Core rule:

Metadata and policy may reattach only by current fingerprint match. Same VMID
with different fingerprint must become Identity Mismatch and block work.

## Current Goal Sequence

This roadmap is historical planning context. Current goal sequencing is tracked
in [`docs/goal/README.md`](../goal/README.md).

Completed later work includes Create VM stabilization, DRS identity/fingerprint
foundation, operation locks, approval/job substrate, narrow live migration
execution with UPID tracking, post-check/reconciliation, Goal Check 01-06,
Goal 7 DRS UI/operations polish, and Goal 7.5 DRS VM Policy Configuration. No
live DRS smoke was run.

Suggested first implementation boundary:

- Backend only plus focused tests.
- No UI mutation.
- No migration endpoint.
- No final pre-check endpoint.

Likely files:

- `backend/app/proxmox/models.py`
- `backend/app/proxmox/inventory.py`
- `backend/app/db/models.py`
- `backend/alembic/versions/*`
- new `backend/app/drs/identity.py` or equivalent
- `backend/app/drs/advisor.py`
- `backend/tests/contracts/test_api_v1_drs.py`
- `backend/tests/proxmox/test_inventory_adapter.py`

## Validation

Run focused validation after each DRS slice:

```bash
PYTHONPATH=backend backend/venv/bin/pytest -q backend/tests/contracts backend/tests/proxmox
node --test frontend/tests/*.mjs
pnpm --dir frontend build
git diff --check
```

Run broader validation before marking a phase complete:

```bash
PYTHONPATH=backend backend/venv/bin/pytest -q backend/tests
node --test frontend/tests/*.mjs
pnpm --dir frontend build
git diff --check
```

Run `pnpm --dir frontend lint` when frontend source or styling changes and the
local dependency/tooling state supports it.

## Deferred

These are not part of the next implementation phase:

- automatic DRS
- scheduled or nightly rebalance
- node drain automation
- maintenance mode automation
- affinity/anti-affinity editor
- backup/snapshot orchestration
- restricted exception approval
- artifact auto deletion
- VMware DRS compatibility claims

## Update Rules

Update this file when:

- a phase is completed
- the next slice changes
- a new DB table or API contract lands
- a validation baseline changes
- a target decision changes implementation order

Do not mark a feature implemented unless active code and tests support that
claim. If a document describes target behavior only, keep the wording explicit.
