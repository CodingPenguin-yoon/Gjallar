# Jobs / Runs Architecture

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Jobs/Runs](../../current/top-tabs/06-jobs-runs.md).

Jobs/Runs is the `/jobs` route. It is a read-only UI over DB-backed job status and artifact metadata.

## Current Route And Component

| Concern | Current implementation |
|---|---|
| Route | `/jobs` |
| Component | `frontend/src/components/TaskBoard.jsx` |
| View model | `frontend/src/utils/jobsScreen.js` and `buildJobsViewModel()` |
| Backend helpers | `backend/app/jobs/runs.py`, `backend/app/jobs/artifacts.py`, `backend/app/jobs/models.py` |
| Storage | `job_runs` and `job_artifacts` tables through `GJALLAR_DATABASE_URL` |
| Mutation controls | None in Jobs/Runs UI |

## Current APIs

| API | Purpose |
|---|---|
| `GET /api/v1/jobs` | List read-only job summaries. |
| `GET /api/v1/jobs/{job_id}` | Read one job summary. |
| `GET /api/v1/jobs/{job_id}/artifacts` | Read artifact metadata for one job. |

The UI has no retry, cancel, resume, approve, or mutation controls.

## Job Status Record

Each job is represented by the latest `job_runs` row. Artifact payloads and
metadata are stored in `job_artifacts`; artifact references use
`db://job-artifacts/<artifact_id>` rather than host file paths.

`record_job_run()` writes:

| Field | Current meaning |
|---|---|
| `job_id` | Operator/UI/API supplied job id. |
| `job_type` | Current Create VM jobs use `vm_create`; Infra Explorer start jobs use `vm_start`. |
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

## Current Step Models

`backend/app/jobs/runs.py` chooses stages by `job_type`. Existing `vm_create` output keeps these stages:

| Stage | Label | Current Create VM use |
|---|---|---|
| `draft` | Request input | Draft created. |
| `preflight` | Preflight | Read-only checks complete or block. |
| `plan` | Create plan | Artifacts and review packet created. |
| `approval` | Approval check | Review metadata accepted or blocked. |
| `create` | VM create | Native Proxmox create running/completed/failed. |

Earlier stages are marked completed when a later stage is recorded.

`vm_start` jobs use a shorter stage list:

| Stage | Label | Current VM start use |
|---|---|---|
| `precheck` | Start precheck | Fresh inventory locator/status/template checks. |
| `start` | VM start request | Proxmox QEMU start request. |
| `task_poll` | Proxmox task check | UPID polling and exitstatus validation. |
| `post_check` | Post-start check | `/status/current` observed-after running check. |

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
| `vm_start_observed_after` | `run_vm_start()` |
| `job_status` | `record_job_run()` |

Artifact APIs return metadata such as id, type, checksum, storage backend, size, and creation time. They do not stream artifact contents or expose local filesystem paths in the UI.

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
| Legacy manifest commit API | `pending`; not part of the primary Create VM step model. |
| Native create starts | `running`, stage `create`. |
| Native create succeeds | `completed`, stage `create`. |
| Native create fails/uncertain | `failed`, stage `create`, step status `apply_failed` or `needs_reconciliation`. |

## VM Start Job Updates

| VM start event | Job status/stage |
|---|---|
| Missing acknowledgement or idempotency key | Request is rejected before job creation. |
| Missing/moved/template/non-stopped target | `blocked`, stage `precheck`, no Proxmox mutation. |
| Proxmox start submitted | `running`, stage `task_poll`. |
| Task exitstatus not OK | `failed`, stage `task_poll`, artifact written. |
| Post-check not running | `failed`, stage `post_check`, artifact written. |
| Task OK and observed running | `completed`, stage `post_check`, artifact written. |

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
