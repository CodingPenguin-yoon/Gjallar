# TASKS

Last updated: 2026-05-09 03:05 KST
Project: Gjallar
Thread ownership: 이 Discord thread/session은 Gjallar만 관리한다.

## Current Set Summary

Current Set: Set 7 - Review & Confirm / approval policy
Status: planned
Goal: Set 6 dry-run plan output 위에 Review & Confirm 13개 항목, review summary checksum, approval gate policy를 RED-first로 최소 GREEN 구현한다.
Next action: next worker re-checks Set 6 focused GREEN tests, then runs existing `backend/tests/vm_create/test_preflight_policy.py` RED and adds focused RED tests for review summary/checksum/approval request before production code.
Done criteria summary: Set 7 focused RED→GREEN tests pass with unittest fallback; red risk cannot approve/execute; yellow risk requires ack; no commit/push/delete/live Proxmox/IaC side effect; `git diff --check` pass; docs updated; Set 8 live GitOps/apply remains approval-gated
Blocker: backend `.venv` still lacks pytest; Set 7 may use verified `unittest` fallback, but full backend pytest GREEN requires non-destructive dependency recovery before claim

## Global autonomous gate

Allowed overnight autonomous scope:
- Set 0~7의 비파괴 코드/테스트/문서 작업
- RED-first contract/schema/forbidden/secret tests
- fake/read-only adapter와 dry-run/preflight/plan 구현

Hard stop before:
- commit / push
- file/module deletion or large legacy removal
- Terraform apply or real IaC repo write
- Proxmox write, VM create, power on
- Set 8+ live GitOps/apply/power-on
- red risk override attempt

## Set 0: 작업 준비 / 안전 백업

Status: completed
Goal:
- 새 branch를 만들고, 현재 repo 상태와 legacy route/test inventory를 baseline artifact로 남긴다.

Scope:
- remote repo `codex-vm:/home/yoon/projects/Gjallar` 상태 확인
- 새 branch 생성: `rewrite/prd-v1-mvp` 계열
- baseline artifact 생성: status/tracked files/routes/tests
- frontend current tests 재확인
- backend pytest/env 상태 확인 및 복구 필요성 기록
- Codex VM에서 PRD 접근 방식 결정: snapshot copy 또는 NFS/mount 후속
- root 운영 문서와 PRD/22 리뷰 결과 반영

Out of scope:
- commit/push
- destructive delete, snapshot, rollback, hard stop/reset/kill
- Terraform apply, Proxmox write, VM create/power-on
- Heimdall/Gjallar 외 다른 프로젝트 변경
- Set 1+ 구현 시작 전 Set 0 완료 기준 우회

Dependencies:
- Shared docs path exists: `/mnt/hermes_data/프로젝트/Gjallar`
- Remote repo accessible through `codex-vm`

Ordered task list:
- [x] 1. stale paused Gjallar Hermes cron 제거 및 새 cron ID 문서화
- [x] 2. remote repo status/HEAD/branch 확인: initial clean `main...origin/main`, head `29412e8`; working branch now `rewrite/prd-v1-mvp`
- [x] 3. 작업 branch 생성 또는 이미 있으면 안전하게 재사용 여부 기록: created `rewrite/prd-v1-mvp`, no push
- [x] 4. baseline artifact 디렉터리 생성: `artifacts/rewrite-baseline/20260509-004801-KST/`
- [x] 5. tracked files / route inventory / test inventory 생성
- [x] 6. frontend tests 실행 결과 기록: PASS for `frontend/tests/*.mjs`
- [x] 7. backend pytest/env 복구 필요 여부 기록: BLOCKED, `No module named pytest`; recovery plan recorded
- [x] 8. Codex VM PRD 접근 방식 결정 및 기록: snapshot copy at `artifacts/rewrite-baseline/20260509-004801-KST/prd-snapshot/PRD/`
- [x] 9. CURRENT_STATE.md / TASKS.md 갱신

Done criteria:
- [x] repo status가 clean이거나 기존 변경이 명시적으로 분리됨: initial status clean; current untracked `artifacts/` is intentional Set 0 evidence
- [x] baseline artifact 경로가 기록됨
- [x] frontend tests pass 또는 실패/blocker가 기록됨
- [x] backend test command가 실행 가능하거나 설치 필요성이 명시됨
- [x] no secrets in artifacts/docs: obvious secret assignment / credentialed URL scan passed
- [x] CURRENT_STATE.md 갱신
- [x] TASKS.md 갱신

Stop criteria:
- destructive action 필요
- commit/push 필요
- Proxmox/IaC 실제 mutation 필요
- 같은 실패가 2회 반복
- 사용자 결정 필요
- lock stale 여부가 불확실함
- repo/docs path가 Gjallar가 아님
- secret 노출 위험

Verification commands:
```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && git status --short --branch && git rev-parse --short HEAD'
ssh codex-vm 'cd /home/yoon/projects/Gjallar && git diff --check'
ssh codex-vm 'cd /home/yoon/projects/Gjallar && for f in frontend/tests/*.mjs; do node "$f" || exit 1; done'
ssh codex-vm 'cd /home/yoon/projects/Gjallar && backend/.venv/bin/python -m pytest backend/tests -q'
```

Set 0 completion record:
- `/mnt/hermes_data/프로젝트/Gjallar/logs/2026-05-09_set0_rewrite_baseline.md`
- Remote artifact: `codex-vm:/home/yoon/projects/Gjallar/artifacts/rewrite-baseline/20260509-004801-KST/`
- Repo status after Set 0: `## rewrite/prd-v1-mvp` with untracked `artifacts/`
- No commit/push/delete/apply/power-on was run.

