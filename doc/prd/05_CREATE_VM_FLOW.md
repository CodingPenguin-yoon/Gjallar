# Gjallar Create VM Flow PRD

## 0. 목적

VM 생성 wizard와 원터치/단계별 실행 흐름을 정의한다.

## 1. 기본 원칙

- profile 선택을 먼저 보여준다.
- raw CPU/RAM/Disk 옵션은 고급 설정으로 숨긴다.
- VM은 template 기반으로 만든다.
- hardware 설정은 clone 후 첫 부팅 전 적용한다.
- preflight와 plan 없이는 apply하지 않는다.
- runtime target 등록은 사용자가 체크한 경우에만 수행한다.

## 2. Wizard 단계

### Step 1. Profile 선택

MVP에서 실제 apply 가능한 profile은 `general-vm` 하나다.

2차 후보인 `runtime-server`, `dev-server`, `db-server`는 PRD 방향으로만 남기고 MVP fixture/apply 대상에는 넣지 않는다.
MVP UI에서는 혼란을 줄이기 위해 `general-vm` 하나만 표시한다. future profile은 PRD/스키마 방향으로만 남기고 실제 선택지에는 노출하지 않는다.

표시:

- 용도
- 기본 template
- 기본 CPU/RAM/Disk
- bootstrap role
- 허용 network
- 주요 risk policy

### Step 2. 기본 정보

- VM 이름
- owner
- role
- 설명
- VMID는 MVP에서 수동 입력하지 않고 Proxmox `nextid` 기반 `proxmox_vmid`로 자동 할당

MVP 기본값:

- `general-vm` 이름 추천: `gjallar-vm-<YYYYMMDD>-<short_job_id>`
- 사용자가 이름을 수정할 수 있더라도 Gjallar naming/중복 규칙을 통과해야 한다.
- `proxmox_vmid`는 plan/preflight 단계에서 Proxmox `nextid`로 resolved 한다.
- resolved `proxmox_vmid`는 generated VM manifest에 기록한다.
- apply 직전 `proxmox_vmid`/name 중복을 다시 확인한다.
- nextid가 stale 하거나 충돌하면 apply하지 않고 plan refresh를 요구한다.
- profile별 reserved VMID range는 MVP에 넣지 않고 2차에서 도입할 수 있게만 둔다.

### Step 3. Node / Storage

- target node
- storage
- node resource preview
- storage 여유

### Step 4. Template

- profile 기본 template 확인
- template 존재 여부
- cloud-init 가능 여부
- guest-agent 예상 여부

### Step 5. Network / IP

- network profile 선택
- target node별 bridge mapping 확인
- 선택한 target node의 mapped bridge를 사용
- `yoonmanserver2`, `yoonmanserver3` 두 target node 모두 지원
- 초기 fixture 후보는 두 노드 모두 `vmbr0`
- DHCP 또는 static 둘 다 지원
- 기본/추천 IP mode는 static
- static IP 입력/추천
- gateway/DNS 확인

bridge는 VM 생성 요청에서 raw 값으로 받지 않는다.
Gjallar는 `network_profile.node_bridges[target_node]`로 bridge를 resolve 하고,
plan/preflight에서 해당 target node의 Proxmox live inventory에 bridge가 실제 존재하는지 확인한다.
노드별 실제 vmbr 목록은 Proxmox inventory에서 읽고, vmbr의 의미/subnet/gateway/DNS/고정 IP 범위는 공용 IaC의 `manifests/networks/network-profiles.yaml`에서 관리한다.
Create VM 화면은 이 두 정보를 합쳐 선택한 노드에서 사용 가능한 네트워크만 보여준다.

runtime target으로 등록하려면 static IP 또는 안정적 접근 주소가 필요하다.
DHCP 생성 자체는 허용하지만, smoke에서는 guest-agent/IP discovery가 필수 evidence가 된다.

### Step 6. Hardware Override

기본은 profile 값을 사용한다.
`general-vm` 기본값은 2 vCPU / 4096MB RAM / 40GB disk다.
고급 설정에서만 CPU/RAM/Disk를 수정한다.
수정은 profile limit 안에서만 허용된다.

### Step 7. Cloud-init / Access

`general-vm` 기본값:

- cloud-init user: `yoon`
- SSH key source: operator default public key
- password login: disabled

private key, password, token secret은 manifest/DB/artifact/UI/API 응답에 저장하지 않는다.

### Step 8. Runtime Target 옵션

체크박스:

```text
[ ] 외부 앱 실행 대상으로 등록 가능한 runtime target으로 표시
```

체크 시 추가 조건:

- static IP 또는 고정 DNS 필요
- MVP에서는 candidate로만 표시
- smoke 성공 시 candidate_ready로 표시 가능
- red risk 있으면 blocked로 표시
- active 자동 전환은 2차 기능

### Step 9. Preflight

모든 검사를 실행하고 red/yellow/green을 보여준다.

### Step 10. Plan Review / Review & Confirm

