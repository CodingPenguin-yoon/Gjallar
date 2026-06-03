# Goal 12: Superseded Platform Hardening And Decision Quality Brief

Status: superseded. This file is retained only as a historical pointer. The
previous Goal 12 hardening/decision-quality scope has been folded into
`docs/goal/goal-11-drs-operations-productization.md` as optional selected
hardening slices inside the rewritten Goal 11: DRS Criteria And Operations
Productization.

Do not start this file as an active goal. Use `docs/goal/README.md` and the
rewritten Goal 11 document for current sequencing.

## Superseded Scope

The old Goal 12 described:

- 15-minute average/peak DRS metrics
- deeper read-only active task, HA, and quorum evidence
- stale evidence warnings
- DRS blocker/risk taxonomy
- account/session audit browsing
- CLI audit decisions
- audit atomicity
- API error envelope normalization
- retention and redaction review

Those items remain valid hardening candidates, but they are no longer tracked as
a separate Goal 12. Select them explicitly inside Goal 11 or in a later newly
defined goal.

## Still Required Safety Boundary

No live Proxmox mutation, live DRS smoke, cleanup, reverse migration, retry, live
readiness, corrective action, or reconciliation mutation is authorized by this
historical file. Any such operation still needs explicit active-session approval
for that specific run.
