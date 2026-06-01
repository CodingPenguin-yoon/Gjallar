# Goal 11: DRS Operations Productization

Status: candidate follow-on goal; not started. Start only if the user
explicitly selects this goal after the Goal 10 safety baseline is accepted or
otherwise explicitly superseded.

## Objective

Productize the DRS operator workflow around the existing backend safety gates
without moving execution authority into the frontend.

Goal 11 should make approval, execution readiness, job state, and reconciliation
visibility clearer for operators. It must not make live DRS migration automatic
or imply that every recommendation is executable.

## Starting Point

- `/drs` shows recommendation/check evidence, manual VM policy configuration,
  and local approval packet/job intent creation.
- Recommendation/check results remain `read_only=true`, `executable=false`,
  and `allowed_actions=[]`.
- A narrow operator-only backend execute route exists, but broad live execute UI
  is not implemented.
- Read-only Reconcile preview exists in the backend, but corrective reconcile UI
  is not implemented.
- Jobs/Runs stores `drs_migration` job evidence, including recommendation,
  final pre-check, approval, job intent, operation lock, migration, task poll,
  post-check, and reconciliation stages.
- Live DRS smoke evidence remains pending explicit approval.

## Controlling References

- `docs/goal/README.md`
- `docs/goal/goal-10-drs-live-migration-safety-evidence.md`
- `docs/current/README.md`
- `docs/current/top-tabs/05-placement-drs-advisor.md`
- `docs/current/top-tabs/06-jobs-runs.md`
- `docs/product/drs-advisor/02_UI_AND_FLOWS.md`
- `docs/product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md`
- `docs/architecture/flows/drs-approve-migrate-reconcile.md`

## Safety/UX Rules

- No frontend inference of executability. The frontend may display backend
  readiness and blockers, but backend-owned gates decide whether execution is
  possible.
- Do not expose live execute controls until the Goal 10 safety baseline is in
  place or the user explicitly selects a different safety baseline.
- Every mutation control must reflect backend RBAC and disabled states.
- `allowed` migration policy is only one prerequisite. It is not approval and
  not execution authority.
- Recommendation/check output remains read-only and must not become a direct
  migrate action.
- No live Proxmox mutation, smoke, cleanup, live readiness, corrective action,
  or reconciliation mutation without explicit active-session approval for that
  specific run.

## Scope

1. Guarded execute UI after Goal 10 safety baseline.
   - Add operator-facing controls only for stored approved migration jobs, not
     raw recommendations.
   - Require the backend acknowledgement payload and show backend-returned
     blockers.
   - Disable controls for viewer role, missing approval, stale evidence,
     blocked identity/policy/final pre-check, lock conflicts, reconciliation
     required, or unavailable backend execute state.
2. Approval-to-execute lifecycle visibility.
   - Show recommendation, check, approval packet, job intent, execute readiness,
     UPID/task, post-check, and reconciliation state as a coherent lifecycle.
   - Make stale or invalidated evidence visible.
3. Read-only reconcile-preview UI.
   - Surface backend reconcile-preview output without offering corrective
     mutation.
   - Make `needs_reconciliation` and `reconciliation_required` actionable as
     operator information, not automatic repair.
4. Richer Jobs/Runs DRS panels.
   - Improve `drs_migration` job detail display for recommendation id, VM
     identity, source/target, approval, actor, UPID, lock state, post-check, and
     reconciliation evidence.
5. Operator blockers.
   - Display blockers in a backend-owned taxonomy and keep unknown/stale/
     not-collected evidence as explicit blockers where applicable.
6. RBAC and disabled states.
   - Align visible actions with backend role requirements and exact disabled
     reasons.
7. No frontend inference of executability.
   - Do not compute migration permission from local UI state, policy text, or
     recommendation shape.

## Implementation Order

1. Confirm Goal 10 safety baseline or record the explicit replacement baseline.
2. Add API client helpers only for already-existing backend routes and any new
   backend-owned readiness route selected by the implementation.
3. Improve read-only lifecycle and Jobs/Runs visibility first.
4. Add guarded execute controls only after disabled-state and acknowledgement
   tests exist.
5. Add reconcile-preview UI as read-only visibility.
6. Run focused backend/frontend validation.

## Out Of Scope

- Automatic DRS.
- Recommendation-level migrate aliases.
- Corrective reconcile mutation or repair workflow.
- Background reconciliation automation.
- Richer policy rule/full metadata editor.
- 15-minute metrics and deeper read-only HA/quorum/task collection unless
  separately selected.
- External IdP, public signup, API tokens, OAuth, SSO, or 2FA.

## Definition Of Done

- Goal 11 remains candidate/not started until explicitly selected.
- DRS operator UI shows lifecycle state without weakening backend gates.
- Execute controls, if added, operate only on backend-approved job state and
  require the backend acknowledgement contract.
- Viewer/operator/admin disabled states match backend authorization.
- Reconcile-preview UI is read-only and cannot run corrective mutation.
- Jobs/Runs DRS detail panels make approval, UPID/task, post-check, and
  reconciliation evidence easier to inspect.
- Tests cover disabled states and prove frontend helpers do not infer
  executability.

## Suggested Validation

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/jobs
node --test frontend/tests/drsAdvisor.test.mjs frontend/tests/jobsScreen.test.mjs frontend/tests/apiV1Client.test.mjs frontend/tests/authFlow.test.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```
