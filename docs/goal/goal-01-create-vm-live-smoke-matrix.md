# Goal 1: Create VM Live Smoke Matrix

Status: completed on 2026-05-28.

Evidence is recorded in
`docs/operations/create-vm-live-smoke-2026-05-28.md`.

## Objective

Prove the current Create VM path against a real Proxmox target, record
evidence, and update docs without expanding product scope.

## Constraints

- no live Proxmox mutation/smoke without explicit active-session user approval
- Do not commit secrets, API tokens, SSH private keys, or raw sensitive
  payloads.
- Any live cleanup decision must be explicit.
- DRS migration execution is out of scope.

## Scope

1. Read current runbook and Create VM docs:
   - `docs/operations/runbook.md`
   - `docs/current/README.md`
   - `docs/current/top-tabs/04-create-vm.md`
   - `docs/architecture/VM_PROVISIONING_CONTRACT.md`
   - `docs/engineering/NEXT_SESSION_HANDOFF.md`
2. Confirm target details with the user before mutation:
   - Proxmox cluster/API URL
   - target node
   - template VMID/node
   - storage
   - bridge
   - VMID/name range
   - static IP/DHCP choice
   - cleanup policy
3. Before live mutation, run non-live validation:
   - `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/contracts backend/tests/vm_create backend/tests/proxmox`
   - `node --test frontend/tests/createVmFlow.test.mjs`
   - `git diff --check`
4. With explicit approval, run and record:
   - default `stopped` creation
   - `boot_and_verify` creation with DHCP or approved network values
   - static IP creation with explicit `static_ip`, `prefix`, and `gateway`
   - one invalid target combination to verify operator-facing failure behavior
5. For each live run, record:
   - job id
   - request id
   - VMID/name
   - target node
   - power policy
   - actor fields
   - risk level
   - artifact ids
   - `observed_after`
   - guest-agent IP and cloud-init evidence when applicable
   - cleanup decision
6. Update docs with observed results and any remaining risks.

## Out Of Scope

- DRS migration execution.
- Post-create readiness evidence beyond the approved Create VM smoke matrix.
- Background reconciliation worker.
- Automatic cleanup or delete unless separately approved.

## Definition Of Done

- Live smoke evidence is recorded in docs.
- Create VM runbook reflects actual observed behavior.
- No secrets, API tokens, SSH private keys, or raw sensitive payloads are
  committed.
- Required validation passes.
- Any live cleanup decision is explicit.
