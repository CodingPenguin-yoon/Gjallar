# Gjallar Current Work Plan

Last updated: 2026-06-01

## Purpose

This is the living work plan for the current Gjallar cleanup and Create VM
implementation work. Read this before starting a new slice, then update it as
work is completed or decisions change.

This is not a replacement for product requirements. Product direction remains
under `docs/product/drs-advisor/`, and current implemented state remains
under `docs/current/README.md`.

For the current cross-feature implementation sequence, use
`docs/goal/README.md`. This file preserves the
living checklist for the completed Create VM cleanup/native-create workstream and
the repo-local workflow context.

## Operating Principles

Use `docs/engineering/AI_CODING_WORKFLOW_PRINCIPLES.md` as the workflow guide:

- clarify ambiguous requirements before broad implementation
- document agreed decisions before large changes
- prefer TDD or contract updates before broad implementation
- diagnose failures by reproduction, hypothesis, and direct verification
- improve architecture while keeping slices small
- let the user own product interfaces and high-level architecture
- run separate review for substantial changes

Use `AGENTS.md` for execution mode:

- main session coordinates
- for non-trivial tasks use explorer, reviewer, docs_researcher, then worker
- only worker edits code
- keep summaries concise and validation explicit

## Current Product Context

- Gjallar's next MVP success line is DRS Advisor.
- Create VM is a supporting capability, not the MVP success line.
- Active Create VM mutation path is Proxmox native API.
- Create VM stabilization now includes Gjallar login, server-side sessions,
  simple role-based authorization, and the approved 2026-05-28 live smoke
  matrix.
- Terraform Create VM executor routes/helper code and Terraform-named state
  fields are removed from the active code/API/artifact contracts.
- Create VM profile/template/network target design is documented in
  `docs/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`.

## Current Implementation Baseline

- `/api/v1` is the active frontend/backend contract.
- Gjallar login uses server-side sessions and roles: `viewer`, `operator`, and
  `admin`.
- Read-only `/api/v1` surfaces require `viewer` or above, while Create VM
  workflow writes, Create VM live create, and VM Start require `operator` or
  `admin`.
- Admin-only local user/session management is implemented at `/admin/users`,
  `/api/v1/admin/users*`, and `/api/v1/admin/sessions*`; CLI and API share
  last-enabled-admin protection.
- Admin local account operations include list/create/role/disable/reset-password,
  admin session inventory/revocation, self password change, and sanitized
  account/session audit metadata. Disable and reset-password revoke target
  sessions; role changes do not revoke sessions.
- Inventory is read-only Proxmox live inventory with fake fallback.
- Create VM currently supports draft, preflight, plan, approval, manifest
  commit, Proxmox native preview/create, Jobs/Runs progress, and artifacts.
- Native create clone/config success follows the reviewed power policy:
  `stopped` requires target-node stopped post-check and `observed_after`;
  `boot_and_verify` starts the new VM, records guest-agent IP evidence, verifies
  cloud-init completion, and writes `observed_after`.
- Minimal local-only post-create readiness evidence recording is implemented for
  already-created VMs. Live readiness checks, SSH, Ansible, and app bootstrap
  remain deferred.
- Profile/template/network target design is partially implemented:
  - `GET /api/v1/profiles` exposes active read-only DB-backed `db_seed`
    profiles through `GJALLAR_DATABASE_URL`; the initial manual seed creates
    `general-vm`, `runtime-server`, and `development-vm`
  - profile schema is managed by Alembic, while seed data is applied through a
    separate manual idempotent command that no-ops when profile rows already
    exist
  - profile hardware defaults/min/max are enforced in backend preflight and
    surfaced in plan/review artifacts
  - Create VM active networking now uses explicit `bridge_id` selected from
    active live bridge inventory after target node selection; incoming
    `network_id`/`networkId` is ignored during the transition and is not echoed
    in active draft/plan/review/manifest/job output
  - static mode now requires explicit `static_ip`, `prefix`, and `gateway`
    across draft, preflight, plan, manifest, and native create preview/create
  - native create no longer infers `.1` gateway or `/24` prefix from static IP
  - Create VM templates come from read-only Proxmox inventory through
    `/api/v1/templates`; active selection does not use builtin template
    catalog defaults
  - all three initial profiles require cloud-init and qemu guest-agent capable
    templates; the UI disables failing live templates and backend preflight
    red-blocks selected templates that fail required capabilities
  - Access/SSH is implemented for current profiles: wizard username/key input,
    request or backend env/file default key, missing/malformed key red
    preflight, fixed disabled password login, safe fingerprint/source evidence,
    and native preview/observed sanitization
