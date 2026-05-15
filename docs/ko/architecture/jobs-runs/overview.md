# Jobs / Runs Architecture

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Jobs/Runs architecture](../../../architecture/jobs-runs/overview.md), [Jobs/Runs snapshot](../../../current/top-tabs/06-jobs-runs.md), [Current implemented state](../../../current/README.md).

Jobs/Runs는 `/jobs` route의 read-only UI입니다. File-backed job status와 artifact metadata를 보여줍니다.

## Current route and implementation

| Concern | Current implementation |
|---|---|
| Route | `/jobs` |
| Component | [TaskBoard.jsx](../../../../frontend/src/components/TaskBoard.jsx) |
| View model | [jobsScreen.js](../../../../frontend/src/utils/jobsScreen.js), `buildJobsViewModel()` |
| Backend helpers | [backend/app/jobs](../../../../backend/app/jobs) |
| Storage | `GJALLAR_RUNS_ROOT` 또는 temp fallback |
| Mutation controls | None in Jobs/Runs UI |

## APIs

`GET /api/v1/jobs`는 list, `GET /api/v1/jobs/{job_id}`는 selected detail, `GET /api/v1/jobs/{job_id}/artifacts`는 artifact metadata를 반환합니다.

## Job status file

각 job은 `GJALLAR_RUNS_ROOT/<safe_job_id>/job_status.json` 최신 상태 파일로 표현됩니다. Fields include job id/type/status, target, risk level, timestamps, current stage, message, progress, steps, artifacts, risks, redacted details.

Create VM current stages are `draft`, `preflight`, `plan`, `approval`, `workspace`, `commit`, `create`.

## Target DRS jobs

Future DRS should add `drs_recommendation`, `drs_final_precheck`, `drs_migration`, `drs_reconciliation` job types, with recommendation, approval, final-precheck, UPID/task polling, post-check, reconciliation artifacts.
