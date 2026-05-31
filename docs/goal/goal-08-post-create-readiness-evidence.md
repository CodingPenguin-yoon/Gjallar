# Goal 8: Post-Create Readiness Evidence

Status: minimal local-only evidence recorder slice implemented; live checks,
SSH, Ansible, and app bootstrap remain deferred.

## Objective

Record optional, sanitized readiness evidence for VMs that already exist after
creation.

This goal is about operator confidence after the Create VM contract has already
completed. It must remain opt-in, evidence-focused, and separate from Create VM
success criteria.

## Constraints

- no live Proxmox mutation/smoke without explicit active-session user approval
- no live guest or readiness checks without explicit active-session user
  approval for the exact check
- Do not change Create VM success conditions.
- Do not store secrets, credentials, private keys, raw tokens, or raw sensitive
  guest payloads in DB records, logs, docs, or artifacts.
- Evidence must be sanitized before it is committed, persisted, or shared.

## Scope

1. Define what post-create readiness evidence is useful for an already-created
   VM, such as approved check metadata, timestamps, actor, VM reference,
   observed readiness summary, sanitized output, and known limitations.
2. Keep evidence capture explicitly opt-in. Passive documentation or offline
   artifact review is allowed; active live checks require active-session user
   approval.
3. Keep readiness evidence independent from Create VM success. A VM can satisfy
   the Create VM contract without any Goal 8 evidence.
4. Keep all evidence sanitized and minimal. Store summaries and artifact
   references, not secrets, credentials, private keys, raw tokens, or raw
   sensitive payloads.
5. Make uncertainty visible. Missing, skipped, unavailable, or unapproved checks
   must be recorded as such rather than inferred as healthy.

## Implemented Safe Slice

- `POST /api/v1/nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence`
  records operator-supplied, sanitized readiness evidence for an already-created
  VM.
- The backend recorder is local-only. It does not call inventory, Proxmox
  clients, VM start, Create VM create/readiness, DRS check/execute/reconcile,
  SSH, Ansible, guest-agent, shell, or network code.
- The request requires `post_create_readiness_evidence_acknowledged=true` and a
  non-empty `evidence_id` or `idempotency_key`.
- Stable job ids use the target plus evidence identity:
  `post-create-readiness-{node}-{vmid}-{digest}`. A replay of the same identity
  returns the existing stored result without writing a second evidence artifact.
- Accepted evidence is intentionally narrow: `summary`, `limitations`, and
  `checks` with exact lowercase statuses from `passed`, `failed`, `skipped`,
  `unavailable`, `unapproved`, `not_run`, and `unknown`.
- Live-check, command, endpoint, log, raw payload, and credential-shaped fields
  are rejected before persistence. Secret-looking strings such as private key
  headers, Bearer/JWT/Proxmox tokens, `password=...`, `token=...`,
  `secret=...`, and SSH public key material are rejected without echoing the
  rejected value.
- Accepted requests write a `post_create_readiness` Jobs/Runs record and a
  `post_create_readiness_evidence` DB-backed JSON artifact. Result payloads
  keep `side_effects=[]`, `proxmox_mutation_enabled=false`,
  `live_checks_performed_by_gjallar=false`, and `allowed_actions=[]`.

## Explicitly Not In Scope

- Changing Create VM success criteria.
- Installing, configuring, deploying, or releasing guest workloads.
- Creating DRS identity, policy, approval, migration, or execution authority.
- Changing how VMs are created, configured, deployed, or managed.
- Persisting secrets, credentials, private keys, token material, or plaintext
  sensitive values.
- Running live checks without explicit active-session approval.

## Definition Of Done

- The Goal 8 contract is documented as deferred, opt-in post-create readiness
  evidence for already-created VMs.
- Create VM base success remains independent from Goal 8 evidence.
- Any live check path is gated by explicit active-session approval.
- Any evidence recorded in docs, DB records, logs, or artifacts is sanitized and
  contains no secrets or credentials.
- DRS migration authority and readiness evidence remain separate concerns.
