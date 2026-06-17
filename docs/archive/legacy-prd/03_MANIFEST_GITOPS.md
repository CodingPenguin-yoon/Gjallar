# Gjallar Manifest + GitOps PRD

> Current MVP product source of truth is `docs/product/drs-advisor/`. If this document conflicts with that folder, `docs/product/drs-advisor/` wins.
> This create-first material is historical/supporting capability context only. It must not define the next MVP success line or implementation order.

> 2026-05-13 Create VM profile/template/network update: the target design is
> [`docs/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md).
> For Create VM, profile comes from three enabled UI-visible DB seed profiles
> (`general-vm`, `runtime-server`, `development-vm`); template and bridge come
> from Proxmox live inventory; `network_id`/`server-net`, template catalogs, and
> profile node/storage/network/template/power/version bindings are superseded.

## 0. 목적

Gjallar의 VM 생성/관리 선언 데이터와 IaC 실행 구조를 정의한다.

## 1. 핵심 모델

```text
Git/IaC repo       = desired state / 설계도 원본
Job workspace      = per-job execution copy / 실행용 사본
Terraform state    = actual resource mapping ledger / 실제 VM 연결 장부
Gjallar DB         = job history, approvals, observations, artifact refs
Proxmox            = actual VMs
```

DB만 믿지 않는다.
Manifest와 실제 Proxmox 상태를 계속 대조한다.

## 2. 권장 저장 위치

```text
/mnt/hermes_data/IaC
  manifests/
    profiles/
    templates/
    networks/
    vms/
    runtime-targets/
  terraform/
  ansible/
  generated/

/var/lib/gjallar/runs/<job_id>/iac
  # job별 checkout/copy

/mnt/hermes_data/IaC-state
  gjallar/<manifest_id>/terraform.tfstate
  # MVP local backend. Git에 넣지 않음.
```

Terraform/Ansible 코드는 공용 스토리지/IaC repo에서 관리한다.
MVP에서는 Gjallar가 직접 실행할 수 있지만, 나중에 runner로 분리할 수 있게 job abstraction을 둔다.

## 2.1 Git checkout / commit / push 원칙

IaC는 단순 파일 폴더가 아니라 Git으로 추적되는 repo로 관리한다.

기본 흐름:

```text
IaC Git remote
  -> local checkout / job workspace
  -> manifest/generated 변경
  -> schema validation / preflight / plan
  -> 사용자 review & approval
  -> git commit
  -> git push
  -> apply/bootstrap/smoke
  -> observed state와 artifact 저장
```

역할 분리:

- 사람이 Terraform/Ansible engine code를 수정할 때는 로컬 checkout에서 작업하고 commit/push한다.
- Gjallar job은 깨끗한 checkout 또는 job workspace에서 허용된 manifest/generated 파일만 만든다.
- Gjallar는 apply 전에 repo clean check와 최신 상태 pull/fetch를 수행한다.
- commit에는 job id, actor, approval id, plan artifact reference를 남긴다.
- push 실패, non-fast-forward, dirty tree는 apply 전 red/yellow risk로 막거나 재검토한다.

MVP에서는 `/mnt/hermes_data/IaC`를 durable IaC repo checkout 후보로 쓰되, job 실행은 `/var/lib/gjallar/runs/<job_id>/iac` 같은 per-job workspace에서 수행한다.

## 2.2 Terraform state/backend 정책

MVP에서는 Terraform local backend를 사용한다.

기본 위치:

```text
/mnt/hermes_data/IaC-state/gjallar/<manifest_id>/terraform.tfstate
```

원칙:

- 용어를 분리한다.
  - `manifest_id`: VMInstance manifest의 `metadata.id`인 Gjallar 내부 문자열 ID
  - `proxmox_vmid`: Proxmox가 사용하는 numeric VMID
- state path의 `<manifest_id>`는 VMInstance manifest의 `metadata.id`를 사용한다.
- Terraform state는 Git에 넣지 않는다.
- Gjallar DB에는 state 원문이 아니라 backend type, state path, checksum/hash, last verified timestamp 같은 참조 정보만 저장한다.
- job workspace는 위 state path를 가리키는 backend config로 plan/apply를 실행한다.
- Proxmox token id/secret, SSH key, env secret 원문이 state/backend config/log/artifact에 남으면 안 된다.
- plan/apply 전 per-VMID/per-name/per-IP lock과 Terraform state lock을 확인한다.
- apply 전 manifest의 `proxmox_vmid`/name과 state의 리소스 매핑이 다르면 red risk로 막는다.
- apply 후 state backup/snapshot 또는 checksum을 남기고, observed state를 다시 수집한다.
- MinIO/S3 remote backend와 state migration UI/runbook은 2차 기능으로 둔다.

## 3. Gjallar write allowlist

Gjallar가 자동으로 수정할 수 있는 경로:

```text
manifests/vms/**
generated/**
```

사용자 승인 후에만 가능하다.
`manifests/runtime-targets/**` write는 Runtime Target Phase 6 이후 재검토한다. 첫 구현 MVP에서는 VM 생성 안정화를 위해 제외한다.

## 4. Gjallar write denylist

Gjallar가 자동 수정하면 안 되는 경로:

```text
terraform/modules/**
terraform/providers/**
ansible/roles/**
ansible/playbooks/**
scripts/**
```

이 영역은 사람이 관리하는 엔진 코드다.
수정이 필요하면 별도 코드 작업/리뷰로 처리한다.

## 5. Manifest 종류

### VM Profile Manifest

Create VM target에서는 Profile manifest가 source of truth가 아니다.
Profile은 Gjallar DB seed의 UI-visible read-only creation preset이며, template + node/storage/network binding이 아니다.

초기 enabled profile:

- `general-vm`
- `runtime-server`
- `development-vm`

Profile에는 CPU/RAM/Disk default/limit, template requirement, access recommendation만 둔다.
Profile에는 target node, storage, network/`network_id`, bridge, static IP, template VMID/name, power policy, profile version을 넣지 않는다.

### Template Manifest

Create VM target에서는 Gjallar template catalog나 registration window를 두지 않는다.
Template source of truth는 Proxmox live inventory다.
UI는 live template을 표시하고, 선택 profile requirement를 만족하지 못하는 template은 disabled reason과 함께 비활성화한다.
Backend preflight는 실행 직전 live template requirement를 다시 검증한다.

### Network Profile Manifest

Network Profile manifest는 historical create-first source of truth였다.
Create VM target에서는 Network tab policy/subnet/range state가 future integration point일 뿐, Create VM source of truth가 아니다.

Create VM target 결정:

- `network_id`와 `server-net`을 사용하지 않는다.
- 사용자가 target node를 먼저 고르고, 그 node의 active live bridge를 선택한다.
- plan/preflight는 선택 node의 Proxmox live inventory에서 bridge 존재와 active 상태를 확인한다.
- static mode는 `static_ip`, `prefix`, `gateway`가 모두 필요하다.
- DHCP mode는 허용하지만 guest-agent 또는 inventory discovery가 나중에 필요하다는 warning을 남긴다.

### VM Instance Manifest

생성하려는 VM의 desired state다.

포함 항목:

- manifest_id: `metadata.id`, Gjallar 내부 문자열 ID
- proxmox_vmid: Proxmox numeric VMID
- name
- node
- profile
- template
- CPU/RAM/Disk
- storage
- selected live bridge
- IP mode, static mode의 `static_ip`/`prefix`/`gateway`
- owner / role
- risk policy

MVP VMID 정책:

- UI에서는 VMID 직접 입력을 기본 제공하지 않는다.
- Gjallar는 plan/preflight 단계에서 Proxmox `nextid`를 조회해 `proxmox_vmid`를 resolved 한다.
- VM Instance manifest에는 apply 전 resolved `proxmox_vmid`를 기록한다.
- apply 직전 Proxmox observed state와 VM manifests를 기준으로 `proxmox_vmid`/name 중복을 다시 확인한다.
- 충돌 시 commit/apply를 중단하고 plan refresh를 요구한다.
- profile별 reserved VMID range는 2차 기능으로 둔다.

### Runtime Target Manifest

외부 시스템이 앱 실행 대상으로 참조할 수 있는 Gjallar 내부 VM 후보를 정의한다.
MVP에서는 후보와 readiness만 표현하고, Heimdall deploy target registry에는 직접 write하지 않는다.
첫 구현 MVP에서는 Runtime Target manifest/API/checkbox 구현을 요구하지 않는다. `active` 자동 전환 금지와 Heimdall registry write 금지만 테스트로 고정한다.
공용 runtime-target manifest와 `active` 실행 대상 확정은 Gjallar core VM 생성 flow가 안정화된 뒤 2차에서 재검토한다.

## 6. Network/IP source 원칙

Create VM target의 network source of truth는 선택 target node의 Proxmox live bridge inventory와 request의 IP mode/static fields다.
Network Profile manifest나 Network tab policy는 future integration/historical context이며 Create VM target source of truth가 아니다.
잘못 전달된 외부 참고 자료를 PRD source of truth로 삼지 않는다.

Target 정책:

- `network_id`/`server-net`은 target Create VM draft contract에 넣지 않는다.
- static IP는 `static_ip`, `prefix`, `gateway`를 모두 요구한다.
- 1차 bridge 검사는 Proxmox live inventory를 사용한다.
- 실제 충돌 감지가 부족하면 DHCP/ARP/라우터 lease 조회를 read-only evidence로 추가한다.
- 외부 IP inventory 연동과 Gjallar 자체 IPAM은 MVP 범위 밖이다.

## 7. 실행 guard

모든 job은 아래 guard를 가진다.

- repo clean check
- schema validation
- path allowlist
- per-VMID/per-name/per-IP lock
- plan artifact 저장
- 사용자 승인
- apply 후 observed state 재수집
- MVP에서는 smoke 성공 여부와 관계없이 runtime target active 자동 전환 금지
