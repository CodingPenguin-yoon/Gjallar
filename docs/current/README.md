# Current Implemented State

Last refreshed: 2026-05-15

Gjallar is a human-facing Proxmox Operations & Risk Console. Hermes, AI, and agent flows are control plumbing around the product, not the product identity.

This file is the docs source of truth for implemented behavior after active code and tests. It does not define the product target; [`../product/drs-advisor/`](../product/drs-advisor/README.md) is the active target direction and may describe planned gaps that are not implemented yet.

## Product direction vs implemented state

- Product target: DRS Advisor is the next MVP success line.
- Implemented state: Proxmox inventory, Dashboard, Infra Explorer with gated stopped-VM start, Networks, read-only Placement, Jobs/Runs, Risks/Alerts, and Create VM supporting capability.
- Current gap: backend DRS recommendation API, VM identity/fingerprint policy, DRS final pre-check, approval-gated live migration, Proxmox UPID tracking, operation locks, and reconciliation are not implemented yet.
- Create VM is a supporting existing capability. It must not define the next MVP success line or implementation order.
- Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, Create VM request/VM records, audit, and reconciliation state.
- DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.
- PBS/Veeam references are backup evidence or future integration context only.

## Active surface

- The active frontend contract remains `/api/v1`.
- Do not treat `/api/instances` or `/api/provision` as the active frontend surface.
- Inventory is live read-only Proxmox data with a fake fallback when live inventory is unavailable.
- Create VM uses `/api/v1` draft/preflight/plan/approval endpoints, explicit node/template/storage/network/IP selections, final acknowledgement, and gated Proxmox native create.
- Create VM profile/template/network target design is documented in [`../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md), and is partially implemented through DB-seeded read-only profiles plus live template/network inventory.
- Create VM template selection uses read-only Proxmox inventory from
  `/api/v1/templates`; builtin template defaults are not an active selection
  source.
- Current Create VM create policy is powered-off only: native Proxmox clone, boot disk resize when needed, and config may run after exact approval metadata and `proxmox_mutation_acknowledged=true`; first power-on and Stage A smoke are separate deferred stages.
- Existing VM start is a separate Infra Explorer action at `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start`. It requires `vm_start_acknowledged=true`, a non-empty `idempotency_key`, fresh inventory precheck, Proxmox task polling, running post-check, and `vm_start` Jobs/Runs evidence.
- Terraform plan/apply routes and helper code are removed from the active backend; old URLs naturally return FastAPI 404.
- Read-only inventory is the safe baseline.
- `/placement` is currently a read-only Placement screen. The target product direction is to relabel and expand this route into DRS Advisor.

## Implemented behavior

- Instances UI is a grouped and collapsible inventory card. It exposes only a Start action for stopped, non-template VM rows; stop/reset/shutdown/reboot/delete/terminate controls are absent.
- Create VM review publishes request progress and artifacts to DB-backed Jobs/Runs tables. Native create also records the request/result and created VM summary in DB. The legacy `execute` endpoint can still write request manifests under the configured IaC root, but it is not the primary UI path.
- Create VM plan/review records `first_power_on_included=false`; the generated VMInstance manifest requests `desired_power_state: stopped`.
- `GET /api/v1/profiles` exposes active DB-seeded `db_seed` profile choices. The initial manual seed creates `general-vm`, `runtime-server`, and `development-vm`.
- Profile selection controls draft defaults for CPU/RAM/Disk. Backend preflight red-blocks unknown/disabled profiles and requested CPU/RAM/Disk outside the selected profile min/max.
- All three initial profiles require cloud-init and qemu guest-agent capable
  templates. The wizard keeps all live templates visible but disables those
  that fail the selected profile requirements, and backend preflight red-blocks
  selected templates that fail required readiness. Missing or unknown live
  Proxmox `agent` config is not treated as guest-agent-ready evidence.
- `general-vm` defaults to 2 CPU / 4096 MB RAM / 50 GB disk to match the live Ubuntu template size; preflight blocks requests smaller than the selected template disk and blocks template/requested disks above the selected profile disk max.
- There are no destructive VM list controls.
- VM start writes a `vm_start_observed_after` DB artifact with observed-before inventory, Proxmox UPID/task evidence, observed-after status, target locator, idempotency key, and redacted connection context.
- Legacy `/api` deploy/provision/task/log/LLM routes and legacy helper code are removed from the active tree.
- Native Create VM polls the clone UPID, inspects cloned config for boot disk resize, applies config, reads `/status/current` and `/config`, writes `observed_after`, records `vm_create_requests`/`vm_instances`, and marks applied only when the requested disk resize is unnecessary or completed and the VM exists on the target node and is still stopped.
- Task failure, unknown cloned disk size, resize failure, VM missing, or observed powered-on state records failed/`needs_reconciliation` and does not mark the manifest applied.

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
- Profile has no power policy; create remains stopped/powered off. VM start is
  handled only by the separate Infra Explorer row action with Jobs/Runs audit.
- Raw SSH public key material is used only transiently for native Proxmox
  `sshkeys` config and is not returned in API responses or written to
  draft/plan/review/manifest/preview/observed artifacts.
- Terraform executor routes/helper code and Terraform-named state metadata are
  removed from active draft/preflight/plan/review/API/frontend/artifact
  contracts.

Remaining Create VM gaps:

- Templates come from Proxmox live inventory with no Gjallar template catalog
  or registration window in the active Create VM selection path.
- NetworkPolicy remains Networks-tab legacy/future policy UI and is not a
  red-gate source for Create VM static range membership.

## Recent verification baseline

Development smoke and test results recorded for this refresh:

- Backend `PYTHONPATH=backend backend/venv/bin/pytest -q backend/tests`: `149 passed, 1 warning, 29 subtests passed`.
- Frontend `node --test frontend/tests/*.mjs`: `11 passed`.
- Frontend `pnpm --dir frontend lint`: passed.
- Frontend `pnpm --dir frontend build`: passed.
- `git diff --check`: passed.

## Practical reading

- Use [`../engineering/AI_CODING_WORKFLOW_PRINCIPLES.md`](../engineering/AI_CODING_WORKFLOW_PRINCIPLES.md) for repo-local AI coding workflow rules.
- Use [`../engineering/GJALLAR_CURRENT_WORK_PLAN.md`](../engineering/GJALLAR_CURRENT_WORK_PLAN.md) for the living current-work checklist.
- Use [../operations/runbook.md](../operations/runbook.md) for current verification steps.
- Use [../product/drs-advisor/README.md](../product/drs-advisor/README.md) for active product target direction.
- Use [../product/legacy-prd/README.md](../product/legacy-prd/README.md) for older PRD context.
- Use [`../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md) for the Create VM target profile/template/network model.
- Use [`../architecture/`](../architecture/) for current code-oriented architecture notes; treat [`../archive/features/`](../archive/features/), [`../archive/operations/`](../archive/operations/), and [`../archive/roadmap/`](../archive/roadmap/) as historical context unless a file says otherwise.
