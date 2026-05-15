# Jobs/Runs

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Jobs/Runs snapshot](../../../current/top-tabs/06-jobs-runs.md), [영어 Jobs/Runs architecture](../../../architecture/jobs-runs/overview.md), [Current implemented state](../../../current/README.md).

Jobs/Runs는 `/jobs` route의 read-only job/artifact inspection 화면입니다. 목적은 Create VM 같은 작업의 최신 상태와 artifact metadata를 운영자가 확인하게 하는 것입니다.

## 사용하는 API와 호출 위치

| API | 하는 일 | Frontend 호출 |
|---|---|---|
| `GET /api/v1/jobs` | job summaries list | [frontend/src/components/TaskBoard.jsx](../../../../frontend/src/components/TaskBoard.jsx), [jobsScreen.js](../../../../frontend/src/utils/jobsScreen.js) |
| `GET /api/v1/jobs/{job_id}` | selected job detail | same |
| `GET /api/v1/jobs/{job_id}/artifacts` | artifact metadata | same |

Backend는 [backend/app/jobs/runs.py](../../../../backend/app/jobs/runs.py), [backend/app/jobs/artifacts.py](../../../../backend/app/jobs/artifacts.py), [backend/app/jobs/models.py](../../../../backend/app/jobs/models.py)를 사용합니다.

## 구현 방식

각 job은 `GJALLAR_RUNS_ROOT/<safe_job_id>/job_status.json` 최신 상태 파일로 표현됩니다. `record_job_run()`은 status, stage, progress, artifacts, risks, redacted details를 씁니다. Artifact API는 file content가 아니라 id/type/path/checksum/created time 같은 metadata를 반환합니다.

현재 Create VM stage는 `draft`, `preflight`, `plan`, `approval`, `workspace`, `commit`, `create`입니다.

## 현재 하지 않는 일

Jobs/Runs UI에는 retry, cancel, resume, approve, live-run, VM mutation control이 없습니다. 현재 job store는 immutable append-only audit log가 아니라 latest-state persistence입니다.

## Target gap

DRS Advisor에는 `drs_migration`, `drs_final_precheck`, `drs_reconciliation` 같은 first-class job type, recommendation id, VM locator, source/target node, UPID, lock status, timeout, post-check, reconciliation artifact가 필요합니다.