- Terraform routes/helper/module/tests and Terraform-named state fields are
  removed from active contracts.

## Workstream A: Preserve Principles And Context

Status: in progress.

- [x] Read source design principles from the user's iCloud document.
- [x] Save repo-local workflow principles:
  `docs/engineering/AI_CODING_WORKFLOW_PRINCIPLES.md`.
- [x] Keep project-specific work plans repo-local under `docs/`.
- [x] Keep global Codex memory limited to the user's general AI design
  principles, not Gjallar-specific work state.
- [x] Add this living work plan.
- [ ] Keep `docs/current/README.md` linked to the living work plan.
- [ ] Update this file after each completed slice.

## Workstream B: Create VM Profile/Template/Network Target

Status: implemented for current target slice.

Goal: implement the target design from
`CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`.

Planned slices:

- [x] Expose three enabled seed profiles:
  `general-vm`, `runtime-server`, `development-vm`.
- [x] Convert Create VM profiles to DB-backed `db_seed` rows through
  `GJALLAR_DATABASE_URL`, Alembic migration, and a manual idempotent seed
  command.
- [x] Add profile hardware default/min/max contract.
- [x] Reset CPU/RAM/Disk to profile defaults when profile changes in UI.
- [x] Enforce profile hardware min/max in UI and backend preflight.
- [x] Use Proxmox live template inventory as the template source of truth.
- [x] Disable UI templates that fail selected profile requirements.
- [x] Red-block backend preflight when selected template fails required
  cloud-init or qemu guest-agent checks.
- [x] Remove Create VM dependency on `network_id`/`server-net`.
- [x] Select target node first, then active live bridge for that node.
- [x] Add static `static_ip`, `prefix`, and `gateway` fields.
- [x] Stop gateway inference from static IP; use operator-supplied gateway.
- [x] Add Access section with username and SSH public key.
- [x] Red-block missing SSH key when selected profile requires one.
- [x] Keep password login disabled/fixed for initial profiles.
- [x] Record selected profile and resolved profile hardware limits in plan,
  review, and artifacts.
- [x] Update review/plan/artifacts to record live template evidence, bridge,
  static network fields, access username, and SSH key presence/fingerprint
  without storing secrets.

## Workstream C: Native Proxmox Create Quality

Status: implemented in code/tests and live-smoked on 2026-05-28.

Goal: keep the active Create VM implementation Proxmox-native and auditable.

Planned slices:

- [x] Preserve exact approval metadata validation.
- [x] Remove manifest commit verification from live create; DB-backed request,
  result, and VM records are the active persistence path.
- [x] Preserve `proxmox_mutation_acknowledged=true` gate.
- [x] Preserve stopped/powered-off default success policy.
- [x] Ensure plan/preview/create all use the same reviewed network/access
  fields.
- [x] Replace any implicit gateway/default network behavior with reviewed input.
- [x] Keep read-only inventory adapter separate from mutation client.
- [x] Add explicit request-level `boot_and_verify` power policy for first boot,
  guest-agent IP discovery, and cloud-init completion without adding SSH/Ansible
  bootstrap to Create VM.

## Workstream D: Terraform Legacy Cleanup

Status: executor and state-field cleanup implemented.

Goal: remove legacy Terraform Create VM executor code after native-only
contracts are locked.

Planned slices:

- [x] Lock native-only API contract tests.
- [x] Remove Terraform plan/apply routes from active API.
- [x] Remove Terraform imports from `backend/app/api/v1/router.py`.
- [x] Remove `backend/app/vm_create/terraform_runner.py`.
- [x] Remove Terraform-specific backend tests.
- [x] Remove or park `infra/terraform/` after active references are gone.
- [x] Retire Terraform-named state fields from active draft, preflight, plan,
  review, manifest, API, frontend, and artifact contracts.
- [x] Update docs from "optional/deprecated legacy" to "removed" when removal
  actually lands.

## Workstream E: Documentation And Status Hygiene

Status: ongoing.

- [ ] Keep current-vs-target language explicit.
- [ ] Do not claim implementation is complete until tests and code match.
- [ ] Keep DRS Advisor product direction separate from Create VM supporting
  capability.
- [ ] Update `docs/current/README.md` after code changes.
- [ ] Update top-tab status docs when UI/API behavior changes.
- [ ] Keep historical docs historical; do not rewrite history unless a current
  doc points to stale behavior.

## Workstream F: Validation

Run focused validation after each slice:

