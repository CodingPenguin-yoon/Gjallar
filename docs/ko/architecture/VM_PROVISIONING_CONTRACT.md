# Gjallar Create VM Contract

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 VM provisioning contract](../../architecture/VM_PROVISIONING_CONTRACT.md), [Current Create VM snapshot](../../current/top-tabs/04-create-vm.md), [Create VM native architecture](../../architecture/CREATE_VM_NATIVE_ARCHITECTURE.md), [profile/template/network design](../../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md).

Create VM의 active contract는 `/api/v1/vm-create/*` flow입니다. 이 flow는 operator가 review한 powered-off Proxmox VM을 live template에서 만드는 절차입니다. DRS Advisor와 별도이며, DRS migration 실행 허가로 쓰면 안 됩니다.

## Contract goal

Create VM은 live side effect 전에 risk evidence를 보여주기 위해 draft, preflight, plan, approval, final acknowledgement, native create로 나뉩니다.

```text
draft request
  -> preflight
  -> plan artifacts + Review & Confirm
  -> approval validation
  -> Proxmox native create after explicit acknowledgement
  -> internal Proxmox native preview artifact
```

## Active endpoints

| Endpoint | 핵심 의미 |
|---|---|
| `GET /api/v1/profiles` | Current static-seed creation profiles. |
| `GET /api/v1/vm-create/readiness` | IaC readiness evidence. |
| `POST /api/v1/vm-create/drafts` | Non-mutating server-side draft. |
| `POST /api/v1/vm-create/{draft_id}/preflight` | Read-only checks. |
| `POST /api/v1/vm-create/{draft_id}/plan` | Artifact-backed dry-run plan. |
| `POST /api/v1/vm-create/{draft_id}/approve` | Exact review metadata validation. |
| `POST /api/v1/vm-create/{draft_id}/proxmox-preview` | Approval-gated non-mutating native preview. |
| `POST /api/v1/vm-create/{draft_id}/proxmox-create` | Active live native Proxmox creation path. |

## Draft request boundary

Normal UI flow에서 VMID는 operator가 직접 공급하지 않고 inventory adapter가 `suggest_next_vmid()`로 제안합니다. Incoming `network_id`/`networkId`는 transition compatibility로 무시되고 active draft/plan/review/manifest/job output에 echo되지 않습니다.

Current request는 selected profile, target node, storage, live template reference, hardware overrides, access username/key, live bridge, IP mode, static fields를 담습니다.

## Profile defaults

Current profiles는 transitional `static_seed`입니다.

| Profile | Default | Limits | Requirements |
|---|---|---|---|
| `general-vm` | 2 CPU, 4096 MB, 50 GB | CPU 1-8, memory 1024-32768, disk 50-500 | cloud-init + qemu guest agent |
| `runtime-server` | 4 CPU, 8192 MB, 100 GB | CPU 2-16, memory 4096-65536, disk 80-1000 | cloud-init + qemu guest agent |
| `development-vm` | 2 CPU, 4096 MB, 50 GB | CPU 1-12, memory 2048-32768, disk 50-500 | cloud-init + qemu guest agent |

Profiles do not contain target node, storage, network, bridge, static IP, template VMID/name, power policy, or profile version.

## Preflight contract

Preflight는 read-only입니다. 주요 check는 profile availability, hardware min/max, template readiness, template disk floor, target node online, storage availability/capacity, selected bridge active on target node, VMID/name uniqueness, static field validity, observed IP conflict, IaC readiness, SSH key requirement, password login disabled rule입니다.

Red risks block approval and execution. Yellow risks require acknowledgement where allowed.

## Plan and approval contract

Plan은 `preflight_report`, `plan`, `vm_instance_manifest`, `planned_git_diff`, `review_summary` artifacts를 씁니다. Review evidence에는 selected profile, template, target node, storage, bridge, static network fields, access safe evidence, risks, artifact IDs/checksum이 들어갑니다.

Approval은 exact `plan_artifact_id`, `review_summary_checksum`, `yellow_risk_acknowledged`를 검증합니다. Approval 자체는 manifest commit이나 Proxmox call이 아닙니다.

## Native preview/create contract

`proxmox-preview`는 approval-gated but non-mutating입니다. `build_proxmox_create_preview()`가 clone/config/post-check payload와 redacted artifact를 만듭니다.

`proxmox-create`는 approval metadata, `proxmox_mutation_acknowledged=true`, fresh plan/preflight no red risk를 요구합니다. 그 뒤 internal preview artifact, clone, UPID polling, boot disk resize if needed, config, status/config post-check, `observed_after` artifact를 수행합니다.

## Success boundary

Success는 powered-off/stopped VM 생성입니다. VM이 target node에서 관찰되고 Proxmox status가 `stopped`이며 `observed_after` artifact가 있어야 합니다. First boot, cloud-init smoke, guest-agent discovery, SSH login, Ansible verification, app deploy, DRS identity registration은 current success가 아닙니다.
