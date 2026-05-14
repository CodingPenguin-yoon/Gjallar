# Jobs/Runs

평가일: 2026-05-13

검증 기준: coordinator가 backend `PYTHONPATH=backend backend/venv/bin/pytest -q backend/tests` -> 92 passed, frontend `for test_file in frontend/tests/*.mjs; do node "$test_file"; done` -> passed, `pnpm --dir frontend lint` -> passed, `pnpm --dir frontend build` -> passed를 기록했다.

## 구현 수준

현재 Jobs/Runs는 read-only file-backed job/artifact inspection 화면이다. Create VM oriented progress와 artifacts는 구현되어 있지만, DRS migration job model은 아직 1급 구현이 아니다.

## 구현 API/endpoints

- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/artifacts`

## 관련 파일

- Frontend: [frontend/src/components/TaskBoard.jsx](../../../frontend/src/components/TaskBoard.jsx), [frontend/src/utils/jobsScreen.js](../../../frontend/src/utils/jobsScreen.js), [frontend/src/utils/apiV1ViewModels.js](../../../frontend/src/utils/apiV1ViewModels.js), [frontend/src/services/apiV1.js](../../../frontend/src/services/apiV1.js)
- Backend: [backend/app/api/v1/router.py](../../../backend/app/api/v1/router.py), [backend/app/jobs/runs.py](../../../backend/app/jobs/runs.py), [backend/app/jobs/artifacts.py](../../../backend/app/jobs/artifacts.py), [backend/app/jobs/models.py](../../../backend/app/jobs/models.py)
- Tests: [frontend/tests/jobsScreen.test.mjs](../../../frontend/tests/jobsScreen.test.mjs), [backend/tests/contracts/test_jobs_risks_contract.py](../../../backend/tests/contracts/test_jobs_risks_contract.py), [backend/tests/jobs/test_runs.py](../../../backend/tests/jobs/test_runs.py), [backend/tests/jobs/test_artifact_store.py](../../../backend/tests/jobs/test_artifact_store.py), [backend/tests/jobs/test_job_models.py](../../../backend/tests/jobs/test_job_models.py)

## 현재 구현

backend는 `GJALLAR_RUNS_ROOT` 아래 job status와 artifacts를 file-backed로 저장하고, summary와 artifact metadata를 read-only로 반환한다. Create VM draft/preflight/plan/approval/commit/apply 단계가 job progress로 기록된다.

frontend는 job list, selected job detail, progress steps, artifact links를 보여준다. retry, cancel, live-run, VM mutation control은 없다.

## DRS Advisor 기준 gaps

[DRS UI/flow 목표](../../product/drs-advisor/02_UI_AND_FLOWS.md) 대비 `drs_migration` job_type, recommendation_id, VM locator, identity assertion id, source/target node, approver, UPID, lock id/status, timeout_at, post-check result가 없다.

`needs_reconciliation`, migration timeout, Proxmox task polling/log artifact, Reconcile Now action도 없다.

## 리스크/메모

현재 Jobs/Runs는 Create VM 기록 확인에는 유효하지만 DRS migration 운영 기록으로는 부족하다. 특히 Proxmox task success만으로 migration success를 결정하면 안 되고, target node/running/fingerprint post-check가 필요하다.

## 다음 구현 slice

read-only DRS job schema를 먼저 확장한다. `drs_migration` summary, UPID field, lock status, timeout status, final-precheck artifact link를 표시하되 Reconcile Now mutation은 후속 slice로 분리한다.
