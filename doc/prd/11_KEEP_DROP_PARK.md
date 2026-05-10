# Gjallar Keep / Drop / Park Result

Last updated: 2026-05-11 KST

## 0. Decision rule

This document records Set 1's Keep / Drop / Park classification for the current repo on branch `rewrite/prd-v1-mvp`.

Definitions:

- **Keep**: can be reused or salvaged after tests prove it matches the locked PRD.
- **Drop**: does not belong in the first MVP direction and should be replaced/removed later.
- **Park**: useful idea or later-slice material, but not part of the immediate MVP core.

Safety rule:

> `Drop` and `Park` are classification labels only. They do not authorize deletion, migration reset, file moves, commit, push, Terraform apply, Proxmox write, VM create, or power action. Actual removal requires explicit user approval plus backup/evidence artifacts.

2026-05-09 manual cleanup note: the user approved a first backend cleanup slice. Legacy backend deploy/LLM/proxmox packages and related tests were backed up and moved to `codex-vm:/home/yoon/projects/Gjallar/archive/legacy-backend/2026-05-09_1047KST/`; backup artifact `artifacts/legacy-backend-2026-05-09_1047KST.tar.gz` has SHA256 `9291f0430202185c9e7680901fdc35eac4a798d3f3237d94409ef6357bd5a902`. This did not include commit/push/live IaC/Proxmox actions or unrecoverable deletion.

## 1. Keep candidates

| Area | Keep candidate | Why keep | Required guard before reuse |
|---|---|---|---|
| Backend Proxmox read-only inventory | `backend/app/domains/proxmox/service.py`, read-only sections of `backend/app/domains/proxmox/router.py` | MVP needs cluster/node/VM/template/storage/network inventory and VM detail. | Add `/api/v1` contract tests; verify no secrets in logs/responses; exclude write actions. |
| Backend monitoring signals | Monitoring routes in `backend/app/domains/proxmox/router.py` | Useful for Dashboard / Infra Explorer status. | Shape must be rewritten under PRD `/api/v1`. |
| Backend task/job storage ideas | `backend/app/domains/task/router.py`, `backend/app/shared/tasks.py`, `backend/app/shared/task_store.py`, initial task table migration | MVP needs jobs/runs/artifacts. | Replace with explicit job/artifact/approval models before Set 4. |
| Backend preflight ideas | `backend/app/domains/deploy/readiness.py`, `resource_preflight.py`, related tests | PRD requires preflight and risk evidence. | Must be behind draft/preflight/plan contract; no direct execution. |
| Frontend dashboard/monitoring/list patterns | `App.jsx`, `InstanceList.jsx`, `infraExplorerScreen.js`, `apiV1ViewModels.js` | Current Dashboard and Infra Explorer use `/api/v1` read-only models. | Keep lifecycle controls out of first MVP view. |
| Frontend create wizard/readiness summaries | `CreateInstanceWizard.jsx`, `createVmFlow.js`, `createVmDefaults.js` | Current UX/testing material for `general-vm` creation and Review & Confirm. | Keep aligned to `/api/v1` draft/preflight/plan/review/approval and Terraform gates. |
| Frontend task board summary | `TaskBoard.jsx`, `jobsScreen.js` | Current Jobs/Runs UI reads `/api/v1/jobs` and artifacts. | Keep this aligned to the job/artifact substrate. |
| Terraform VM create base | `infra/terraform/main.tf` | Product eventually uses Terraform-backed powered-off create/apply. | Only fake/dry-run/plan in autonomous work; live IaC/commit/push/apply requires user approval. |
| Fast frontend pure test harness | `frontend/tests/*.mjs` | Set 0 verified it passes and it is good for RED-first UI utility tests. | Add new RED tests before utility/component changes. |

## 2. Drop candidates

| Area | Drop candidate | Why drop for MVP | Before-delete safety |
|---|---|---|---|
| LLM/chat backend | `backend/app/domains/llm/*` | PRD excludes LLM/chat from Gjallar MVP. | 2026-05-09: backed up and moved to legacy archive after forbidden endpoint guard passed. |
| LLM assistant frontend | `frontend/src/components/LlmInfraChat.jsx`, `/assistant` route | PRD excludes LLM/chat from Gjallar MVP. | Removed from active frontend; app navigation test guards absence. |
| Independent VM lifecycle write/destructive routes | `/instances/terminate`, `/instances/action`, `/instances/resources` in `backend/app/domains/proxmox/router.py` | First MVP excludes existing-VM independent power actions, delete/terminate, hard stop/reset, and live resource mutation. | 2026-05-09: legacy router unmounted from `main.py`; `backend/app/domains/proxmox` backed up and moved to legacy archive. |
| Frontend destructive/lifecycle controls | lifecycle action pieces in `InstanceList.jsx`, `lifecycleSafety.js` | Independent power/delete/reset actions are outside first MVP. | Removed from active frontend; infra explorer/navigation tests guard absence. |
| Legacy GitLab/staging/app-deploy migrations | `backend/alembic/versions/20260322_0002_*` through `20260426_0010_*` | Not part of Gjallar Proxmox operations MVP; carries old app/staging concerns. | Migration reset/removal is destructive and requires explicit approval. |
| Legacy Terraform state migration helper | `scripts/migrate_legacy_tf_state.py` | Tied to old backend service/state layout. | Do not delete without approval; record backup path first. |
| App deploy / arbitrary package bootstrap behavior | app-deploy paths in deploy service and Ansible playbook | PRD excludes app deploy, arbitrary shell, and DB migration from Gjallar MVP. | Confirm with tests that new flow cannot call these paths. |

