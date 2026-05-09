# Gjallar Legacy Backend Archive

Archived at: 2026-05-09_1047KST
Approval: user requested legacy backup-folder cleanup in Discord thread.

## Scope

This archive removes PRD v1 MVP Drop/Park legacy backend packages from the active import tree while retaining recoverable copies.
No commit, push, Proxmox action, Terraform apply, VM create, or power action was performed by this archive step.

## Backup artifact created before moves

- `artifacts/legacy-backend-2026-05-09_1047KST.tar.gz`
- SHA256: `9291f0430202185c9e7680901fdc35eac4a798d3f3237d94409ef6357bd5a902`

## Moved source directories

- `backend/app/domains/deploy` -> `archive/legacy-backend/2026-05-09_1047KST/backend/app/domains/deploy`
- `backend/app/domains/llm` -> `archive/legacy-backend/2026-05-09_1047KST/backend/app/domains/llm`
- `backend/app/domains/proxmox` -> `archive/legacy-backend/2026-05-09_1047KST/backend/app/domains/proxmox`
- `backend/app/integrations/terraform` -> `archive/legacy-backend/2026-05-09_1047KST/backend/app/integrations/terraform`

## Parked legacy tests

Parked tests use `.py.legacy` suffix so they are preserved but not collected by pytest.

- `backend/tests/test_deployment_service_logs.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_deployment_service_logs.py.legacy`
- `backend/tests/test_operational_restore_drills.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_operational_restore_drills.py.legacy`
- `backend/tests/test_operational_risk.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_operational_risk.py.legacy`
- `backend/tests/test_operational_risk_overrides.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_operational_risk_overrides.py.legacy`
- `backend/tests/test_operational_risk_state.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_operational_risk_state.py.legacy`
- `backend/tests/test_operational_risk_thresholds.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_operational_risk_thresholds.py.legacy`
- `backend/tests/test_optional_readonly_ssh_collector.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_optional_readonly_ssh_collector.py.legacy`
- `backend/tests/test_provision_readiness.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_provision_readiness.py.legacy`
- `backend/tests/test_provision_route.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_provision_route.py.legacy`
- `backend/tests/test_proxmox_service_performance.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_proxmox_service_performance.py.legacy`
- `backend/tests/test_resource_preflight.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_resource_preflight.py.legacy`
- `backend/tests/test_terraform_service_logging.py` -> `archive/legacy-backend/2026-05-09_1047KST/backend/tests/test_terraform_service_logging.py.legacy`

## Kept active for now

- `backend/app/domains/task` remains active until `/api/v1/jobs` and artifact read APIs replace legacy task/log routes.
- `backend/app/integrations/ansible` remains active/parked-in-place pending Stage B scope decisions.
- New PRD v1 MVP packages remain active under `backend/app/api/v1`, `backend/app/core`, `backend/app/jobs`, `backend/app/manifests`, `backend/app/proxmox`, and `backend/app/vm_create`.
