# Goal Documents

## Canonical Entrypoint

This file is the canonical entrypoint for goal-sized Gjallar work. It is the
source of truth for the Goal 1 through Goal 12 map, the inserted Goal 7.5,
document roles, status, and next-session prompt. Goals 10-12 are candidate
follow-on goals, not started work. Start one only if the user explicitly selects
it.

Do not infer a second goal sequence from standalone files. Each goal has
exactly one detailed document, listed below.

## Document Roles

- `docs/goal/README.md`: canonical entrypoint, goal map, and next-session
  prompt.
- `docs/goal/remaining-operations-work.md`: concise overall operations
  backlog, status, validation, and risk overview only.
- `docs/goal/goal-01-create-vm-live-smoke-matrix.md` through
  `docs/goal/goal-12-platform-hardening-decision-quality.md`, plus
  `docs/goal/goal-07-5-drs-vm-policy-management.md`: one detailed document per
  goal, including the inserted Goal 7.5. Goals 10-12 are candidate/not-started
  follow-on briefs.
- `docs/goal/goal-check-01-06-implementation-quality.md`: non-numbered gate
  that verifies Goal 1 through Goal 6 implementation quality before Goal 7.
- `docs/goal/goal-check-01-06-summary-ko.md`: Korean operator-readable summary
  of the completed Goal 1-6 implementation quality audit.
- `docs/goal/goal-check-current-implementation-validation.md`: completed
  non-numbered validation gate that established the code/docs/test baseline
  before Goal 9 polish.

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
| Goal 10: DRS Live Migration Safety And Evidence | Candidate / not started | `docs/goal/goal-10-drs-live-migration-safety-evidence.md` | Next planned candidate if the user selects it. Harden execute acknowledgement/evidence and optionally record an approved live DRS smoke only after explicit run approval. |
| Goal 11: DRS Operations Productization | Candidate / not started | `docs/goal/goal-11-drs-operations-productization.md` | Productize guarded DRS operations UI after Goal 10 safety baseline; no frontend inference of executability. |
| Goal 12: Platform Hardening And Decision Quality | Candidate / not started | `docs/goal/goal-12-platform-hardening-decision-quality.md` | Metrics, read-only evidence depth, blocker taxonomy, audit browsing, error envelope, retention, and redaction hardening candidate. |

When a future session says "next goal", do not restart Goal 7.5, the minimal
Goal 8 recorder, or Goal 9 polish. Goal 10 is the next planned candidate only
if the user explicitly selects it. Goal 11 and Goal 12 are later candidate
follow-ons unless separately selected.
The Goal 1-6 implementation quality audit is complete with result
`pass-with-risk`; Goal 7, Goal 7.5, and the minimal local-only Goal 8 slice
are complete; no live DRS smoke was run.
Goal 9 local account/session polish is complete: admin local account
operations, admin session inventory/revocation UI, self password change, and
sanitized account/session audit metadata are implemented. Disable and
reset-password revoke target sessions while role changes do not.

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

## Current DRS Gap Summary

- Narrow backend DRS execute exists.
- Broad live execute UI remains a gap.
- Corrective reconcile UI and corrective reconciliation mutation remain gaps.
- Live DRS smoke evidence remains a gap.
- Richer policy rule/full metadata editor remains a gap.
- 15-minute average/peak metrics remain a gap.
- Deeper read-only task/HA/quorum collection remains a gap.

## Next Session Short Prompt

Use this prompt to continue DRS work in a new session:

```text
Use docs/goal/README.md as the canonical goal entrypoint.
Goal Check 01-06 is complete with result pass-with-risk; read
docs/goal/goal-check-01-06-summary-ko.md for the audit summary.
Goal 7, Goal 7.5, the minimal local-only Goal 8 recorder, and Goal 9 local
account/session polish are complete; no live DRS smoke was run. Goal 9 includes
admin list/create/role/disable/reset-password, admin session inventory and
revocation UI, self password change, and sanitized account/session audit
metadata; disable/reset-password revoke target sessions and role change does
not. The non-numbered current implementation validation gate completed with
result pass-with-risk in
docs/goal/goal-check-current-implementation-validation.md. Goals 10-12 are
candidate/not-started follow-on briefs. Goal 10 is the next planned candidate
only if the user explicitly selects it; Goal 11 and Goal 12 are later candidate
follow-ons unless separately selected. Treat 192.168.2.140-150/24 as candidate
selection guard only, not execution authority. Do not run live Proxmox mutation,
smoke, live readiness, cleanup, corrective action, or reconciliation mutation
without explicit active-session approval for that specific run. Preserve all
DRS backend gates: policy `allowed` is only one prerequisite, not migration
approval. Current implemented state includes narrow backend DRS execute;
broad live execute UI, corrective reconcile UI, live DRS smoke, richer policy
editor, 15-minute metrics, and deeper read-only task/HA/quorum collection
remain gaps.
```