## 3. Park candidates

| Area | Park candidate | Why park | Revisit when |
|---|---|---|---|
| Direct `/deploy` and `/provision` execution flow | `backend/app/domains/deploy/router.py`, `service.py`, legacy frontend API client | Contains reusable ideas but contract is wrong: it bypasses draft/plan/review/approval. | 2026-05-09: backend deploy package and legacy Terraform integration backed up and moved to archive. 2026-05-11: legacy frontend client/helpers are absent from active `src`. |
| Network/IP pool helpers | `backend/app/shared/network.py`, `/network/ip-pool/*` routes | Adjacent to static IP preflight, but PRD says NetworkProfile + Proxmox observed state are MVP evidence. | If preflight needs supplemental IP evidence after manifest/live inventory tests. |
| Operational risk thresholds/overrides/restore drills | risk config/overrides/state/restore modules and tests | Risks matter, but current policy editing/restore features exceed first create-flow MVP. | 2026-05-09: legacy backend risk modules/tests backed up and moved to archive; new `/api/v1/risks` remains to implement. |
| Alembic operational risk/restore migrations | `20260503_0011_*` through `20260504_0015_*` | Useful historical model ideas but not the new baseline schema yet. | When job/risk persistence schema is designed by tests. |
| Ansible bootstrap | `infra/ansible/playbook.yml` | Stage B minimal Ansible verify is deferred; current playbook contains app deploy/bootstrap behavior. | After Stage A smoke works and user approves later live/smoke scope. |
| Repo-local docs | `docs/**`, `README.md` | Historical context; shared PRD/root docs are source of truth. | After code rewrite stabilizes, refresh repo-local docs to match. |
| Codex/agent repo files | `.codex/*`, `AGENTS.md` | Operational helper material, not product runtime. | Only if repo cleanup scope is explicitly approved. |

## 4. Set 2 RED-test handoff

Next Set should write tests first and verify RED before implementation.

Recommended RED files/areas:

| Test area | Target behavior |
|---|---|
| `backend/tests/contracts/test_api_v1_shape.py` | `/api/v1` response/error shape exists and legacy `/api` routes are not the new contract. |
| `backend/tests/contracts/test_forbidden_mvp_endpoints.py` | No MVP endpoints for LLM/chat, hard stop/reset, delete/snapshot/rollback, raw shell, app deploy, DB migration, Heimdall registry write, Runtime Target write/active, or independent existing-VM power actions. |
| `backend/tests/manifests/test_profile_schema.py` | `general-vm` profile accepts defaults; future profiles are not create/apply enabled. |
| `backend/tests/manifests/test_network_profile.py` | `NetworkProfile.node_bridges` required; `yoonmanserver2` and `yoonmanserver3` resolve to `vmbr0`; DHCP/static accepted; default static. |
| `backend/tests/manifests/test_secret_redaction.py` | Raw secrets/token IDs/credentialed URLs are not serialized/logged; safe redaction marker appears. |
| `backend/tests/vm_create/test_draft_contract.py` | Create draft contract hides/rejects manual VMID and uses `general-vm` only. |
| `backend/tests/vm_create/test_preflight_policy.py` | Red/yellow/green policy blocks red risk; yellow requires ack later. |
| `frontend/tests/reviewSummary.test.mjs` | Review & Confirm shows required 13 fields. |
| `frontend/tests/createVmFlow.test.mjs` and `backend/tests/vm_create/test_preflight_policy.py` | Red risk disables approve/execute; yellow requires explicit ack. |
| `frontend/tests/createVmDefaults.test.mjs` | UI defaults match `general-vm`, static default, DHCP selectable, destructive controls absent. |

Backend blocker resolved: current backend pytest passes, and `/api/v1/jobs` plus `/api/v1/risks` read APIs are implemented.

## 5. Final Set 1 decision

Set 1 classification is complete enough for Set 2 to begin after docs are updated:

- All top-level backend/frontend/infra/docs/script areas have a Keep / Drop / Park classification.
- Drop/Park items were initially not deleted without approval; on 2026-05-09 the user approved a recoverable backend archive/move slice for deploy/LLM/proxmox legacy packages and related tests.
- Backend test dependency was recovered in the current Codex VM `.venv`; current backend pytest is GREEN.
- No commit, push, unrecoverable deletion, Terraform apply, Proxmox write, VM creation, or power action was performed.
