# Set 5 completion — Read-only Proxmox inventory adapter

Completed: 2026-05-09 02:42 KST
Project: Gjallar
Thread ownership: Gjallar only
Repo: `codex-vm:/home/yoon/projects/Gjallar`
Branch: `rewrite/prd-v1-mvp`
HEAD: `29412e8`

## Goal

Create a non-destructive, fake/read-only Proxmox inventory adapter and wire `/api/v1` inventory endpoints to the adapter shape before any live Proxmox mutation work.

## RED-first evidence

Focused Set 5 tests were written before production code:

- `backend/tests/proxmox/test_inventory_adapter.py`
- `backend/tests/contracts/test_api_v1_inventory.py`

Initial RED command:

```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/proxmox/test_inventory_adapter.py backend/tests/contracts/test_api_v1_inventory.py'
```

Initial RED result:

```text
FAILED (failures=5)
- `app.proxmox` missing
- `/api/v1/storage` missing
- existing `/api/v1` skeleton inventory responses lacked read-only adapter metadata/payload
```

Additional secret-safety RED check was added for credentialed URL redaction after observing control characters in the redacted URL output:

```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend.tests.proxmox.test_inventory_adapter.ProxmoxInventoryAdapterTests.test_connection_context_and_snapshot_are_secret_safe'
```

RED result:

```text
FAILED (failures=1)
AssertionError: '\x01' unexpectedly found in redacted `api_url`
```

## GREEN implementation

Remote code added/changed:

- `backend/app/proxmox/__init__.py`
- `backend/app/proxmox/models.py`
- `backend/app/proxmox/inventory.py`
- `backend/app/api/v1/router.py`
- `backend/app/core/redaction.py`
- `backend/tests/proxmox/test_inventory_adapter.py`
- `backend/tests/contracts/test_api_v1_inventory.py`

Implemented behavior:

- `FakeProxmoxInventoryAdapter` fixture-backed read-only adapter.
- Dataclass inventory models for nodes, VMs, templates, storage, networks, guest-agent/IP, and snapshots.
- `/api/v1/nodes`, `/api/v1/vms`, `/api/v1/vms/{vmid}`, `/api/v1/templates`, `/api/v1/storage`, `/api/v1/networks`, and cluster summary now return adapter-backed read-only payloads with `meta.source=fake_read_only` where relevant.
- Adapter exposes no create/apply/delete/power methods.
- Credentialed URL redaction no longer emits control characters and still redacts raw credentials.

## Verification

```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/proxmox/test_inventory_adapter.py backend/tests/contracts/test_api_v1_inventory.py'
# GREEN: Ran 5 tests in 0.540s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/contracts/test_api_v1_shape.py backend/tests/manifests/test_profile_schema.py backend/tests/manifests/test_network_profile.py backend/tests/manifests/test_secret_redaction.py backend/tests/jobs/test_artifact_store.py backend/tests/jobs/test_job_models.py backend/tests/proxmox/test_inventory_adapter.py backend/tests/contracts/test_api_v1_inventory.py'
# GREEN: Ran 16 tests in 0.551s, OK

ssh codex-vm 'cd /home/yoon/projects/Gjallar && git diff --check'
# PASS

ssh codex-vm 'cd /home/yoon/projects/Gjallar && backend/.venv/bin/python -m pytest backend/tests/proxmox backend/tests/contracts/test_api_v1_inventory.py -q'
# BLOCKED: No module named pytest
```

Backend full pytest remains blocked by the known missing pytest dependency; focused Set 5 verification uses the documented `unittest` fallback.

## Remaining intentional RED / deferred tests

These were not expanded into Set 5 scope:

- `backend/tests/contracts/test_forbidden_mvp_endpoints.py::test_legacy_destructive_and_llm_routes_are_not_exposed_in_mvp` remains RED until later legacy cutover/hardening.
- `backend/tests/contracts/test_jobs_risks_contract.py` remains RED because read API routes for Jobs/Risks are later scope.
- `backend/tests/vm_create/test_draft_contract.py` remains RED and is the main Set 6 draft target.
- `backend/tests/vm_create/test_preflight_policy.py` remains RED and should be split/handled across Set 6 preflight and Set 7 approval policy.
- Frontend pure RED tests for Review Summary, risk policy, and Create VM defaults remain later frontend/UI scope.

## Repo status

```text
## rewrite/prd-v1-mvp
 M backend/app/main.py
?? artifacts/
?? backend/app/api/
?? backend/app/core/
?? backend/app/jobs/
?? backend/app/manifests/
?? backend/app/proxmox/
?? backend/tests/contracts/
?? backend/tests/jobs/
?? backend/tests/manifests/
?? backend/tests/proxmox/
?? backend/tests/vm_create/
?? frontend/tests/createVmDefaults.test.mjs
?? frontend/tests/reviewSummary.test.mjs
?? frontend/tests/riskPolicy.test.mjs
```

Existing uncommitted Set 0~4 artifacts/tests/packages remain intentional. Set 5 adds the `backend/app/proxmox/` package and `backend/tests/proxmox/` tests plus `/api/v1` inventory router changes.

## Safety

No commit, push, deletion, Terraform apply, live IaC write, Proxmox write, VM create, or power action was run.

## Next Set

Promote to `Set 6 — Create draft / preflight / plan` as the next documented non-destructive TDD Set. The next worker should re-check Set 5 focused GREEN tests, then write/confirm RED tests for `app.vm_create` draft/preflight/plan before production code.
