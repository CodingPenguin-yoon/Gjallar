# Goal 2: DRS Safe Execution Readiness Foundation

Status: completed on 2026-05-28.

Follow-on DRS slices are tracked in
`docs/goal/drs-execution-goal-slices.md`.

## Purpose

This goal prepares DRS Advisor for safe future execution without adding live
migration yet.

The goal is intentionally larger than only "VM identity" and intentionally
smaller than "DRS migration execution". It builds the foundation DRS needs
before any migration mutation can be trusted:

- stable VM identity and fingerprinting
- operator migration policy memory
- identity/policy blockers in DRS recommendations
- read-only final pre-check
- tests and docs that keep the safety contract explicit

## Plain Terms

- VM identity means Gjallar can recognize the same Proxmox VM after inventory
  refresh, service restart, node move, or harmless name/config changes.
- Fingerprint means the small set of stable evidence Gjallar uses to decide
  whether a Proxmox VM observation belongs to an existing identity.
- Observation means one read-only view of a VM from current Proxmox inventory.
- Migration policy means the operator's remembered decision about whether this
  VM is allowed to be moved by DRS later.
- Final pre-check means the last read-only safety check before a future
  migration execution path. This goal does not execute migration.

## Objective

Build the DB-backed identity, fingerprint, migration policy, and read-only final
pre-check foundation required before DRS migration execution can be safely added.

Gjallar must recognize the same Proxmox VM across node moves, inventory
refreshes, and service restarts. Unknown, uncertain, or policy-blocked VMs must
remain execution-ineligible.

## Non-Negotiables

- Do not implement live migration execution.
- Do not call Proxmox mutation APIs.
- Keep DRS Advisor read-only.
- Default migration policy is `unknown` and execution-blocking.
- Low-confidence VM identity is execution-blocking.
- Keep DB schema small and normalized.
- Do not store large raw Proxmox inventory blobs unless explicitly justified.
- Do not add a broad policy UI in this goal.
- Do not add a complex rule engine in this goal.
- Do not make Create VM the DRS success line.
- Prefer targeted implementation over broad refactors.

## Why This Scope

Too small:

- If the goal only creates identity tables, DRS still cannot explain why a
  recommendation is unsafe or prove that a future execution target is still the
  same VM.

Too large:

- If the goal includes live migration execution, operation locks, full
  reconciliation, bulk policy UI, and rule evaluation, the data model and safety
  contract will be harder to review and easier to get wrong.

Correct slice:

- Build the read-only safety substrate first. DRS can recommend and explain,
  but cannot mutate Proxmox.

## Starting Point

- Create VM live smoke completed on 2026-05-28.
- Create VM stores `observed_after` fingerprint evidence for newly created VMs.
- DRS Advisor is currently read-only.
- DRS final pre-check, identity/fingerprint policy, DB-backed operation lock
  lookup, and config-lock evidence are implemented as read-only foundations.
- Live migration, approval/job substrate, operation lock acquisition/release,
  UPID tracking, and reconciliation are not implemented yet.
- Proxmox remains the source of truth for actual VM, node, task, HA, storage,
  and network state.

## Target Data Model

The schema should be minimal. Exact naming can follow existing local patterns.

### `vm_identities`

Long-lived identity row for one VM.

Recommended fields:

- `vm_identity_id`
- `cluster_id`
- `stable_fingerprint`
- `identity_status`: `active`, `uncertain`, `retired`
- `first_seen_at`
- `last_seen_at`
- `created_at`
- `updated_at`

Notes:

- This table should not duplicate full inventory payloads.
- This table should survive node moves and normal inventory refreshes.

### `vm_identity_observations`

Small observed evidence row from read-only Proxmox inventory.

Recommended fields:

- `observation_id`
- `vm_identity_id`
- `observed_at`
- `cluster_id`
- `node_id`
- `vmid`
- `name`
- `power_state`
- `template`
- `fingerprint_hash`
- `fingerprint_components`
- `match_confidence`
- `match_reason`
- `source`

