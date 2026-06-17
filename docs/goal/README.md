# Goal Documents

## Canonical Entrypoint

This file is the canonical entrypoint for goal-sized Gjallar work. It is the
source of truth for the Goal 1 through Goal 11 map, the inserted Goal 7.5,
document roles, status, and next-session prompt. Goal 10 safety baseline and the
approved VMID `140` live DRS smoke evidence are complete. The old Goal 11/12
split has been superseded by the rewritten Goal 11 DRS Criteria And Operations
Productization follow-on. Start future live mutation, cleanup, corrective action,
or broader work only if the user explicitly selects it.

Do not infer a second goal sequence from standalone files. Each goal has
exactly one detailed document, listed below.

## Document Roles

- `docs/goal/README.md`: canonical entrypoint, goal map, and next-session
  prompt.
- `docs/goal/remaining-operations-work.md`: concise overall operations
  backlog, status, validation, and risk overview only.
- `docs/goal/goal-01-create-vm-live-smoke-matrix.md` through
  `docs/goal/goal-11-drs-operations-productization.md`, plus
  `docs/goal/goal-07-5-drs-vm-policy-management.md`: one detailed document per
  current goal, including the inserted Goal 7.5. Goal 10 safety baseline and
  approved VMID `140` live evidence are complete. Goal 11 is the rewritten
  criteria/operations productization follow-on.
- `docs/goal/goal-12-platform-hardening-decision-quality.md`: historical
  superseded pointer only. Do not start it as an active goal.
- `docs/goal/goal-check-01-06-implementation-quality.md`: non-numbered gate
  that verifies Goal 1 through Goal 6 implementation quality before Goal 7.
- `docs/goal/goal-check-01-06-summary-ko.md`: Korean operator-readable summary
  of the completed Goal 1-6 implementation quality audit.
- `docs/goal/goal-check-current-implementation-validation.md`: completed
  non-numbered validation gate that established the code/docs/test baseline
  before Goal 9 polish.
- `docs/goal/docs-renewal/`: separate documentation-renewal workspace. This is
  not part of the numbered DRS/productization goal sequence and must not be
  treated as a new source of truth for implemented behavior; it only plans and
  tracks the documentation refactor.

## Canonical Goal Map

| Goal | Status | Detailed document | Notes |
| --- | --- | --- | --- |
| Goal 1: Create VM Live Smoke Matrix | Completed | `docs/goal/goal-01-create-vm-live-smoke-matrix.md` | Evidence recorded in `docs/operations/create-vm-live-smoke-2026-05-28.md`. |
| Goal 2: DRS Identity And Final Pre-Check Preparation | Completed | `docs/goal/goal-02-drs-identity-final-precheck-preparation.md` | DRS remained read-only; no live migration. |
| Goal 3: DRS Final Pre-Check And Operation Lock Foundation | Completed | `docs/goal/goal-03-drs-final-precheck-operation-lock-foundation.md` | Operation lock lookup and read-only conflict evidence foundation. |
| Goal 4: DRS Approval And Migration Job Substrate | Completed | `docs/goal/goal-04-drs-approval-migration-job-substrate.md` | Local approval/job substrate only; no Proxmox mutation. |
| Goal 5: DRS Live Migration Execution And UPID Tracking | Completed | `docs/goal/goal-05-drs-live-migration-upid-tracking.md` | Narrow backend execution path; no live DRS smoke run. |
| Goal 6: DRS Post-Check And Reconciliation | Completed | `docs/goal/goal-06-drs-post-check-reconciliation.md` | Verified post-check and read-only Reconcile preview; no live DRS smoke run. |
| Goal Check: Goal 1-6 Implementation Verification And Quality Audit | Completed | `docs/goal/goal-check-01-06-implementation-quality.md` / `docs/goal/goal-check-01-06-summary-ko.md` | Result: pass-with-risk; Goal 7 is unblocked. No live DRS smoke was run. |
| Goal 7: DRS UI And Operations Polish | Completed | `docs/goal/goal-07-drs-ui-operations-polish.md` | Minimal safe UI slice exposes lifecycle and blockers without weakening backend gates. |
| Goal 7.5: DRS VM Policy Configuration | Completed | `docs/goal/goal-07-5-drs-vm-policy-management.md` | Manual VM policy API/UI/audit slice is implemented. No live DRS smoke was run. |
| Goal 8: Post-Create Readiness Evidence | Completed | `docs/goal/goal-08-post-create-readiness-evidence.md` | Minimal local-only opt-in recorder is implemented for already-created VMs; Create VM success is unchanged; future live readiness checks remain deferred and require explicit active-session approval. |
| Goal Check: Current Implementation Validation Before Goal 9 | Completed | `docs/goal/goal-check-current-implementation-validation.md` | Result: pass-with-risk; no live DRS smoke was run. |
| Goal 9: Account/Session Operations Polish | Completed | `docs/goal/goal-09-account-session-operations-polish.md` | Admin local account operations, admin session inventory/revocation UI, self password change, and sanitized account/session audit metadata are implemented. |
| Goal 10: DRS Live Migration Safety And Evidence | Completed with approved VMID `140` live evidence | `docs/goal/goal-10-drs-live-migration-safety-evidence.md` | Execute acknowledgement gate, optional live smoke runbook/evidence matrix, approved live migration, verified post-check, stored-UPID reconciliation follow-up, and lock release are complete. Future live mutation/cleanup still requires separate explicit run approval. |
| Goal 11: DRS Criteria And Operations Productization | In progress; first criteria/taxonomy and Jobs/Runs evidence slices implemented | `docs/goal/goal-11-drs-operations-productization.md` | Supersedes the old Goal 11/12 split. Align DRS criteria, Advisor blocker taxonomy, UI operations workflow, and Jobs/Runs evidence without moving execution authority into the frontend. |
| Goal 12: Superseded Platform Hardening And Decision Quality Brief | Superseded | `docs/goal/goal-12-platform-hardening-decision-quality.md` | Historical pointer only; selected hardening slices now live inside the rewritten Goal 11 or a later newly defined goal. |

