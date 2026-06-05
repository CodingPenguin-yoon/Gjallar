# Operations / Jobs

평가일: 2026-06-03

검증 기준: 2026-06-03에 focused Jobs/Runs DRS evidence validation `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs/test_execution.py backend/tests/jobs/test_runs.py backend/tests/contracts/test_api_v1_drs.py`가 `59 passed, 33 subtests passed`, frontend validation `node --test frontend/tests/jobsScreen.test.mjs frontend/tests/apiV1Client.test.mjs frontend/tests/apiV1ViewModels.test.mjs`가 `3 passed`, and `pnpm --dir frontend lint`, `pnpm --dir frontend build`, `git diff --check`가 통과했다.

## 구현 수준

현재 Operations / Jobs는 canonical `/operations/jobs` route의 read-only DB-backed job/artifact inspection 화면이며, legacy `/jobs` deep link도 같은 화면을 렌더링한다. Create VM progress/artifacts, VM Instances `vm_start` job evidence, DRS `drs_migration` job evidence, and local-only `post_create_readiness` evidence jobs가 구현되어 있다.

## 구현 API/endpoints

- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/artifacts`

## 관련 파일

- Frontend: [frontend/src/components/TaskBoard.jsx](../../../frontend/src/components/TaskBoard.jsx), [frontend/src/utils/jobsScreen.js](../../../frontend/src/utils/jobsScreen.js), [frontend/src/utils/apiV1ViewModels.js](../../../frontend/src/utils/apiV1ViewModels.js), [frontend/src/services/apiV1.js](../../../frontend/src/services/apiV1.js)
- Backend: [backend/app/api/v1/router.py](../../../backend/app/api/v1/router.py), [backend/app/jobs/runs.py](../../../backend/app/jobs/runs.py), [backend/app/jobs/artifacts.py](../../../backend/app/jobs/artifacts.py), [backend/app/jobs/models.py](../../../backend/app/jobs/models.py)
- Tests: [frontend/tests/jobsScreen.test.mjs](../../../frontend/tests/jobsScreen.test.mjs), [backend/tests/contracts/test_jobs_risks_contract.py](../../../backend/tests/contracts/test_jobs_risks_contract.py), [backend/tests/jobs/test_runs.py](../../../backend/tests/jobs/test_runs.py), [backend/tests/jobs/test_artifact_store.py](../../../backend/tests/jobs/test_artifact_store.py), [backend/tests/jobs/test_job_models.py](../../../backend/tests/jobs/test_job_models.py)

## 현재 구현

backend는 `job_runs`와 `job_artifacts` 테이블에 job status와 artifacts를 저장하고, summary와 artifact metadata를 read-only로 반환한다. Artifact reference는 `db://job-artifacts/<artifact_id>` 형태이며 UI는 로컬 파일 경로를 노출하지 않는다. Create VM draft/preflight/plan/approval/create 단계, VM Instances VM start `precheck/start/task_poll/post_check` 단계, and DRS migration `recommendation/final_precheck/approval/job_intent/operation_lock/migration/task_poll/post_check/reconciliation` 단계가 job progress로 기록된다. DRS execute acknowledgement failures are request validation errors; they do not create operation locks, do not call the DRS migration client, and do not change a pending `drs_migration` job to `blocked`.

DRS `job_runs.details` now includes compact `drs_evidence` for operator inspection: approval packet/status, recommendation/VM identity, source/target, approved/executed actor, execution acknowledgement evidence when present, final pre-check blockers/check statuses/criteria taxonomy, live pre-check summary, historical UPID/task/status/exitstatus/log excerpt, side effects as historical evidence, operation lock ids/records/scopes/statuses, post-check expected/observed/fingerprint evidence, and reconciliation reason/events/resolved events. It is explicitly `read_only=true`, `allowed_actions=[]`, and `current_mutation_controls=[]`.

`vm_start` jobs는 `vm_start_observed_after.json` artifact를 남긴다. Artifact에는 observed-before inventory, target node/VMID/name, idempotency key, Proxmox start UPID/task poll result, observed-after status, redacted connection context가 포함된다.

`post_create_readiness` jobs는 operator-supplied sanitized evidence만 기록한다. Artifact type은 `post_create_readiness_evidence`이며 endpoint result는 `side_effects=[]`, `proxmox_mutation_enabled=false`, `live_checks_performed_by_gjallar=false`, and `allowed_actions=[]`를 유지한다. Operations/Jobs UI에는 이 job을 실행하거나 재실행하는 control이 없다.

frontend는 job list, selected job detail, progress steps, artifact metadata를 보여준다. DRS jobs render artifact metadata type/id/checksum/storage backend/size but not artifact payloads or local paths. retry, cancel, live-run, reconcile, cleanup, reverse migration, or VM mutation controls are absent.

## DRS Advisor 기준 gaps

[DRS UI/flow 목표](../../product/drs-advisor/02_UI_AND_FLOWS.md) 대비 backend는 `drs_migration` job_type, recommendation id, VM locator, identity id, source/target node, approver, UPID, lock id/status, timeout/post-check/reconciliation evidence를 저장한다. Approved VMID `140` live DRS smoke evidence도 기록됐다. Operations/Jobs now has the first richer read-only DRS evidence panel. 남은 gap은 broader DRS operations UI polish, corrective reconciliation mutation/action, and background reconciliation automation이다.

## 리스크/메모

DRS migration success는 Proxmox task success만으로 결정하지 않는다. Completed status requires task `OK` plus direct target-node status/config post-check, expected power-state evidence, matching fingerprint, and no conflicting active task. Ambiguous evidence remains `needs_reconciliation`. Missing or malformed `drs_live_migration_acknowledged=true` never becomes a job-state transition.

## 다음 구현

Goal Check 01-06, Goal 7 DRS UI/operations polish, and Goal 7.5 DRS VM Policy
Configuration, Goal 8, and Goal 9 are complete. 현재 순서는
[`docs/goal/README.md`](../../goal/README.md)를 기준으로 본다. Goal 10
safety baseline and approved VMID `140` live evidence are complete.
Goal 11 is rewritten as DRS Criteria And Operations Productization, and Goal 12
is superseded. Backend read-only Reconcile preview and stored-UPID local
follow-up exist, but corrective reconciliation mutation and broad UI action
remain deferred.