Notes:

- Store only the fields needed to explain identity matching.
- If `fingerprint_components` is JSON, keep it small and curated.
- Do not store raw large Proxmox inventory blobs.

### `vm_migration_policies`

Operator policy row for DRS movement eligibility.

Recommended fields:

- `policy_id`
- `vm_identity_id`
- `policy`: `unknown`, `allowed`, `restricted`, `blocked`
- `reason`
- `source`: `default`, `manual`, `tag`, `imported`
- `updated_by`
- `created_at`
- `updated_at`

Policy behavior:

- `unknown`: default. Recommendation may be shown, execution ineligible.
- `allowed`: eligible if identity and final pre-check also pass.
- `restricted`: not automatically executable; final pre-check must explain the
  restriction.
- `blocked`: execution ineligible.

## Fingerprint Design Rules

The resolver should compute a stable fingerprint from curated evidence.

Good candidates:

- Proxmox VM config UUID or SMBIOS UUID when available
- VMID plus cluster evidence
- current node plus VMID as a locator, not a permanent identity by itself
- name as weak evidence only
- disk identifiers or config hashes when stable enough
- MAC addresses only if they are stable in this environment and treated as
  supporting evidence, not the only identity
- Create VM `observed_after` fingerprint if the VM was created by Gjallar

Avoid:

- relying only on VM name
- relying only on current node
- treating current node plus VMID as enough after migration becomes possible
- storing raw full config unless a small normalized fingerprint would not work

## Matching Confidence

The resolver should classify match confidence in a way DRS can explain.

Suggested values:

- `high`: strong stable fingerprint match
- `medium`: multiple supporting evidence fields match, but no strong stable id
- `low`: weak or conflicting evidence
- `unknown`: no identity row or no usable fingerprint

Execution eligibility:

- `high`: can proceed to policy and final pre-check
- `medium`: read-only recommendation can be shown, but execution remains blocked
  unless a later goal explicitly defines a manual confirmation path
- `low`: blocked
- `unknown`: blocked

## DRS Blockers

Add these blockers to recommendation or final pre-check output:

- `vm_identity_unknown`
- `vm_identity_uncertain`
- `migration_policy_unknown`
- `migration_policy_restricted`
- `migration_policy_blocked`
- `drs_final_precheck_failed`

Existing DRS blockers should continue to work. This goal should not replace the
current read-only DRS recommendation logic; it should enrich it.

## Read-Only Final Pre-Check

Add a final pre-check model or endpoint that rereads current state and reports
whether a recommendation would be executable in the future.

It must remain read-only.

Minimum checks:

- VM identity still resolves with acceptable confidence.
- Migration policy allows execution.
- Source VM still exists.
- Source node still matches the recommendation or the recommendation is marked
  stale.
- Target node still exists and is eligible.
- VM power/state is still eligible according to current DRS rules.
- Storage and network evidence still match the recommendation.
- Recommendation is not stale.
- No existing conflict signal is present. DB-backed DRS operation lock lookup
  reports matching active/stale/reconciliation-required locks and blocks
  `would_be_executable`; released locks do not block.

Output should include:

- `executable`: always false until a later live migration goal enables mutation
- `would_be_executable`: true only when identity, policy, and read-only checks pass
- `blockers`
- `identity_evidence`
- `policy_evidence`
- `checked_at`

## API And UI Expectations

Backend:

- Keep DRS endpoints read-only.
- Add or extend a DRS read endpoint for identity and final pre-check evidence.
- Do not add mutation endpoints for migration.

Frontend:

- Show why a recommendation is blocked.
- Show identity/policy status in a compact operator-facing way.
- Do not add migration execute buttons.
- Do not require operators to classify every VM manually in this goal.

## User Policy Workflow

The product should not force a user to review every VM one by one.

This goal should support the safe default:

