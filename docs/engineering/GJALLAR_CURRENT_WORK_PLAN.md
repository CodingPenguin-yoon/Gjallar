# Gjallar Current Work Plan

Last updated: 2026-05-14

## Purpose

This is the living work plan for the current Gjallar cleanup and Create VM
implementation work. Read this before starting a new slice, then update it as
work is completed or decisions change.

This is not a replacement for product requirements. Product direction remains
under `docs/product/drs-advisor/`, and current implemented state remains
under `docs/current/README.md`.

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
- Terraform Create VM executor routes/helper code and Terraform-named state
  fields are removed from the active code/API/artifact contracts.
- Create VM profile/template/network target design is documented in
  `docs/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`.

## Current Implementation Baseline

- `/api/v1` is the active frontend/backend contract.
- Inventory is read-only Proxmox live inventory with fake fallback.
- Create VM currently supports draft, preflight, plan, approval, manifest
  commit, Proxmox native preview/create, Jobs/Runs progress, and artifacts.
- Native create clone/config success is only valid when Proxmox post-check sees
  the VM on the target node in `stopped` state and writes `observed_after`.
- Profile/template/network target design is partially implemented:
  - `GET /api/v1/profiles` exposes exactly three enabled read-only static-seed
    profiles: `general-vm`, `runtime-server`, and `development-vm`
  - profile hardware defaults/min/max are enforced in backend preflight and
    surfaced in plan/review artifacts; DB/ORM seed source remains future work
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

Status: partially implemented.

Goal: implement the target design from
`CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`.

Planned slices:

- [x] Expose three enabled seed profiles:
  `general-vm`, `runtime-server`, `development-vm`.
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

Status: partially implemented.

Goal: keep the active Create VM implementation Proxmox-native and auditable.

Planned slices:

- [ ] Preserve exact approval metadata validation.
- [ ] Preserve manifest commit verification before live create.
- [ ] Preserve `proxmox_mutation_acknowledged=true` gate.
- [ ] Preserve stopped/powered-off success policy.
- [x] Ensure plan/preview/create all use the same reviewed network/access
  fields.
- [ ] Replace any implicit gateway/default network behavior with reviewed input.
- [ ] Keep read-only inventory adapter separate from mutation client.
- [ ] Keep first power-on and smoke out of the create mutation slice.

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

## Open Decisions

- Profile seed source is currently transitional `source: static_seed`.
  A real DB/ORM seed source remains a later implementation decision.
- Removed Terraform endpoints disappear from the route table and naturally return
  FastAPI 404.
- Whether Network tab policy should provide future recommendations for gateway
  and static ranges, while live bridge remains Create VM source of truth.

## Next Slice Candidate

Recommended next implementation slice:

1. Decide DB/ORM profile seed source for Create VM profiles.
2. Start DRS Advisor read model and final pre-check contract work without
   reusing Create VM mutation semantics.
