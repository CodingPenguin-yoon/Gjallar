# Create VM Profile, Template, And Network Design

Last updated: 2026-05-14

This document is the target design for the Create VM profile, template, and
network selection model. It is not a statement that all behavior is implemented
today. Current implementation gaps are listed near the end.

Create VM remains a supporting capability. The current MVP product source of
truth is [`docs/product/drs-advisor/`](../product/drs-advisor/README.md).
If this document conflicts with that folder, `drs-advisor/` wins.

## Purpose

The goal is to remove ambiguity between three different concerns:

- Profile: an operator-visible creation preset.
- Template: a live Proxmox template selected for clone.
- Network: a live bridge on the selected target node, plus IP configuration.

The target design makes each source of truth explicit:

| Concern | Target source of truth | Create VM behavior |
|---|---|---|
| Profile | Gjallar DB seed | UI-visible read-only preset, initially seeded by the backend. |
| Template | Proxmox live inventory | User selects a Proxmox template. Gjallar disables templates that fail selected profile requirements. |
| Network | Proxmox live bridge inventory | User selects target node, then an active bridge on that node. |

## Glossary

- Creation profile: a named preset that gives default hardware, hardware
  min/max bounds, template requirements, and access recommendations.
- Template: a Proxmox QEMU VM marked as a template and visible through live
  inventory. Gjallar does not maintain a separate target template catalog.
- Active bridge: a bridge reported by live Proxmox network inventory for the
  selected target node and available for VM NIC configuration.
- Static IP mode: operator supplies `static_ip`, `prefix`, and `gateway`.
- DHCP mode: operator does not supply static address fields. Gjallar warns that
  guest-agent or inventory discovery is needed later.
- Access section: the Create VM form section where the operator edits cloud-init
  username and SSH public key. Access is not a separately selectable object.

## Design Decisions

### Profiles

- A profile is UI-visible and represents a creation preset. It is not a
  replacement for a Proxmox template.
- The target profile source of truth is Gjallar DB seed data.
- Initial UI behavior is read-only. Profile create/edit/delete UI is a future
  management feature.
- Initial seeded profiles are all `enabled=true`:
  - `general-vm`: General VM, 범용 VM
  - `runtime-server`: Runtime Server, 서비스 실행용 VM
  - `development-vm`: Development VM, 개발/테스트용 VM
- Profile selection sets CPU, memory, and disk to the selected profile defaults.
  If the operator changes profile after editing hardware, CPU/RAM/Disk reset to
  the new profile defaults.
- The operator may edit CPU/RAM/Disk after profile selection, but only inside
  the selected profile min/max limits.
- Profiles have template requirement booleans:
  - `require_cloud_init`
  - `require_qemu_guest_agent`
- Both template requirement booleans are `true` for all initial profiles.
- Profiles have access recommendations:
  - `default_user=yoon`
  - `require_ssh_key=true`
  - `allow_password_login=false`
  - `allow_user_override=true`
- Password login is disabled and fixed for the initial design.
- A default SSH public key may come from environment-backed backend
  configuration. If no key is available and the profile requires one, preflight
  returns a red block.

Profiles do not include:

- target node
- storage
- network or `network_id`
- bridge
- static IP
- template VMID or template name
- power policy
- profile version

### Templates

- Template source of truth is Proxmox live inventory.
- The target design has no Gjallar template catalog and no template registration
  window.
- The UI shows Proxmox templates from live inventory.
- Templates that fail the selected profile requirements are visible but disabled
  with a reason.
- Backend preflight still verifies selected template requirements immediately
  before plan/create. UI disabling is advisory, not authoritative.
- Template capability checks for the initial profiles:
  - cloud-init capable
  - qemu guest agent expected/enabled
- Missing or unknown capability evidence is not treated as ready. In live
  Proxmox inventory, missing `agent` config means `guest_agent_ready=false`.
- Template disk size remains evidence for disk floor checks. Requested disk size
  cannot be smaller than the selected template disk.

### Network

- Create VM target networking does not use `network_id` or `server-net`.
- The operator first selects a target node.
- After target node selection, the operator selects an active live bridge on
  that node.
- Static IP mode requires all of:
  - `static_ip`
  - `prefix`
  - `gateway`
- `gateway` is operator-supplied input. Gjallar must not infer it from
  `static_ip` by assuming the `.1` address or any other subnet convention.
