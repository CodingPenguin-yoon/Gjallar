# Current Implemented State

Last refreshed: 2026-05-28

Gjallar is a human-facing Proxmox Operations & Risk Console. Hermes, AI, and agent flows are control plumbing around the product, not the product identity.

This file is the docs source of truth for implemented behavior after active code and tests. It does not define the product target; [`../product/drs-advisor/`](../product/drs-advisor/README.md) is the active target direction and may describe planned gaps that are not implemented yet.

## Product direction vs implemented state

- Product target: DRS Advisor is the next MVP success line.
- Implemented state: Proxmox inventory, Dashboard, Infra Explorer with gated stopped-VM start, Networks, read-only DRS Advisor Phase 1 with identity/policy readiness foundation, DB-backed operation lock lookup, config-lock evidence, and read-only final pre-check, Jobs/Runs, Risks/Alerts, Create VM supporting capability, and admin local-user management.
- Current gap: approval-gated live migration, Proxmox UPID tracking, operation lock acquisition/release, task/HA/quorum evidence, DRS migration jobs, and reconciliation are not implemented yet.
- Create VM is a supporting existing capability. It must not define the next MVP success line or implementation order.
- Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, Create VM request/VM records, audit, and reconciliation state.
- DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.
- PBS/Veeam references are backup evidence or future integration context only.

## Active surface

