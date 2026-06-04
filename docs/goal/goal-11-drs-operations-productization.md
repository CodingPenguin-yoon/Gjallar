# Goal 11: DRS Criteria And Operations Productization

Status: rewritten canonical follow-on goal; first criteria/taxonomy and
Jobs/Runs evidence slices implemented while broader Goal 11 remains in
progress. This goal
supersedes the previous split between Goal 11 DRS Operations Productization and
Goal 12 Platform Hardening And Decision Quality. Continue broader implementation
only when the user explicitly selects the next Goal 11 slice.

## Objective

Make the DRS decision model and operator workflow consistent from backend
evidence through UI display without weakening the existing live-migration safety
gates.

Goal 11 should turn the VMID `140` live-smoke lessons into the next coherent DRS
product slice:

- distinguish advisory/pre-filter evidence from final technical gates
- clarify which blockers are Gjallar policy/identity gates and which are Proxmox
  feasibility gates
- productize the approval-to-execute-to-reconcile workflow in the UI
- make Jobs/Runs DRS evidence inspectable enough for operators
- keep cleanup, reverse migration, retry, corrective mutation, automatic DRS, and
  bulk migration outside this goal unless separately approved for a specific run

## Starting Point

- Goal 10 safety baseline is implemented.
- VMID `140` was migrated live from `yoonmanserver` to `yoonserver3` after exact
  operator approval; Proxmox task evidence was `OK`.
- Gjallar initially held the job in `needs_reconciliation` because direct
  post-check identity extraction included a cloud-init cdrom volume. The parser
  was aligned with inventory fingerprint normalization, the stored-UPID
  reconciliation follow-up passed, the DRS job completed locally, and operation
  locks were released.
- `/drs` currently shows recommendation/check evidence, manual VM migration
  policy configuration, and local approval packet/job intent creation.
- Backend-only explicit test candidate helpers, narrow migration-job execute,
  read-only reconcile preview, and stored-UPID local reconciliation follow-up are
  implemented.
- Broad DRS execute UI, corrective reconcile UI, broader DRS lifecycle panels,
  and Risks criteria taxonomy polish are not implemented. The first
  recommendation/check backend-owned criteria taxonomy slice exists, and the
  first Jobs/Runs read-only DRS evidence slice records/renders compact
  approval, task, lock, post-check, reconciliation, taxonomy, and artifact
  metadata evidence.
- First implementation slice now exposes backend-owned criteria taxonomy fields
  on recommendation/check output and reclassifies Advisor route/network,
  local-storage, and passthrough evidence as advisory/pre-filter signals.
  Current recommendation/check output no longer mixes those advisory/pre-filter
  signals into the compatibility hard `blockers` list.
- Remaining gaps include broad live execute UI, corrective reconcile UI,
  broader DRS lifecycle panels, Risks taxonomy polish, richer policy rule/full
  metadata editing, 15-minute average/peak metrics, and deeper read-only
  task/HA/quorum collection.

## Controlling References

- `docs/goal/README.md`
- `docs/goal/goal-10-drs-live-migration-safety-evidence.md`
- `docs/operations/drs-explicit-test-candidate-prep-2026-06-03.md`
- `docs/current/README.md`
- `docs/current/top-tabs/05-placement-drs-advisor.md`
- `docs/current/top-tabs/06-jobs-runs.md`
- `docs/product/drs-advisor/02_UI_AND_FLOWS.md`
- `docs/product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md`
- `docs/architecture/flows/drs-approve-migrate-reconcile.md`

Use the current checkout and the VMID `140` evidence as authoritative. If older
Goal 11/12 wording disagrees with this file, this file wins.

## DRS Authority Model

Goal 11 must preserve this split:

- Proxmox migration preconditions, UPID task status/logs, target-node status, and
  target-node config are the final technical authority for whether the migration
  can run and whether Proxmox completed it.
- Gjallar VM identity/fingerprint, migration policy, approval packet, execute
  acknowledgement, operation locks, audit artifacts, post-check contract, and
  reconciliation state are the DRS operational authority for whether Gjallar may
  approve, execute, or locally complete a job.
- Advisor local storage, passthrough, route, and network evidence are
  advisory/pre-filter signals unless the implementation deliberately promotes a
  specific signal to a backend-owned hard gate with tests and UI copy explaining
  why.
- Proxmox task `OK` alone is never Gjallar success. Gjallar success still needs
  verified post-check and lock/reconciliation completion.

## Hard Constraints

- No live Proxmox mutation, smoke, cleanup, reverse migration, retry, live
  readiness check, corrective action, or reconciliation mutation without explicit
  active-session approval for that specific run.
- Do not add automatic DRS, scheduled balancing, bulk migration, or
  recommendation-level migrate aliases.
- Do not move execution authority into the frontend. The UI may display
  backend-owned readiness and disabled reasons only.
- Recommendation/check output remains read-only and must not become a direct
  migration action.
- `allowed` migration policy remains one prerequisite. It is not approval and not
  execution authority.
- VMID/IP/name/node/tag/Create VM history alone is not stable identity.
- VMID `140` cleanup, reverse migration, or deletion is an operations decision
  outside this goal and requires separate approval if selected.

## Scope

