# Goal Documents

## Purpose

Use this directory as the next-session entry point for goal-sized Gjallar work.
For DRS work, prefer the newest standalone goal brief over older planning
sections.

## Current DRS Goal State

Completed:

- DRS safe execution readiness foundation:
  `docs/goal/drs-safe-execution-readiness-foundation.md`
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