- DHCP mode is allowed, but the UI shows a warning that IP discovery depends on
  later guest-agent or inventory evidence.
- Network tab policy, subnet/gateway/range management, and Create VM bridge/IP
  recommendations are future integration points.
- Existing Network tab policy routes may remain for current or legacy support
  until code changes, but they are not the target source of truth for Create VM.

### Power Policy

- Profiles have no power policy.
- Create VM power policy is request-level: default `stopped` completes powered
  off, while `boot_and_verify` starts the new VM and verifies guest-agent IP plus
  cloud-init completion.
- Existing-VM start is a separate Infra Explorer VM row action with Jobs/Runs
  audit.
- SSH verification, Ansible verification, and app bootstrap remain separate
  follow-up stages.

## Seed Profile Table

### Hardware Defaults And Limits

| Profile ID | Display name | Korean label | CPU default | CPU min | CPU max | Memory default MB | Memory min MB | Memory max MB | Disk default GB | Disk min GB | Disk max GB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `general-vm` | General VM | 범용 VM | 2 | 1 | 8 | 4096 | 1024 | 32768 | 50 | 50 | 500 |
| `runtime-server` | Runtime Server | 서비스 실행용 VM | 4 | 2 | 16 | 8192 | 4096 | 65536 | 100 | 80 | 1000 |
| `development-vm` | Development VM | 개발/테스트용 VM | 2 | 1 | 12 | 4096 | 2048 | 32768 | 50 | 50 | 500 |

### Requirements And Access

| Profile ID | Enabled | Require cloud-init | Require qemu guest agent | Default user | Require SSH key | Password login | User override |
|---|---:|---:|---:|---|---:|---|---:|
| `general-vm` | true | true | true | `yoon` | true | disabled | true |
| `runtime-server` | true | true | true | `yoon` | true | disabled | true |
| `development-vm` | true | true | true | `yoon` | true | disabled | true |

## Target Payload Examples

These examples describe the current DB-backed profile contract for the initial
read-only preset slice. Profile management UI remains future work.

### Profiles Response

```json
{
  "profiles": [
    {
      "id": "general-vm",
      "display_name": "General VM",
      "display_name_ko": "범용 VM",
      "enabled": true,
      "hardware": {
        "cpu": { "default": 2, "min": 1, "max": 8 },
        "memory_mb": { "default": 4096, "min": 1024, "max": 32768 },
        "disk_gb": { "default": 50, "min": 50, "max": 500 }
      },
      "template_requirements": {
        "require_cloud_init": true,
        "require_qemu_guest_agent": true
      },
      "access_recommendations": {
        "default_user": "yoon",
        "require_ssh_key": true,
        "allow_password_login": false,
        "allow_user_override": true
      },
      "source": "db_seed",
      "management": "read_only"
    }
  ]
}
```

### Template Selection Model

```json
{
  "selected_profile_id": "runtime-server",
  "templates": [
    {
      "node_id": "yoonmanserver2",
      "vmid": 9000,
      "name": "ubuntu-template",
      "disk_gb": 50,
      "capabilities": {
        "cloud_init": true,
        "qemu_guest_agent": true
      },
      "selectable": true,
      "disabled_reason": null
    },
    {
      "node_id": "yoonmanserver2",
      "vmid": 9010,
      "name": "legacy-template",
      "disk_gb": 32,
      "capabilities": {
        "cloud_init": false,
        "qemu_guest_agent": false
      },
      "selectable": false,
      "disabled_reason": "Requires cloud-init and qemu guest agent"
    }
  ]
}
```

### Static Draft Request

```json
{
  "operator_id": "api-preview",
  "job_id": "job-api-preview",
  "name": "gjallar-vm-20260513-a1b2",
  "profile_id": "general-vm",
  "target_node_id": "yoonmanserver2",
  "storage_id": "local-lvm",
  "template": {
    "node_id": "yoonmanserver2",
    "vmid": 9000,
    "name": "ubuntu-template"
  },
  "hardware": {
    "cpu": 2,
    "memory_mb": 4096,
    "disk_gb": 50
  },
  "access": {
    "username": "yoon",
    "ssh_public_key": "ssh-ed25519 AAAA...",
    "password_login": false
  },
  "network": {
    "bridge": "vmbr0",
    "ip_mode": "static",
    "static_ip": "192.168.2.150",
    "prefix": 24,
    "gateway": "192.168.2.1"
  }
}
```

