# Gjallar Manifest Schema PRD

> Current MVP product source of truth is `drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.
> This create-first manifest material is historical/supporting capability context only. It must not define the next MVP success line or implementation order.

## 0. 목적

Gjallar manifest schema 초안을 정의한다.
정식 JSON Schema/YAML Schema는 구현 단계에서 테스트와 함께 작성한다.

## 0.1 Create VM target source-of-truth update

2026-05-13 Create VM profile/template/network target design:

- Profile source of truth target은 Gjallar DB seed다. Profile은 생성 preset이며
  Proxmox template 대체물이 아니다.
- Template source of truth는 Proxmox live inventory다. Target에는 Gjallar
  template catalog/registration window가 없다.
- Create VM network source of truth는 selected target node의 Proxmox live
  active bridge다. Target Create VM은 `network_id`/`server-net`에 의존하지 않는다.
- NetworkPolicy manifest는 current/legacy Network tab support 또는 future
  recommendation/validation evidence로 남을 수 있지만 target Create VM source
  of truth는 아니다.

Current implementation note: 현재 code는 three enabled read-only `static_seed`
profiles와 live template/network inventory를 사용한다. DB seeded profile source는
아직 target/future다. 아래 target schema는 구현 업데이트 전 current code로 읽지
않는다.

## 1. 권장 디렉터리

Target Create VM에서는 profiles/templates/networks를 VM 생성 source of truth
manifest로 두지 않는다. 생성 결과와 intent evidence는 VMInstance manifest와
Jobs/Runs artifacts에 남긴다.

```text
manifests/
  vms/
    gjallar-vm-20260508-a1b2.yaml
```

Current/legacy code may still read profile/network fixtures until implementation
is updated. That compatibility should not redefine the target source of truth.

## 2. 공통 규칙

모든 manifest는 아래 필드를 가진다.

```yaml
apiVersion: gjallar/v1
kind: <Kind>
metadata:
  id: string
  name: string
  owner: string
  description: string
spec: {}
```

## 3. Create VM Profile Seed

Profile target은 DB seed다. 아래 YAML은 seed shape 설명용이며 target
VMProfile manifest kind가 아니다.

```yaml
profiles:
  - id: general-vm
    display_name: General VM
    display_name_ko: 범용 VM
    enabled: true
    hardware:
      cpu: { default: 2, min: 1, max: 8 }
      memory_mb: { default: 4096, min: 1024, max: 32768 }
      disk_gb: { default: 50, min: 50, max: 500 }
    template_requirements:
      require_cloud_init: true
      require_qemu_guest_agent: true
    access_recommendations:
      default_user: yoon
      require_ssh_key: true
      allow_password_login: false
      allow_user_override: true
  - id: runtime-server
    display_name: Runtime Server
    display_name_ko: 서비스 실행용 VM
    enabled: true
    hardware:
      cpu: { default: 4, min: 2, max: 16 }
      memory_mb: { default: 8192, min: 4096, max: 65536 }
      disk_gb: { default: 100, min: 80, max: 1000 }
    template_requirements:
      require_cloud_init: true
      require_qemu_guest_agent: true
    access_recommendations:
      default_user: yoon
      require_ssh_key: true
      allow_password_login: false
      allow_user_override: true
  - id: development-vm
    display_name: Development VM
    display_name_ko: 개발/테스트용 VM
    enabled: true
    hardware:
      cpu: { default: 2, min: 1, max: 12 }
      memory_mb: { default: 4096, min: 2048, max: 32768 }
      disk_gb: { default: 50, min: 50, max: 500 }
    template_requirements:
      require_cloud_init: true
      require_qemu_guest_agent: true
    access_recommendations:
      default_user: yoon
      require_ssh_key: true
      allow_password_login: false
      allow_user_override: true
```

Profile seed explicitly excludes target node, storage, network/network_id,
bridge, static IP, template VMID/name, power policy, and profile version.

## 4. Template

Template target source of truth는 Proxmox live inventory다. Target에는
Gjallar Template manifest kind, template catalog, template registration window를
두지 않는다.

Plan/review artifacts should record selected live template evidence:

```yaml
template:
  source: proxmox_live_inventory
  node_id: yoonmanserver2
  vmid: 9000
  name: ubuntu-template
  disk_gb: 50
  capabilities:
    cloud_init: true
    qemu_guest_agent: true
  collected_at: 2026-05-13T00:00:00Z
```

## 5. NetworkProfile

Target Create VM에서는 NetworkProfile을 source of truth로 사용하지 않는다.
Target request는 target node 선택 뒤 live active bridge를 직접 선택한다.
Static mode는 `static_ip`, `prefix`, `gateway`를 모두 요구한다.

아래 shape는 current/legacy Network tab policy support 또는 future
recommendation/validation evidence로만 읽는다.

```yaml
apiVersion: gjallar/v1
kind: NetworkProfile
metadata:
  id: server-net
  name: Server Network
  owner: infra
