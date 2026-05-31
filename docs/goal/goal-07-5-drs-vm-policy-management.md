# Goal 7.5: DRS VM Policy Configuration

Status: completed on 2026-05-31. No live DRS smoke was run.

## Objective

Add the operator-facing VM configuration workflow for DRS migration eligibility
before live DRS smoke, Goal 8, or Goal 9 work.

Gjallar already has compact VM identity/fingerprint evidence and a
`vm_migration_policies` table. The missing product operation is a way for an
operator to open the VM list, choose a resolved VM identity, and configure that
VM's DRS migration policy as `allowed`, `restricted`, `blocked`, or `unknown`,
with reason, actor, audit evidence, and clear DRS Advisor impact.

This is primarily VM-level DRS configuration, not a live migration task. Safety
and auditability are implementation constraints around that configuration
workflow.

## Implementation Evidence

Implemented slice: `GET /api/v1/drs/policies`,
`GET /api/v1/drs/policies/{vm_identity_id}`, and
`PUT /api/v1/drs/policies/{vm_identity_id}`; `/drs` VM policy configuration
UI with filters and deliberate review modal; immutable
`vm_migration_policy_events` audit evidence; focused backend DB/service/API/auth
tests and frontend client/view-model/auth-flow tests. Validation passed for the
focused backend DRS/contracts/DB suite, focused frontend tests, frontend lint,
frontend build, and `git diff --check`.

## Why This Goal Exists

DRS execution currently requires migration policy `allowed`, but the default
policy is `unknown` and execution-blocking. Operators need an explicit place to
configure which VMs are eligible, restricted, blocked, or still unclassified.

Goal 8 covers opt-in sanitized post-create readiness evidence for
already-created VMs. Goal 9 covers account and session operations. Neither goal
owns VM-level DRS policy configuration, so this work is inserted as Goal 7.5.

## Standing Non-Negotiables

- no live Proxmox mutation/smoke without explicit active-session user approval
- Do not add automatic DRS.
- Do not add corrective reconciliation mutation or background automation.
- Do not weaken backend DRS execution gates.
- Do not treat VMID, IP, name, tag, Create VM history, or current node alone as
  stable policy identity.
- Do not create or update migration policy against a raw Proxmox VM locator.
  Policy must attach to a Gjallar `vm_identity_id`.
- Default `unknown` remains execution-blocking.
- Low, medium, stale, missing, or mismatched identity evidence remains
  execution-blocking.
- Do not infer `allowed` from tags, names, ranges, or prior Create VM records in
  this goal.
- Do not write raw Proxmox inventory blobs, secrets, or large config payloads to
  policy records or audit artifacts.
- Do not accept editable actor/operator fields from the client. Use the trusted
  authenticated session actor.

## Target Policy Semantics

Policy values:

- `unknown`: default, no operator decision recorded, execution-blocking
- `allowed`: operator permits this resolved VM identity to be considered for
  DRS migration, subject to all other fresh gates
- `restricted`: VM may be movable only under a future explicit exception path;
  current DRS execution remains blocked
- `blocked`: VM must not be migrated by DRS

`allowed` is not execution approval. It is only one prerequisite. Live migration
still requires high-confidence identity/fingerprint, current Proxmox locator,
passing final pre-check, valid approval packet/job, operation lock, verified
post-check contract, operator authorization, and explicit active-session user
approval for any live smoke.

## Scope

1. Policy coverage read model.
   - Add a backend read model for all current DRS candidate/resolved VM
     identities and their policy state.
   - Include identity confidence, current locator, latest observation age,
     fingerprint hash/evidence summary, policy value, reason, source,
     updated_by, updated_at, and current DRS blocker impact.
   - Surface unclassified or identity-uncertain VMs as blocked from policy write
     until identity is resolvable.

2. Policy update API.
   - Add a narrow authenticated API for updating one `vm_identity_id` policy.
   - Require operator/admin authorization.
   - Require a non-empty reason for `allowed`, `restricted`, and `blocked`.
   - Prefer requiring a compact expected-observation guard, such as
     `cluster_id`, `node_id`, `vmid`, `fingerprint_hash`, and `observed_at`, so
     stale browser state cannot silently classify the wrong VM.
   - Server sets `source=manual` for UI/API writes.
   - Preserve idempotent behavior when the same policy/reason is submitted.
   - Return the previous policy, new policy, actor fields, audit/event id, and
     updated recommendation/check impact.

