# Goal Check: Current Implementation Validation Before Goal 9

Status: completed 2026-06-01 04:59 KST. Result: `pass-with-risk`.

## Objective

Establish a trustworthy current implementation baseline before Goal 9 polish,
optional live DRS smoke evidence, or any other new goal-sized work.

This is a non-numbered validation gate, not a product feature goal. It should
verify that the current checkout, tests, and refreshed documents agree about
implemented behavior, remaining gaps, and safety boundaries.

## Starting Point

Current goal sequencing is tracked in `docs/goal/README.md`.

- Goal Check 01-06 completed with result `pass-with-risk`.
- Goal 7 DRS UI/operations polish is complete.
- Goal 7.5 manual VM migration policy configuration is complete.
- Goal 8 minimal local-only post-create readiness evidence recorder is
  complete.
- Goal 9 polish has since completed admin session inventory/revocation UI,
  self password change, and expanded sanitized audit metadata.
- No live DRS migration smoke has been run.

Admin local account operations already include list/create/role/disable/reset
password behavior. Disable and reset-password revoke target sessions; role
changes do not revoke target sessions.

## Hard Constraints

- no live Proxmox mutation/smoke without explicit active-session user approval
- no live DRS migration smoke in this gate unless the user explicitly changes
  the scope
- no live post-create readiness checks, SSH, Ansible, guest-agent, shell, or
  network probing in this gate
- keep Create VM success independent from post-create readiness evidence
- keep DRS execution authority separate from Create VM mutation authority
- do not weaken tests to pass validation
- do not add Goal 9 implementation while running this validation gate
- do not broaden API permissions or mutation paths as part of validation

## Scope

1. Confirm repository state and dirty working tree.
   - Record branch and changed files.
   - Separate pre-existing code/test changes from documentation-only changes.
   - Do not revert user or prior-session changes.
2. Validate Goal 8 local-only readiness evidence.
   - Confirm the endpoint, job type, artifact type, idempotency, secret
     rejection, acknowledgement gate, and no-live-check boundary.
3. Validate DRS policy/approval/reconciliation boundaries.
   - Confirm manual VM migration policy UI/API exists.
   - Confirm recommendation/check output remains `read_only=true`,
     `executable=false`, and `allowed_actions=[]`.
   - Confirm local approval packet/job intent creation does not call Proxmox.
   - Confirm live migration execute remains a narrow backend route without
     broad UI controls.
   - Confirm reconcile preview remains read-only and has no corrective mutation.
4. Validate existing Goal 9 account operations.
   - Confirm admin list/create/role/disable/reset-password behavior.
   - Confirm disable/reset-password revoke target sessions.
   - Confirm role changes do not revoke target sessions.
   - Confirm last enabled admin protection is still enforced.
   - Confirm raw password/session token material is not returned.
5. Validate documentation alignment.
   - Confirm canonical goal docs identify Goal 8 as complete and Goal 9 as
     polish remaining, not a blank slate.
   - Confirm current/product/Korean docs distinguish manual VM policy
     configuration from richer policy rule/full metadata editing.
   - Confirm no current docs claim `/drs` is only recommendation/check when the
     UI also exposes manual policy configuration and local approval packet
     creation.

## Out Of Scope

- Live DRS migration smoke evidence.
- Corrective reconciliation mutation.
- Background reconciliation automation.
- Automatic DRS.
- Broad live DRS execution UI.
- Goal 9 implementation work.
- Public signup, email reset, OAuth, SSO, 2FA, API tokens, or external identity
  providers.
- SSH smoke, Ansible verification, app bootstrap, or live readiness checks.

## Focused Validation

Run focused validation first to isolate the surfaces most affected by recent
Goal 8, DRS, and account/session documentation updates:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q \
  backend/tests/vm_actions \
  backend/tests/contracts/test_api_v1_vm_actions.py \
  backend/tests/jobs/test_runs.py \
  backend/tests/contracts/test_api_v1_admin_users.py \
  backend/tests/drs