- The active frontend contract remains `/api/v1`.
- Do not treat `/api/instances` or `/api/provision` as the active frontend surface.
- Inventory is live read-only Proxmox data with a fake fallback when live inventory is unavailable.
- Create VM uses `/api/v1` draft/preflight/plan/approval endpoints, explicit node/template/storage/network/IP/power selections, final acknowledgement, and gated Proxmox native create.
- Create VM profile/template/network target design is documented in [`../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md), and is partially implemented through DB-seeded read-only profiles plus live template/network inventory.
- Create VM template selection uses read-only Proxmox inventory from
  `/api/v1/templates`; builtin template defaults are not an active selection
  source.
- Current Create VM create policy is explicit per request: the default `stopped` policy performs native Proxmox clone, boot disk resize when needed, config, and stopped post-check; the optional `boot_and_verify` policy starts the new VM, waits for guest-agent IP discovery, and verifies `cloud-init status --wait`. SSH login, Ansible, app bootstrap, and DRS identity registration remain deferred.
- Existing VM start is a separate Infra Explorer action at `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start`. It requires `vm_start_acknowledged=true`, a non-empty `idempotency_key`, fresh inventory precheck, Proxmox task polling, running post-check, and `vm_start` Jobs/Runs evidence.
- Admin local-user management is available at `/admin/users` for users with the
  `admin` role. The backend endpoints are `GET/POST /api/v1/admin/users`,
  `PATCH /api/v1/admin/users/{username}/role`,
  `POST /api/v1/admin/users/{username}/disable`, and
  `POST /api/v1/admin/users/{username}/reset-password`.
- Terraform plan/apply routes and helper code are removed from the active backend; old URLs naturally return FastAPI 404.
- Read-only inventory is the safe baseline.
- `/drs` is currently a read-only DRS Advisor Phase 1 screen with DB-backed VM identity/policy evidence, DB-backed operation lock lookup, config-lock evidence, and a read-only final pre-check model. It consumes backend `/api/v1/drs/*` read endpoints; all recommendations and checks remain `executable=false`.

## Implemented behavior

- Instances UI is a grouped and collapsible inventory card. It exposes only a Start action for stopped, non-template VM rows; stop/reset/shutdown/reboot/delete/terminate controls are absent.
- Create VM review publishes request progress and artifacts to DB-backed Jobs/Runs tables. Native create also records the request/result and created VM summary in DB. Legacy `execute/archive` routes are removed from the active API.
- Create VM plan/review records `power_policy` and `first_power_on_included`. The generated VMInstance manifest requests `desired_power_state: stopped` for default creation and `running` for `boot_and_verify`.
- `GET /api/v1/profiles` exposes active DB-seeded `db_seed` profile choices. The initial manual seed creates `general-vm`, `runtime-server`, and `development-vm`.
- Profile selection controls draft defaults for CPU/RAM/Disk. Backend preflight red-blocks unknown/disabled profiles and requested CPU/RAM/Disk outside the selected profile min/max.
- All three initial profiles require cloud-init and qemu guest-agent capable
  templates. The wizard keeps all live templates visible but disables those
  that fail the selected profile requirements, and backend preflight red-blocks
  selected templates that fail required readiness. Missing or unknown live
  Proxmox `agent` config is not treated as guest-agent-ready evidence.
- `general-vm` defaults to 2 CPU / 4096 MB RAM / 50 GB disk to match the live Ubuntu template size; preflight blocks requests smaller than the selected template disk and blocks template/requested disks above the selected profile disk max.
- There are no destructive VM list controls.
- There is no public signup flow. Local users are created by CLI or by an
  authenticated admin. Account disable and password reset revoke target
  sessions; role changes do not revoke sessions. The last enabled admin cannot
  be disabled or demoted, and disabled admin rows do not count toward that
  protection.
- VM start writes a `vm_start_observed_after` DB artifact with observed-before inventory, Proxmox UPID/task evidence, observed-after status, target locator, idempotency key, and redacted connection context.
- Legacy `/api` deploy/provision/task/log/LLM routes and legacy helper code are removed from the active tree.
- Native Create VM polls the clone UPID, inspects cloned config for boot disk resize, applies config, reads `/status/current` and `/config`, writes `observed_after`, records `vm_create_requests`/`vm_instances`, and marks applied only when the requested disk resize is unnecessary or completed and the selected power-policy post-check passes.
- Task failure, unknown cloned disk size, resize failure, VM missing, stopped-policy powered-on mismatch, or boot-and-verify guest-agent/cloud-init failure records failed/`needs_reconciliation` and does not mark the manifest applied.
- Approved live Create VM smoke completed on 2026-05-28 against
  `yoonserver3` using template `yoonmanserver / 118 / ubuntu-templte`, storage
  `nas-server`, bridge `vmbr0`, and explicit static IPs. The matrix covered a
  negative bridge gate with `side_effects=[]`, default `stopped`, optional
  `boot_and_verify`, and static IP stopped creation. Results are recorded in
  [`../operations/create-vm-live-smoke-2026-05-28.md`](../operations/create-vm-live-smoke-2026-05-28.md).

## Create VM Implementation And Gaps

Implemented profile DB seed behavior:

- Profiles are Gjallar DB-seeded read-only presets through `GJALLAR_DATABASE_URL`.
  The Alembic schema is separate from the manual idempotent seed command, and
  the initial active profiles are `general-vm`, `runtime-server`, and
  `development-vm`.
- Disabled or archived profile rows are hidden from Create VM selection and are
  not hard-deleted.

Implemented target behaviors retained:

- Current code now uses explicit `bridge_id` from active live bridge inventory
  as the Create VM network source of truth. Incoming `network_id`/`networkId`
  is ignored for transition compatibility and is not echoed in active draft,
  plan, review, manifest, or job output.
- Static mode now requires explicit `static_ip`, `prefix`, and `gateway`
  across draft, preflight, plan/review, manifest, and native create
  preview/create.
- Native create no longer infers a `.1` gateway or `/24` prefix from
  `static_ip`.
- Create VM Access/SSH is implemented: the wizard accepts a cloud-init user
  and SSH public key, backend preflight red-blocks missing or malformed keys
  when the selected profile requires one, password login is fixed disabled, and
  plan/review/manifest/preview/observed evidence records only safe SSH key
  presence/source/fingerprint metadata.
- Profile has no power policy. The operator chooses `stopped` or
  `boot_and_verify` per Create VM request; separate existing-VM starts still use
  the Infra Explorer row action with Jobs/Runs audit.
- Raw SSH public key material is used only transiently for native Proxmox
  `sshkeys` config and is not returned in API responses or written to
  draft/plan/review/manifest/preview/observed artifacts.
- Terraform executor routes/helper code and Terraform-named state metadata are
  removed from active draft/preflight/plan/review/API/frontend/artifact
  contracts.
- `/networks` is a read-only Network Readiness / migration pre-check
  visualization composed from `GET /api/v1/nodes`, `/vms`, and `/networks`.
  It uses a migration source selector, target network comparison rows for that
  selected source, CIDR-verified exact bridge match / CIDR remap evidence, and
  VM impact filtered to the selected source.
  It has no Proxmox network mutation, API write path, YAML persistence, DB
  migration, or DRS execution authority.

Remaining Create VM gaps:

- Templates come from Proxmox live inventory with no Gjallar template catalog
  or registration window in the active Create VM selection path.
- Networks readiness is not a red-gate source for Create VM static range
  membership.
- `boot_and_verify` now covers first boot, guest-agent IP discovery, and
  cloud-init completion for the new VM. SSH/Ansible/app bootstrap smoke remains
  deferred.
- Create VM shows the authenticated session user as the request actor instead
  of exposing an editable `operator_id` field. Backend job/request evidence
  continues to use trusted session actor fields.

## Recent verification baseline

Development smoke and test results recorded for this refresh:

- Pre-live and post-doc backend targeted validation
  `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/contracts backend/tests/vm_create backend/tests/proxmox`:
  `170 passed, 33 warnings, 26 subtests passed`.
- Pre-live and post-doc frontend `node --test frontend/tests/createVmFlow.test.mjs`:
  passed.
- Post-doc `git diff --check`: passed.
- Live Create VM smoke matrix: negative gate, stopped create, boot-and-verify,
  and static IP stopped create passed with final smoke VMs left stopped.
- Full prior auth-stabilization baseline remains:
  backend `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests`
  `182 passed, 33 warnings, 29 subtests passed`; frontend
  `node --test frontend/tests/*.mjs` `13 passed`; lint/build passed.

## Practical reading

- Use [`../engineering/GJALLAR_IMPLEMENTATION_ROADMAP.md`](../engineering/GJALLAR_IMPLEMENTATION_ROADMAP.md) for the current implementation order and next slice.
- Use [`../engineering/AI_CODING_WORKFLOW_PRINCIPLES.md`](../engineering/AI_CODING_WORKFLOW_PRINCIPLES.md) for repo-local AI coding workflow rules.
- Use [`../engineering/GJALLAR_CURRENT_WORK_PLAN.md`](../engineering/GJALLAR_CURRENT_WORK_PLAN.md) for the living current-work checklist.
- Use [../operations/runbook.md](../operations/runbook.md) for current verification steps.
- Use [../product/drs-advisor/README.md](../product/drs-advisor/README.md) for active product target direction.
- Use [../product/legacy-prd/README.md](../product/legacy-prd/README.md) for older PRD context.
- Use [`../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md) for the Create VM target profile/template/network model.
- Use [`../architecture/`](../architecture/) for current code-oriented architecture notes; treat [`../archive/features/`](../archive/features/), [`../archive/operations/`](../archive/operations/), and [`../archive/roadmap/`](../archive/roadmap/) as historical context unless a file says otherwise.