spec:
  subnet: 192.168.2.0/24
  gateway: 192.168.2.1
  dns:
    - 192.168.2.1
  node_bridges:
    yoonmanserver2: vmbr0
    yoonmanserver3: vmbr0
  ip_modes:
    allowed:
      - dhcp
      - static
    default: static
  static:
    allowed_ranges:
      - 192.168.2.140-192.168.2.150
    reserved:
      - 192.168.2.1
  runtime_target_allowed: true
```

Current implementation still uses `node_id` + `network_id` to resolve a bridge
through NetworkProfile. That is an implementation gap, not the target Create VM
contract.

## 6. VMInstance

```yaml
apiVersion: gjallar/v1
kind: VMInstance
metadata:
  id: gjallar-vm-20260508-a1b2
  name: gjallar-vm-20260508-a1b2
  owner: yoon
spec:
  proxmox_vmid: 150
  proxmox_vmid_allocation:
    mode: proxmox_nextid
    resolved_at_plan: true
  state_backend:
    type: local
    path: /mnt/hermes_data/IaC-state/gjallar/gjallar-vm-20260508-a1b2/terraform.tfstate
  node: yoonmanserver2
  profile_id: general-vm
  template:
    source: proxmox_live_inventory
    node_id: yoonmanserver2
    vmid: 9000
    name: ubuntu-template
  hardware:
    cpu: 2
    memory_mb: 4096
    disk_gb: 50
  storage: local-lvm
  access:
    username: yoon
    ssh_public_key_fingerprint: SHA256:example
    password_login: false
  network:
    bridge: vmbr0
    ip_mode: static
    static_ip: 192.168.2.150
    prefix: 24
    gateway: 192.168.2.1
  lifecycle:
    desired_power_state: stopped
  safety:
    require_approval_for_apply: true
```

## 7. RuntimeTarget

```yaml
apiVersion: gjallar/v1
kind: RuntimeTarget
metadata:
  id: gjallar-vm-20260508-a1b2
  name: gjallar-vm-20260508-a1b2
  owner: yoon
spec:
  vm_ref: gjallar-vm-20260508-a1b2
  address: 192.168.2.150
  roles:
    - runtime
  status: candidate
  activation:
    require_smoke_success: true
    block_on_red_risk: true
    active_enabled_in_mvp: false
```

RuntimeTarget은 optional/deferred다.
첫 구현 MVP에서는 VM 생성과 동시에 만들지 않는다.
Runtime Target slice를 붙인 뒤에도 `candidate`, `candidate_ready`, `blocked`까지만 사용한다.
`active`는 2차 기능이다.

## 8. Validation 규칙

- profile seed 참조가 존재하고 enabled여야 한다.
- live Proxmox template 참조가 존재하고 selected profile requirements를 만족해야 한다.
- `proxmox_vmid`/name/IP는 중복되면 안 된다.
- MVP에서는 VMID 직접 입력을 기본 허용하지 않고 Proxmox `nextid` 기반 resolved `proxmox_vmid`를 사용한다.
- resolved `proxmox_vmid`는 apply 직전 다시 중복 검증해야 한다.
- MVP Terraform state backend는 local이며 Git에 저장하지 않는다.
- state path는 `/mnt/hermes_data/IaC-state/gjallar/<manifest_id>/terraform.tfstate` 형식이어야 한다.
- state와 manifest의 `proxmox_vmid`/name 매핑 불일치는 red risk다.
- hardware override는 profile limit 안에 있어야 한다.
- selected target node의 live active bridge가 존재해야 한다.
- Target Create VM request는 `network_id`를 요구하거나 source of truth로 사용하지 않는다.
- static mode에는 `static_ip`, `prefix`, `gateway`가 모두 있어야 한다.
- DHCP mode는 허용하지만 이후 guest-agent/inventory discovery warning을 남긴다.
- profile에는 power policy가 없고 VMInstance desired power state는 `stopped`다.
- required SSH key가 없으면 red risk다.
- password login은 initial seeded profiles에서 false/disabled다.
- runtime target은 red risk가 있으면 `candidate_ready`가 될 수 없다.
- 첫 구현 MVP에서는 runtime target manifest/API 구현을 요구하지 않는다.
- MVP 및 이후 Runtime Target slice에서도 runtime target `active` 전환을 금지한다.
- Terraform destroy/delete plan은 create flow에서 금지한다.

## 9. 외부 참고 자료 제외 원칙

잘못 전달된 외부 참고 자료는 Gjallar manifest schema에 반영하지 않는다.
Target Create VM Network/IP는 Proxmox live bridge inventory와 static
`static_ip`/`prefix`/`gateway` 입력, 그리고 별도 확정된 운영 evidence만 따른다.
NetworkProfile은 current/legacy Network tab policy support 또는 future evidence로만 읽는다.