Reporting policy:
- every cron tick final response는 originating Discord thread로 전달한다.
- 상태 라벨: LOCK_WAIT / SET_START / SET_PROGRESS / SET_COMPLETE / BLOCKER / DECISION_REQUIRED / STALE_LOCK / NO_APPROVED_WORK
- `[SILENT]` 금지.

Lock policy:
- lock dir: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock`
- lock file: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json`
- acquire: atomic `mkdir`
- stale threshold: 일반 작업 90분, 긴 build/test는 2~3시간

Next Set candidate:
- Set 1: Fresh code inventory / Keep-Drop-Park

Known risks/context:
- backend venv에 pytest가 없어서 backend tests는 아직 GREEN이 아니다. Set 2+ backend TDD 전에 pytest dependency setup이 필요하다.
- Codex VM에는 `/mnt/hermes_data`가 없으므로 현재 PRD 접근은 snapshot copy다.
- `/mnt/hermes_data/공통/iac`는 현재 보이지 않으므로 Set 8+는 hard stop.

## Set 1: Fresh code inventory / Keep-Drop-Park

Status: completed
Goal:
- PRD 기준으로 기존 코드를 `Keep / Drop / Park`로 분류하고, 구현 직전 inventory/handoff 문서를 갱신한다.

Scope:
- remote repo `codex-vm:/home/yoon/projects/Gjallar` branch `rewrite/prd-v1-mvp`
- Set 0 baseline artifacts, route inventory, test inventory
- `PRD/10_CODE_INVENTORY.md`
- `PRD/11_KEEP_DROP_PARK.md`
- 필요 시 Set 1 상세 로그 under `logs/`

Out of scope:
- production code behavior change
- commit/push
- file/module deletion or large legacy removal
- Terraform/Proxmox/IaC live mutation
- Set 2 RED test creation before Set 1 inventory is done
- non-Gjallar project changes

Dependencies:
- Set 0 baseline artifact exists: `artifacts/rewrite-baseline/20260509-004801-KST/`
- PRD snapshot exists on Codex VM: `artifacts/rewrite-baseline/20260509-004801-KST/prd-snapshot/PRD/`

Ordered task list:
- [x] 1. Read Set 0 artifacts and current repo tree on `rewrite/prd-v1-mvp`
- [x] 2. Inventory backend top-level packages/routes/migrations/tests
- [x] 3. Inventory frontend pages/features/API clients/tests
- [x] 4. Inventory infra/scripts/docs that intersect PRD MVP
- [x] 5. Classify every relevant module/file group as Keep / Drop / Park with rationale
- [x] 6. Update `PRD/10_CODE_INVENTORY.md` and `PRD/11_KEEP_DROP_PARK.md`
- [x] 7. Record no-delete/no-commit status and next Set 2 RED-test handoff in CURRENT_STATE/TASKS

Done criteria:
- [x] all top-level backend/frontend/infra areas have a Keep/Drop/Park classification
- [x] Drop/Park items are documented as not deleted without explicit approval
- [x] `PRD/10_CODE_INVENTORY.md` updated or created from current repo evidence
- [x] `PRD/11_KEEP_DROP_PARK.md` updated or created from current repo evidence
- [x] `git diff --check` passes
- [x] repo status/diff is recorded, including intentional untracked/modified docs/artifacts
- [x] CURRENT_STATE.md and TASKS.md updated

Stop criteria:
- destructive deletion/removal needed
- commit/push needed
- same command/test failure repeats twice
- repo/docs path is not Gjallar
- secret exposure risk
- user decision needed

Verification commands:
```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && git status --short --branch && git diff --check'
ssh codex-vm 'cd /home/yoon/projects/Gjallar && test -s artifacts/rewrite-baseline/20260509-004801-KST/route-inventory.txt && test -s artifacts/rewrite-baseline/20260509-004801-KST/test-inventory.txt'
```

Reporting policy:
- every cron tick final response는 originating Discord thread로 전달한다.
- 상태 라벨: LOCK_WAIT / SET_START / SET_PROGRESS / SET_COMPLETE / BLOCKER / DECISION_REQUIRED / STALE_LOCK / NO_APPROVED_WORK
- `[SILENT]` 금지.

Lock policy:
- lock dir: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock`
- lock file: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json`
- acquire: atomic `mkdir`
- stale threshold: 일반 작업 90분, 긴 build/test는 2~3시간

Next Set candidate:
- Set 2: Contract/schema tests 먼저 작성

Set 1 completion record:
- `/mnt/hermes_data/프로젝트/Gjallar/logs/2026-05-09_set1_code_inventory.md`
- Updated shared docs: `PRD/10_CODE_INVENTORY.md`, `PRD/11_KEEP_DROP_PARK.md`
- Remote synced artifact/snapshot: `artifacts/rewrite-baseline/20260509-004801-KST/shared-docs-set1/` and refreshed `prd-snapshot/PRD/10_CODE_INVENTORY.md`, `prd-snapshot/PRD/11_KEEP_DROP_PARK.md`
- Repo status after Set 1: `## rewrite/prd-v1-mvp` with untracked `artifacts/`
- No commit/push/delete/apply/power-on was run.

Known risks/context:
- backend pytest dependency is missing; Set 1 is docs/inventory and can proceed, but Set 2+ backend RED/GREEN requires pytest setup.
- Actual Drop deletion/removal is not authorized; only classification/Park proposal is allowed.

## Set 2: Contract/schema tests first

Status: completed
Goal:
- PRD 기준 `/api/v1`, manifest/profile/network, forbidden MVP surface, create-flow, Review & Confirm 계약을 생산 코드 변경 전에 RED 테스트로 고정한다.

Scope:
- remote repo `codex-vm:/home/yoon/projects/Gjallar` branch `rewrite/prd-v1-mvp`
- Set 1 updated docs: `PRD/10_CODE_INVENTORY.md`, `PRD/11_KEEP_DROP_PARK.md`
- backend tests under `backend/tests/contracts/`, `backend/tests/manifests/`, `backend/tests/vm_create/`
- frontend pure utility tests under `frontend/tests/*.mjs`
- test dependency/setup docs if backend pytest remains unavailable