1. Goal 10 live evidence close-out.
   - Update canonical goal/current docs so they no longer claim no live DRS smoke
     was run.
   - Link VMID `140` evidence and final reconciliation result.
   - Keep future live mutation and cleanup approvals explicit and run-specific.
2. Backend-owned DRS criteria and blocker taxonomy.
   - Classify blockers as `hard_gate`, `technical_gate`, `policy_gate`,
     `advisory`, `warning`, or another explicit backend-owned taxonomy selected
     during implementation.
   - Ensure unknown, stale, unavailable, ambiguous, and not-collected evidence is
     visible and does not silently become executable.
   - Normalize route/storage/network/passthrough messaging so operators can tell
     advisory/pre-filter evidence apart from final Proxmox technical gates.
   - First slice implemented fields: `criteria`, `criteria_details`,
     `advisory_signals`, and `technical_gate_status`, with `authority`,
     `category`, `severity`, `evidence_state`, and `action_blocked`.
3. Advisor hard-blocker cleanup.
   - Decide which local Advisor checks remain hard blockers before approval and
     which become warnings/advisory evidence.
   - Preserve hard blocks for Gjallar identity, policy, approval, acknowledgement,
     lock, and post-check/fingerprint requirements.
   - Preserve Proxmox migration preconditions as the final technical feasibility
     check before mutation.
   - First slice keeps the compatibility `blockers` list as the hard-gate subset
     and removes Advisor route/network/local-storage/passthrough from hard
     recommendation/check blockers.
4. DRS operations UI.
   - Add guarded UI for explicit test candidate preparation where selected.
   - Show approval packet/job creation and lifecycle state.
   - Add guarded live execute controls only for stored approved jobs and only
     through the backend acknowledgement contract.
   - Surface read-only reconcile preview and stored-UPID local reconciliation
     follow-up without offering corrective mutation.
   - Display exact backend disabled reasons for viewer/operator/admin states.
5. Jobs/Runs and operator evidence.
   - Improve `drs_migration` detail panels for recommendation id, VM identity,
     source/target, approver, acknowledgement, UPID/task, lock, post-check, and
     reconciliation evidence.
   - Keep Jobs/Runs read-only unless a later goal explicitly selects mutation
     controls.
   - Current slice adds `job_runs.details.drs_evidence` with explicit
     `read_only=true`, `allowed_actions=[]`, `current_mutation_controls=[]`,
     final-precheck criteria details/advisory signals/statuses, historical
     execution evidence, lock/post-check/reconciliation summaries, and DRS
     artifact metadata display without payloads or local paths.
6. Decision-quality foundations selected for this slice.
   - Add freshness/stale evidence display where it materially affects DRS trust.
   - Include 15-minute average/peak metrics, deeper read-only active task/HA/quorum
     collection, account/session audit browsing, error-envelope normalization, or
     retention/redaction work only if the implementation plan explicitly selects
     those as part of this goal. Otherwise leave them as future hardening slices.

## Implementation Order

1. Close Goal 10 documentation/evidence inconsistencies.
2. Define the backend-owned criteria/taxonomy contract before UI changes.
3. Update Advisor blocker/warning/advisory behavior and tests.
4. Update API response shapes or view-model helpers only where the taxonomy needs
   them.
5. Improve read-only lifecycle visibility in `/drs` and Jobs/Runs.
6. Add guarded execute/reconcile UI controls after disabled-state and
   acknowledgement tests exist.
7. Run focused backend/frontend validation, then broader validation if contracts
   or shared view models changed.

## Out Of Scope

- Corrective Proxmox mutation, retry, rollback, reverse migration, cleanup, or VM
  deletion without separate active-session approval for that exact operation.
- Automatic DRS, scheduled balancing, and bulk migration.
- Recommendation-level migrate/live-migrate aliases.
- Background reconciliation automation.
- External IdP, OAuth, SSO, 2FA, API tokens, or public signup.
- Create VM success-condition changes.
- SSH/Ansible/app bootstrap checks unless separately requested and approved.

## Definition Of Done

- Goal docs identify this file as the canonical successor to the old Goal 11/12
  split.
- Current docs reflect that VMID `140` live DRS migration evidence exists and was
  locally completed after stored-UPID reconciliation.
- Backend/API/UI expose the same DRS criteria vocabulary.
- Operators can distinguish advisory/pre-filter evidence from Proxmox final
  technical gates and Gjallar policy/identity/approval gates.
- Advisor hard blockers are intentionally classified and covered by tests.
- UI execution controls, if added, operate only on stored approved jobs and
  require backend acknowledgement; frontend helpers do not infer executability.
- Reconcile UI remains read-only or local stored-UPID follow-up only; no
  corrective mutation is exposed.
- Jobs/Runs DRS detail panels make approval, UPID/task, post-check, lock, and
  reconciliation evidence easier to inspect. Artifact metadata is visible, but
  artifact payloads and local paths are not rendered.
- Remaining hardening slices are explicitly listed instead of mixed into the
  active goal.

## Suggested Validation

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/jobs backend/tests/proxmox
node --test frontend/tests/drsAdvisor.test.mjs frontend/tests/jobsScreen.test.mjs frontend/tests/apiV1Client.test.mjs frontend/tests/authFlow.test.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```

For docs-only restructuring, run the requested document checks and
`git diff --check`.
