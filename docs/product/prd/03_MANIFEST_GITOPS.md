# Gjallar Manifest + GitOps PRD

> Current MVP product source of truth is `drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.
> This create-first material is historical/supporting capability context only. It must not define the next MVP success line or implementation order.

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

Profile은 template + 기본 hardware + override 제한 + bootstrap role + safety policy다.

MVP 실제 생성 profile은 `general-vm` 하나만 둔다.

2차 profile 후보는 문서상 방향으로만 남긴다.
MVP에서 manifest fixture나 실제 apply 대상으로 만들지 않는다.

- `runtime-server`: Docker 기반 앱 실행 VM
- `dev-server`: Docker/Node/Python/uv/gh 포함 개발 VM
- `db-server`: DB 전용 VM

### Template Manifest

Proxmox template의 ID/name/storage/cloud-init 가능 여부를 정의한다.
Template 생성/업데이트 자체는 MVP 범위 밖이다.

### Network Profile Manifest

네트워크 profile은 VM마다 붙는 임의 값이 아니라, 실제 Proxmox node bridge와 subnet 정책을 표현한다.

포함 항목:

- network_id
- node별 bridge mapping
- subnet/gateway/DNS
- DHCP/static 허용 여부
- static allowed range
- reserved IP
- runtime target 허용 여부

MVP 결정:

- NetworkProfile이 node별 bridge mapping의 source of truth다.
- `yoonmanserver2`, `yoonmanserver3` 두 target node를 모두 지원한다.
- 초기 fixture 후보는 두 노드 모두 `vmbr0`이다.
- bridge는 사용자가 고르는 raw 값이 아니라, 선택한 target node와 NetworkProfile mapping으로 결정한다.
- plan/preflight는 선택 노드의 Proxmox live inventory에서 mapped bridge 존재를 확인한다.
- 해당 노드에 mapping이 없거나 bridge가 없으면 red risk로 실행을 차단한다.
- IP mode는 `dhcp`, `static` 둘 다 지원하고 기본값은 `static`이다.

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
- network
- IP mode / IP
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

IP 정책은 Gjallar의 Network Profile manifest에서 명시한다.
잘못 전달된 외부 참고 자료를 PRD source of truth로 삼지 않는다.

MVP 정책:

- 최종 reserved/allowed range source는 Network Profile manifest에서 명시한다.
- 1차 IP 충돌 검사는 Network Profile manifest와 Proxmox observed state를 사용한다.
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