Out of scope:
- production code implementation before RED is observed
- commit/push
- file/module deletion or large legacy removal
- Terraform/Proxmox/IaC live mutation
- Set 8+ live side effects
- non-Gjallar project changes

Dependencies:
- Set 1 completed and docs/snapshot synced
- backend pytest blocker acknowledged: `backend/.venv/bin/python -m pytest backend/tests -q` currently reports `No module named pytest`
- frontend Node pure-test harness available from Set 0

Ordered task list:
- [x] 1. Re-check repo status and backend test runner availability: branch `rewrite/prd-v1-mvp`, HEAD `29412e8`, backend pytest still blocked with `No module named pytest`
- [x] 2. If pytest is missing, add/confirm a non-destructive dependency recovery plan or test requirements change using RED-first policy where applicable: used `unittest` fallback for RED verification and carried pytest dependency recovery into Set 3+
- [x] 3. Write backend RED tests for `/api/v1` response/error shape and forbidden MVP endpoints
- [x] 4. Write backend RED tests for manifest/profile/network schema and secret redaction
- [x] 5. Write backend RED tests for create draft/preflight/plan/Review & Confirm/approval contract
- [x] 6. Write frontend RED pure tests for review summary, risk policy, and create VM defaults
- [x] 7. Run focused tests and verify they fail for expected missing-contract reasons, not syntax/import mistakes
- [x] 8. Record intentional RED state, backend pytest status, repo status, and next Set 3 GREEN handoff in shared docs

Done criteria:
- [x] RED tests exist for contract/schema/forbidden/secret/create-flow/review-summary areas
- [x] RED tests were executed and failed for expected missing-contract reasons where implementation is absent; one forbidden guard was already satisfied because Runtime Target write route is absent
- [x] backend pytest blocker is explicitly recorded with recovery task/fallback
- [x] frontend RED tests executed with Node where applicable
- [x] no production code was changed before RED verification
- [x] `git diff --check` passes
- [x] repo status/diff is recorded
- [x] CURRENT_STATE.md and TASKS.md updated

Stop criteria:
- backend pytest dependency cannot be recovered or documented safely
- same command/test failure repeats twice
- production code change would be needed before a RED test exists
- destructive deletion/removal needed
- commit/push needed
- repo/docs path is not Gjallar
- secret exposure risk
- user decision needed

Verification commands/results:
```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && git status --short --branch && git diff --check'
# PASS; status includes intentional untracked artifacts and Set 2 test files

ssh codex-vm 'cd /home/yoon/projects/Gjallar && backend/.venv/bin/python -m pytest backend/tests/contracts backend/tests/manifests backend/tests/vm_create -q'
# BLOCKED: No module named pytest

ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest <Set 2 backend test files>'
# RED: 17 tests run, 16 expected failures, 1 forbidden guard already satisfied

ssh codex-vm 'cd /home/yoon/projects/Gjallar && node frontend/tests/reviewSummary.test.mjs'
ssh codex-vm 'cd /home/yoon/projects/Gjallar && node frontend/tests/riskPolicy.test.mjs'
ssh codex-vm 'cd /home/yoon/projects/Gjallar && node frontend/tests/createVmDefaults.test.mjs'
# RED: 3/3 fail for missing PRD utility modules
```

Reporting policy:
- every cron tick final response는 originating Discord thread로 전달한다.
- 상태 라벨: LOCK_WAIT / SET_START / SET_PROGRESS / SET_COMPLETE / BLOCKER / DECISION_REQUIRED / STALE_LOCK / NO_APPROVED_WORK
- `[SILENT]` 금지.

Lock policy:
- lock dir: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock`
- lock file: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json`
- acquire: atomic `mkdir`
- stale threshold: 일반 작업 90분, 긴 build/test는 2~3시간

Set 2 completion record:
- `/mnt/hermes_data/프로젝트/Gjallar/logs/2026-05-09_set2_red_contract_tests.md`
- Remote evidence artifact: `artifacts/rewrite-baseline/20260509-004801-KST/set2-red-tests/verification-summary.txt`
- Added backend tests: `backend/tests/contracts/`, `backend/tests/manifests/`, `backend/tests/vm_create/`
- Added frontend tests: `frontend/tests/reviewSummary.test.mjs`, `frontend/tests/riskPolicy.test.mjs`, `frontend/tests/createVmDefaults.test.mjs`
- Repo status after Set 2: `## rewrite/prd-v1-mvp` with intentional untracked `artifacts/` plus Set 2 test files
- No production code, commit, push, delete, apply, Proxmox write, VM create, or power-on was run.

Next Set candidate:
- Set 3: Backend `/api/v1` skeleton + manifest loader 최소 GREEN 구현

Known risks/context:
- backend venv currently lacks pytest; Set 3 can use focused `unittest` fallback, but full backend pytest GREEN requires non-destructive dependency recovery before claim.
- Set 2 intentionally leaves later-slice RED tests for forbidden legacy route unmounting, jobs/risks, vm_create, and frontend utilities.
- Drop/Park/deletion remains approval-gated.

## Set 3: Backend `/api/v1` skeleton + manifest loader

Status: completed
Goal:
- Set 2 RED tests 중 `/api/v1` skeleton, response helper, manifest/profile/network defaults, secret redaction에 해당하는 backend 계약을 최소 GREEN으로 만든다.

Scope:
- remote repo `codex-vm:/home/yoon/projects/Gjallar` branch `rewrite/prd-v1-mvp`
- `backend/app/api/v1/` response helpers/router and minimal read-only skeleton routes
- `backend/app/manifests/` profile/network/template models and builtin loader defaults
- `backend/app/core/redaction.py`
- Focused Set 2 backend tests that correspond to API skeleton/manifest/redaction

