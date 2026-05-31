# Goal Check: Goal 1-6 Implementation Verification And Quality Audit

Status: completed. Result: pass-with-risk.

This completed audit verified Goal 1 through Goal 6 before Goal 7 work began.
Goal 7 was unblocked by the accepted `pass-with-risk` result. No live DRS
migration smoke was run.

## Objective

Verify that Goal 1 through Goal 6 are genuinely implemented,
production-quality, and not test-shaped or docs-only. The audit must connect
the goal claims to active code, database schema/migrations, API behavior,
frontend behavior where applicable, tests, current docs, and validation output.

The recorded result used these decision values:

- pass: Goal 7 may start after this audit is recorded
- pass-with-risk: Goal 7 may start after the listed non-blocking risks are
  accepted in the final report
- fail: Goal 7 stays blocked until the listed gaps are remediated and
  revalidated

## Inputs And Controlling Docs

Read these first, then use the current checkout as authoritative:

- `AGENTS.md`
- `docs/goal/README.md`
- `docs/goal/remaining-operations-work.md`
- `docs/goal/goal-01-create-vm-live-smoke-matrix.md`
- `docs/goal/goal-02-drs-identity-final-precheck-preparation.md`
- `docs/goal/goal-03-drs-final-precheck-operation-lock-foundation.md`
- `docs/goal/goal-04-drs-approval-migration-job-substrate.md`
- `docs/goal/goal-05-drs-live-migration-upid-tracking.md`
- `docs/goal/goal-06-drs-post-check-reconciliation.md`
- `docs/current/README.md`
- `docs/current/top-tabs/04-create-vm.md`
- `docs/current/top-tabs/05-placement-drs-advisor.md`
- `docs/current/top-tabs/06-jobs-runs.md`
- `docs/architecture/README.md`
- `docs/architecture/CREATE_VM_NATIVE_ARCHITECTURE.md`
- `docs/architecture/VM_PROVISIONING_CONTRACT.md`
- `docs/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`
- `docs/operations/create-vm-live-smoke-2026-05-28.md`
- `docs/operations/runbook.md`

Use relevant current architecture docs when a goal claim depends on Create VM,
DRS identity, Jobs/Runs, database records, Proxmox adapters, operation locks,
or API contracts. Treat product docs as target direction only unless a current
doc says a feature is implemented.

## Operating Mode

Follow `AGENTS.md`.

- The main session coordinates the audit.
- For a non-trivial audit, delegate explorer, reviewer, docs_researcher, then
  worker.
- If model control is required, spawn `default` agents with `model: gpt-5.5`
  and `reasoning_effort: xhigh`, and assign the intended role in the prompt.
- Do not start worker until explorer and reviewer have returned.
- Only worker edits files.
- Prefer concise summaries over raw logs and long command dumps.
- Keep the main thread focused on requirements, decisions, and final output.

## Hard Constraints

- no live Proxmox mutation/smoke without explicit active-session approval
- `192.168.2.140-150/24` is candidate selection guard only
- VMID/IP/name/node/tag/Create VM history alone is not stable identity
- Proxmox task OK alone is not Gjallar success
- no scope creep
- no Goal 7 UI polish
- no richer policy/rule editor
- no corrective mutation/background automation/automatic DRS
- do not weaken tests to pass

Additional audit constraints:

- Do not treat documentation claims as implementation evidence.
- Do not treat passing tests alone as implementation evidence.
- Do not treat fake/mock-only success as equivalent to live evidence.
- Do not add live smoke, cleanup, migration, or other Proxmox mutation unless
  the active session explicitly approves the exact operation.
- Do not broaden public API contracts, permissions, or mutation paths while
  remediating audit failures unless the remediating change is explicitly scoped.

## Audit Workflow Phases

### 1. Inventory

Establish the current branch, dirty state, and relevant files before changing
anything.

Required actions:

- Run `git status --short --branch`.
- List goal docs with `find docs/goal -maxdepth 1 -type f | sort`.
- Search for Goal 1 through Goal 6 implementation symbols, tests, migrations,
  and docs references.
- Identify any uncommitted user changes and do not overwrite them.

Evidence to record:

- branch and dirty-state summary
- files inspected
- uncommitted changes that affected the audit
- any expected files that are missing

### 2. Docs/Code Mapping