Plan 생성 후 사용자 승인 화면을 보여준다. VM 생성은 일반 Confirm 버튼으로 승인한다.
yellow risk가 있으면 경고 체크박스를 명시적으로 체크해야 한다.
red risk가 있으면 approve/execute 버튼을 비활성화한다.

Review & Confirm에 반드시 표시할 것:

1. 생성될 VM 이름
2. VMID
3. target node
4. storage
5. template
6. CPU/RAM/Disk
7. network / IP
8. Terraform state path
9. 첫 power on 포함 여부
10. smoke timeout 요약
11. red/yellow risk summary
12. plan artifact link
13. Git commit 예정 diff 요약

VM 생성 approve request에는 사용자가 본 `plan_artifact_id`, `review_summary_checksum`, `yellow_risk_acknowledged`를 남긴다.
VM 생성에는 typed confirmation을 요구하지 않는다. typed confirmation은 삭제/rollback/destructive 작업에만 사용한다.

### Step 11. Execute

원터치 모드:

```text
checkout/pull -> generate manifest -> preflight -> plan -> review/approve -> commit -> push -> apply/create-powered-off -> first power on -> Stage A smoke -> snapshot DB/artifacts
```

현재 구현 slice는 승인된 plan을 기준으로 `IaC` repo에 `VMInstance` manifest를 쓰고 local Git commit을 만드는 `gitops_commit_only` 단계를 연다.
추가로 승인된 plan에서 격리된 Terraform workspace를 생성하고, 명시 승인 후 `terraform init/plan`과 `terraform apply`를 실행하는 단계를 연다.
Terraform apply는 powered-off clone/config까지만 허용한다. `terraform_apply_acknowledged=true`와 `proxmox_mutation_acknowledged=true`가 모두 없으면 실행하지 않는다.
first power on과 Stage A smoke는 현재 apply 승인에 포함하지 않고 다음 slice의 별도 실행/검증 단계로 둔다.

첫 구현 완료선은 powered-off VM 생성과 manifest/status 기록이다.
Stage A smoke까지의 완료선은 다음 create-readiness slice에서 달성한다.
Stage B minimal Ansible verify와 Runtime Target candidate/readiness API는 VM 생성 flow가 안정화된 뒤 별도 slice에서 붙인다.
Heimdall registry에는 어떤 경우에도 직접 write하지 않는다.

MVP Terraform state는 local backend로 사용하며, root는 환경변수 `GJALLAR_TF_STATE_ROOT`/`GJALLAR_TERRAFORM_STATE_ROOT`가 있으면 그 값을 쓰고, 없으면 `GJALLAR_SHARED_ROOT/IaC-state/gjallar/<manifest_id>/terraform.tfstate`를 사용한다.
apply 전 state lock과 manifest/state `proxmox_vmid`/name 일치 여부를 확인한다.
apply 후 state backup/checksum과 observed snapshot을 남긴다.

단계별 모드:

- commit만 실행
- Terraform plan 준비/실행
- apply/configure powered-off만 실행
- first power on 실행: 다음 slice
- smoke 재시도: 다음 slice
- minimal Ansible verify 재시도: Stage B를 붙인 뒤 허용
- Gjallar runtime target readiness 재평가: Runtime Target slice를 붙인 뒤 허용

## 3. Job 상태

```text
DRAFT
PREFLIGHT_RUNNING
PREFLIGHT_BLOCKED
PLAN_READY
WAITING_APPROVAL
APPLY_RUNNING
FIRST_POWER_ON_RUNNING
BOOTSTRAP_RUNNING
SMOKE_RUNNING
COMPLETED
COMPLETED_WITH_WARNINGS
FAILED
CANCELLED
```

원칙:

- `job.status`는 위 enum만 사용한다.
- smoke/cloud-init/guest-agent/IP/SSH 실패는 별도 job status로 만들지 않는다.
- 생성은 됐지만 준비 실패인 경우 `job.status=FAILED` 또는 `COMPLETED_WITH_WARNINGS`로 남기고, 상세 원인은 `readiness_state`와 `failed_stage`에 기록한다.
- Stage B를 나중에 붙이면 Ansible 실행 중 상태 enum은 별도 migration으로 추가한다. 첫 구현 MVP enum에는 넣지 않는다.

## 4. 성공 기준

현재 powered-off create 성공 기준:

- 승인된 manifest가 IaC repo에 commit되어 있다.
- Terraform apply가 성공했고 VM이 Proxmox에 존재한다.
- generated manifest와 Terraform state/status가 연결된다.
- VMInstance manifest의 desired power state는 `stopped`다.
- 작업 artifact가 저장됐다.
- red risk가 남아 있지 않다.

다음 create-readiness slice의 추가 성공 기준:

- IP/guest-agent 상태를 확인했다.
- smoke 결과가 저장됐다.

## 5. general-vm bootstrap 단계화

