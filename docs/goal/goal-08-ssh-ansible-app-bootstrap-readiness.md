# Goal 8: SSH/Ansible/App Bootstrap Readiness

Status: safe no-live readiness intent slice implemented; live SSH/Ansible/app
bootstrap remains deferred.

## Objective

Optionally extend post-create confidence after Create VM live smoke is stable.
The implemented safe slice records an operator-only bootstrap readiness intent
from read-only inventory evidence only.

## Constraints

- no live Proxmox mutation/smoke without explicit active-session user approval
- no live SSH login, SSH socket opening, Ansible execution, guest exec, VM
  start, or app bootstrap in the readiness intent slice
- Add SSH login smoke only after explicit approval.
- Keep app bootstrap separate from Create VM success unless product direction
  changes.
- Avoid storing private keys or raw secrets in DB/artifacts.
- Do not convert bootstrap checks into default Create VM success criteria
  unless a later goal changes that contract.

## Scope

Implemented safe slice:

1. `POST /api/v1/nodes/{node_id}/vms/{vmid}/bootstrap-readiness-intents`
   records a local `bootstrap_readiness` job and `bootstrap_readiness_intent`
   artifact.
2. The route is operator-only, requires
   `bootstrap_readiness_acknowledged=true` and a non-empty `idempotency_key`,
   binds the target by fresh read-only inventory `node_id` + `vmid`, and blocks
   templates, missing/moved targets, expected name/status/IP mismatches,
   non-running VMs, and missing guest-agent IP evidence.
3. Credential/execution payload keys such as private keys, public keys,
   passwords, tokens, key paths, Ansible inventory/playbook text, shell,
   command, and env are rejected without storing raw values.
4. Recorded evidence always reports `proxmox_mutation_enabled=false`,
   `ssh_login_ran=false`, `ansible_ran=false`, `app_bootstrap_ran=false`, and
   `side_effects=[]`.

Deferred scope:

1. Add SSH login smoke only after explicit approval and clear requirements.
2. Add Ansible verification only if target bootstrap requirements are clear.
3. Keep app bootstrap separate from Create VM success unless product direction
   changes.
4. Avoid storing private keys or raw secrets in DB/artifacts.

## Definition Of Done

- Bootstrap checks are explicit, opt-in, and safe.
- Create VM base success remains independent from app deploy success unless a
  later goal changes that contract.
- Any evidence recorded in docs/artifacts is sanitized.
- Live SSH login, Ansible, and app bootstrap execution are not implemented by
  the safe readiness intent slice.