When a future session says "next goal", do not restart Goal 7.5, the minimal
Goal 8 recorder, Goal 9 polish, the Goal 10 safety baseline, or the approved
VMID `140` live DRS smoke. The next coherent goal-sized follow-on is the
rewritten Goal 11 unless the user selects a different task.
The Goal 1-6 implementation quality audit is complete with result
`pass-with-risk`; Goal 7, Goal 7.5, and the minimal local-only Goal 8 slice
are complete. That historical audit predated the later VMID `140` live DRS
smoke.
Goal 9 local account/session polish is complete: admin local account
operations, admin session inventory/revocation UI, self password change, and
sanitized account/session audit metadata are implemented. Disable and
reset-password revoke target sessions while role changes do not.
Goal 10 now has exact execute acknowledgement validation, a live smoke readiness
matrix, and approved VMID `140` live evidence recorded in
`docs/operations/drs-explicit-test-candidate-prep-2026-06-03.md`.

## DRS Safety Constraints

- no live Proxmox mutation, smoke, live readiness check, cleanup, corrective
  action, or reconciliation mutation without explicit active-session user
  approval for that specific run
- 192.168.2.140-150/24 is candidate selection guard only
- VMID/IP/name/node/tag/Create VM history alone is not stable identity
- Proxmox task OK alone is not Gjallar success
- Keep DRS execution authority separate from Create VM mutation authority.
- DRS migration requires high-confidence VM identity/fingerprint, current
  Proxmox locator, migration policy `allowed`, passing final pre-check, valid
  approval, exact `drs_live_migration_acknowledged=true`, operation lock,
  verified post-check contract, and explicit active-session user approval before
  any live Proxmox mutation.

## Live Migration Test Target Guard

The approved Create VM smoke range remains the live-smoke candidate range:

- Static network: `192.168.2.140-150/24`
- Gateway: `192.168.2.1`
- Bridge used in the recorded smoke: `vmbr0`
- Evidence source:
  `docs/operations/create-vm-live-smoke-2026-05-28.md`

Goal 5, Goal 6, and the Goal 10 safety baseline used automated fake/mock
validation. The later approved Goal 10 live smoke moved VMID `140` from
`yoonmanserver` to `yoonserver3`, recorded Proxmox task `OK`, verified Gjallar
post-check after parser normalization, completed stored-UPID reconciliation, and
released operation locks.

## Current DRS Gap Summary

- Narrow backend DRS execute exists.
- Broad live execute UI remains a gap.
- Corrective reconcile UI and corrective reconciliation mutation remain gaps.
- Backend-owned criteria taxonomy and `/drs` UI display exist for the first
  recommendation/check slice.
- Jobs/Runs has the first read-only `drs_migration` evidence panel with compact
  approval, task, lock, post-check, reconciliation, taxonomy, and artifact
  metadata evidence.
- Risks taxonomy polish and broader DRS lifecycle/operations polish remain gaps.
- Richer policy rule/full metadata editor remains a gap.
- 15-minute average/peak metrics remain a gap.
- Deeper read-only task/HA/quorum collection remains a gap.

## Next Session Short Prompt

Use this prompt to continue DRS work in a new session:

```text
Use docs/goal/README.md as the canonical goal entrypoint.
Goal Check 01-06 is complete with result pass-with-risk; read
docs/goal/goal-check-01-06-summary-ko.md for the audit summary.
Goal 7, Goal 7.5, the minimal local-only Goal 8 recorder, Goal 9 local
account/session polish, and Goal 10 are complete; Goal 10 includes approved
VMID 140 live DRS smoke evidence and stored-UPID reconciliation completion. Goal
9 includes
admin list/create/role/disable/reset-password, admin session inventory and
revocation UI, self password change, and sanitized account/session audit
metadata; disable/reset-password revoke target sessions and role change does
not. The non-numbered current implementation validation gate completed with
result pass-with-risk in
docs/goal/goal-check-current-implementation-validation.md. The next coherent
follow-on is the rewritten Goal 11 DRS Criteria And Operations Productization
unless the user selects a different task. Treat
192.168.2.140-150/24 as candidate
selection guard only, not execution authority. Do not run live Proxmox mutation,
smoke, live readiness, cleanup, corrective action, or reconciliation mutation
without explicit active-session approval for that specific run. Preserve all
DRS backend gates: policy `allowed` is only one prerequisite, not migration
approval, and execute requires exact `drs_live_migration_acknowledged=true`
before DRS service/client/lock/migration work. Current implemented state
includes narrow backend DRS execute and approved VMID 140 live evidence; broad
live execute UI, corrective reconcile UI, richer policy editor, 15-minute
metrics, deeper read-only task/HA/quorum collection, Risks taxonomy polish, and
broader DRS lifecycle/operations polish remain gaps. The first
recommendation/check backend-owned criteria taxonomy slice and first read-only
Jobs/Runs DRS evidence slice exist.
```
