# Gjallar Code Inventory

Last updated: 2026-05-09 01:11 KST

## 0. Purpose

This document records the fresh Set 1 inventory of the current Gjallar codebase before the PRD rewrite continues. It replaces the earlier policy-only placeholder for implementation handoff.

The existing code is **not** the source of truth. The locked PRD is the source of truth; existing modules are only material to Keep / Drop / Park after evidence-based review.

## 1. Inventory scope and evidence

- Shared PRD source of truth: `/mnt/hermes_data/프로젝트/Gjallar/PRD/`
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

Current route baseline:

- Backend currently mounts legacy routers under `/api`, not the PRD target `/api/v1`.
- Backend legacy route groups include deploy/provision, task/logs, Proxmox inventory/actions/risk, monitoring/network IP pool, and LLM/chat.
- Frontend legacy routes include `/`, `/list`, `/tasks`, `/monitoring`, `/risks`, `/assistant`, and `/create`.

## 2. Backend inventory

| Group | Status for rewrite | Evidence | Notes |
|---|---|---|---|
| App entrypoint / legacy router mounting | Park | `backend/app/main.py` | Keep as reference only. New API must add `/api/v1`; existing `/api` route shape must not drive the PRD contract. |
| Read-only Proxmox inventory and VM detail | Keep candidate | `backend/app/domains/proxmox/router.py`, `backend/app/domains/proxmox/service.py`, tests around Proxmox service/performance | Aligns with Dashboard / Infra Explorer / Nodes / VMs / VM Detail. Reuse only read-only logic after contract tests and redaction review. |
| Proxmox monitoring signals | Keep candidate | `/monitoring/nodes`, `/monitoring/vms/...` routes in `backend/app/domains/proxmox/router.py` | Useful for read-only dashboard/inventory slices. Must be reshaped under `/api/v1`. |
| Task/log tracking | Keep candidate | `backend/app/domains/task/router.py`, `backend/app/shared/tasks.py`, `backend/app/shared/task_store.py`, `backend/app/shared/platform_models.py`, `backend/alembic/versions/20260322_0001_platform_task_tables.py` | MVP needs jobs/artifacts. Existing task persistence can inform Set 4 job/artifact substrate. |
| Provisioning readiness / resource preflight | Keep candidate | `backend/app/domains/deploy/readiness.py`, `backend/app/domains/deploy/resource_preflight.py`, `backend/tests/test_provision_readiness.py`, `backend/tests/test_resource_preflight.py` | Useful preflight ideas. Must be re-tested against PRD `draft -> preflight -> plan -> Review & Confirm` contract. |
| Direct deploy/provision execution | Park | `backend/app/domains/deploy/router.py`, `backend/app/domains/deploy/service.py` | Current route can jump to execution. PRD requires draft/plan/review/approval and no live side effect in autonomous Sets 0~7. |
| Terraform integration code | Park / later Keep candidate | `backend/app/integrations/terraform/`, `backend/tests/test_terraform_service_logging.py`, `backend/tests/test_terraform_vm_ip_output_safety.py` | Potentially useful for Set 8+, but live IaC write/commit/push/apply are approval-gated. Keep as reference until fake/dry-run contract tests exist. |
| Network/IP pool helpers | Park | `backend/app/shared/network.py`, `/network/ip-pool/*` routes | Adjacent to preflight, but PRD MVP evidence is NetworkProfile manifest plus Proxmox observed state, not an autonomous IPAM authority. |
| Operational risk core | Park / later Keep candidate | `backend/app/domains/proxmox/risk.py`, `risk_config.py`, `risk_overrides.py`, `risk_state.py`, `restore_drills.py`, `backend/tests/test_operational_risk*.py` | Risks are MVP-visible, but current thresholds/overrides/restore drills are broader than first create-flow contract. Extract only tested display/policy pieces later. |
| Independent VM lifecycle writes | Drop for MVP | `/instances/terminate`, `/instances/action`, `/instances/resources` in `backend/app/domains/proxmox/router.py` | Existing VM power/action/resource mutation is excluded from first MVP. Deletion/removal still requires explicit user approval; Set 2 should add forbidden endpoint tests first. |
| LLM/chat domain | Drop | `backend/app/domains/llm/*`, `Test/llm_test.py` | PRD explicitly excludes LLM/chat from Gjallar MVP. Do not delete without approval; first add forbidden/exclusion tests. |
| Alembic GitLab/staging/app-deploy migrations | Drop candidate | `backend/alembic/versions/20260322_0002_*` through `20260426_0010_*` | Pre-rewrite GitLab/staging/app-deploy concerns conflict with the locked PRD. Actual migration reset/removal needs explicit approval. |
| Alembic operational risk / restore migrations | Park | `backend/alembic/versions/20260503_0011_*` through `20260504_0015_*` | Could inform later risk/job storage but should not be blindly carried into the new core schema. |
| Backend tests | Keep as regression ideas, not authoritative contracts | `backend/tests/*.py` | Pytest is currently missing in `backend/.venv`, so backend GREEN cannot be claimed until dependency setup is fixed. |

## 3. Frontend inventory

