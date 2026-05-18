# Stale And Superseded Statements

Status source: [current product status](../../current/README.md). Top-tab status index: [top tabs](../../current/top-tabs/README.md).

Use this appendix when reading old PRDs, historical notes, or older architecture text. These statements are stale or target-only unless active code and current status docs say otherwise.

## Create VM

| Stale/superseded statement | Current correction |
|---|---|
| Older single-profile Create VM statements are stale. | Current profiles are exactly `general-vm`, `runtime-server`, and `development-vm`; all are enabled `db_seed` choices. |
| `runtime-server`, `dev-server`, and `db-server` are the next Create VM choices. | Current enabled profile names are `runtime-server` and `development-vm`; `dev-server` and `db-server` are not current enabled profile ids. |
| Create VM profiles are static-only today. | Current profiles are DB-seeded read-only presets; profile management UI remains future work. |
| Create VM uses target static fields as future-only work. | Current Create VM already requires explicit `static_ip`, `prefix`, and `gateway` for static mode. |
| Create VM may infer gateway from static IP, such as `.1`. | Current native config uses explicit operator `gateway`; missing gateway is a red static-mode preflight risk. |
| Create VM uses `NetworkPolicy`, `network_id`, or `server-net` as its source of truth. | Current Create VM uses selected target node active live bridge plus explicit network fields. Incoming `network_id`/`networkId` is ignored and not echoed. |
| `POST /api/v1/vm-create/{draft_id}/execute` creates the VM. | Legacy `execute` has been removed from the active API. Live mutation is `proxmox-create`. |
| Terraform is the active Create VM UI path. | Terraform endpoints are removed. Active frontend uses native Proxmox preview/create. |
| Create VM success always excludes first boot and guest-agent discovery. | Current default success is stopped after Proxmox post-check and `observed_after`; optional `boot_and_verify` success includes first boot, guest-agent IP discovery, and cloud-init completion. SSH/Ansible/app smoke remains out of scope. |

## Network

| Stale/superseded statement | Current correction |
|---|---|
| Networks tab mutates Proxmox bridges or writes network policy files. | Current Networks is read-only migration pre-check evidence. It does not mutate Proxmox bridges, write YAML, write DB policy, or authorize DRS execution. |
| Network policy is a required Create VM gate. | Current Create VM source of truth is selected target node active live bridge plus explicit network fields. |
| `server-net` is the Create VM network selector. | Current Create VM selects a live active bridge on the selected target node. |

## Placement / DRS

| Stale/superseded statement | Current correction |
|---|---|
| DRS Advisor backend is implemented. | No `/api/v1/drs/*` backend exists. |
| Current `/placement` can approve and execute migration. | Current `/placement` is frontend read-only read model only. |
| Placement recommendations are backend-owned operation records. | Current recommendation cards are frontend-generated from inventory/jobs/risks. |
| Migration execution, UPID tracking, locks, and reconciliation exist. | These are target-only. |
| DRS identity/fingerprint/policy DB exists. | Not implemented. Current Create VM fingerprint is an artifact, not a DB identity layer. |
| Old placement APIs are active. | Current Placement uses existing `/api/v1` inventory, jobs, and risks APIs; no DRS API route surface exists. |

## Jobs/Risks

| Stale/superseded statement | Current correction |
|---|---|
| Jobs/Runs is a full workflow engine. | Current Jobs/Runs is read-only UI over latest DB-backed job status records. |
| Risks/Alerts is an independent risk engine. | Current risks are derived from `risks` arrays in DB-backed job status records. |
| DRS blocker taxonomy is integrated into risks. | Not implemented. |

## Reading Rule

When a stale phrase appears in older material, prefer:

1. Active code.
2. [`docs/current/README.md`](../../current/README.md).
3. Relevant top-tab status page.
4. These domain architecture docs.

Only then use old PRD or historical text as background.
