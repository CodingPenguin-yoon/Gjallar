# Goal Documents

## Purpose

Use this file as the next-session entry point for goal-sized Gjallar work.
It is the canonical map from goal number to controlling document, status, and
next action.

Do not infer a second goal sequence from standalone files. The active backlog
has Goal 1 through Goal 9 only, as listed below.

## Document Roles

- `docs/goal/README.md`: canonical goal map and next-session prompt.
- `docs/goal/remaining-operations-work.md`: full operations backlog containing
  Goal 1 through Goal 9.
- `docs/goal/drs-execution-goal-slices.md`: DRS execution sub-index for Goal 3
  through Goal 7 details.
- `docs/goal/drs-goal-*.md`: standalone detailed briefs for later DRS goals
  when the brief was split out.
- `docs/goal/operations-console-stabilization.md`: completed historical goal
  brief. Do not treat it as the active next goal unless the user explicitly
  reopens that workstream.

There are intentionally no standalone `drs-goal-1`, `drs-goal-2`, or
`drs-goal-3` files. Use the canonical map below for those goals.

## Canonical Goal Map

| Goal | Status | Controlling document | Notes |
| --- | --- | --- | --- |
| Goal 1: Create VM Live Smoke Matrix | Completed | `docs/goal/remaining-operations-work.md` | Evidence recorded in `docs/operations/create-vm-live-smoke-2026-05-28.md`. |
| Goal 2: DRS Identity And Final Pre-Check Preparation | Completed | `docs/goal/drs-safe-execution-readiness-foundation.md` | DRS remained read-only; no live migration. |
| Goal 3: DRS Final Pre-Check And Operation Lock Foundation | Completed | `docs/goal/drs-execution-goal-slices.md` | Operation lock lookup and read-only conflict evidence foundation. |
| Goal 4: DRS Approval And Migration Job Substrate | Completed | `docs/goal/drs-goal-4-approval-job-substrate.md` | Local approval/job substrate only; no Proxmox mutation. |
| Goal 5: DRS Live Migration Execution And UPID Tracking | Completed | `docs/goal/drs-goal-5-live-migration-upid.md` | Narrow backend execution path; no live DRS smoke run. |
| Goal 6: DRS Post-Check And Reconciliation | Completed | `docs/goal/drs-goal-6-post-check-reconciliation.md` | Verified post-check and read-only reconcile preview; no live DRS smoke run. |
| Goal 7: DRS UI And Operations Polish | Next | `docs/goal/drs-execution-goal-slices.md` | Expose lifecycle and blockers without weakening backend gates. |
| Goal 8: SSH/Ansible/App Bootstrap Readiness | Deferred | `docs/goal/remaining-operations-work.md` | Optional post-create confidence work, only after explicit direction. |
| Goal 9: Account/Session Operations Polish | Deferred | `docs/goal/remaining-operations-work.md` | Operational convenience around accounts/sessions. |

When a future session says "next goal", start with Goal 7 unless the user
explicitly chooses optional live DRS smoke, Goal 8, Goal 9, or another task.

## Current DRS Goal State

Completed:

- Goal 2 DRS safe execution readiness foundation:
  `docs/goal/drs-safe-execution-readiness-foundation.md`
- Goal 3 DRS final pre-check and operation lock foundation:
  `docs/goal/drs-execution-goal-slices.md`
- Goal 4 approval and migration job substrate:
  `docs/goal/drs-goal-4-approval-job-substrate.md`
- Goal 5 live migration execution and UPID tracking:
  `docs/goal/drs-goal-5-live-migration-upid.md`
- Goal 6 post-check and reconciliation:
  `docs/goal/drs-goal-6-post-check-reconciliation.md`

Next:

- Goal 7 DRS UI and operations polish:
  `docs/goal/drs-execution-goal-slices.md`
- Optional live DRS migration smoke evidence, only with explicit
  active-session approval.

Planning indexes:

- DRS goal sequence:
  `docs/goal/drs-execution-goal-slices.md`
- Broader operations backlog:
  `docs/goal/remaining-operations-work.md`

## Live Migration Test Target Guard

The approved Create VM smoke range remains the live-smoke candidate range:

- Static network: `192.168.2.140-150/24`
- Gateway: `192.168.2.1`
- Bridge used in the recorded smoke: `vmbr0`
- Evidence source:
  `docs/operations/create-vm-live-smoke-2026-05-28.md`

Use this range only to narrow candidate test VMs. It is not execution authority.
DRS migration must still require high-confidence VM identity/fingerprint,
current Proxmox locator, migration policy `allowed`, passing final pre-check,
valid approval, operation lock, verified post-check contract, and explicit
active-session user approval before any live Proxmox mutation.

Goal 6 validation was automated fake/mock validation. No live DRS migration
smoke has been run.

Do not treat IP, VMID, node, name, tags, or prior Create VM records alone as a
stable identity.

## Next Session Short Prompt

Use this prompt to continue DRS work in a new session:

```text
Use docs/goal/drs-execution-goal-slices.md as the controlling goal index.
Start Goal 7: DRS UI And Operations Polish, or prepare an explicitly approved
live DRS smoke run. Treat 192.168.2.140-150/24 as the live-smoke candidate
range only, not as execution authority, and do not run live Proxmox mutation
without explicit approval in this session.
```