Map each goal claim to the active implementation surface.

Required actions:

- For each goal, identify backend modules, DB models/migrations, API routes,
  frontend files, tests, and current docs that support or contradict the goal.
- Separate implemented behavior from target/planned behavior.
- Flag claims that only appear in docs and have no active code/test evidence.
- Flag code paths that exist but are unreachable from the active `/api/v1`
  surface.

Evidence to record:

- source files and line references
- API endpoints and request/response contract surfaces
- DB tables/models/migrations
- tests that exercise the behavior
- docs that accurately reflect the behavior

### 3. Goal 1-6 Audit

Complete the per-goal checks in this document. Each goal needs a decision:

- `pass`: evidence supports the goal and no blocking production-quality gap was
  found
- `pass-with-risk`: evidence supports the goal, but a non-blocking risk remains
  and is documented
- `fail`: a required claim is missing, test-shaped, unsafe, unreachable, or
  contradicted by current docs/code

Goal 7 was unblocked only after every Goal 1 through Goal 6 row was `pass` or
`pass-with-risk` and the listed risks were explicitly accepted in the final
report.

### 4. Test Quality Audit

Do not only count tests. Read representative tests and determine whether they
prove behavior.

Required checks:

- Behavior coverage: tests must exercise the operator-visible contract, not
  only internal helpers.
- Fake/mock-heavy risks: fake clients must prove call/no-call behavior,
  required evidence, error handling, and ambiguous outcomes.
- Blocked path mutation assertions: tests must assert that Proxmox mutation
  clients are not called when gates fail.
- Route aliases: tests must prove only intended routes exist, and that unsafe
  aliases such as recommendation-level migrate/live-migrate routes are absent
  if docs claim they are absent.
- Transaction/session risks: tests must cover DB transaction boundaries,
  operation lock acquisition/release, session-backed authorization, and stale
  approval/checksum behavior where applicable.
- Negative and ambiguous outcomes: tests must cover task failure, timeout,
  missing UPID, post-check mismatch, fingerprint mismatch, and unknown evidence
  where those outcomes are in scope.

Evidence to record:

- test files and representative test names
- what each test actually proves
- missing assertions
- tests that are overly coupled to implementation shape rather than behavior
- any test weakened, skipped, or deleted during remediation

### 5. Live-Mutation Safety Audit

Verify that all Goal 1 through Goal 6 behavior preserves live Proxmox safety.

Required checks:

- Create VM live smoke evidence exists and is sanitized.
- No future smoke target is treated as execution authority.
- DRS recommendation/check/approval paths remain non-mutating until the narrow
  execution endpoint.
- DRS execution uses the dedicated DRS migration client, not Create VM mutation
  authority.
- Every mutation path requires the documented gates before calling Proxmox.
- Proxmox task OK alone cannot mark DRS success.
- Ambiguous or missing evidence becomes failed or `needs_reconciliation`, not
  successful.
- Corrective mutation, background automation, and automatic DRS are absent.

Evidence to record:

- mutation clients and callers
- endpoint permissions
- gate ordering before mutation
- call/no-call tests
- post-check and reconciliation handling

### 6. Legacy/Dead-Code Audit

Confirm old routes and helper paths do not confuse the active contract.

Required checks:

- Legacy provisioning executor routes/helper code are absent from active
  backend routing.
- Legacy `/api/instances`, `/api/provision`, task/log, deploy, and LLM surfaces
  are not active frontend contracts.
- Stale helper code is either removed, archived, or clearly unreachable.
- Docs do not instruct operators to use stale routes or outdated sequencing.

Evidence to record:

- route table or router references
- frontend API client references
- removed or archived helper references
- stale docs found and fixed

### 7. Docs Accuracy Audit

Verify current docs match current behavior and do not overclaim.

Required checks:

- `docs/current/README.md` accurately states implemented DRS identity, policy,
  approval/job substrate, narrow execution, UPID tracking, post-check, and
  reconciliation state.
- `docs/current/top-tabs/05-placement-drs-advisor.md` matches current API and
  UI behavior.
- `docs/current/top-tabs/06-jobs-runs.md` matches DRS job/artifact behavior.
- `docs/current/top-tabs/04-create-vm.md` does not claim old DRS identity work
  is still the next slice.
