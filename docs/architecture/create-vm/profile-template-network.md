# Profile, Template, And Network Model

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Create VM](../../current/top-tabs/04-create-vm.md).

This document separates the current implemented selection model from target DB/access extensions.

## Current Profiles

Current profiles come from transitional read-only `static_seed` data in `backend/app/manifests/loader.py`, exposed by `GET /api/v1/profiles`.

| Profile | Display | Enabled | Source | Management |
|---|---|---:|---|---|
| `general-vm` | General VM | true | `static_seed` | `read_only` |
| `runtime-server` | Runtime Server | true | `static_seed` | `read_only` |
| `development-vm` | Development VM | true | `static_seed` | `read_only` |

DB seed is target/future. Profile create/edit/delete UI is not current.

## Hardware Defaults And Limits

| Profile | CPU default/min/max | Memory default/min/max MB | Disk default/min/max GB |
|---|---|---|---|
| `general-vm` | 2 / 1 / 8 | 4096 / 1024 / 32768 | 50 / 50 / 500 |
| `runtime-server` | 4 / 2 / 16 | 8192 / 4096 / 65536 | 100 / 80 / 1000 |
| `development-vm` | 2 / 1 / 12 | 4096 / 2048 / 32768 | 50 / 50 / 500 |

Changing profile in the UI resets hardware to the selected profile defaults, then raises disk to the selected template disk floor if needed. Backend preflight validates CPU, memory, and disk against selected profile min/max.

## Template Requirements

All current profiles require cloud-init readiness and qemu guest agent readiness.

Current template selection source is `GET /api/v1/templates`, backed by the Proxmox inventory adapter.

| Template behavior | Current implementation |
|---|---|
| Source of truth | Proxmox live/fake read-only inventory. |
| UI visibility | All templates remain listed. |
| UI disabled state | Templates that fail selected profile requirements are disabled with a reason. |
| Backend authority | Preflight red-blocks selected templates that fail required readiness. |
| Missing evidence | Not ready by default. |
| Disk floor | Requested disk must be at least selected template `disk_gb`. |

There is no current Gjallar template catalog or template registration UI.

## Current Network Source

Current Create VM target networking uses live bridge inventory and explicit operator inputs.

| Field | Current source |
|---|---|
| Target node | `GET /api/v1/nodes` option selected by operator/UI default. |
| Bridge | Active bridge from `GET /api/v1/networks`, filtered to target node. |
| IP mode | Operator selects `static` or `dhcp`. |
| Static IP | Operator input. |
| Prefix | Operator input. |
| Gateway | Operator input. |

The current Create VM path does not use `NetworkPolicy`, `network_id`, or `server-net` as the Create VM source of truth. Incoming `network_id`/`networkId` is transition-ignored and not echoed in active outputs.

## Static And DHCP Rules

| Mode | Current checks | Current create payload |
|---|---|---|
| `static` | `static_ip` present/valid IPv4, `prefix` present/valid 1-32, `gateway` present/valid IPv4, static IP not already observed on current VMs. | `ipconfig0=ip=<static_ip>/<prefix>,gw=<gateway>`. |
| `dhcp` | Allowed, but returns yellow risk because later guest-agent/IP discovery is needed. | `ipconfig0=ip=dhcp`. |

Gateway is never inferred. A missing gateway is a red preflight risk in static mode.

## Current Access And SSH

Profiles expose access recommendations and all current profiles require an SSH
public key with password login disabled.

| Field | Current behavior |
|---|---|
| Username | Wizard input; defaults from profile `default_user=yoon`; sent as `access.cloud_init_user`. |
| SSH public key | Wizard textarea or backend default from `GJALLAR_DEFAULT_SSH_PUBLIC_KEY` / `GJALLAR_DEFAULT_SSH_PUBLIC_KEY_FILE`. |
| Validation | Backend preflight red-blocks missing required keys, private-key-looking values, and malformed OpenSSH public keys. |
| Fingerprint | OpenSSH-style `SHA256:<base64>` over the decoded public key blob. Comments and extra whitespace do not change it. |
| Password login | Fixed disabled for current profiles and red-blocked if requested true. |
| Evidence | Draft/preflight/plan/review/manifest record username, disabled password login, key presence/source/fingerprint only. |

Raw SSH public key material is not returned in API responses and is not written
to plan, review, manifest, preview, or observed artifacts. It is held only
transiently for native Proxmox `sshkeys` config.

Do not document SSH login verification as current Create VM success. First login and SSH smoke are deferred.
