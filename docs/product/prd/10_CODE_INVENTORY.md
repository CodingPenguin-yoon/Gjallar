# Gjallar Code Inventory

Last updated: 2026-05-11 KST

## DRS Advisor update

Current MVP product source of truth is `drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.

This inventory is now read through the DRS Advisor direction. Create VM remains a supporting existing capability, but it must not define the next MVP success line or implementation order. The next implementation sequence is `drs-advisor/05_IMPLEMENTATION_PLAN.md`.

Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.

## 0. Purpose

This document records the Set 1 inventory plus the current cleanup status of the Gjallar codebase as the PRD rewrite continues.

The existing code is **not** the product source of truth. `drs-advisor/` is the current MVP product source of truth; existing modules are only material to Keep / Drop / Park after evidence-based review.

## 1. Inventory scope and evidence

- Shared PRD source of truth: `docs/product/prd/drs-advisor/`
- Remote repo: `codex-vm:/home/yoon/projects/Gjallar`
- Branch: `rewrite/prd-v1-mvp`
- Head: `29412e8`
- Set 0 baseline artifact: `artifacts/rewrite-baseline/20260509-004801-KST/`
- Set 0 inventory files used:
  - `status.txt`
  - `tracked-files.txt`
  - `route-inventory.txt`
  - `test-inventory.txt`
  - `verification-results.txt`
- Codex read-only inventory helper output: `/tmp/gjallar_set1_codex_inventory.md` on codex-vm
- `.env` exists locally on the repo host but was not read or copied. It remains outside this inventory.

Current tracked top-level count from Set 0:

| Area | Count / note |
|---|---:|
| Total tracked files | 144 |
| `backend/` | 69 |
| `frontend/` | 40 |
| `infra/` | 5 |
| `docs/` | 14 |
| `artifacts/` | 0 tracked; Set 0 artifact is intentional untracked evidence |

Current active route baseline:

- Backend mounts the active PRD contract under `/api/v1`.
- Legacy `/api` deploy/provision/task/log/LLM route groups are not active.
- Frontend active routes are Dashboard, Infra Explorer, Networks, Create VM, Placement, Jobs/Runs, and Risks/Alerts.
- `/placement` is currently read-only Placement. DRS Advisor target work should relabel/expand it rather than treating the old Placement PRD as the active product goal.

## 2. Backend inventory

| Group | Status for rewrite | Evidence | Notes |
|---|---|---|---|
| App entrypoint / active router mounting | Keep | `backend/app/main.py`, `backend/app/api/v1/router.py` | Active backend mounts only the explicit `/api/v1` operator surface plus health/root checks. |
| Read-only Proxmox inventory and VM detail | Keep | `backend/app/proxmox/inventory.py`, `backend/app/proxmox/models.py`, `backend/tests/proxmox/test_inventory_adapter.py` | Current inventory adapter supports live read-only Proxmox data with fake fallback and redaction. |
| Proxmox monitoring signals | Keep through dashboard model | `/api/v1/cluster/summary`, `/api/v1/nodes`, `/api/v1/vms`, dashboard logic in `frontend/src/App.jsx` | Current dashboard uses live read-only inventory shape instead of legacy monitoring routes. |
| Job/artifact tracking | Keep | `backend/app/jobs/*`, `backend/tests/jobs/*` | Active Jobs/Runs substrate records Create VM progress and artifacts under `GJALLAR_RUNS_ROOT`. |
| Create VM preflight/readiness | Keep as supporting capability | `backend/app/vm_create/*`, `backend/tests/vm_create/*` | Current flow uses draft -> preflight -> plan -> Review & Confirm -> gated Terraform plan/apply. Reuse approval/artifact ideas for DRS, but do not use Create VM as the next MVP success line. |
| DRS Advisor backend API | Gap | no `/api/v1/drs/*` implementation yet | Add backend recommendation read model before migration execution. |
| VM identity/fingerprint/policy | Gap | no DB-backed DRS tables yet | Required before Allowed VM execution; VMID alone is only a locator. |
| Proxmox migration/UPID/reconciliation | Gap | no mutation client for DRS migration yet | Must be implemented with final pre-check, operation lock, UPID tracking, post-check, and Reconcile Now. |
| Direct deploy/provision execution | Removed from active tree | legacy backend archive noted in `11_KEEP_DROP_PARK.md` | Wrong contract for MVP; forbidden endpoint tests guard against reintroduction. |
| Terraform integration code | Keep | `backend/app/vm_create/terraform_runner.py`, `infra/terraform/main.tf`, Terraform safety tests | Terraform is now wired through approved Create VM plan/apply gates and powered-off create policy. |
| Network/IP policy helpers | Keep | `backend/app/network_policy.py`, `backend/tests/contracts/test_api_v1_network_policy.py` | Current MVP evidence is IaC NetworkPolicy plus Proxmox observed bridge inventory. |
| Operational risk display | Keep | `backend/app/api/v1/router.py`, `frontend/src/components/OperationalRiskDashboard.jsx`, `frontend/src/utils/risksScreen.js` | Current risks API is read-only and derived from job records. |
| Independent VM lifecycle writes | Removed / forbidden for MVP | `backend/tests/contracts/test_forbidden_mvp_endpoints.py` | Existing-VM power/delete/reset/resource mutations are not active. |
| LLM/chat domain | Removed / forbidden for MVP | `backend/tests/contracts/test_forbidden_mvp_endpoints.py`, `frontend/tests/appNavigation.test.mjs` | PRD excludes LLM/chat from Gjallar MVP. |
| Alembic GitLab/staging/app-deploy migrations | Drop candidate | `backend/alembic/versions/20260322_0002_*` through `20260426_0010_*` | Pre-rewrite GitLab/staging/app-deploy concerns conflict with the locked PRD. Actual migration reset/removal needs explicit approval. |
| Alembic operational risk / restore migrations | Park | `backend/alembic/versions/20260503_0011_*` through `20260504_0015_*` | Could inform later risk/job storage but should not be blindly carried into the new core schema. |
| Backend tests | Keep | `backend/tests/*.py` | Current backend pytest passes in the local venv. |

## 3. Frontend inventory

| Group | Status for rewrite | Evidence | Notes |
|---|---|---|---|
| App shell/navigation | Keep | `frontend/src/App.jsx` | Current navigation is Dashboard / Infra Explorer / Networks / Create VM / Placement / Jobs/Runs / Risks/Alerts. |
| Overview dashboard | Keep | `frontend/src/App.jsx` | Current dashboard summary reads `/api/v1` data shapes directly. |
| Inventory list/detail patterns | Keep | `frontend/src/components/InstanceList.jsx`, `frontend/src/utils/infraExplorerScreen.js`, `frontend/src/utils/apiV1ViewModels.js`, `frontend/tests/infraExplorerScreen.test.mjs` | Current Infra Explorer uses `/api/v1` read-only VM list/detail models; legacy standalone inventory summary utilities were removed. |
| Monitoring dashboard/signals | Dropped from active code | `/api/v1` dashboard model in `frontend/src/App.jsx` | Legacy standalone monitoring signal utilities were removed after their useful read-only summary behavior was folded into the current dashboard and inventory view models. |
| Create wizard UX shell | Keep | `frontend/src/components/CreateInstanceWizard.jsx`, `frontend/src/utils/createVmFlow.js`, `frontend/tests/createVmFlow.test.mjs` | Current wizard uses `/api/v1` draft/preflight/plan/approval/Terraform gates. Legacy provisioning helpers are removed from active `src`. |
| Legacy provisioning payload/client | Removed from active tree | `frontend/tests/appNavigation.test.mjs`, `frontend/tests/apiV1Client.test.mjs` | `frontend/src/services/api.js` and old provisioning helpers must stay absent. |
| Operational risk UI | Keep | `frontend/src/components/OperationalRiskDashboard.jsx`, `frontend/src/utils/risksScreen.js`, `frontend/tests/risksScreen.test.mjs` | Current screen is read-only and aligned to `/api/v1/risks`. |
| Task board | Keep | `frontend/src/components/TaskBoard.jsx`, `frontend/src/utils/jobsScreen.js`, `frontend/tests/jobsScreen.test.mjs` | Current Jobs/Runs UI is aligned to `/api/v1/jobs` and job/artifact models; legacy task summary utility was removed. |
| Placement screen/model | Keep as DRS seed | `frontend/src/components/PlacementScreen.jsx`, `frontend/src/utils/placement.js`, `frontend/tests/placement.test.mjs` | Current model is read-only and frontend-derived. DRS Advisor should move recommendation authority to backend and add identity/policy/final-pre-check/execution gaps. |
| Lifecycle safety/destructive UI | Removed / forbidden for MVP | `frontend/tests/appNavigation.test.mjs`, `frontend/tests/infraExplorerScreen.test.mjs` | Independent power actions/terminate/hard stop/reset/delete are excluded from first MVP. |
| LLM assistant UI | Removed / forbidden for MVP | `frontend/tests/appNavigation.test.mjs` | PRD excludes LLM/chat from Gjallar MVP. |
| Frontend tests | Keep as fast harness | `frontend/tests/*.mjs` | Set 0 ran all current frontend pure tests successfully. Use this harness for Set 2+ RED tests around pure UI policy utilities. |

## 4. Infra, scripts, and repo-local docs inventory

| Group | Status for rewrite | Evidence | Notes |
|---|---|---|---|
| Terraform VM clone/provisioning base | Keep candidate for later gated Set | `infra/terraform/main.tf`, Terraform safety tests | The Terraform-backed VM create path is part of the product direction, but live commit/push/apply and Set 8+ side effects require explicit approval. |
| Ansible bootstrap playbook | Park | `infra/ansible/playbook.yml` | PRD Stage A is smoke only. Minimal Ansible verification is deferred; app deploy/bootstrap behavior is not first MVP. |
| Legacy Terraform state migration script | Drop candidate | `scripts/migrate_legacy_tf_state.py` | Tied to old service/state layout. Do not delete without approval. |
| Repo-local architecture/provisioning docs | Park | `docs/README.md`, `docs/engineering/architecture/*`, `docs/history/features/*`, `docs/history/operations/*`, `docs/history/roadmap/*` | `docs/engineering/architecture/*` can describe current code architecture and DRS target gaps; `docs/history/features`, `docs/history/operations`, and `docs/history/roadmap` are historical context. Current product source of truth is `docs/product/prd/drs-advisor/`. |
| Codex config / agent prompts | Park | `.codex/*`, `AGENTS.md` | Operational support files; not part of product MVP. Preserve unless the user asks for repo cleanup. |

## 5. Slow/backend risk notes

- Current backend pytest is GREEN in the local venv.
- `/api/v1/jobs` and `/api/v1/risks` read APIs are implemented as read-only MVP summaries.
- Forbidden endpoint tests guard the legacy deploy/provision/destructive/LLM surface.

## 6. Historical Set 2 handoff

The following handoff reflects the older create-first implementation sequence.
It is useful context only and must not define the next MVP success line or implementation order.
Next DRS Advisor work starts from `drs-advisor/05_IMPLEMENTATION_PLAN.md`.

Set 2 originally started with RED tests, not implementation. Priority RED targets were:

1. `/api/v1` response/error shape.
2. Manifest/profile/network schema for `general-vm`, `server-net`, node bridge mapping, DHCP/static, default static IP mode, hardware defaults, cloud-init user, and password login disabled.
3. Forbidden MVP endpoints: LLM/chat, independent VM power action, terminate/delete, snapshot/rollback, hard stop/reset, raw shell, app deploy, DB migration, Heimdall registry write, Runtime Target write/`active=true`.
4. Create-flow contract: draft, preflight, plan, Review & Confirm payload, approval checksum/artifact references.
5. Job/artifact substrate schema for Set 4: no fake approval checksum without stored artifact.
6. Frontend pure utility RED tests for review summary, risk policy, and create VM defaults.

## 7. Safety conclusion

Set 1 is classification only. `Drop` and `Park` do **not** authorize deletion, renaming, migration reset, commit, push, Terraform apply, or Proxmox write. Those remain explicit approval gates.
