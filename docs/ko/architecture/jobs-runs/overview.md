# Jobs / Runs Architecture

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Jobs/Runs architecture](../../../architecture/jobs-runs/overview.md), [Jobs/Runs snapshot](../../../current/top-tabs/06-jobs-runs.md), [Current implemented state](../../../current/README.md).

Jobs/Runs는 `/jobs` route의 read-only UI입니다. DB-backed job status와 artifact metadata를 보여줍니다.

## Current route and implementation

| Concern | Current implementation |
|---|---|
| Route | `/jobs` |
| Component | [TaskBoard.jsx](../../../../frontend/src/components/TaskBoard.jsx) |
| View model | [jobsScreen.js](../../../../frontend/src/utils/jobsScreen.js), `buildJobsViewModel()` |
| Backend helpers | [backend/app/jobs](../../../../backend/app/jobs) |
| Storage | `GJALLAR_DATABASE_URL`의 `job_runs`, `job_artifacts` tables |
| Mutation controls | None in Jobs/Runs UI |

## APIs

`GET /api/v1/jobs`는 list, `GET /api/v1/jobs/{job_id}`는 selected detail, `GET /api/v1/jobs/{job_id}/artifacts`는 artifact metadata를 반환합니다.

## Job status record

각 job은 `job_runs` 최신 상태 row로 표현됩니다. Artifact content와 metadata는 `job_artifacts`에 저장되고, reference는 `db://job-artifacts/<artifact_id>` 형태입니다. Fields include job id/type/status, target, risk level, timestamps, current stage, message, progress, steps, artifacts, risks, redacted details.

Create VM current stages are `draft`, `preflight`, `plan`, `approval`, `create`.

## Current DRS jobs

Current DRS backend records `drs_migration` job state with recommendation evidence, approval packet/job intent, final-precheck, operation-lock, migration, UPID/task polling, post-check, and read-only reconciliation evidence. Jobs/Runs UI remains read-only and still lacks retry/cancel/live execute/corrective reconcile controls.