- `README.md` and `docs/README.md` do not contain stale current-state claims
  that contradict Goal 1 through Goal 6.
- Historical docs are clearly marked as historical when they keep older
  sequencing or state.

Evidence to record:

- stale claims found
- docs updated
- docs intentionally left unchanged because they are archived or historical

### 8. Remediation

If the audit finds a blocking gap, fix the smallest coherent issue before
Goal 7 starts.

Rules:

- Keep remediation targeted to the failed Goal 1 through Goal 6 evidence.
- Do not use remediation to begin Goal 7 UI polish.
- Do not add broad policy UI, automatic DRS, corrective mutation, background
  automation, or live smoke.
- Do not weaken tests to pass.
- If remediation touches code, update or add focused tests that prove the fixed
  behavior.
- If remediation touches docs, keep current-vs-target language explicit.

### 9. Validation

Run validation appropriate to the final change set.

Minimum documentation-only validation:

```bash
find docs/goal -maxdepth 1 -type f | sort
rg -n "Goal 7.*\
Next|next active \
goal is Goal \
7|Start Goal \
7|Goal \
7 using|다음 active goal은 Goal \
7|다음 slice는 Goal \
7" docs README.md
rg -n "goal-check-01-06-implementation-quality" docs README.md
git diff --check
```

Focused Goal Check validation when code/tests are audited without code changes:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/db backend/tests/jobs backend/tests/proxmox
node --test frontend/tests/drsAdvisor.test.mjs frontend/tests/jobsScreen.test.mjs frontend/tests/createVmFlow.test.mjs
git diff --check
```

Broader validation before unblocking Goal 7 after code remediation:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
node --test frontend/tests/*.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```

If validation cannot run, record the exact command, failure reason, and residual
risk. Do not mark the Goal Check complete on unrun required validation unless
the final report explicitly accepts that risk.

### 10. Final Report

The final report must be concise and evidence-based.

Required contents:

- decision: pass, pass-with-risk, or fail
- matrix for Goal 1 through Goal 6
- validation commands and results
- remediation performed
- remaining risks
- explicit statement whether Goal 7 is unblocked
- if blocked, exact next remediation step

## Goal 1-6 Verification Matrix Template

Use one row per goal. Fill every evidence field.

| Goal | Code paths | DB/migrations | APIs | Frontend | Tests | Docs | Validation | Gaps | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Goal 1: Create VM Live Smoke Matrix |  |  |  |  |  |  |  |  |  |
| Goal 2: DRS Identity And Final Pre-Check Preparation |  |  |  |  |  |  |  |  |  |
| Goal 3: DRS Final Pre-Check And Operation Lock Foundation |  |  |  |  |  |  |  |  |  |
| Goal 4: DRS Approval And Migration Job Substrate |  |  |  |  |  |  |  |  |  |
| Goal 5: DRS Live Migration Execution And UPID Tracking |  |  |  |  |  |  |  |  |  |
| Goal 6: DRS Post-Check And Reconciliation |  |  |  |  |  |  |  |  |  |

Decision values:

- `pass`
- `pass-with-risk`
- `fail`

## Detailed Per-Goal Audit

### Goal 1: Create VM Live Smoke Matrix

Goal claim:

- Approved live Create VM smoke was completed and recorded.
- The matrix included default `stopped`, optional `boot_and_verify`, static IP
  stopped creation, and at least one negative pre-mutation gate.
- Evidence is sanitized and does not authorize later live mutation.

Audit checks:

- Confirm `docs/operations/create-vm-live-smoke-2026-05-28.md` exists and
  records each matrix case with VMID/name, node, power policy, network choice,
  job/request evidence, result, and cleanup decision where applicable.
- Confirm the evidence does not expose secrets, tokens, SSH private keys, raw
  sensitive payloads, or unsafe Proxmox credentials.
- Confirm active Create VM code still uses the same safety contract:
  draft -> preflight -> plan/review -> approval -> native create.
- Confirm stopped creation requires native clone/config and stopped post-check
  before applied success.
- Confirm `boot_and_verify` starts only when requested and checks guest-agent IP
  and cloud-init completion.
- Confirm static IP creation requires explicit static IP, prefix, and gateway.
- Confirm invalid target/preflight failures produce `side_effects=[]` or
  equivalent no-mutation evidence.
- Confirm session actor evidence is trusted from auth/session state, not an
  editable payload field.
