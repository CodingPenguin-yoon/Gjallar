# Goal Documents

## Canonical Entrypoint

This file is the canonical entrypoint for goal-sized Gjallar work. It is the
source of truth for the Goal 1 through Goal 9 map, document roles, status, and
next-session prompt.

Do not infer a second goal sequence from standalone files. Each goal has
exactly one detailed document, listed below.

## Document Roles

- `docs/goal/README.md`: canonical entrypoint, goal map, and next-session
  prompt.
- `docs/goal/remaining-operations-work.md`: concise overall operations
  backlog, status, validation, and risk overview only.
- `docs/goal/goal-01-create-vm-live-smoke-matrix.md` through
  `docs/goal/goal-09-account-session-operations-polish.md`: one detailed
  document per Goal 1 through Goal 9.
- `docs/goal/goal-check-01-06-implementation-quality.md`: non-numbered gate
  that verifies Goal 1 through Goal 6 implementation quality before Goal 7.

## Canonical Goal Map

| Goal | Status | Detailed document | Notes |
| --- | --- | --- | --- |
| Goal 1: Create VM Live Smoke Matrix | Completed | `docs/goal/goal-01-create-vm-live-smoke-matrix.md` | Evidence recorded in `docs/operations/create-vm-live-smoke-2026-05-28.md`. |
| Goal 2: DRS Identity And Final Pre-Check Preparation | Completed | `docs/goal/goal-02-drs-identity-final-precheck-preparation.md` | DRS remained read-only; no live migration. |
| Goal 3: DRS Final Pre-Check And Operation Lock Foundation | Completed | `docs/goal/goal-03-drs-final-precheck-operation-lock-foundation.md` | Operation lock lookup and read-only conflict evidence foundation. |
| Goal 4: DRS Approval And Migration Job Substrate | Completed | `docs/goal/goal-04-drs-approval-migration-job-substrate.md` | Local approval/job substrate only; no Proxmox mutation. |
| Goal 5: DRS Live Migration Execution And UPID Tracking | Completed | `docs/goal/goal-05-drs-live-migration-upid-tracking.md` | Narrow backend execution path; no live DRS smoke run. |
| Goal 6: DRS Post-Check And Reconciliation | Completed | `docs/goal/goal-06-drs-post-check-reconciliation.md` | Verified post-check and read-only Reconcile preview; no live DRS smoke run. |
| Goal Check: Goal 1-6 Implementation Verification And Quality Audit | Next | `docs/goal/goal-check-01-06-implementation-quality.md` | Non-numbered gate; verify Goal 1-6 are production-quality before Goal 7. |
| Goal 7: DRS UI And Operations Polish | Pending after Goal Check | `docs/goal/goal-07-drs-ui-operations-polish.md` | Expose lifecycle and blockers without weakening backend gates. |
| Goal 8: SSH/Ansible/App Bootstrap Readiness | Deferred | `docs/goal/goal-08-ssh-ansible-app-bootstrap-readiness.md` | Optional post-create confidence work, only after explicit direction. |
| Goal 9: Account/Session Operations Polish | Deferred | `docs/goal/goal-09-account-session-operations-polish.md` | Operational convenience around accounts/sessions. |

When a future session says "next goal", start with the non-numbered Goal Check
unless the user explicitly chooses optional live DRS smoke, Goal 8, Goal 9, or
another task. Goal 7 remains Goal 7, but it must not start until the Goal Check
is complete.

## DRS Safety Constraints

- no live Proxmox mutation/smoke without explicit active-session user approval
- 192.168.2.140-150/24 is candidate selection guard only
- VMID/IP/name/node/tag/Create VM history alone is not stable identity
- Proxmox task OK alone is not Gjallar success
- Keep DRS execution authority separate from Create VM mutation authority.
- DRS migration requires high-confidence VM identity/fingerprint, current
  Proxmox locator, migration policy `allowed`, passing final pre-check, valid
  approval, operation lock, verified post-check contract, and explicit
  active-session user approval before any live Proxmox mutation.

## Live Migration Test Target Guard

The approved Create VM smoke range remains the live-smoke candidate range:

- Static network: `192.168.2.140-150/24`
- Gateway: `192.168.2.1`
- Bridge used in the recorded smoke: `vmbr0`
- Evidence source:
  `docs/operations/create-vm-live-smoke-2026-05-28.md`

Goal 5 and Goal 6 validation used automated fake/mock validation. No live DRS
migration smoke has been run.

## Next Session Short Prompt

Use this prompt to continue DRS work in a new session:

```text
Use docs/goal/README.md as the canonical goal entrypoint.
Start the non-numbered Goal Check using docs/goal/goal-check-01-06-implementation-quality.md.
This is not Goal 7; Goal 7 remains DRS UI And Operations Polish and must not
start until the Goal Check is complete. Treat 192.168.2.140-150/24 as candidate
selection guard only, not execution authority, and do not run live Proxmox
mutation/smoke without explicit active-session user approval.
```
