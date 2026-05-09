# CURRENT_STATE

Last updated: 2026-05-09 02:17 KST
Project: Gjallar
Thread ownership: 이 Discord thread/session은 Gjallar만 관리한다.
Repo: codex-vm:/home/yoon/projects/Gjallar
Shared docs: /mnt/hermes_data/프로젝트/Gjallar

## Current Work

Cron mode: active_set_runner
Current Set: Set 5 - Read-only Proxmox inventory adapter
Set status: planned
Stage: Set 4 complete / Set 5 ready for next worker tick
Progress summary: Set 4 completed the minimum `app.jobs` substrate with RED-first focused tests, real file-backed JSON/text artifacts, SHA-256 checksums, approval metadata, and secret-safe artifact serialization. Set 5 is promoted as the next documented non-destructive read-only adapter Set.
Last progress at: 2026-05-09 02:17 KST

## Lock / Safety

Lock status: none after Set 4 release
Lock path: /mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json
Lock owner: none
Blocker: backend pytest dependency still missing for the pytest command; Set 5 may use verified unittest fallback but must not claim full pytest GREEN until dependency recovery is verified
Decision required: none for Set 5 non-destructive read-only TDD work; commit/push/delete/apply/Proxmox write/power-on require explicit approval

## Cron Jobs

Worker cron: 70d963726132 — Gjallar PRD rewrite Set-runner worker — every 10m — deliver=origin
Heartbeat lane: systemd user timer `gjallar-heartbeat.timer` — every 5m — direct Discord bot send to this thread — verified message_id `1502348136914485409`
Paused built-in heartbeat cron: 6fe5fc477ae6, because Hermes cron heartbeat is serialized behind worker and was not user-visible

## Next Action

Next action: next worker starts Set 5 by re-checking Set 4 focused GREEN tests, then writing focused RED tests for read-only Proxmox inventory adapter models/API shape before any production code.
Next tick should: heartbeat report, worker start Set 5
Verification status: Set 4 complete; `git diff --check` pass; Set 3+4 focused unittest pass; backend pytest command still blocked by missing pytest
Touched areas: TASKS.md, CURRENT_STATE.md, README.md, logs/2026-05-09_set4_job_artifact_substrate.md, remote new `backend/app/jobs/`, remote new `backend/tests/jobs/`, remote `artifacts/rewrite-baseline/20260509-004801-KST/shared-docs-set4/`; existing Set 0~3 artifacts/tests remain untracked and intentional