| Group | Status for rewrite | Evidence | Notes |
|---|---|---|---|
| App shell/navigation | Keep candidate | `frontend/src/App.jsx` | Existing shell can inform navigation, but route names should change toward Dashboard / Infra Explorer / Create VM / Jobs / Risks. |
| Overview dashboard | Keep candidate | `frontend/src/components/OverviewDashboard.jsx` | Useful dashboard summary patterns. Must align with `/api/v1` data shapes. |
| Inventory list/detail patterns | Keep candidate | `frontend/src/components/InstanceList.jsx`, `frontend/src/utils/inventorySummary.js`, `frontend/tests/inventorySummary.test.mjs` | Useful for Infra Explorer read-only VM list/detail, but lifecycle action controls must be excluded. |
| Monitoring dashboard/signals | Keep candidate | `frontend/src/components/MonitoringDashboard.jsx`, `frontend/src/utils/monitoringSignals.js`, `frontend/tests/monitoringSignals.test.mjs` | Good source for read-only node/VM visibility. |
| Create wizard UX shell | Keep candidate | `frontend/src/components/CreateInstanceWizard.jsx`, `frontend/src/utils/provisioningReadiness.js`, `resourcePreflight.js`, `provisioningSummary.js`, related tests | Can seed `general-vm` wizard and Review & Confirm summaries, but direct submit/payload must be replaced by draft/preflight/plan/approve contract. |
| Legacy provisioning payload/client | Park | `frontend/src/services/api.js`, `frontend/src/utils/provisioningPayload.js`, `frontend/tests/provisioningPayload.test.mjs` | Current client targets legacy `/api/provision`. Preserve only as reference until `/api/v1` tests are RED/GREEN. |
| Operational risk UI | Park / later Keep candidate | `frontend/src/components/OperationalRiskDashboard.jsx`, `frontend/src/utils/operationalRisk.js`, `frontend/tests/operationalRisk.test.mjs` | Risk display belongs in MVP, but suppression/threshold editing is broader than first create-flow scope. |
| Task board | Keep candidate | `frontend/src/components/TaskBoard.jsx`, `frontend/src/utils/taskBoardSummary.js`, `frontend/tests/taskBoardSummary.test.mjs` | Can inform Jobs/Runs UI. Needs job/artifact model alignment. |
| Lifecycle safety/destructive UI | Drop for MVP | `frontend/src/utils/lifecycleSafety.js`, `frontend/tests/lifecycleSafety.test.mjs`, lifecycle controls inside `InstanceList.jsx` | Independent power actions/terminate/hard stop/reset/delete are excluded from first MVP. Keep tests as forbidden-scope reference before deletion. |
| LLM assistant UI | Drop | `frontend/src/components/LlmInfraChat.jsx`, `/assistant` route in `frontend/src/App.jsx` | PRD excludes LLM/chat from Gjallar MVP. |
| Frontend tests | Keep as fast harness | `frontend/tests/*.mjs` | Set 0 ran all current frontend pure tests successfully. Use this harness for Set 2+ RED tests around pure UI policy utilities. |

## 4. Infra, scripts, and repo-local docs inventory

| Group | Status for rewrite | Evidence | Notes |
|---|---|---|---|
| Terraform VM clone/provisioning base | Keep candidate for later gated Set | `infra/terraform/main.tf`, Terraform safety tests | The Terraform-backed VM create path is part of the product direction, but live commit/push/apply and Set 8+ side effects require explicit approval. |
| Ansible bootstrap playbook | Park | `infra/ansible/playbook.yml` | PRD Stage A is smoke only. Minimal Ansible verification is deferred; app deploy/bootstrap behavior is not first MVP. |
| Legacy Terraform state migration script | Drop candidate | `scripts/migrate_legacy_tf_state.py` | Tied to old service/state layout. Do not delete without approval. |
| Repo-local architecture/provisioning docs | Park | `docs/README.md`, `docs/architecture/*`, `docs/features/*`, `docs/operations/*`, `docs/roadmap/*` | Useful historical context, but shared PRD/root docs are source of truth. Repo docs still mention direct `/api/provision` era behavior. |
| Codex config / agent prompts | Park | `.codex/*`, `AGENTS.md` | Operational support files; not part of product MVP. Preserve unless the user asks for repo cleanup. |

## 5. Slow/backend risk notes

- Backend tests cannot currently be run because `backend/.venv/bin/python -m pytest backend/tests -q` fails with `No module named pytest`.
- Do not retry the same pytest command unchanged. Recovery should add/confirm an explicit test dependency setup before Set 2+ backend RED/GREEN verification.
- Existing backend route shape and direct execute paths are the main PRD mismatch; new tests should lock `/api/v1` behavior before code is changed.

## 6. Set 2 handoff

Set 2 should start with RED tests, not implementation. Priority RED targets:

1. `/api/v1` response/error shape.
2. Manifest/profile/network schema for `general-vm`, `server-net`, node bridge mapping, DHCP/static, default static IP mode, hardware defaults, cloud-init user, and password login disabled.
3. Forbidden MVP endpoints: LLM/chat, independent VM power action, terminate/delete, snapshot/rollback, hard stop/reset, raw shell, app deploy, DB migration, Heimdall registry write, Runtime Target write/`active=true`.
4. Create-flow contract: draft, preflight, plan, Review & Confirm payload, approval checksum/artifact references.
5. Job/artifact substrate schema for Set 4: no fake approval checksum without stored artifact.
6. Frontend pure utility RED tests for review summary, risk policy, and create VM defaults.

## 7. Safety conclusion

Set 1 is classification only. `Drop` and `Park` do **not** authorize deletion, renaming, migration reset, commit, push, Terraform apply, or Proxmox write. Those remain explicit approval gates.
