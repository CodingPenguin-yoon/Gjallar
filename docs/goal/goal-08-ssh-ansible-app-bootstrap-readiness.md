# Goal 8: SSH/Ansible/App Bootstrap Readiness

Status: deferred.

## Objective

Optionally extend post-create confidence after Create VM live smoke is stable.

## Constraints

- no live Proxmox mutation/smoke without explicit active-session user approval
- Add SSH login smoke only after explicit approval.
- Keep app bootstrap separate from Create VM success unless product direction
  changes.
- Avoid storing private keys or raw secrets in DB/artifacts.
- Do not convert bootstrap checks into default Create VM success criteria
  unless a later goal changes that contract.

## Scope

1. Add SSH login smoke only after explicit approval.
2. Add Ansible verification only if target bootstrap requirements are clear.
3. Keep app bootstrap separate from Create VM success unless product direction
   changes.
4. Avoid storing private keys or raw secrets in DB/artifacts.

## Definition Of Done

- Bootstrap checks are explicit, opt-in, and safe.
- Create VM base success remains independent from app deploy success unless a
  later goal changes that contract.
- Any evidence recorded in docs/artifacts is sanitized.