Out of scope:
- commit/push
- file/module deletion or large legacy removal
- live Proxmox/IaC/Terraform mutation
- unmounting/removing legacy routers unless a focused RED test and non-destructive compatibility plan make it safe
- full create/apply/power-on flow beyond minimal stubs needed by Set 3
- frontend UI implementation
- non-Gjallar project changes

Dependencies:
- Set 2 RED tests completed
- backend `.venv` can run `unittest`; `pytest` is still missing

Ordered task list:
- [x] 1. Re-check repo status and confirm Set 2 RED tests are present: branch `rewrite/prd-v1-mvp`, HEAD `29412e8`, Set 2 tests present
- [x] 2. Implement minimal `app.api.v1.responses` and router skeleton without touching live side-effect code
- [x] 3. Include `/api/v1` read-only skeleton routes in FastAPI app
- [x] 4. Implement manifest/profile/network/template builtin models and loaders for `general-vm`, `server-net`, and Ubuntu template defaults
- [x] 5. Implement `app.core.redaction.redact_secrets`
- [x] 6. Run focused unittest for Set 3 target tests and record remaining intentional RED tests for later Sets
- [x] 7. Run `git diff --check`, record repo status, update CURRENT_STATE.md/TASKS.md

Done criteria:
- [x] `backend/tests/contracts/test_api_v1_shape.py` passes
- [x] `backend/tests/manifests/test_profile_schema.py`, `test_network_profile.py`, and `test_secret_redaction.py` pass
- [x] No production code was written outside Set 3 scope
- [x] Later-slice RED tests are listed once as intentional remaining RED
- [x] `git diff --check` passes
- [x] repo status/diff is recorded
- [x] CURRENT_STATE.md and TASKS.md updated

Verification commands/results:
```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/contracts/test_api_v1_shape.py backend/tests/manifests/test_profile_schema.py backend/tests/manifests/test_network_profile.py backend/tests/manifests/test_secret_redaction.py'
# RED before production code: 8 failures for missing `/api/v1`, `app.api`, `app.manifests`, and `app.core`
# GREEN after implementation: Ran 8 tests in 0.555s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && git diff --check'
# PASS

ssh codex-vm 'cd /home/yoon/projects/Gjallar && backend/.venv/bin/python -m pytest backend/tests/contracts backend/tests/manifests backend/tests/vm_create -q'
# BLOCKED: No module named pytest
```

Remaining intentional RED / deferred tests:
- `backend/tests/contracts/test_forbidden_mvp_endpoints.py::test_legacy_destructive_and_llm_routes_are_not_exposed_in_mvp` remains RED because legacy `/api` routers are still mounted; unmount/cutover is out of Set 3 scope and deletion/cutover remains approval-sensitive.
- `backend/tests/vm_create/test_draft_contract.py` remains RED because `app.vm_create` create-draft utilities are Set 6 scope.
- `backend/tests/vm_create/test_preflight_policy.py` remains RED because approval/preflight policy is Set 7 scope.
- Frontend RED tests for Review Summary, risk policy, and Create VM defaults remain later frontend work, not Set 3 scope.

Set 3 completion record:
- `/mnt/hermes_data/프로젝트/Gjallar/logs/2026-05-09_set3_backend_api_manifest_skeleton.md`
- Remote changed files include `backend/app/main.py`, new `backend/app/api/`, `backend/app/core/`, and `backend/app/manifests/`
- Repo status after Set 3: `## rewrite/prd-v1-mvp` with modified `backend/app/main.py` and intentional untracked artifacts/tests/new backend packages
- No commit/push/delete/apply/Proxmox write/VM create/power-on was run.

Reporting policy:
- every cron tick final response는 originating Discord thread로 전달한다.
- 상태 라벨: LOCK_WAIT / SET_START / SET_PROGRESS / SET_COMPLETE / BLOCKER / DECISION_REQUIRED / STALE_LOCK / NO_APPROVED_WORK
- `[SILENT]` 금지.

Lock policy:
- lock dir: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock`
- lock file: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json`
- acquire: atomic `mkdir`
- stale threshold: 일반 작업 90분, 긴 build/test는 2~3시간

Next Set candidate:
- Set 4: Minimum job/artifact substrate

Known risks/context:
- Existing legacy `/api` routes remain mounted; forbidden endpoint tests may stay intentionally RED until a later cutover/hardening Set unless a focused RED test and non-destructive compatibility plan make it safe.
- Backend pytest is still unavailable; do not claim full pytest GREEN until dependency recovery is verified.

## Set 4: Minimum job/artifact substrate

Status: completed
Goal:
- preflight/plan/approval 이전에 job, approval, artifact 모델과 실제 파일/checksum 저장소를 최소 GREEN으로 만든다.

Scope:
- remote repo `codex-vm:/home/yoon/projects/Gjallar` branch `rewrite/prd-v1-mvp`
- new backend tests for job/artifact substrate, approval artifact references, SHA-256 checksum, and secret-safe artifact serialization
- `backend/app/jobs/` minimal models/artifacts helpers
- temp/local run directories only for tests

Out of scope:
- commit/push
- file/module deletion or large legacy removal
- live Proxmox/IaC/Terraform mutation
- `/var/lib/gjallar` live write outside tests/temp fixtures
- approval execution, VM create, Terraform apply, Proxmox write, or power action
- frontend UI implementation
- non-Gjallar project changes

Dependencies:
- Set 3 completed
- backend `.venv` can run `unittest`; `pytest` is still missing
- `app.core.redaction.redact_secrets` exists and passes focused Set 3 test

