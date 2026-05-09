# RUNBOOK

Last updated: 2026-05-09 01:26 KST

## Before work

1. Read common docs and this project root docs.
2. Confirm thread ownership is Gjallar only.
3. Confirm lock path and stale threshold.
4. Confirm remote repo through `codex-vm`.
5. Work only on the Current Set in `TASKS.md`.

## Cron operating mode

Worker:
- cadence: every 10m
- mode: Set-runner
- allowed mutation: Gjallar docs and Gjallar repo only, inside Current Set
- final response every tick with status label

Heartbeat:
- lane: systemd user timer `gjallar-heartbeat.timer` + service `gjallar-heartbeat.service`
- cadence: every 5m
- read-only only
- reads lock/CURRENT_STATE/TASKS via `/home/yoon/.hermes/project-lanes/bin/gjallar-heartbeat.py`
- delivery: direct Discord bot send to this Gjallar thread; verified at 2026-05-09 01:35 KST, message_id `1502348136914485409`
- never edits docs/repo/locks/scheduler
- old Hermes heartbeat cron `6fe5fc477ae6` is paused because Hermes cron jobs can serialize behind the worker

## Lock policy

- lock dir: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock`
- lock file: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json`
- acquire by atomic directory creation
- fresh lock: report `LOCK_WAIT`, no mutation
- uncertain stale lock: report `STALE_LOCK`, no forced recovery
- stale threshold: normal 90m; long build/test 2~3h

## Stop gates

Stop and report `DECISION_REQUIRED` or `BLOCKER` before:
- commit / push
- delete / destructive file removal
- Terraform apply / real IaC write
- Proxmox write / VM create / power-on
- red risk override
- secret exposure risk
- any non-Gjallar project change

## Verification commands

```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && git status --short --branch && git diff --check'
ssh codex-vm 'cd /home/yoon/projects/Gjallar && for f in frontend/tests/*.mjs; do node "$f" || exit 1; done'
ssh codex-vm 'cd /home/yoon/projects/Gjallar && backend/.venv/bin/python -m pytest backend/tests -q'
```

## Codex VM PRD access

- Current method: snapshot copy in repo artifact, because codex-vm does not have `/mnt/hermes_data/프로젝트/Gjallar/PRD` mounted.
- Latest snapshot path: `artifacts/rewrite-baseline/20260509-004801-KST/prd-snapshot/PRD/`.
- If Codex CLI workers need live PRD sync, configure and verify a read-only mount before relying on it.

## Cron job IDs

- Worker: 70d963726132 — Gjallar PRD rewrite Set-runner worker — every 10m — deliver=origin
- Heartbeat: systemd `gjallar-heartbeat.timer` — every 5m — direct Discord bot send; verified `1502348136914485409`
- Paused old Hermes heartbeat cron: 6fe5fc477ae6
