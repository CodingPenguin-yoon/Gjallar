# Next Session Handoff

Last updated: 2026-05-16

## Current State

- Latest pushed code commit before this docs refresh: `b6db2e5 feat: complete native VM create flow`.
- Create VM is now the strongest supporting capability, not the DRS MVP success line.
- Active Create VM mutation path is `POST /api/v1/vm-create/{draft_id}/proxmox-create`.
- Terraform plan/apply and legacy GitOps `execute/archive` routes are removed from the active API.
- Profiles, Jobs/Runs, artifacts, Create VM requests, and created VM records are DB-backed.
- `/networks` is now read-only Network Readiness / migration pre-check visualization composed from existing live inventory APIs. There is no Proxmox network mutation, Networks API write path, YAML persistence, DB migration, or DRS execution authority.
- Create VM power policy is request-level:
  - `stopped`: default, clone/config and stopped post-check.
  - `boot_and_verify`: start the new VM, observe guest-agent IP, and verify `cloud-init status --wait`.
- SSH login, Ansible verification, app bootstrap, background reconciliation, and DRS identity registration are not implemented.

## Validation Baseline

Most recent code validation before docs-only refresh:

```bash
PYTHONPATH=backend backend/venv/bin/pytest -q backend/tests
for test_file in frontend/tests/*.mjs; do node "$test_file"; done
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```

Backend result recorded after the final boot verification fix: `148 passed, 1 warning, 29 subtests passed`.

## Next Work 2: Create VM Live Smoke Matrix

Goal: verify the completed Create VM behavior against live Proxmox.

Run and record:

1. `stopped` creation with default settings.
2. `boot_and_verify` with DHCP and guest-agent IP display.
3. Static IP creation with explicit `static_ip`, `prefix`, and `gateway`.
4. Invalid target combination, such as template/node/storage mismatch, to confirm the error is understandable.

Check Jobs/Runs after each run:

- job status and stage
- generated VM summary
- IP display and meaning
- `observed_after`
- `cloud_init`
- `boot_verification`

## Next Work 3: DRS Advisor Read Model

Goal: start DRS without adding migration mutation yet.

Start by reading:

- `docs/product/drs-advisor/README.md`
- `docs/product/drs-advisor/05_IMPLEMENTATION_PLAN.md`
- `frontend/src/components/PlacementScreen.jsx`
- `frontend/src/utils/placement.js`
- `backend/app/api/v1/router.py`
- `backend/app/proxmox/inventory.py`

Initial backend endpoints should be read-only:

```http
GET /api/v1/drs/summary
GET /api/v1/drs/recommendations
GET /api/v1/drs/recommendations/{recommendation_id}
POST /api/v1/drs/recommendations/{recommendation_id}/check
```

Phase 1 rules:

- No live migration endpoint yet.
- No Proxmox mutation yet.
- Recommendations are non-executable until identity, metadata, final pre-check, locks, and reconciliation exist.
- Reuse Create VM's approval/artifact/job lessons, but do not reuse Create VM success criteria as DRS migration criteria.

## First Commands In A New Session

```bash
git status --short --branch
git pull --ff-only
nl -ba docs/engineering/GJALLAR_CURRENT_WORK_PLAN.md | sed -n '1,270p'
nl -ba docs/engineering/NEXT_SESSION_HANDOFF.md | sed -n '1,220p'
```