Ordered task list:
- [x] 1. Re-check repo status and Set 3 focused tests are GREEN: Set 3 focused unittest PASS; branch `rewrite/prd-v1-mvp`
- [x] 2. Write focused RED tests for `app.jobs` models/artifact write behavior before production code: after fixing test syntax draft, RED was `No module named 'app.jobs'`
- [x] 3. Implement minimal job/artifact dataclasses for job, approval, and artifact records: `backend/app/jobs/models.py`
- [x] 4. Implement artifact writer that stores JSON/text under a caller-provided temp run directory and records real SHA-256 checksum: `backend/app/jobs/artifacts.py`
- [x] 5. Ensure artifact serialization calls `redact_secrets` and never stores raw token/password/credentialed URL values: focused artifact test verifies redacted payload
- [x] 6. Run focused `unittest` for Set 4 tests and record later-slice intentional RED: Set 4 PASS; later Set 2 RED remains deferred below
- [x] 7. Run `git diff --check`, record repo status, update CURRENT_STATE.md/TASKS.md/logs

Done criteria:
- [x] Set 4 focused RED tests were observed before production code
- [x] focused Set 4 tests pass with `PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/jobs/test_artifact_store.py backend/tests/jobs/test_job_models.py`
- [x] artifact records point to real files, not fake IDs only
- [x] artifact checksum is real SHA-256 of stored content
- [x] secret raw values do not appear in artifact files or serialized records in the focused test
- [x] No production code was written outside Set 4 scope
- [x] Later-slice RED tests are listed once as intentional remaining RED
- [x] `git diff --check` passes
- [x] repo status/diff is recorded
- [x] CURRENT_STATE.md and TASKS.md updated

Verification commands/results:
```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/jobs/test_artifact_store.py backend/tests/jobs/test_job_models.py'
# RED before production code: FAILED (failures=3), No module named 'app.jobs'
# GREEN after implementation: Ran 3 tests in 0.006s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/contracts/test_api_v1_shape.py backend/tests/manifests/test_profile_schema.py backend/tests/manifests/test_network_profile.py backend/tests/manifests/test_secret_redaction.py backend/tests/jobs/test_artifact_store.py backend/tests/jobs/test_job_models.py'
# GREEN: Ran 11 tests in 0.551s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && git diff --check'
# PASS

ssh codex-vm 'cd /home/yoon/projects/Gjallar && backend/.venv/bin/python -m pytest backend/tests/jobs -q'
# BLOCKED: No module named pytest
```

Remaining intentional RED / deferred tests:
- `backend/tests/contracts/test_forbidden_mvp_endpoints.py::test_legacy_destructive_and_llm_routes_are_not_exposed_in_mvp` remains RED because legacy `/api` routers are still mounted; cutover remains later/approval-sensitive.
- `backend/tests/vm_create/test_draft_contract.py` remains RED because `app.vm_create` create-draft utilities are Set 6 scope.
- `backend/tests/vm_create/test_preflight_policy.py` remains RED because approval/preflight policy is Set 7 scope.
- Frontend RED tests for Review Summary, risk policy, and Create VM defaults remain later frontend work.
- Backend pytest remains unavailable until dependency recovery.

Set 4 completion record:
- `/mnt/hermes_data/프로젝트/Gjallar/logs/2026-05-09_set4_job_artifact_substrate.md`
- Remote changed files include `backend/app/jobs/` and `backend/tests/jobs/`
- Remote synced shared-doc snapshot: `artifacts/rewrite-baseline/20260509-004801-KST/shared-docs-set4/`
- Repo status after Set 4: `## rewrite/prd-v1-mvp` with modified `backend/app/main.py` and intentional untracked artifacts/tests/new backend packages
- No commit/push/delete/apply/Proxmox write/VM create/power-on was run.

Reporting policy:
- every cron tick final response는 originating Discord thread로 전달한다.
- 상태 라벨: LOCK_WAIT / SET_START / SET_PROGRESS / SET_COMPLETE / BLOCKER / DECISION_REQUIRED / STALE_LOCK / NO_APPROVED_WORK
- `[SILENT]` 금지.

Lock policy:
- lock dir: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock`
- lock file: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json`
- acquire: atomic `mkdir`
- stale threshold: 일반 작업 90분, 긴 build/test는 2~3시간

Next Set candidate:
- Set 5: Read-only Proxmox inventory adapter

Known risks/context:
- Backend pytest is still unavailable; use focused `unittest` fallback unless safe dependency recovery is performed.
- Live job run directory writes are out of scope; tests should use temp directories.
- Commit/push/delete/live side effects remain approval-gated.

## Set 5: Read-only Proxmox inventory adapter

Status: completed
Goal:
- Proxmox nodes/VMs/templates/storage/network/guest-agent/IP read-only 조회를 fake/read-only adapter로 먼저 계약화하고 최소 GREEN으로 만든다.

Scope:
- remote repo `codex-vm:/home/yoon/projects/Gjallar` branch `rewrite/prd-v1-mvp`
- focused backend RED tests for `app.proxmox` inventory adapter and `/api/v1` inventory response shape
- `backend/app/proxmox/` read-only models/adapter helpers only
- fake/static fixtures and temp artifacts only; no live Proxmox mutation

Out of scope:
- commit/push
- file/module deletion or large legacy removal
- Terraform/IaC live write or apply
- Proxmox create/update/delete/power action
- Heimdall registry write
- frontend UI implementation
- non-Gjallar project changes

Dependencies:
- Set 4 completed
- Set 3 `/api/v1` skeleton exists
- backend `.venv` can run `unittest`; `pytest` is still missing

