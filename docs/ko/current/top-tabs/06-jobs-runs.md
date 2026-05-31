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

각 job은 `job_runs` 최신 상태 row로 표현됩니다. `record_job_run()`은 status, stage, progress, artifacts, risks, redacted details를 씁니다. Artifact content와 metadata는 `job_artifacts`에 저장되고, Artifact API는 file content가 아니라 id/type/checksum/storage backend/created time 같은 metadata를 반환합니다. UI는 로컬 파일 경로를 노출하지 않습니다.

현재 Create VM stage는 `draft`, `preflight`, `plan`, `approval`, `create`입니다.

## 현재 하지 않는 일

Jobs/Runs UI에는 retry, cancel, resume, approve, live-run, VM mutation control이 없습니다. 현재 job store는 immutable append-only audit log가 아니라 latest-state persistence입니다.

## Target gap

Current backend에는 DRS local approval/job intent, `drs_migration` execution evidence, UPID/post-check/reconciliation preview evidence, 그리고 Goal 8 `post_create_readiness` job/artifact evidence가 있습니다. 남은 gap은 broad DRS UI, corrective/background reconciliation, live DRS smoke evidence, 그리고 Jobs/Runs에서의 더 풍부한 DRS 운영 표시입니다.
