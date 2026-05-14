# Gjallar First Implementation Slice

> Superseded/historical create-first note:
> Current MVP product source of truth is `drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.
> This create-first material is historical/supporting capability context only. It must not define the next MVP success line or implementation order.
> Next implementation work should follow `drs-advisor/05_IMPLEMENTATION_PLAN.md`.
> 2026-05-13 Create VM profile/template/network update: if this historical slice
> is reused for Create VM, use
> [`docs/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md).
> The older `server-net`/NetworkProfile fixture, single `general-vm` target,
> template catalog fixture, and first-power-on create success are superseded.

## 0. 목적

첫 구현 범위를 작게 고정한다.
처음부터 전체 VMware clone을 만들지 않는다.

## 1. Slice 이름

**Read-only Inventory + Create VM Preflight Skeleton**

## 2. Scope

포함:

- backend/frontend 새 skeleton
- manifest parser skeleton
- profile seed fixture plus live template/bridge inventory fixture adapter
- Dashboard summary mock/live adapter
- Nodes list
- VMs list/detail
- Create VM draft
- Preflight dry-run
- risk result 표시
- jobs table skeleton

제외:

- 실제 VM apply
- VM 삭제
- snapshot
- resource resize
- VM console
- 앱 배포 기능

## 3. 성공 기준

- PRD의 API shape가 테스트로 고정됨
- Dashboard/Infra Explorer가 최소 데이터로 렌더링됨
- Create VM wizard에서 profile 선택 → preflight 결과까지 진행됨
- red risk가 execute를 막음
- artifact/job 구조가 잡힘

## 4. 필요한 fixture

```text
profiles/seed-profiles.json
inventory/proxmox-templates.json
inventory/proxmox-node-bridges.json
vms/example-draft.yaml
```

2026-05-13 target fixture 전제:

```yaml
profiles:
  - id: general-vm
    enabled: true
  - id: runtime-server
    enabled: true
  - id: development-vm
    enabled: true
profile_bindings_forbidden:
  - target_node
  - storage
  - network_id
  - bridge
  - template_vmid
  - power_policy
  - profile_version
template_source: proxmox_live_inventory
network_source: selected_target_node_live_bridge
network_id: not_used
static_requires:
  - static_ip
  - prefix
  - gateway
dhcp: allowed_with_discovery_warning
hardware:
  source: selected_profile_defaults_and_limits
access:
  cloud_init_user: yoon
  ssh_key_source: operator_default_public_key
  password_login: disabled
```

storage 이름, 실제 template VMID/name/capabilities, node bridge 목록은 구현 직전 Proxmox live inventory로 확인한다.

## 5. 이후 slice

Slice 2:

- real Proxmox read-only adapter
- observed snapshot DB

Slice 3:

- plan-only job workspace
- Terraform plan artifact
- Review & Confirm summary artifact

Slice 4:

- 승인 후 selected enabled profile 기반 VM 생성
- VM 생성 승인은 일반 Confirm 버튼으로 처리
- yellow risk가 있으면 경고 체크박스 필요
- red risk는 approve/execute 비활성화
- VM 이름 기본값은 `gjallar-vm-<YYYYMMDD>-<short_job_id>` 형식
- VMID는 Proxmox `nextid` 기반 자동 할당
- profile별 reserved VMID range는 2차로 둠
- Terraform state는 local backend로 `/mnt/hermes_data/IaC-state/gjallar/<manifest_id>/terraform.tfstate`에 저장
- apply 전 state lock과 manifest/state `proxmox_vmid`/name 일치 확인
- Terraform/Proxmox apply/config 성공 전에는 power on 금지
- 2026-05-13 target 생성 성공은 powered-off/stopped 상태다.
- first power-on, smoke, guest-agent discovery, SSH verification은 별도 follow-up stage다.

아래 Stage A/Stage B는 historical create-first readiness context다.
현재 target design에서는 Create VM success 조건에 포함하지 않는다.

Stage A:

- clone/hardware/cloud-init 설정은 가능하면 powered-off 상태에서 완료
- apply/config 성공 후 첫 power on
- cloud-init 완료 확인
- guest-agent 응답 확인
- IP 확인
- SSH 접속 확인
- 별도 패키지 설치 없음

Stage A가 안정화되면 Stage B로 최소 Ansible 검증을 추가한다.

Stage B:

- Ansible inventory 생성
- Ansible ping 또는 facts 수집
- 최소 운영 패키지 확인 또는 설치
- Docker/Node/Python/uv/gh 설치는 제외

Ansible 검증은 SSH가 필요하므로 first power on 이후에만 실행한다.
Ansible 실패 VM은 이미 부팅된 VM으로 보고 `created_but_not_ready`로 표시한다.

Slice 4 MVP readiness timeout 기본값:

- first power on task timeout: 5분
- cloud-init timeout: 15분
- guest-agent timeout: 5분
- IP 발견 timeout: 5분
- SSH timeout: 5분
- minimal Ansible verify timeout: 5분

Timeout 발생 시 자동 삭제/자동 reboot 없이 실패 stage와 artifact를 남긴다.