3. Audit/event evidence.
   - Add compact immutable policy-change evidence if no suitable audit substrate
     exists yet.
   - Record old/new policy, reason, actor, request id, timestamp, identity id,
     locator guard, fingerprint hash, and validation result.
   - Do not rely only on the mutable `vm_migration_policies` row to explain
     historical policy changes.

4. DRS Advisor UI.
   - Add a VM policy configuration surface in or adjacent to `/drs`.
   - Show filters for `unknown`, `allowed`, `restricted`, `blocked`, and
     identity-confidence state.
   - Use a deliberate review modal/form for changes. Avoid one-click toggles.
   - Show why a VM cannot be marked `allowed` when identity evidence is stale,
     low-confidence, or mismatched.
   - Show that policy changes do not start migration.

5. DRS integration.
   - Ensure recommendations, detail, final-check, approval readiness, and job
     intent readiness reflect policy changes consistently.
   - Confirm `unknown`, `restricted`, and `blocked` continue to block execution.
   - Confirm `allowed` only removes the policy blocker and does not bypass any
     other blocker.

6. Operator runbook.
   - Document how to classify a VM, why reason text is required, and how to
     verify that DRS Advisor reflects the change.
   - Document rollback/reset to `unknown` or `blocked`.

## Out Of Scope

- Live DRS migration smoke.
- Automatic DRS.
- Bulk migration.
- Bulk policy import.
- Tag-based policy defaults.
- Full owner/team/environment metadata catalog.
- Complex placement/rule engine.
- Recommendation-level migrate aliases.
- Corrective reconciliation mutation.
- Background reconciliation automation.
- Public API tokens or non-session machine automation.
- Proxmox tag writes or any other Proxmox mutation.

## Suggested API Shape

The implementation can adjust names after reading the existing router/service
patterns, but keep the boundary narrow:

```text
GET /api/v1/drs/policies
GET /api/v1/drs/policies/{vm_identity_id}
PUT /api/v1/drs/policies/{vm_identity_id}
```

Example update payload:

```json
{
  "policy": "allowed",
  "reason": "Operator verified this VM is stateless and may move during DRS balancing.",
  "expected_observation": {
    "cluster_id": "gjallar-mvp",
    "node_id": "yoonserver3",
    "vmid": 103,
    "fingerprint_hash": "sha256:...",
    "observed_at": "2026-05-31T00:00:00Z"
  },
  "policy_change_acknowledged": true
}
```

The backend must ignore any client-provided actor fields and derive actor
evidence from the authenticated session.

## Implementation Order

1. Explorer pass: map existing DRS identity/policy models, router conventions,
   auth dependencies, frontend DRS view model, and test patterns.
2. Reviewer pass: identify safety regressions before editing, especially
   identity mismatch, stale browser state, RBAC, and audit gaps.
3. Docs/API pass: confirm local FastAPI/SQLAlchemy/Alembic/frontend conventions.
4. Backend model/service/API slice.
5. Backend tests for schema, read model, update validation, RBAC, audit/event
   evidence, and DRS blocker integration.
6. Frontend service/view-model slice.
7. Frontend UI and tests.
8. Validation and documentation update.

For non-trivial implementation, follow `AGENTS.md`: main session coordinates;
delegate explorer, reviewer, docs_researcher, then worker; only worker edits
code; do not start worker until explorer and reviewer have returned.

## Definition Of Done

- Operators can see current VM policy coverage and identity confidence.
- Operators can set one resolved VM identity to `allowed`, `restricted`,
  `blocked`, or `unknown` through a deliberate authenticated workflow.
- Every non-`unknown` policy decision requires reason text.
- Policy writes are auditable with old/new values and trusted session actor
  evidence.
- Stale or mismatched locator/fingerprint evidence cannot silently mark the
  wrong VM as `allowed`.
- DRS recommendations and final-check results reflect policy changes.
- `allowed` removes only the policy blocker and does not bypass identity,
  locator, final pre-check, approval, lock, Proxmox evidence, or post-check
  gates.
- `unknown`, `restricted`, and `blocked` remain execution-blocking.
- No Proxmox mutation is added.
- Relevant backend/frontend tests and build/lint validation pass.

## Suggested Validation

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/db
node --test frontend/tests/drsAdvisor.test.mjs frontend/tests/apiV1Client.test.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```

Broaden to the full backend and frontend suites if shared auth, DB, or API
contract behavior changes:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
node --test frontend/tests/*.mjs
```
