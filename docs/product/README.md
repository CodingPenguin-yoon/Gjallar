# Gjallar Product Docs

Gjallar is a human-facing Proxmox Operations & Risk Console / operations platform.

This product tree is focused on product direction. Current implemented status, operational runbooks, and architecture docs live outside this folder.

## Start Here

- [DRS Advisor target direction](drs-advisor/README.md)
- [Archived legacy PRD index](../archive/legacy-prd/README.md)
- [Current implemented state](../current/README.md)
- [Architecture index](../architecture/README.md)

## Product Framing

- DRS Advisor is the next MVP success line.
- Create VM is a supporting capability, not the MVP success line.
- Proxmox is the source of truth for actual VM/node/task/HA/storage state.
- Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.
- DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, automatic DRS for Proxmox, or a backup product.
- PBS/Veeam references are backup evidence or future integration context only.

## Current Boundaries

- The active contract is `/api/v1`.
- Old `/api/instances`, `/api/provision`, deploy/task/log/LLM surfaces are not active.
- Current `/drs` UI includes recommendation/detail/check, manual per-VM migration policy configuration, and local approval packet/job intent creation. Backend DRS includes compact identity/fingerprint evidence, migration policy memory, final pre-check, operation locks, local approval/job substrate, narrow operator-only live migration execution, UPID/task tracking, verified post-check, and read-only reconcile preview.
- DRS recommendation/detail/check output is Proxmox-read-only and remains `read_only=true`, `executable=false`, `allowed_actions=[]`. Approval packet creation does not start migration; live migration only starts through the dedicated migration-job execute route after fresh gates.
- There is no live DRS execution UI, corrective reconcile UI, richer policy rule/full metadata editor, corrective reconciliation mutation, background automation, automatic DRS, or recommendation-level migrate/live-migrate alias. Approved VMID `140` live DRS smoke evidence exists, but it does not authorize broad UI execution or future live mutation.
- The active Create VM path is native Proxmox preview/create.
- The legacy Terraform Create VM executor route surface and helper code are removed.
- Create VM default success is powered-off/stopped after Proxmox post-check and
  `observed_after`; optional `boot_and_verify` starts the new VM and verifies
  guest-agent IP plus cloud-init completion.
- Local users are managed by CLI or admin-only UI/API. There is no public
  signup flow.
- Inventory is read-only with fake fallback.
- Dashboard and read-only screens should remain usable when DB-backed job history is unavailable or temporarily unreadable.
