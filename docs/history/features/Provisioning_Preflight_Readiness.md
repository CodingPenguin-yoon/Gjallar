# Provisioning Preflight / Readiness

> Historical note:
> This `docs/history/features` file is historical implementation/planning context, not current product source of truth or current implementation status.
> Current MVP product source of truth is [`../../product/prd/drs-advisor/`](../../product/prd/drs-advisor/README.md); current implemented status is [`../../product/status/current.md`](../../product/status/current.md).
> This create-first material is historical/supporting capability context only. It must not define the next MVP success line or implementation order.

## Summary

Gjallar now exposes provisioning readiness before VM creation so operators can see whether the backend runtime is ready to run Terraform/Ansible-based VM provisioning.

## API

```text
GET /api/provision/readiness
```

The endpoint checks local runtime/config prerequisites and returns a safe summary:

- Terraform CLI availability
- ansible-playbook CLI availability
- `infra/terraform/main.tf` presence
- `infra/ansible/playbook.yml` presence
- required Proxmox API environment key presence
- `terraform validate` result

## Security

Proxmox credential values are never returned by the readiness API.
The API only reports whether required keys are configured and uses hidden/redacted details.

## Status model

```text
ready    - no blocking issue
warning  - no blocker, but attention is required
error    - VM provisioning should be fixed before proceeding
unknown  - frontend could not read readiness state
```

## Frontend

The Create Instance wizard now shows a `Provisioning Readiness` panel in the review step.
It displays:

- status badge
- OK/warning/error counts
- each readiness check
- next actions
- manual refresh button

Relevant files:

```text
frontend/src/components/CreateInstanceWizard.jsx
frontend/src/services/api.js
frontend/src/utils/provisioningReadiness.js
frontend/tests/provisioningReadiness.test.mjs
```

## Backend

Relevant files:

```text
backend/app/domains/deploy/readiness.py
backend/app/domains/deploy/router.py
backend/tests/test_provision_readiness.py
```

## Verification

The implementation was verified with:

```bash
node frontend/tests/provisioningReadiness.test.mjs
node frontend/tests/provisioningSummary.test.mjs
node frontend/tests/inventorySummary.test.mjs
node frontend/tests/lifecycleSafety.test.mjs
node frontend/tests/taskBoardSummary.test.mjs
node frontend/tests/monitoringSignals.test.mjs
cd frontend && npm run lint && npm run build
cd backend && PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"
python3 -m compileall backend/app backend/tests
git diff --check
```

Runtime smoke:

```text
GET http://127.0.0.1:8001/api/provision/readiness
HTTP 200
status: ready
```

## Current limitation

This is a runtime/config preflight, not a full Proxmox resource validation yet.
Future improvements should validate selected template, storage, network bridge, cloud-init behavior, and guest SSH readiness before/after provisioning.