Ordered task list:
- [x] 1. Re-check repo status and Set 4 focused tests are GREEN: Set 3+4 focused unittest PASS; branch `rewrite/prd-v1-mvp`
- [x] 2. Write focused RED tests for read-only nodes/VMs/templates/storage/network/guest-agent/IP adapter contract before production code: initial RED failed because `app.proxmox` was missing and `/api/v1` inventory skeleton lacked adapter payloads/meta
- [x] 3. Write/confirm forbidden tests that the adapter exposes no create/apply/delete/power methods
- [x] 4. Implement minimal fake/read-only `app.proxmox` inventory models/adapter: `backend/app/proxmox/`
- [x] 5. Wire `/api/v1` inventory skeleton to the fake/read-only adapter only if covered by focused tests: nodes/vms/vm detail/templates/storage/networks now adapter-backed
- [x] 6. Ensure secret/log redaction for adapter payloads: added RED check for credentialed URL control characters, then fixed URL redaction replacement
- [x] 7. Run focused `unittest`, `git diff --check`, record repo status, update CURRENT_STATE.md/TASKS.md/logs

Done criteria:
- [x] Set 5 focused RED tests were observed before production code
- [x] focused Set 5 tests pass with `PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/proxmox/test_inventory_adapter.py backend/tests/contracts/test_api_v1_inventory.py`
- [x] read-only adapter returns nodes/VMs/templates/storage/network/guest-agent/IP fixture shape
- [x] adapter has no create/apply/delete/power methods or live mutation path
- [x] secret/log payloads are redacted
- [x] No production code was written outside Set 5 scope
- [x] Later-slice RED tests are listed once as intentional remaining RED
- [x] `git diff --check` passes
- [x] repo status/diff is recorded
- [x] CURRENT_STATE.md and TASKS.md updated

Verification commands/results:
```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/proxmox/test_inventory_adapter.py backend/tests/contracts/test_api_v1_inventory.py'
# RED before production code: FAILED (failures=5), missing `app.proxmox`, missing `/api/v1/storage`, and skeleton inventory responses lacked adapter metadata/payloads
# GREEN after implementation: Ran 5 tests in 0.540s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend.tests.proxmox.test_inventory_adapter.ProxmoxInventoryAdapterTests.test_connection_context_and_snapshot_are_secret_safe'
# RED after adding control-character regression: FAILED (failures=1), redacted credentialed URL contained `\\x01`/`\\x02`
# GREEN after redaction fix: Ran 1 test in 0.007s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/contracts/test_api_v1_shape.py backend/tests/manifests/test_profile_schema.py backend/tests/manifests/test_network_profile.py backend/tests/manifests/test_secret_redaction.py backend/tests/jobs/test_artifact_store.py backend/tests/jobs/test_job_models.py backend/tests/proxmox/test_inventory_adapter.py backend/tests/contracts/test_api_v1_inventory.py'
# GREEN: Ran 16 tests in 0.551s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && git diff --check'
# PASS

ssh codex-vm 'cd /home/yoon/projects/Gjallar && backend/.venv/bin/python -m pytest backend/tests/proxmox backend/tests/contracts/test_api_v1_inventory.py -q'
# BLOCKED: No module named pytest
```

Remaining intentional RED / deferred tests:
- `backend/tests/contracts/test_forbidden_mvp_endpoints.py::test_legacy_destructive_and_llm_routes_are_not_exposed_in_mvp` remains RED because legacy `/api` routers are still mounted; cutover/hardening remains later and deletion/removal approval-gated.
- `backend/tests/contracts/test_jobs_risks_contract.py` remains RED because Jobs/Risks read API routes are later scope.
- `backend/tests/vm_create/test_draft_contract.py` remains RED and is a Set 6 target.
- `backend/tests/vm_create/test_preflight_policy.py` remains RED and should be split/handled across Set 6 preflight and Set 7 approval policy.
- Frontend RED tests for Review Summary, risk policy, and Create VM defaults remain later frontend/UI scope.
- Backend pytest remains unavailable until dependency recovery.

Set 5 completion record:
- `/mnt/hermes_data/프로젝트/Gjallar/logs/2026-05-09_set5_read_only_proxmox_inventory.md`
- Remote changed files include `backend/app/proxmox/`, `backend/tests/proxmox/`, `backend/app/api/v1/router.py`, and `backend/app/core/redaction.py`
- Remote synced shared-doc snapshot: `artifacts/rewrite-baseline/20260509-004801-KST/shared-docs-set5/`
- Repo status after Set 5: `## rewrite/prd-v1-mvp` with modified `backend/app/main.py` and intentional untracked artifacts/tests/new backend packages
- No commit/push/delete/apply/Proxmox write/VM create/power-on was run.

Reporting policy:
- every cron tick final response는 originating Discord thread로 전달한다.
- 상태 라벨: LOCK_WAIT / SET_START / SET_PROGRESS / SET_COMPLETE / BLOCKER / DECISION_REQUIRED / STALE_LOCK / NO_APPROVED_WORK
- `[SILENT]` 금지.

Lock policy:
- lock dir: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock`
- lock file: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json`
- acquire: atomic `mkdir`
- stale threshold: 일반 작업 90분, 긴 build/test는 2~3시간

Next Set candidate:
- Set 6: Create draft / preflight / plan

Known risks/context:
- Backend pytest is still unavailable; use focused `unittest` fallback unless safe dependency recovery is performed.
- Existing legacy Proxmox domain code may be used only as read-only reference; no deletion or live mutation is authorized.
- Commit/push/delete/live side effects remain approval-gated.

## Set 6: Create draft / preflight / plan

Status: completed
Goal:
- `general-vm` 생성 draft, non-destructive preflight, plan response를 Set 5 fake/read-only inventory와 Set 4 artifact substrate 위에서 RED-first로 최소 GREEN 구현한다.

Scope:
- remote repo `codex-vm:/home/yoon/projects/Gjallar` branch `rewrite/prd-v1-mvp`
- focused backend RED tests for `app.vm_create` draft/preflight/plan shape before production code
- `backend/app/vm_create/` minimal draft/preflight/planner helpers only
- existing manifest defaults, Set 5 fake/read-only inventory, and temp/local artifacts only