- unclassified VM means `unknown`
- `unknown` blocks execution
- DRS can still show recommendations with a clear blocker

Future goals can add:

- bulk classification
- tag-based defaults
- import/export
- owner/team/environment metadata
- richer policy UI

Do not build those future workflows in this goal unless they are the smallest
possible support needed by the read-only blocker model.

## Implementation Order

1. Read current DRS, inventory, DB, and Create VM fingerprint code paths.
2. Write a short local design note or implementation summary before editing.
3. Add Alembic migration for the minimal tables.
4. Add SQLAlchemy models and DB helpers.
5. Implement fingerprint extraction from current inventory.
6. Implement read-only identity resolver.
7. Add migration policy default handling.
8. Feed identity and policy blockers into DRS recommendation output.
9. Add read-only final pre-check model or endpoint.
10. Add focused tests.
11. Update current docs and handoff docs.

## Required Tests

Backend tests should cover:

- new DB migration/model behavior
- identity creation from first observation
- identity match on repeated observation
- unknown identity blocker
- low-confidence identity blocker
- default `unknown` policy blocker
- `blocked` policy blocker
- `allowed` policy with passing identity reaches read-only final pre-check
- stale recommendation or changed VM state blocks final pre-check
- DRS endpoints remain read-only

Frontend tests should cover only visible contract changes if the UI is touched:

- recommendation blocker display
- identity/policy labels
- no execute action exposed

## Validation

Run the relevant subset first:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/proxmox
node --test frontend/tests/drsAdvisor.test.mjs
git diff --check
```

If shared contracts or UI surfaces change broadly, expand to:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
node --test frontend/tests/*.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```

## Out Of Scope

- Live migration execution.
- Proxmox mutation calls.
- Operation lock acquisition/release or reconciliation behavior beyond the
  read-only lookup foundation.
- Full reconciliation worker.
- Bulk policy UI.
- Full owner/team/environment metadata system.
- Complex rule engine.
- SSH, Ansible, app bootstrap, or guest workload validation.
- Automatic deletion or cleanup of any VM.

## Definition Of Done

- DB migration and models exist.
- Current inventory VMs can be resolved to identity records or marked unknown.
- Low-confidence identity blocks DRS execution eligibility.
- Unknown, restricted, or blocked migration policy blocks DRS execution
  eligibility.
- DRS recommendation output explains identity and policy blockers.
- Read-only final pre-check reports executable/non-executable status with
  reasons.
- No live migration or Proxmox mutation path is added.
- Relevant tests pass.
- Docs describe the model, matching rules, blockers, and next steps.

## Goal Prompt

Use this prompt to start the next goal:

```text
Goal resume.

Use docs/goal/drs-safe-execution-readiness-foundation.md as the controlling
goal document.

Objective: implement the DRS Safe Execution Readiness Foundation. Build the
minimal DB-backed VM identity/fingerprint, migration policy, DRS blocker, and
read-only final pre-check foundation needed before live migration execution can
be added.

Hard constraints:
- Do not implement live migration execution.
- Do not call Proxmox mutation APIs.
- Keep DRS Advisor read-only.
- Default migration policy is unknown and execution-blocking.
- Low-confidence VM identity is execution-blocking.
- Keep schema small and normalized.
- Do not store large raw Proxmox inventory blobs unless explicitly justified.
- Do not add a broad policy UI or complex rule engine.
- Preserve Create VM as a supporting capability, not the DRS success line.

Expected result:
- DB migration and models for VM identity, observations, and migration policy.
- Read-only identity resolver using current Proxmox inventory evidence.
- DRS recommendation blockers for identity and policy state.
- Read-only final pre-check output that explains executable/non-executable
  status without performing mutation.
- Focused backend tests, frontend tests only if the UI changes, and updated docs.

Before editing, inspect the current DRS, inventory, DB model, migration, and
Create VM fingerprint/evidence paths. Keep implementation targeted and avoid
unrelated refactors.
```
