# Jobs / Runs Architecture

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Jobs/Runs](../../current/top-tabs/06-jobs-runs.md).

Jobs/Runs is the `/jobs` route. It is a read-only UI over file-backed job status and artifact metadata.

## Current Route And Component

| Concern | Current implementation |
|---|---|
| Route | `/jobs` |
| Component | `frontend/src/components/TaskBoard.jsx` |
| View model | `frontend/src/utils/jobsScreen.js` and `buildJobsViewModel()` |
| Backend helpers | `backend/app/jobs/runs.py`, `backend/app/jobs/artifacts.py`, `backend/app/jobs/models.py` |
| Storage | `GJALLAR_RUNS_ROOT` or temp fallback `gjallar-set6-api-preview` |
| Mutation controls | None in Jobs/Runs UI |

## Current APIs

| API | Purpose |
|---|---|
| `GET /api/v1/jobs` | List read-only job summaries. |
| `GET /api/v1/jobs/{job_id}` | Read one job summary. |
| `GET /api/v1/jobs/{job_id}/artifacts` | Read artifact metadata for one job. |

The UI has no retry, cancel, resume, approve, or mutation controls.

## Job Status File

Each job is represented by the latest status file:

```text
GJALLAR_RUNS_ROOT/<safe_job_id>/job_status.json
```

`record_job_run()` writes:

| Field | Current meaning |
|---|---|
| `job_id` | Operator/UI/API supplied job id. |
| `job_type` | Current Create VM jobs use `vm_create`. |
| `status` | `in_progress`, `pending`, `running`, `completed`, `blocked`, `failed`, etc. |
| `target_id` | Current target label, usually `<node>:<vm_name>`. |
| `risk_level` | Risk level from preflight/plan or `unknown`. |
| `started_at`, `finished_at`, `updated_at` | Timestamps. |
| `current_stage` | Current stage id. |
| `message` | Human-readable latest message. |
| `progress_percent` | Derived from step status. |
| `steps` | Ordered stage progress. |
| `artifacts` | Artifact metadata, including a `job_status` artifact. |
| `risks` | Current job risk list. |
| `details` | Redacted extra details. |

This is latest-state persistence, not an immutable append-only audit log.

## Current Step Model

`backend/app/jobs/runs.py` defines these stages:

| Stage | Label | Current Create VM use |
|---|---|---|
| `draft` | Request input | Draft created. |
| `preflight` | Preflight | Read-only checks complete or block. |
| `plan` | Create plan | Artifacts and review packet created. |
| `approval` | Approval check | Review metadata accepted or blocked. |
| `workspace` | Create preparation | Native preview preparation. |
| `commit` | Request saved | VMInstance manifest committed or archived. |
| `create` | VM create | Native Proxmox create running/completed/failed. |

Earlier stages are marked completed when a later stage is recorded.

## Artifacts

Current Create VM jobs can publish:

| Artifact type | Producer |
|---|---|
| `preflight_report` | `build_vm_create_plan()` |
| `plan` | `build_vm_create_plan()` |
| `vm_instance_manifest` | `build_vm_create_plan()` |
| `planned_git_diff` | `build_vm_create_plan()` |
| `review_summary` | `build_vm_create_plan()` |
| `proxmox_create_preview` | `build_proxmox_create_preview()` |
| `observed_after` | `run_proxmox_create()` |
| `job_status` | `record_job_run()` |

Artifact APIs return metadata such as id, type, path, checksum, and creation time. They do not stream the file contents.

## Create VM Job Updates

| Create VM event | Job status/stage |
|---|---|
| Draft | `in_progress`, stage `draft`. |
| Red preflight | `blocked`, stage `preflight`. |
| Non-red preflight | `in_progress`, stage `preflight`. |
| Plan red risk | `blocked`, stage `plan`. |
| Plan non-red | `in_progress`, stage `plan`. |
| Approval valid | `in_progress`, stage `approval`. |
| Approval invalid | `blocked`, stage `approval`. |
| Manifest commit | `pending`, stage `commit`. |
| Native create starts | `running`, stage `create`. |
| Native create succeeds | `completed`, stage `create`. |
| Native create fails/uncertain | `failed`, stage `create`, step status `apply_failed` or `needs_reconciliation`. |

## UI Behavior

| UI area | Current behavior |
|---|---|
| Summary cards | Total, running, completed, blocked, failed. |
| Search | Filters by id, type, status, target, risk. |
| Job cards | Status, target, risk, artifact count, timestamps. |
| Selected panel | Current message, fields, progress steps, artifact metadata. |
| Auto-refresh | Polls every 2.5 seconds while selected job is live. |

## Target DRS Jobs

Future DRS should add first-class job types such as `drs_recommendation`, `drs_final_precheck`, `drs_migration`, and `drs_reconciliation`.

Those jobs should include:

- recommendation evidence artifact
- approval artifact
- final pre-check artifact
- migration UPID/task polling artifact
- post-check artifact
- reconciliation artifact when needed

No current DRS migration job model exists.
