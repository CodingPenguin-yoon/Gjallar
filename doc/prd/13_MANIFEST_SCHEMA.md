# Gjallar Manifest Schema PRD

## 0. 목적

Gjallar manifest schema 초안을 정의한다.
정식 JSON Schema/YAML Schema는 구현 단계에서 테스트와 함께 작성한다.

## 1. 권장 디렉터리

```text
manifests/
  profiles/
    general-vm.yaml
    # 2차 후보. MVP에서는 fixture/apply 대상 아님:
    # runtime-server.yaml
    # dev-server.yaml
    # db-server.yaml
  templates/
    ubuntu-template.yaml
  networks/
    server-net.yaml
  vms/
    gjallar-vm-20260508-a1b2.yaml
  runtime-targets/
    gjallar-vm-20260508-a1b2.yaml
```

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

## 3. VMProfile

```yaml
apiVersion: gjallar/v1
kind: VMProfile
metadata:
  id: general-vm
  name: General VM
  owner: infra
spec:
  purpose: general-vm-create
  default_template_id: ubuntu-template
  hardware:
    cpu:
      default: 2
      min: 1
      max: 4
    memory_mb:
      default: 4096
      min: 2048
      max: 8192
    disk_gb:
      default: 40
      min: 20
      max: 100
  access:
    cloud_init_user: yoon
    ssh_key_source: operator_default_public_key
    password_login: disabled
  bootstrap:
    stage_a:
      package_install: false
      checks:
        - cloud_init
        - qemu_guest_agent
        - ip_discovery
        - ssh
    stage_b:
      enabled_after_stage_a_stable: true
      ansible_verify: true
      install_dev_runtime_packages: false
  naming:
    default_prefix: gjallar-vm
    default_pattern: gjallar-vm-<YYYYMMDD>-<short_job_id>
  vmid:
    allocation_mode: proxmox_nextid
    reserved_range: null
  allowed_networks:
    - server-net
  safety:
    require_preflight: true
    require_approval_for_apply: true
```

## 4. Template

```yaml
apiVersion: gjallar/v1
kind: Template
metadata:
  id: ubuntu-template
  name: Ubuntu Cloud Image Template
  owner: infra
spec:
  proxmox:
    node: yoonmanserver2
    proxmox_vmid: 9000
    template_name: ubuntu-template
  capabilities:
    cloud_init: true
    qemu_guest_agent: true
  allowed_profiles:
    - general-vm
```

Template 생성/업데이트는 MVP 범위 밖이다.

## 5. NetworkProfile

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

MVP에서 `node_bridges`는 NetworkProfile의 필수 필드다.
Gjallar는 VM 생성 draft의 `node_id`와 `network_id`를 기준으로 bridge를 resolve 한다.
client가 raw bridge 값을 직접 넘기는 방식은 MVP 기본 UI/API에 두지 않는다.
`dhcp`와 `static`은 둘 다 허용하지만 기본값은 `static`이다.

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
  template_id: ubuntu-template
  hardware:
    cpu: 2
    memory_mb: 4096
    disk_gb: 40
  storage: local-lvm
  access:
    cloud_init_user: yoon
    ssh_key_source: operator_default_public_key
    password_login: disabled
  network:
    profile_id: server-net
    ip_mode: static
    ip: 192.168.2.150
  lifecycle:
    desired_power_state: running
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

- profile/template/network/vm 참조가 존재해야 한다.
- `proxmox_vmid`/name/IP는 중복되면 안 된다.
- MVP에서는 VMID 직접 입력을 기본 허용하지 않고 Proxmox `nextid` 기반 resolved `proxmox_vmid`를 사용한다.
- resolved `proxmox_vmid`는 apply 직전 다시 중복 검증해야 한다.
- MVP Terraform state backend는 local이며 Git에 저장하지 않는다.
- state path는 `/mnt/hermes_data/IaC-state/gjallar/<manifest_id>/terraform.tfstate` 형식이어야 한다.
- state와 manifest의 `proxmox_vmid`/name 매핑 불일치는 red risk다.
- hardware override는 profile limit 안에 있어야 한다.
- node bridge mapping이 존재해야 한다.
- runtime target은 red risk가 있으면 `candidate_ready`가 될 수 없다.
- 첫 구현 MVP에서는 runtime target manifest/API 구현을 요구하지 않는다.
- MVP 및 이후 Runtime Target slice에서도 runtime target `active` 전환을 금지한다.
- Terraform destroy/delete plan은 create flow에서 금지한다.

## 9. 외부 참고 자료 제외 원칙

잘못 전달된 외부 참고 자료는 Gjallar manifest schema에 반영하지 않는다.
Network/IP 정책은 이 문서의 NetworkProfile과 별도 확정된 운영 evidence만 따른다.