MVP 실제 생성 profile인 `general-vm`의 주 목적은 일반 VM 생성 파이프라인을 빠르고 안전하게 검증하는 것이다.
즉 “앱 실행 서버”나 “개발 서버”가 아니라, template clone + hardware/network/cloud-init + smoke까지 되는 기본 VM이다.
따라서 MVP 첫 단계에서는 bootstrap을 최소화한다.

### Stage A — smoke only

먼저 구현한다.

- cloud-init 완료 확인
- guest-agent 응답 확인
- IP 확인
- SSH 접속 확인
- 별도 패키지 설치는 원칙적으로 하지 않음

### Stage B — minimal Ansible verification

Stage A가 안정화된 뒤 붙인다. 첫 구현 MVP 완료 기준에는 포함하지 않는다.

- Ansible inventory 생성 확인
- Ansible ping 또는 facts 수집 확인
- `curl`, `git`, `qemu-guest-agent` 같은 최소 운영 패키지 존재 확인 또는 설치
- Docker/Node/Python/uv/gh 설치는 `general-vm` 범위가 아니라 `dev-server`/`runtime-server` profile로 넘김

이 구조는 어렵지 않다. Stage A의 smoke가 SSH와 IP를 이미 검증하므로, Stage B는 같은 접속 정보를 사용해 얇은 Ansible 검증을 추가하면 된다.

## 5.1 First boot gate

현재 powered-off create 정책에서는 첫 power on을 Terraform apply 승인에 포함하지 않는다.
첫 power on은 apply/config 성공과 manifest status 확인 뒤, 별도 create-readiness slice에서 명시 승인/검증을 붙여 실행한다.

원칙:

- Terraform/Proxmox apply는 template clone, hardware 설정, cloud-init/network 설정을 가능하면 powered-off 상태에서 끝낸다.
- Terraform/provider/template 설정이 VM을 자동 부팅시키는 경우 preflight 또는 plan review에서 red/yellow risk로 표시한다.
- Review & Confirm의 `first_power_on_included`는 현재 구현에서 `false`다.
- apply/config 단계가 실패하면 Gjallar는 첫 power on을 실행하지 않는다.
- 첫 power on 이후에 smoke를 실행한다. 이 단계는 현재 apply와 분리한다.
- Ansible 검증은 SSH가 필요하므로 첫 power on 이후에만 가능하다.
- 따라서 Terraform/Proxmox 실패 VM은 부팅하지 않을 수 있지만, Ansible 실패 VM은 이미 부팅된 상태에서 실패한 것으로 표시한다.
- Ansible 실패 시 추가 reboot/power action은 하지 않고 `created_but_not_ready`로 표시한다.

## 5.2 Readiness timeout 기본값

MVP 기본 timeout은 아래처럼 둔다.
값은 제품 기본값이며, 이후 Settings/Profile에서 조정 가능하게 만들 수 있다.

```yaml
first_power_on_task_timeout: 5m
cloud_init_timeout: 15m
guest_agent_timeout: 5m
ip_discovery_timeout: 5m
ssh_timeout: 5m
minimal_ansible_verify_timeout: 5m
```

Timeout 실패 정책:

- Terraform/Proxmox apply/config timeout 또는 실패는 `provision_failed_not_booted`로 표시하고 첫 power on을 실행하지 않는다.
- first power on 이후 cloud-init/guest-agent/IP/SSH/Ansible timeout은 `created_but_not_ready`로 표시한다.
- timeout이 발생해도 VM 자동 삭제, 자동 reboot, 자동 rollback은 하지 않는다.
- Runtime Target slice가 구현된 뒤에는 기존 상태 체계 안에서 `blocked`로 표시하거나 `candidate`에 readiness 실패 사유를 붙이며, `active=true`로 전환하지 않는다.

## 6. 생성 후 실패 처리 정책

VM 생성 자체가 성공한 뒤 smoke/cloud-init/SSH/guest-agent/Ansible 검증이 실패해도 Gjallar는 VM을 자동 삭제하지 않는다.

정책:

- 실패한 VM은 디버깅 증거로 보존한다.
- job 상태는 `FAILED` 또는 `COMPLETED_WITH_WARNINGS`로 남긴다.
- VM readiness는 `created_but_not_ready`로 표시한다.
- 상세 원인은 `failed_stage=first_power_on | cloud_init | guest_agent | ip | ssh | ansible` 중 하나로 기록한다. `ansible`은 Stage B를 붙인 뒤에만 사용한다.
- runtime target은 active 금지다.
- UI는 “생성은 됐지만 준비 실패”를 명확히 표시한다.
- 사용자는 재시도/조사/수동 삭제 후보 등록 중 하나를 선택한다.

MVP에서는 자동 cleanup을 구현하지 않는다.
대신 아래 메타데이터만 남길 수 있다.

```yaml
cleanup_candidate: true
cleanup_reason: smoke_failed | expired_test_vm | user_cancelled_after_create
expires_at: optional
```

실제 삭제/cleanup은 2차 기능으로 두며, typed confirmation과 사용자 승인을 반드시 요구한다.
