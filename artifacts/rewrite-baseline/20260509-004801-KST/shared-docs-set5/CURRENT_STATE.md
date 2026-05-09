# CURRENT_STATE

Last updated: 2026-05-09 02:42 KST
Project: Gjallar
Thread ownership: 이 Discord thread/session은 Gjallar만 관리한다.
Repo: codex-vm:/home/yoon/projects/Gjallar
Shared docs: /mnt/hermes_data/프로젝트/Gjallar

## Current Work

Cron mode: active_set_runner
Current Set: Set 6 - Create draft / preflight / plan
Set status: planned
Stage: Set 5 complete / Set 6 ready for next worker tick
Progress summary: Set 5 completed a RED-first fake/read-only Proxmox inventory adapter, `/api/v1` inventory payload wiring, `/api/v1/storage`, no-mutation adapter guard, and credentialed URL redaction regression fix. Set 6 is promoted as the next documented non-destructive draft/preflight/plan Set.
Last progress at: 2026-05-09 02:42 KST

## Lock / Safety

Lock status: none after Set 5 release
Lock path: /mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json
Lock owner: none
Blocker: backend pytest dependency still missing for the pytest command; Set 6 may use verified unittest fallback but must not claim full pytest GREEN until dependency recovery is verified
Decision required: none for Set 6 non-destructive TDD work; commit/push/delete/apply/Proxmox write/VM create/power-on require explicit approval

## Cron Jobs

Worker cron: 70d963726132 — Gjallar PRD rewrite Set-runner worker — every 10m — deliver=origin
Heartbeat lane: systemd user timer `gjallar-heartbeat.timer` — every 5m — direct Discord bot send to this thread — verified message_id `1502348136914485409`
Paused built-in heartbeat cron: 6fe5fc477ae6, because Hermes cron heartbeat is serialized behind worker and was not user-visible

## Next Action

Next action: next worker re-checks Set 5 focused GREEN tests, then writes/confirms focused RED tests for `app.vm_create` draft/preflight/plan before production code.
Next tick should: heartbeat report, worker start Set 6
Verification status: Set 5 complete; `git diff --check` pass; Set 3+4+5 focused unittest pass; backend pytest command still blocked by missing pytest
Touched areas: TASKS.md, CURRENT_STATE.md, README.md, logs/2026-05-09_set5_read_only_proxmox_inventory.md, remote new `backend/app/proxmox/`, remote new `backend/tests/proxmox/`, remote changed `/api/v1` router and `app.core.redaction`; existing Set 0~4 artifacts/tests remain untracked and intentional