Out of scope:
- commit/push
- file/module deletion or large legacy removal
- Terraform/IaC live write or apply
- Proxmox create/update/delete/power action or VM create
- GitOps commit/push/apply execution
- Review & Confirm approval execution beyond plan/preflight handoff; Set 7 owns approval policy completion
- frontend UI implementation
- non-Gjallar project changes

Dependencies:
- Set 5 completed
- Set 4 job/artifact substrate exists
- Set 3 manifest/profile/network defaults exist
- backend `.venv` can run `unittest`; `pytest` is still missing

Ordered task list:
- [x] 1. Re-check repo status and Set 5 focused tests are GREEN: Set 5 focused unittest PASS; branch `rewrite/prd-v1-mvp`
- [x] 2. Re-run existing `backend/tests/vm_create/test_draft_contract.py` RED and add focused RED tests for preflight/plan response shape before production code: RED failed for missing `app.vm_create` modules and missing `/api/v1/vm-create` routes
- [x] 3. Implement minimal `app.vm_create.drafts` for default `general-vm` draft and create-enabled profile options
- [x] 4. Implement non-destructive preflight helpers that consume manifests + Set 5 fake inventory and return red/yellow/green risk results without live mutation
- [x] 5. Implement minimal plan response shape with VM name/VMID/node/storage/template/hardware/network/IP/state path/smoke timeout/risk summary/artifact references, but no GitOps/apply execution
- [x] 6. Ensure secret/log/artifact payloads remain redacted and no raw credential values are serialized: focused plan test asserts raw credential markers are absent; Set 4 artifact redaction remains GREEN
- [x] 7. Run focused `unittest`, `git diff --check`, record repo status, update CURRENT_STATE.md/TASKS.md/logs

Done criteria:
- [x] Set 6 focused RED tests were observed before production code
- [x] focused Set 6 tests pass with `PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/vm_create/test_draft_contract.py backend/tests/vm_create/test_preflight_plan_contract.py backend/tests/contracts/test_api_v1_vm_create.py`
- [x] `general-vm` draft uses locked profile/network/template defaults and only `general-vm` is create-enabled
- [x] preflight/plan code is non-destructive and uses fake/read-only inventory only
- [x] plan response includes artifact-ready fields but does not commit/push/apply/create/power-on
- [x] secret/log payloads are redacted
- [x] No production code is written outside Set 6 scope
- [x] Later-slice RED tests are listed once as intentional remaining RED
- [x] `git diff --check` passes
- [x] repo status/diff is recorded
- [x] CURRENT_STATE.md and TASKS.md updated

Stop criteria:
- live Proxmox mutation would be required
- live IaC write/apply or Git commit/push would be required
- destructive deletion/removal would be required
- approval execution/yellow ack handling expands into Set 7 without RED boundary
- same command/test failure repeats twice
- backend test dependency recovery becomes required but cannot be done non-destructively
- repo/docs path is not Gjallar
- secret exposure risk
- user decision needed

Verification commands/results:
```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/proxmox/test_inventory_adapter.py backend/tests/contracts/test_api_v1_inventory.py'
# Set 5 re-check: Ran 5 tests in 0.597s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/vm_create/test_draft_contract.py backend/tests/vm_create/test_preflight_plan_contract.py backend/tests/contracts/test_api_v1_vm_create.py'
# RED before production code: FAILED (failures=7), missing `app.vm_create` and `/api/v1/vm-create` routes
# GREEN after implementation: Ran 7 tests in 0.576s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/contracts/test_api_v1_shape.py backend/tests/manifests/test_profile_schema.py backend/tests/manifests/test_network_profile.py backend/tests/manifests/test_secret_redaction.py backend/tests/jobs/test_artifact_store.py backend/tests/jobs/test_job_models.py backend/tests/proxmox/test_inventory_adapter.py backend/tests/contracts/test_api_v1_inventory.py backend/tests/vm_create/test_draft_contract.py backend/tests/vm_create/test_preflight_plan_contract.py backend/tests/contracts/test_api_v1_vm_create.py'
# GREEN: Ran 23 tests in 0.562s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && git diff --check && git status --short --branch'
# PASS; status includes modified `backend/app/main.py` plus intentional untracked artifacts/tests/new backend packages including `backend/app/vm_create/`

ssh codex-vm 'cd /home/yoon/projects/Gjallar && backend/.venv/bin/python -m pytest backend/tests/vm_create -q'
# BLOCKED: No module named pytest
```

Reporting policy:
- every cron tick final response는 originating Discord thread로 전달한다.
- 상태 라벨: LOCK_WAIT / SET_START / SET_PROGRESS / SET_COMPLETE / BLOCKER / DECISION_REQUIRED / STALE_LOCK / NO_APPROVED_WORK
- `[SILENT]` 금지.

Lock policy:
- lock dir: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock`
- lock file: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json`
- acquire: atomic `mkdir`
- stale threshold: 일반 작업 90분, 긴 build/test는 2~3시간

Next Set candidate:
- Set 7: Review & Confirm / approval policy

Set 6 completion record:
- `/mnt/hermes_data/프로젝트/Gjallar/logs/2026-05-09_set6_create_draft_preflight_plan.md`
- Remote changed files include `backend/app/vm_create/`, `backend/app/api/v1/router.py`, `backend/tests/vm_create/test_preflight_plan_contract.py`, and `backend/tests/contracts/test_api_v1_vm_create.py`
- Remote synced shared-doc snapshot: `artifacts/rewrite-baseline/20260509-004801-KST/shared-docs-set6/`
- Repo status after Set 6: `## rewrite/prd-v1-mvp` with modified `backend/app/main.py` and intentional untracked artifacts/tests/new backend packages
- No commit/push/delete/apply/Proxmox write/VM create/power-on was run.