### DHCP Draft Request

```json
{
  "operator_id": "api-preview",
  "job_id": "job-api-preview",
  "name": "gjallar-vm-20260513-c3d4",
  "profile_id": "development-vm",
  "target_node_id": "yoonmanserver3",
  "storage_id": "local-lvm",
  "template": {
    "node_id": "yoonmanserver2",
    "vmid": 9000,
    "name": "ubuntu-template"
  },
  "hardware": {
    "cpu": 2,
    "memory_mb": 4096,
    "disk_gb": 50
  },
  "access": {
    "username": "yoon",
    "ssh_public_key": "ssh-ed25519 AAAA...",
    "password_login": false
  },
  "network": {
    "bridge": "vmbr0",
    "ip_mode": "dhcp"
  }
}
```

## Preflight Rules

Preflight is authoritative and must re-check live state. UI disabled states are
not sufficient.

### Profile Checks

- Selected profile exists in the Gjallar DB seed data.
- Selected profile is `enabled=true`.
- Requested CPU/RAM/Disk are inside the selected profile min/max limits.
- If the profile requires an SSH key, the request or configured default key must
  provide one.
- Password login must be false for initial seeded profiles.

### Template Checks

- Selected template still exists in Proxmox live inventory.
- Selected template is still a template.
- Selected template satisfies `require_cloud_init`.
- Selected template satisfies `require_qemu_guest_agent`.
- Requested disk size is not smaller than the observed template disk size.
- Template node/VMID/name mismatch is a red risk if the selected live reference
  cannot be resolved unambiguously.

### Node And Storage Checks

- Target node exists and is online.
- Storage exists on the target node or is otherwise valid for clone target.
- Storage capacity is sufficient.

### Network Checks

- Selected bridge exists in live inventory for the selected target node.
- Selected bridge is active/usable according to live inventory evidence.
- Static mode requires `static_ip`, `prefix`, and `gateway`.
- Static mode validates IP syntax, gateway IP syntax, and prefix range.
- Static mode uses the requested `gateway` value exactly for plan/preview/create
  payloads. Missing gateway is a red risk; implicit gateway derivation is not
  allowed.
- Static mode checks duplicate/reserved IP when evidence is available.
- DHCP mode is allowed but returns a yellow warning until guest-agent or
  inventory discovery confirms the assigned IP in a later stage.
- `network_id` is not accepted by the target Create VM draft contract.

### Identity And Safety Checks

- VMID is resolved by Gjallar from Proxmox inventory, not supplied by the
  operator in the normal UI.
- VMID uniqueness and VM name uniqueness are checked before approval and again
  immediately before live mutation.
- Red risks block approval and live create.
- Yellow risks require explicit operator acknowledgement where the approval
  contract allows it.

## UI Behavior

- Profile is the first selection.
- Profile cards show display name, Korean label, purpose, default hardware, and
  hardware bounds.
- Changing profile resets CPU/RAM/Disk to the new defaults.
- Hardware controls are editable after profile selection and constrained by
  min/max.
- Template list is live Proxmox inventory. Failing templates remain visible but
  disabled with the failed requirement reason.
- Target node selection precedes bridge selection.
- Bridge options are live bridges for the selected node only.
- The Create VM form has an Access section with username and SSH public key.
- Username defaults to `yoon`; operator edits are allowed for the initial
  profiles.
- SSH public key may be provided by the operator or by backend env/file default
  configuration. If no key is present, preflight returns a red blocker.
- Password login is shown as disabled/fixed or omitted as an editable control.
- Static IP mode shows `static_ip`, `prefix`, and `gateway` fields.
- DHCP mode shows a warning about later discovery.
- Network tab policy/subnet/range state is not the source of truth for this
  Create VM target flow.
- Review & Confirm shows profile, template, target node, storage, bridge, IP
  mode, static IP fields when used, access username, hardware, VMID, power
  policy `stopped`, risks, and artifact links.

## Logging And Artifact Expectations

Create VM artifacts should make the operator decision auditable without storing
secrets.

Expected evidence:

- selected `profile_id`
- resolved profile defaults and limits used for validation
- selected live template reference: node, VMID, name, observed disk, capability
  evidence, and collection timestamp