node --test \
  frontend/tests/apiV1Client.test.mjs \
  frontend/tests/jobsScreen.test.mjs \
  frontend/tests/drsAdvisor.test.mjs \
  frontend/tests/adminUsersScreen.test.mjs
```

## Broad Validation

If focused validation passes or any failures are understood and documented, run
the broader baseline:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
node --test frontend/tests/*.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```

## Documentation Checks

Run targeted stale-claim searches after any documentation cleanup:

```bash
rg -n "Goal 8.*Def[e]rred|SSH/Ansible/App Bootstrap Readines[s]|Goal 9: Account/Session Operations Polish \\| Def[e]rred|Goal 7 pendin[g]|next active gat[e]|read/check onl[y]|DRS policy editor AP[I]|policy editor remai[n]|policy editor[는]|migration execution path는 없습니[다]" docs/current docs/product/drs-advisor docs/goal docs/ko docs/engineering README.md docs/README.md
```

Expected result: no direct current-state contradiction. Matches in historical
documents are acceptable only when the file clearly marks the content as
historical and points readers back to `docs/goal/README.md` or
`docs/current/README.md`.

## Decision Model

Record one result:

- `pass`: focused and broad validation pass, docs are aligned, and no blocking
  risk remains.
- `pass-with-risk`: implementation is usable, but a bounded non-blocking risk
  remains and is documented with owner/next action.
- `fail`: validation fails, docs contradict active code, or a safety boundary is
  unclear enough to block Goal 9 or live smoke work.

## Evidence To Record

When this gate is executed, update this document with:

- date/time and branch
- dirty-state summary before validation
- focused validation commands and results
- broad validation commands and results
- documentation search results
- failures or skipped commands with reasons
- final decision
- remaining risks

## Execution Record: 2026-06-01

Branch and checkout state:

- Branch: `main`, tracking `origin/main`.
- Dirty state before validation: mixed code, test, and documentation changes
  were already present. They were treated as the current implementation
  baseline and were not reverted.
- Pre-validation code changes included
  `backend/app/api/v1/router.py`, `backend/app/jobs/runs.py`,
  `frontend/src/services/apiV1.js`, and untracked
  `backend/app/vm_actions/post_create_readiness.py`.
- Pre-validation test changes included
  `backend/tests/contracts/test_api_v1_vm_actions.py`,
  `backend/tests/jobs/test_runs.py`, `frontend/tests/apiV1Client.test.mjs`,
  `frontend/tests/jobsScreen.test.mjs`, and untracked
  `backend/tests/vm_actions/`.
- Pre-validation documentation changes included the Goal 8 readiness evidence
  replacement, current/architecture/product/Korean documentation updates,
  deletion of
  `docs/goal/goal-08-ssh-ansible-app-bootstrap-readiness.md`, and untracked
  `docs/goal/goal-08-post-create-readiness-evidence.md`.

Focused validation:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q \
  backend/tests/vm_actions \
  backend/tests/contracts/test_api_v1_vm_actions.py \
  backend/tests/jobs/test_runs.py \
  backend/tests/contracts/test_api_v1_admin_users.py \
  backend/tests/drs
```

Result: pass. `98 passed, 15 warnings, 4 subtests passed in 6.59s`.
Warnings were httpx `app` shortcut deprecations from admin-user contract tests.

```bash
node --test \
  frontend/tests/apiV1Client.test.mjs \
  frontend/tests/jobsScreen.test.mjs \
  frontend/tests/drsAdvisor.test.mjs \
  frontend/tests/adminUsersScreen.test.mjs
```

Result: pass. `4` frontend test files passed in `128.642459ms`.

Supplemental focused validation:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q \
  backend/tests/contracts/test_api_v1_drs.py
```

Result: pass. `11 passed in 0.74s`. This was added because the original
focused backend command omitted the DRS route contract file that directly
covers policy, approval-packet, execute, and reconcile-preview boundaries.