Remaining intentional RED / deferred tests:
- `backend/tests/vm_create/test_preflight_policy.py` remains Set 7 scope for approval-gate semantics.
- `backend/tests/contracts/test_jobs_risks_contract.py` remains later Jobs/Risks read API scope.
- `backend/tests/contracts/test_forbidden_mvp_endpoints.py` remains legacy cutover/hardening scope because legacy `/api` routers are still mounted.
- Frontend RED tests for Review Summary, risk policy, and Create VM defaults remain later frontend/UI scope.
- Backend pytest remains unavailable until dependency recovery.

Known risks/context:
- Backend pytest is still unavailable; use focused `unittest` fallback unless safe dependency recovery is performed.
- Approval gate code is intentionally not completed in Set 6; Set 7 owns red/yellow approval semantics and review checksum.
- Commit/push/delete/live side effects remain approval-gated.

## Set 7: Review & Confirm / approval policy

Status: planned
Goal:
- Set 6 dry-run plan output 위에 Review & Confirm 13개 항목, review summary checksum, and approval gate policy를 RED-first로 최소 GREEN 구현한다.

Scope:
- remote repo `codex-vm:/home/yoon/projects/Gjallar` branch `rewrite/prd-v1-mvp`
- focused backend RED tests for `app.vm_create.approval` and review summary/checksum behavior
- `backend/app/vm_create/approval.py` minimal policy helpers only
- Set 4 artifact substrate and Set 6 dry-run plan artifacts only

Out of scope:
- commit/push
- file/module deletion or large legacy removal
- Terraform/IaC live write or apply
- Proxmox create/update/delete/power action or VM create
- GitOps commit/push/apply execution
- frontend UI implementation
- non-Gjallar project changes

Dependencies:
- Set 6 completed
- Set 4 job/artifact substrate exists
- backend `.venv` can run `unittest`; `pytest` is still missing

Ordered task list:
- [ ] 1. Re-check repo status and Set 6 focused tests are GREEN
- [ ] 2. Run existing `backend/tests/vm_create/test_preflight_policy.py` RED and add focused RED tests for review summary/checksum/approval request before production code
- [ ] 3. Implement minimal `app.vm_create.approval.evaluate_approval_gate` for red/yellow/green policy
- [ ] 4. Implement review summary builder/checksum tied to real plan/review artifacts
- [ ] 5. Implement approval request validator that requires `plan_artifact_id` and matching `review_summary_checksum`; red risk blocks approval/execute; yellow risk requires ack
- [ ] 6. Ensure typed confirmation is not required for normal VM creation and no live execution method is exposed
- [ ] 7. Run focused `unittest`, `git diff --check`, record repo status, update CURRENT_STATE.md/TASKS.md/logs

Done criteria:
- [ ] Set 7 focused RED tests are observed before production code
- [ ] focused Set 7 tests pass with `PYTHONPATH=backend backend/.venv/bin/python -m unittest ...`
- [ ] Review & Confirm summary contains VM name, VMID, node, storage, template, CPU/RAM/Disk, network/IP, Terraform state path, first power on, smoke timeout summary, risk summary, plan artifact link, and planned Git diff summary
- [ ] review summary checksum is real SHA-256 of stored review summary artifact
- [ ] red risk cannot be approved/executed even with ack
- [ ] yellow risk requires explicit ack before approval
- [ ] green risk can approve but does not execute live side effects in Set 7
- [ ] no commit/push/delete/apply/Proxmox write/VM create/power-on
- [ ] Later-slice RED tests are listed once as intentional remaining RED
- [ ] `git diff --check` passes
- [ ] repo status/diff is recorded
- [ ] CURRENT_STATE.md and TASKS.md updated

Stop criteria:
- live Proxmox mutation would be required
- live IaC write/apply or Git commit/push would be required
- destructive deletion/removal would be required
- approval execution expands into Set 8 GitOps/apply without user approval
- same command/test failure repeats twice
- backend test dependency recovery becomes required but cannot be done non-destructively
- repo/docs path is not Gjallar
- secret exposure risk
- user decision needed

Verification commands:
```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && git status --short --branch && git diff --check'
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/vm_create/test_draft_contract.py backend/tests/vm_create/test_preflight_plan_contract.py backend/tests/contracts/test_api_v1_vm_create.py'
# Set 7 worker must add/run focused Set 7 unittest command after RED is written.
```

Reporting policy:
- every cron tick final response는 originating Discord thread로 전달한다.
- 상태 라벨: LOCK_WAIT / SET_START / SET_PROGRESS / SET_COMPLETE / BLOCKER / DECISION_REQUIRED / STALE_LOCK / NO_APPROVED_WORK
- `[SILENT]` 금지.

Lock policy:
- lock dir: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock`
- lock file: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json`
- acquire: atomic `mkdir`
- stale threshold: 일반 작업 90분, 긴 build/test는 2~3시간

Next Set candidate:
- Set 8: GitOps guard — live side-effect approval gate; do not start without explicit user approval

Known risks/context:
- Backend pytest is still unavailable; use focused `unittest` fallback unless safe dependency recovery is performed.
- Set 8 requires explicit user approval before live GitOps/apply/power-on side-effect work.
- Commit/push/delete/live side effects remain approval-gated.

## Later Set gates

- Set 1~2: inventory와 RED contract/schema tests까지만 우선 진행.
- Set 3~7: RED 확인 후 최소 GREEN 구현 가능.
- Set 8: GitOps allowlist/denylist와 fake/temp repo 테스트는 가능하지만 live commit/push/apply는 승인 전 금지.
- Set 9~10: 실제 VM 생성/power-on/smoke는 승인 전 금지.
- Set 12: legacy 삭제는 승인 전 금지. cron은 Park/disable 제안까지만 가능.