- selected target node and storage
- selected live bridge and collection timestamp
- network mode and static IP fields when static mode is used
- access username
- SSH public key presence, source, and fingerprint/hash, not raw key material
- password login fixed false
- preflight checks and red/yellow/green risks
- plan/review checksum and artifact ids
- Proxmox preview payload with secret redaction
- Proxmox create result, UPID, post-check, and `observed_after` fingerprint
- final observed power state, which must be `stopped` for success

The following must not be persisted in API responses, job logs, or artifacts:

- private SSH keys
- raw SSH public keys outside the transient Proxmox config call
- passwords
- Proxmox token secrets
- raw environment values

## Current Implementation State

As of 2026-05-15, current code partially matches this target design.

- Profiles are implemented through DB-seeded read-only rows with
  `source: db_seed`.
- `general-vm`, `runtime-server`, and `development-vm` are all active enabled
  Create VM choices with hardware default/min/max contracts.
- Some older docs mention `dev-server` or `db-server`; the target seeded
  development profile is `development-vm`, and `db-server` is not an initial
  seeded enabled profile.
- Current Create VM active networking uses explicit `bridge_id` selected from
  active live bridge inventory after target node selection. Incoming
  `network_id`/`networkId` is ignored for transition compatibility and is not
  echoed in active draft/plan/review/manifest/job output.
- Current Create VM draft handling requires target static `static_ip`,
  `prefix`, and `gateway`.
- Current native create config no longer derives `.1` gateway or `/24` prefix
  from `static_ip`; it uses explicit operator input.
- Current Network tab policy support may remain as current/legacy functionality,
  but it is not the target Create VM network source of truth.
- Current template handling uses read-only Proxmox inventory from
  `/api/v1/templates` as the active template selection source. Builtin template
  defaults are not used for active Create VM selection.
- Current UI keeps all live templates listed, disables templates that fail the
  selected profile's cloud-init or qemu guest-agent requirements, and blocks
  review when no passing template is selected.
- Current backend preflight red-blocks selected templates that fail required
  cloud-init or qemu guest-agent readiness. If a future profile marks a
  requirement false, missing readiness remains advisory/yellow; unknown
  profiles stay red through profile checks without borrowing fallback profile
  requirements.
- Current Access/SSH behavior is implemented for the active Create VM path:
  wizard username/key input, backend default key fallback, missing/malformed key
  red preflight, fixed disabled password login, safe access evidence in
  preflight/plan/review/manifest, and redacted native preview/observed output.
- Terraform plan/apply routes, helper code, and Terraform-named state metadata
  are removed from active contracts.

## Implementation Checklist

1. Add DB seed data for the three enabled profiles.
   Implemented through Alembic schema plus a manual idempotent seed command.
2. Expose profile seed data through `GET /api/v1/profiles` with hardware
   defaults/limits, template requirements, and access recommendations.
3. Keep profile management UI out of the initial slice.
4. Update Create VM form state so profile changes reset CPU/RAM/Disk to
   defaults.
5. Enforce hardware min/max in UI and backend preflight.
6. Load templates from live Proxmox inventory only. Implemented for the active
   selection path through `/api/v1/templates`.
7. Disable UI template options that fail selected profile requirements.
   Implemented.
8. Re-check template requirements in backend preflight. Implemented with
   profile-derived red severity for required capabilities.
9. Remove target Create VM dependency on `network_id`/`server-net`.
10. After target node selection, load active live bridge options for that node.
11. Add target static network fields: `static_ip`, `prefix`, and `gateway`.
12. Preserve DHCP as an allowed mode with a yellow discovery warning.
13. Keep Network tab policy/range integration as future work, not target source
    of truth for Create VM.
14. Load default SSH public key from configured backend environment when
    available.
    Implemented through env/file default fallback.
15. Red-block preflight when required SSH key is absent.
    Implemented.
16. Keep password login disabled for initial profiles.
    Implemented.
17. Keep create success tied to explicit request power policy.
18. Add Infra Explorer start action separately with Jobs/Runs audit.
    Implemented for stopped non-template VM rows.
19. Update plan, review, job, and artifact schemas to record the target fields.
    Implemented for current profile/template/network/access evidence and DB
    seed source.
20. Update tests to lock the current-code gap closed only after implementation
    is actually changed.