- Confirm Create VM smoke range is not treated as future DRS execution
  authority.

Likely evidence paths:

- `backend/app/api/v1/router.py`
- `backend/app/vm_create/`
- `backend/app/proxmox/`
- `backend/app/jobs/`
- `backend/app/db/models.py`
- `frontend/src/components/CreateVmWizard.jsx`
- `frontend/src/services/apiV1.js`
- `backend/tests/vm_create`
- `backend/tests/contracts`
- `backend/tests/proxmox`
- `frontend/tests/createVmFlow.test.mjs`
- `docs/current/top-tabs/04-create-vm.md`
- `docs/operations/create-vm-live-smoke-2026-05-28.md`

Blocking failures:

- Smoke evidence missing or unsanitized.
- Create VM success can be marked without observed post-check evidence.
- Negative gate can call mutation.
- Static IP defaults are inferred when docs claim explicit network fields.
- Actor/operator identity can be spoofed by payload.

### Goal 2: DRS Identity And Final Pre-Check Preparation

Goal claim:

- DB-backed VM identity, fingerprint observation, and migration policy memory
  exist.
- DRS recommendations surface identity and policy blockers.
- Read-only final pre-check exists and keeps unknown/uncertain/policy-blocked
  VMs execution-ineligible.
- VMID/IP/name/node/tag/Create VM history alone is not stable identity.

Audit checks:

- Confirm identity tables/models/migrations exist and store compact curated
  evidence rather than large raw inventory blobs.
- Confirm resolver computes fingerprints from stable curated evidence such as
  SMBIOS UUID, VM generation ID, MAC addresses, and disk volume IDs where
  available.
- Confirm node, VMID, name, IP, tag, and Create VM history are locator or
  supporting evidence only.
- Confirm match confidence controls execution eligibility and only high
  confidence can proceed to policy/final-pre-check gates.
- Confirm default migration policy is `unknown` and blocks execution.
- Confirm restricted/blocked/unknown policy is represented in recommendation
  blockers and approval readiness.
- Confirm final pre-check endpoint re-reads current evidence and is read-only.
- Confirm final pre-check output does not expose mutation authority.

Likely evidence paths:

- `backend/app/drs/identity.py`
- `backend/app/drs/advisor.py`
- `backend/app/db/models.py`
- `backend/alembic/versions/*drs_identity*`
- `backend/tests/drs/test_identity_resolution.py`
- `backend/tests/drs/test_advisor_readiness.py`
- `backend/tests/contracts/test_api_v1_drs.py`
- `backend/tests/db/test_drs_identity_schema.py`
- `frontend/src/components/DrsAdvisorScreen.jsx`
- `frontend/tests/drsAdvisor.test.mjs`
- `docs/current/top-tabs/05-placement-drs-advisor.md`

Blocking failures:

- High confidence can be granted from VMID/name/node/IP/tag alone.
- Unknown policy does not block execution readiness.
- Final pre-check mutates Proxmox or local lock state in a read-only path.
- Recommendation output implies executable authority before later gates.

### Goal 3: DRS Final Pre-Check And Operation Lock Foundation

Goal claim:

- `operation_locks` schema/model exists for `drs_migration`.
- Read-only final pre-check checks VM identity, Proxmox locator, and route
  operation locks.
- `active`, `stale`, and `reconciliation_required` locks block execution
  readiness; `released` locks do not.
- Config-lock evidence blocks when collected.
- Unsupported Proxmox conflict evidence is explicit and never faked healthy.

Audit checks:

- Confirm operation lock model, migration, and scope fields exist.
- Confirm final pre-check performs lookup only and does not create/update locks.
- Confirm blocking lock states are represented in blockers and
  `would_be_executable=false`.
- Confirm released locks do not block.
- Confirm config lock evidence is collected from curated current VM config and
  blocks when present.
- Confirm active task, HA, quorum, and cluster-health gaps are represented as
  `not_collected`, `not_implemented`, unavailable, or otherwise explicit
  non-healthy evidence.
- Confirm unsupported conflict evidence cannot be treated as passing by default.
- Confirm tests cover blocking and non-blocking lock states.

Likely evidence paths:

