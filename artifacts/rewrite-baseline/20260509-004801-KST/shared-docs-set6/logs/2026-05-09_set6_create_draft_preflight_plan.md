# Set 6 completion — Create draft / preflight / plan

Completed: 2026-05-09 03:05 KST
Project: Gjallar
Repo: codex-vm:/home/yoon/projects/Gjallar
Branch: rewrite/prd-v1-mvp

## Goal

Implement the non-destructive `general-vm` create draft, preflight, and dry-run plan contract on top of Set 3 manifests, Set 4 artifact substrate, and Set 5 fake/read-only Proxmox inventory.

## TDD evidence

RED before production code:

```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/vm_create/test_draft_contract.py'
# FAILED (failures=2): No module named 'app.vm_create'

ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/vm_create/test_draft_contract.py backend/tests/vm_create/test_preflight_plan_contract.py backend/tests/contracts/test_api_v1_vm_create.py'
# FAILED (failures=7): missing app.vm_create modules and /api/v1/vm-create route surface
```

GREEN after implementation:

```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/vm_create/test_draft_contract.py backend/tests/vm_create/test_preflight_plan_contract.py backend/tests/contracts/test_api_v1_vm_create.py'
# Ran 7 tests in 0.576s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/contracts/test_api_v1_shape.py backend/tests/manifests/test_profile_schema.py backend/tests/manifests/test_network_profile.py backend/tests/manifests/test_secret_redaction.py backend/tests/jobs/test_artifact_store.py backend/tests/jobs/test_job_models.py backend/tests/proxmox/test_inventory_adapter.py backend/tests/contracts/test_api_v1_inventory.py backend/tests/vm_create/test_draft_contract.py backend/tests/vm_create/test_preflight_plan_contract.py backend/tests/contracts/test_api_v1_vm_create.py'
# Ran 23 tests in 0.562s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && git diff --check && git status --short --branch'
# PASS; status remains uncommitted/untracked on rewrite/prd-v1-mvp
```

Blocked full backend pytest check:

```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && backend/.venv/bin/python -m pytest backend/tests/vm_create -q'
# /home/yoon/projects/Gjallar/backend/.venv/bin/python: No module named pytest
```

## Implemented

- New focused Set 6 tests:
  - `backend/tests/vm_create/test_preflight_plan_contract.py`
  - `backend/tests/contracts/test_api_v1_vm_create.py`
- New non-destructive backend package:
  - `backend/app/vm_create/drafts.py`
  - `backend/app/vm_create/preflight.py`
  - `backend/app/vm_create/planner.py`
  - `backend/app/vm_create/models.py`
- `/api/v1` route surface for dry-run create flow:
  - `POST /api/v1/vm-create/drafts`
  - `POST /api/v1/vm-create/{draft_id}/preflight`
  - `POST /api/v1/vm-create/{draft_id}/plan`
- Preflight checks cover profile schema, template readiness, node online, storage, bridge mapping/existence, VMID/name/static-IP availability, state lock placeholder, destroy/delete absence, and read-only credential scope.
- Plan output includes VM name, VMID, node, storage, template, hardware, network/IP, Terraform state path, first-power-on flag, smoke timeouts, risk summary, plan artifact reference, and planned Git diff summary.

## Remaining intentional RED / deferred work

- `backend/tests/vm_create/test_preflight_policy.py` remains Set 7 scope for approval gate semantics.
- `backend/tests/contracts/test_jobs_risks_contract.py` remains later Jobs/Risks read API scope.
- `backend/tests/contracts/test_forbidden_mvp_endpoints.py` remains legacy cutover/hardening scope because legacy `/api` routers are still mounted.
- Frontend RED tests for Review Summary, risk policy, and Create VM defaults remain later frontend/UI scope.
- Backend `pytest` command remains blocked until non-destructive dependency recovery is verified.

## Safety

No commit, push, delete, Terraform apply, Proxmox write, VM create, or power action was run.