Broad validation:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
```

Result: pass. `278 passed, 36 warnings, 29 subtests passed in 16.38s`.
Warnings were the same httpx `app` shortcut deprecation class.

```bash
node --test frontend/tests/*.mjs
```

Result: pass. `13` frontend test files passed in `185.052042ms`.

```bash
pnpm --dir frontend lint
```

Result: pass. ESLint completed with `--max-warnings 0`.

```bash
pnpm --dir frontend build
```

Result: pass. Vite `5.4.21` production build completed in `1.44s`.

```bash
git diff --check
```

Result: pass before and after the documentation cleanup.

Documentation checks:

```bash
rg -n "Goal 8.*Def[e]rred|SSH/Ansible/App Bootstrap Readines[s]|Goal 9: Account/Session Operations Polish \\| Def[e]rred|Goal 7 pendin[g]|next active gat[e]|read/check onl[y]|DRS policy editor AP[I]|policy editor remai[n]|policy editor[는]|migration execution path는 없습니[다]" docs/current docs/product/drs-advisor docs/goal docs/ko docs/engineering README.md docs/README.md
```

Result: pass. The prescribed stale-claim search returned no matches both
before and after the documentation cleanup.

Supplemental documentation review found stale active-document wording outside
the prescribed search scope. The stale wording described current `/drs` as
limited to recommendation/check, said the UI exposed no local approval-packet
controls, or described policy editing as fully deferred. Documentation-only
cleanup updated the active English and Korean current/architecture/product docs
to state the current
boundary: `/drs` has recommendation/check, manual per-VM migration policy
configuration, and local approval packet/job intent creation; live execute UI,
corrective reconcile UI, richer policy rule/full metadata editing, corrective
mutation, background automation, automatic DRS, and live DRS smoke evidence
remain deferred.

Post-cleanup supplemental searches found no direct current-state contradiction.
Remaining matches were the validation gate's own scope text or accurate
statements that live execute/corrective reconcile and broad
approval-to-execute controls remain deferred.

Skipped commands and safety:

- No prescribed validation command was skipped.
- No live Proxmox mutation/smoke was run.
- No live DRS smoke was run.
- No live post-create readiness checks, SSH, Ansible, guest-agent, shell, or
  network probing were run.
- No Goal 9 implementation was added during this validation gate.

Final decision: `pass-with-risk`.

The current implementation baseline is usable and aligned after the
documentation cleanup. `pass-with-risk` is acceptable for committing the
coherent current state because focused and broad validation passed, the
prescribed stale-claim search is clean, supplemental DRS contract coverage
passed, and the stale active documentation claims found by supplemental review
were corrected.

Remaining risks and next actions:

- The original stale-claim search was too narrow for active architecture and
  product index pages. Next validation should keep a supplemental search that
  includes `docs/architecture` and `docs/product` broad index files.
- The original focused backend command omitted
  `backend/tests/contracts/test_api_v1_drs.py`. It passed as supplemental
  validation and was covered by the broad suite; future focused DRS validation
  should include it explicitly.
- Post-create readiness route authorization is enforced by the router's
  `require_operator` dependency and the recorder remained local-only in tests,
  but there is no dedicated HTTP auth contract for that new route yet. Add one
  if the local-only readiness evidence surface expands.
- No live DRS migration smoke has been run. This remains an intentional,
  non-blocking risk unless the user gives explicit active-session approval for
  a separate live-smoke task.

Next explicit task: optional approved live DRS smoke evidence or another
user-selected task from `docs/goal/README.md`.

## Completion Criteria

- Current implementation scope is clear.
- Validation results are recorded.
- Documentation agrees with active code/tests about Goal 8, Goal 9, DRS policy,
  DRS approval, and live execution boundaries.
- No live Proxmox mutation was performed unless separately approved and
  documented.
- The next task is explicit: optional approved live DRS smoke evidence or
  another user-selected task.