- `backend/app/drs/operation_locks.py`
- `backend/app/drs/advisor.py`
- `backend/app/db/models.py`
- `backend/alembic/versions/*operation_locks*`
- `backend/tests/drs`
- `backend/tests/contracts/test_api_v1_drs.py`
- `backend/tests/db/test_drs_identity_schema.py`
- `backend/tests/proxmox/test_inventory_adapter.py`
- `docs/current/top-tabs/05-placement-drs-advisor.md`

Blocking failures:

- Final pre-check creates or releases locks in the read-only path.
- Open locks are visible but do not block execution readiness.
- Missing Proxmox evidence is silently interpreted as healthy.
- Config locks are ignored after docs claim they block.

### Goal 4: DRS Approval And Migration Job Substrate

Goal claim:

- Local approval packet/checksum and pending `drs_migration` job intent
  substrate exist.
- Approval is bound to exact recommendation and final-precheck evidence.
- Approval/job substrate does not call Proxmox mutation APIs.
- Blocked or unknown states do not create runnable jobs.

Audit checks:

- Confirm approval packet records are compact and checksum-bound to
  recommendation and final pre-check evidence.
- Confirm warning acknowledgement fields are represented.
- Confirm pending job intent contains DRS migration shape and local evidence.
- Confirm substrate records `runnable=false`,
  `proxmox_mutation_enabled=false`, and `side_effects=[]` or equivalent until
  later execution gates apply.
- Confirm blocked identity, blocked policy, failed final pre-check, open lock,
  stale evidence, and missing acknowledgement cases do not create runnable jobs.
- Confirm approval route authorization is operator/admin only.
- Confirm approval substrate is separate from Create VM approval semantics.
- Confirm tests assert no Proxmox mutation call during approval/job intent
  creation.

Likely evidence paths:

- `backend/app/drs/approval.py`
- `backend/app/drs/advisor.py`
- `backend/app/jobs/runs.py`
- `backend/app/jobs/artifacts.py`
- `backend/app/db/models.py`
- `backend/app/api/v1/router.py`
- `backend/tests/drs`
- `backend/tests/contracts/test_api_v1_drs.py`
- `backend/tests/jobs/test_runs.py`
- `frontend/src/utils/drsAdvisor.js`
- `docs/current/top-tabs/05-placement-drs-advisor.md`
- `docs/current/top-tabs/06-jobs-runs.md`

Blocking failures:

- Approval packets can be created from stale or mismatched checksums.
- Blocked recommendations create runnable jobs.
- Approval path can call Proxmox mutation.
- Job evidence overclaims executable state.

### Goal 5: DRS Live Migration Execution And UPID Tracking

Goal claim:

- A narrow backend endpoint can execute one approved DRS live migration.
- Execution uses a dedicated DRS Proxmox migration client, not Create VM
  mutation authority.
- All gates pass before any Proxmox migration mutation call.
- UPID/task metadata is stored once mutation is accepted.
- Missing, failed, timeout, or ambiguous task evidence is not success.
- No live DRS migration smoke has been run.

Audit checks:

- Confirm the execution endpoint exists only at the intended route, such as
  `POST /api/v1/drs/migration-jobs/{job_id}/execute`.
- Confirm recommendation-level aliases such as `/migrate` or `/live-migrate`
  are absent if docs claim they are absent.
- Confirm authorization requires operator/admin.
- Confirm execution loads stored job and approval packet records.
- Confirm execution rejects missing, stale, cancelled, already-executed, or
  checksum-mismatched records before mutation.
- Confirm execution reruns fresh final pre-check before mutation.
- Confirm execution collects live pre-mutation evidence through the dedicated
  DRS client before mutation.
- Confirm operation locks are transactionally acquired before mutation and lock
  acquisition failure prevents mutation.
- Confirm the mutation call is limited to the Proxmox QEMU migrate path with
  controlled parameters.
- Confirm UPID/task metadata is persisted promptly after acceptance.
- Confirm missing UPID, failed task, timeout, ambiguous task, or unavailable
  task evidence becomes failed or `needs_reconciliation`, not completed.
- Confirm no automatic DRS, bulk migration, rollback, or broad UI path was
  added.

Likely evidence paths:

- `backend/app/drs/execution.py`
- `backend/app/proxmox/drs_migration.py`
- `backend/app/drs/operation_locks.py`
- `backend/app/drs/approval.py`
- `backend/app/api/v1/router.py`
- `backend/app/jobs/runs.py`
- `backend/app/db/models.py`
- `backend/tests/drs/test_execution.py`
- `backend/tests/contracts/test_api_v1_drs.py`
- `backend/tests/jobs/test_runs.py`
- `backend/tests/proxmox/test_mutation_client.py`
- `docs/current/top-tabs/05-placement-drs-advisor.md`

Blocking failures:

- Mutation can occur before identity, policy, final-precheck, approval, or
  lock gates pass.
- Execution reuses Create VM mutation authority.
- Ambiguous task evidence can mark completion.
- Tests prove only success paths and do not assert mutation call blocking.
- Hidden route aliases allow migration outside the documented job endpoint.

### Goal 6: DRS Post-Check And Reconciliation

Goal claim:

- DRS migration completion requires Proxmox task `OK` plus direct target-node
  status/config post-check, expected power-state evidence, matching DRS
  fingerprint, and no conflicting active task.
- Operation locks release only after verified post-check.
- Ambiguous outcomes stay `needs_reconciliation` and locks become
  `reconciliation_required`.
- Read-only Reconcile preview exists before any corrective mutation.
- No live DRS migration smoke has been run.

Audit checks:

- Confirm post-check reads direct target-node status/config after task terminal
  evidence.
- Confirm completed status requires task `OK` and actual-state post-check.
- Confirm wrong target, unexpected power state, fingerprint mismatch, missing
  config/status, active task uncertainty, timeout, worker restart ambiguity, or
  task evidence ambiguity blocks success.
- Confirm operation locks release only when the terminal outcome is verified
  safe.
- Confirm ambiguous outcomes set or preserve `needs_reconciliation`.
- Confirm reconciliation-required locks and job state appear in DRS readiness
  and Jobs/Runs evidence.
- Confirm Reconcile preview is read-only and returns no corrective mutation
  authority.
- Confirm corrective mutation, background reconciliation automation, and
  automatic DRS are absent.
- Confirm tests cover task OK without post-check, wrong target, fingerprint
  mismatch, and read-only preview behavior.

Likely evidence paths:

- `backend/app/drs/execution.py`
- `backend/app/drs/operation_locks.py`
- `backend/app/proxmox/drs_migration.py`
- `backend/app/jobs/runs.py`
- `backend/app/api/v1/router.py`
- `backend/app/db/models.py`
- `backend/tests/drs/test_execution.py`
- `backend/tests/contracts/test_api_v1_drs.py`
- `backend/tests/jobs/test_runs.py`
- `frontend/tests/drsAdvisor.test.mjs`
- `frontend/tests/jobsScreen.test.mjs`
- `docs/current/top-tabs/05-placement-drs-advisor.md`
- `docs/current/top-tabs/06-jobs-runs.md`

Blocking failures:

- Task `OK` alone can complete the job.
- Locks release before verified post-check.
- Reconcile preview performs mutation or exposes corrective mutation authority.
- Ambiguous evidence is hidden from operator-facing job/readiness state.

## Deliverables

- Completed Goal 1-6 verification matrix.
- Per-goal evidence notes with file paths and validation references.
- List of blocking gaps, if any.
- Remediation commits or working-tree changes, if remediation is in scope for
  the active session.
- Validation results.
- Final audit decision and explicit Goal 7 gate status.

## Binary Acceptance Criteria

This Goal Check is complete only when all criteria are true:

- Every Goal 1 through Goal 6 matrix row has code, DB/migration where
  applicable, API, frontend where applicable, tests, docs, validation, gaps,
  and decision fields filled.
- Each goal decision is `pass` or `pass-with-risk`; any `fail` blocks Goal 7.
- All blocking gaps found during audit are remediated or explicitly listed as
  blockers.
- Required validation has run, or any unrun command is explicitly recorded with
  risk accepted by the final report.
- Docs no longer claim Goal 7 is next before the Goal Check gate.
- The final report explicitly says either "Goal 7 is unblocked" or "Goal 7 is
  blocked".

## Historical Starting Prompt

```text
Use docs/goal/README.md as the canonical goal entrypoint.
This Goal Check is complete with result pass-with-risk. Goal 1 through Goal 6 passed with accepted risks, and no live DRS migration smoke was run. Continue only with the user-selected next task from the canonical README.
```