```bash
PYTHONPATH=backend python3 -m pytest -q backend/tests/contracts backend/tests/vm_create backend/tests/proxmox
node --test frontend/tests/*.mjs
pnpm --dir frontend build
```

Run broader validation before marking a workstream complete:

```bash
PYTHONPATH=backend python3 -m pytest -q backend/tests
node --test frontend/tests/*.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
```

## Workstream G: Create VM Stabilization

Status: implemented and live-smoked on 2026-05-28.

Goal: close Create VM as a safe supporting capability before DRS Phase 2.

Plan source:
`docs/engineering/CREATE_VM_STABILIZATION_PLAN.md`.

Planned slices:

- [x] Add backend `users` and `sessions` tables.
- [x] Add first-admin CLI.
- [x] Add `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, and
  `GET /api/v1/auth/me`.
- [x] Add `viewer`, `operator`, and `admin` roles.
- [x] Require authenticated `operator` or `admin` for Create VM workflow writes
  and live mutation.
- [x] Require authenticated `operator` or `admin` for existing VM Start.
- [x] Require authenticated `viewer` or above for operator read APIs, leaving
  only public health/login endpoints open.
- [x] Add actor evidence to mutation jobs and Create VM request records.
- [x] Add frontend `/login`, session bootstrap, logout, and role-aware controls.
- [x] Add tests for unauthenticated, viewer, operator, and admin behavior.
- [x] Add admin-only local user management UI/API without public signup.
- [x] Share last-enabled-admin protection between CLI and API.
- [x] Make Create VM display the session-derived actor instead of editable
  `operator_id`.
- [x] Record Create VM live smoke for `stopped`, `boot_and_verify`, static IP,
  and a negative pre-mutation gate.

Non-goals:

- OAuth/SSO/2FA.
- API token automation.
- SSH smoke, Ansible, app bootstrap, full reconciliation worker, or DRS identity
  registration.

## Completed Decisions

- Create VM profile seed source is DB-backed `source: db_seed` through
  `GJALLAR_DATABASE_URL`.
- Local development can use SQLite through the same SQLAlchemy/Alembic URL
  boundary that enterprise deployment can point at PostgreSQL.
- Profile schema is migration-managed; profile seed is a separate manual
  idempotent command.
- The initial `general-vm`, `runtime-server`, and `development-vm` profiles are
  inserted only when the profile table is empty, so process restarts do not
  overwrite operator changes or re-enable disabled rows.
- Future profile deletion means disabled/archive, not hard delete, and
  disabled/archived profiles are hidden from Create VM selection.
- Jobs/Runs and artifacts are DB-backed through `job_runs` and `job_artifacts`;
  `GJALLAR_RUNS_ROOT` is no longer an active runtime setting.
- Native Create VM records request/result and the created VM summary in
  `vm_create_requests` and `vm_instances`.
- Create VM now supports request-level `power_policy`: default `stopped`, or
  `boot_and_verify` for VM start, guest-agent IP discovery, and cloud-init
  completion. Profile definitions still do not own power policy.
- Gjallar auth uses local `users` and server-side `sessions`; first admin is
  created by `python -m app.auth.users create-admin --username yoon`.
- Session-derived actor evidence is recorded in Create VM and VM Start
  jobs/artifacts/request records as `actor_user_id`, `actor_username`, and
  `actor_role`.
- Local user disable/reset revoke target sessions. Role changes do not revoke
  sessions. The last enabled admin cannot be disabled or demoted, and disabled
  admin rows do not count toward that guard.

## Future Decisions

- Removed Terraform endpoints disappear from the route table and naturally return
  FastAPI 404.
- Networks is now read-only Network Readiness / migration pre-check
  visualization composed from live inventory. It has no Proxmox network
  mutation, API write path, YAML persistence, DB migration, or DRS execution
  authority.
- `GJALLAR_SHARED_ROOT` and `GJALLAR_IAC_ROOT` remain transitional settings for
  Create VM/IaC readiness only. They are not used for Jobs/Runs, artifacts, or
  Networks readiness.
- Shared-folder/NFS usage originally came from Terraform-era IaC/state needs.
  Profiles, Jobs/Runs, artifacts, and native Create VM records are now
  DB-backed; retire the remaining shared-folder dependency once Create VM/IaC
  readiness no longer needs it.

## Next Slice Candidate

Current goal sequencing is tracked in `docs/goal/README.md`. Goal Check 01-06,
Goal 7, Goal 7.5, the minimal local-only Goal 8 recorder, and Goal 9 local
account/session polish are complete. Remaining candidates are optional approved
live DRS smoke evidence or another explicitly requested task. No live DRS smoke
was run.
