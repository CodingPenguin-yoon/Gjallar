# Gjallar Implementation Roadmap

Last updated: 2026-05-27

## Purpose

This is the implementation roadmap to read before starting a new Gjallar slice.
It connects the implemented-state docs, DRS product target, architecture notes,
and validation commands into one execution-oriented view.

This document does not replace detailed requirements. It tells the next engineer
what is implemented, what remains, what should be built next, and which source
documents to read for the detailed contract.

## Source Of Truth

Use this order when documents disagree:

1. Active code and tests.
2. Current implemented state: [`docs/current/README.md`](../current/README.md).
3. Top-tab snapshots: [`docs/current/top-tabs/`](../current/top-tabs/README.md).
4. Current and target architecture: [`docs/architecture/`](../architecture/README.md).
5. DRS product target: [`docs/product/drs-advisor/`](../product/drs-advisor/README.md).
6. Legacy PRDs and archive docs only as historical context.

For implementation order, read this file first, then open the specific product
or architecture document linked from the relevant phase.

## Current Baseline

Gjallar is currently a Proxmox Operations & Risk Console with these active
surfaces:

| Area | Current implementation | Current status |
|---|---|---|
| Dashboard | Proxmox inventory, Jobs/Runs, Risks aggregation. | Implemented read-only overview. |
| Infra Explorer | VM/node inventory, VM detail, gated stopped-VM Start action. | Implemented; no DRS identity panel yet. |
| Networks | Selected-source read-only network readiness and migration pre-check visualization. | Implemented; no mutation or DRS authority. |
| Create VM | DB profile seed, draft/preflight/plan/approval, native Proxmox create, jobs/artifacts, request/VM records. | Implemented supporting capability. |
| DRS Advisor | `/drs` UI with backend-owned read-only recommendations/check. | Phase 1 implemented; all recommendations `executable=false`. |
| Jobs/Runs | DB-backed latest job state and artifact metadata. | Implemented for Create VM and VM start. |
| Risks/Alerts | Job-derived risk summaries. | Implemented; not yet a DRS blocker engine. |
| Auth/Admin | Local login, server-side sessions, RBAC, and admin local-user management. | Implemented; no public signup/OAuth/API tokens. |

Implemented DB tables:

- `create_vm_profiles`
- `job_runs`
- `job_artifacts`
- `vm_create_requests`
- `vm_instances`
- `users`
- `sessions`

Not implemented yet:

- generalized DRS VM identity/fingerprint DB
- DRS metadata/policy DB
- DRS observed VM/node history
- final pre-check
- operation locks
- DRS approval/migration job execution
- Proxmox migration UPID tracking
- reconciliation/restart safety worker

## Current Product Direction

DRS Advisor is the next MVP success line. Create VM is a strong supporting
capability, but it must not define DRS execution semantics.

Before DRS Phase 2 implementation, keep the Create VM supporting capability
closed under login/session/role-based authorization and admin-managed local
accounts. The agreed stabilization plan is
[`CREATE_VM_STABILIZATION_PLAN.md`](CREATE_VM_STABILIZATION_PLAN.md).

DRS execution must not open until VM identity, fingerprint, metadata, policy,
final pre-check, operation locks, UPID tracking, post-check, and reconciliation
contracts are in place.

## Feature Matrix

| Feature | Implemented | Remaining | Next action | Key docs |
|---|---|---|---|---|
| `/drs` read-only Advisor | Backend endpoints and UI route exist. | Add real identity/policy evidence and richer table fields. | Close Phase 1 docs/tests, then start identity DB. | [`05_IMPLEMENTATION_PLAN.md`](../product/drs-advisor/05_IMPLEMENTATION_PLAN.md) |
| Create VM auth/session hardening | Login/session/RBAC, actor evidence, admin local-user management, and approved 2026-05-28 live smoke are implemented. | Future live smoke or cleanup still needs explicit approval. | Proceed to DRS identity. | [`CREATE_VM_STABILIZATION_PLAN.md`](CREATE_VM_STABILIZATION_PLAN.md) |
| Recommendation calculation | Uses current CPU/memory pressure, imbalance, bridge/storage evidence, red-risk exclusion. | 15m average/peak metrics, HA/quorum/task/lock evidence. | Add identity/fingerprint first; metrics can follow in same Phase 2 track. | [`04_DRS_RECOMMENDATION_AND_EXECUTION.md`](../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md) |
| VM identity/fingerprint | Create VM stores `observed_after` fingerprint evidence in artifacts and `vm_instances`. | No generalized identity for all Proxmox VMs. | Implement DRS identity/fingerprint DB and resolver. | [`03_DATA_DB_AND_IDENTITY.md`](../product/drs-advisor/03_DATA_DB_AND_IDENTITY.md), [`data-identity/overview.md`](../architecture/data-identity/overview.md) |
| Metadata/policy | Not implemented for DRS. | owner/environment/sensitivity/migration_policy, allowed/restricted/blocked. | Add read-only metadata/policy model after identity table shape. | [`03_DATA_DB_AND_IDENTITY.md`](../product/drs-advisor/03_DATA_DB_AND_IDENTITY.md) |
| Final pre-check | Not implemented. Current `/check` is reference-only. | Authoritative live reread before migration. | Implement only after identity/policy resolver exists. | [`target-drs-api.md`](../architecture/api/target-drs-api.md) |
| Migration execution | Not implemented. | Approval, locks, mutation client, UPID, post-check. | Keep blocked until Phase 4/5. | [`drs-approve-migrate-reconcile.md`](../architecture/flows/drs-approve-migrate-reconcile.md) |
| Reconciliation/restart safety | Not implemented for DRS. | Reattach by UPID/current state/fingerprint, Reconcile Now. | Implement after migration job model and locks. | [`05_IMPLEMENTATION_PLAN.md`](../product/drs-advisor/05_IMPLEMENTATION_PLAN.md) |

## DRS Implementation Phases

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

## Current Next Slice

Recommended next slice before DRS Phase 2:

1. Implement Create VM stabilization from
   [`CREATE_VM_STABILIZATION_PLAN.md`](CREATE_VM_STABILIZATION_PLAN.md):
   login, sessions, roles, protected mutation APIs, frontend login, and live
   smoke documentation.
2. Keep Create VM scope closed: no SSH smoke, Ansible, app bootstrap, profile
   management UI, or DRS identity registration in this stabilization slice.
3. After stabilization, start DRS Phase 2 identity/fingerprint work.

Recommended first DRS slice after stabilization:

1. Add the roadmap and status docs cleanup.
2. Extend inventory models/adapters with fingerprint evidence fields.
3. Add Alembic/SQLAlchemy tables for DRS identity and metadata.
4. Add a read-only identity resolver with contract tests.
5. Feed resolver output into DRS recommendations while keeping all execution
   unavailable.

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
