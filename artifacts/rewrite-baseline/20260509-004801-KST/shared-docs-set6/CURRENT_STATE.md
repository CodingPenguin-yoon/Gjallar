# CURRENT_STATE

Last updated: 2026-05-09 03:05 KST
Project: Gjallar
Thread ownership: 이 Discord thread/session은 Gjallar만 관리한다.
Repo: codex-vm:/home/yoon/projects/Gjallar
Shared docs: /mnt/hermes_data/프로젝트/Gjallar

## Current Work

Cron mode: active_set_runner
Current Set: Set 7 - Review & Confirm / approval policy
Set status: planned
Stage: Set 6 complete / Set 7 ready for next worker tick
Progress summary: Set 6 completed RED-first non-destructive `app.vm_create` draft/preflight/plan helpers, `/api/v1/vm-create` dry-run route surface, real artifact-backed plan output, and fake/read-only inventory preflight checks. Set 7 is promoted as the next documented non-destructive approval-policy Set; Set 8 live GitOps/apply remains approval-gated.
Last progress at: 2026-05-09 03:05 KST

## Lock / Safety

Lock status: none after Set 6 release
Lock path: /mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json
Lock owner: none
Blocker: backend pytest dependency still missing for the pytest command; Set 7 may use verified unittest fallback but must not claim full pytest GREEN until dependency recovery is verified
Decision required: none for Set 7 non-destructive TDD work; commit/push/delete/apply/Proxmox write/VM create/power-on require explicit approval. Set 8+ live side-effect gate requires explicit user approval.

## Cron Jobs

Worker cron: 70d963726132 — Gjallar PRD rewrite Set-runner worker — every 10m — deliver=origin
Heartbeat lane: systemd user timer `gjallar-heartbeat.timer` — every 5m — direct Discord bot send to this thread — verified message_id `1502348136914485409`
Paused built-in heartbeat cron: 6fe5fc477ae6, because Hermes cron heartbeat is serialized behind worker and was not user-visible

## Next Action

Next action: next worker re-checks Set 6 focused GREEN tests, then runs existing `backend/tests/vm_create/test_preflight_policy.py` RED and adds focused RED tests for review summary/checksum/approval request before production code.
Next tick should: heartbeat report, worker start Set 7
Verification status: Set 6 complete; `git diff --check` pass; Set 3+4+5+6 focused unittest pass; backend pytest command still blocked by missing pytest
Touched areas: TASKS.md, CURRENT_STATE.md, logs/2026-05-09_set6_create_draft_preflight_plan.md, remote new `backend/app/vm_create/`, remote new `backend/tests/vm_create/test_preflight_plan_contract.py`, remote new `backend/tests/contracts/test_api_v1_vm_create.py`, remote changed `/api/v1` router; existing Set 0~5 artifacts/tests remain untracked and intentional
