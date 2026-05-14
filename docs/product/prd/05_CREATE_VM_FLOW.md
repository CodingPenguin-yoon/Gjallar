# Gjallar Create VM Flow PRD

> Current MVP product source of truth is `drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.
> This create-first material is historical/supporting capability context only. It must not define the next MVP success line or implementation order.

## 0. 목적

VM 생성 wizard와 원터치/단계별 실행 흐름을 정의한다.

## 0.1 Profile / Template / Network target update

2026-05-13 target design은
[`../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md)를 따른다.

핵심 변경:

- Profile은 UI에 보이는 생성 preset이다. Proxmox template 대체물이 아니다.
- Profile source of truth target은 Gjallar DB seed이며, 초기 UI에서는 read-only다. Profile create/edit/delete UI는 future다.
- 초기 seeded enabled profile은 `general-vm`, `runtime-server`, `development-vm` 세 개다.
- Template source of truth는 Proxmox live inventory다. Gjallar template catalog/registration window는 target에 없다.
- Create VM network target은 `network_id`/`server-net`이 아니라 target node 선택 후 해당 node의 active live bridge 선택이다.
- Static mode는 `static_ip`, `prefix`, `gateway`를 모두 요구한다. DHCP는 허용하지만 이후 guest-agent/inventory discovery warning을 표시한다.
- `gateway`는 사용자가 입력하는 값이다. Gjallar는 static IP에서 `.1`
  gateway를 추론하지 않는다.
- Create VM은 global create policy에 따라 항상 powered-off/stopped로 완료한다. Profile에는 power policy가 없다.

현재 구현 gap:

- 현재 code는 아직 built-in profile 경로이며 `general-vm`만 create-enabled다.
- 현재 Create VM active path는 target node 선택 후 active live bridge의
  explicit `bridge_id`를 사용한다. Incoming `network_id`/`networkId`는
  transition compatibility로 ignore되고 active output에 echo되지 않는다.
- 현재 static network 입력은 `static_ip`, `prefix`, `gateway`를 요구하며,
  native create는 static IP에서 `.1` gateway 또는 `/24` prefix를 추론하지
  않는다.
- 아래 target design은 구현 완료 전까지 current implemented state로 읽으면 안 된다.

## 1. 기본 원칙

- profile 선택을 먼저 보여준다.
- raw CPU/RAM/Disk 옵션은 고급 설정으로 숨긴다.
- VM은 template 기반으로 만든다.
- hardware 설정은 clone 후 첫 부팅 전 적용한다.
- preflight와 plan 없이는 Proxmox native create를 실행하지 않는다.
- runtime target 등록은 사용자가 체크한 경우에만 수행한다.

## 2. Wizard 단계

### Step 1. Profile 선택

Target UI에서 선택 가능한 seeded enabled profile은 세 개다.

| Profile ID | Display name | Korean label | 기본 CPU | 기본 RAM | 기본 Disk |
|---|---|---|---:|---:|---:|
| `general-vm` | General VM | 범용 VM | 2 | 4096MB | 50GB |
| `runtime-server` | Runtime Server | 서비스 실행용 VM | 4 | 8192MB | 100GB |
| `development-vm` | Development VM | 개발/테스트용 VM | 2 | 4096MB | 50GB |

현재 구현에서는 아직 `general-vm` 하나만 create-enabled다. `runtime-server`와
`development-vm`은 target seed profile이며, 코드 변경 전에는 current UI/API
상태로 주장하지 않는다.

표시:

- 용도
- 기본 CPU/RAM/Disk
- CPU/RAM/Disk min/max
- template 요구사항: cloud-init required, qemu guest agent required
- access recommendation: default user, SSH key required, password login disabled

Profile은 target node, storage, template VMID/name, network/network_id, bridge,
static IP, power policy, profile version을 포함하지 않는다.

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
- create 직전 `proxmox_vmid`/name 중복을 다시 확인한다.
- nextid가 stale 하거나 충돌하면 create하지 않고 plan refresh를 요구한다.
- profile별 reserved VMID range는 MVP에 넣지 않고 2차에서 도입할 수 있게만 둔다.

### Step 3. Node / Storage

- target node
- storage
- node resource preview
- storage 여유

### Step 4. Template

Template source of truth는 Proxmox live inventory다.
Target에는 Gjallar template catalog 또는 template registration window가 없다.

UI 동작:

- Proxmox live template 목록을 보여준다.
- 선택된 profile이 요구하는 cloud-init/qemu guest agent 조건을 만족하지 못하는 template은 disabled 상태로 표시한다.
- disabled template에는 실패 이유를 표시한다.
- backend preflight가 template 존재 여부와 요구사항을 다시 확인하고 red-block한다.
- 선택 template disk보다 작은 요청 disk는 preflight red risk다.

### Step 5. Network / IP

- target node 선택
- 선택한 target node의 active live bridge 선택
- DHCP 또는 static 둘 다 지원
- 기본/추천 IP mode는 static
- static mode는 `static_ip`, `prefix`, `gateway`를 모두 입력해야 함
- DHCP mode는 허용하지만 guest-agent/inventory discovery warning 표시

Target Create VM request는 `network_id`/`server-net`에 의존하지 않는다.
선택 가능한 bridge는 선택 target node의 Proxmox live inventory에서 읽는다.
Network tab의 policy/subnet/gateway/range 정보와 추천 IP 통합은 future다.
현재 Network tab policy route는 code 변경 전 current/legacy support로 남을 수 있지만,
target Create VM source of truth는 아니다.

runtime target으로 등록하려면 static IP 또는 안정적 접근 주소가 필요하다.
DHCP 생성 자체는 허용하지만, smoke에서는 guest-agent/IP discovery가 필수 evidence가 된다.

### Step 6. Hardware Override

기본은 profile 값을 사용한다.
Target profile별 기본값과 limit:

| Profile ID | CPU default/min/max | Memory default/min/max MB | Disk default/min/max GB |
|---|---|---|---|
| `general-vm` | 2 / 1 / 8 | 4096 / 1024 / 32768 | 50 / 50 / 500 |
| `runtime-server` | 4 / 2 / 16 | 8192 / 4096 / 65536 | 100 / 80 / 1000 |
| `development-vm` | 2 / 1 / 12 | 4096 / 2048 / 32768 | 50 / 50 / 500 |

고급 설정에서만 CPU/RAM/Disk를 수정한다.
요청 디스크는 선택한 템플릿 디스크보다 작을 수 없다. 작으면 native create 전에 preflight red risk로 차단한다.
수정은 profile limit 안에서만 허용된다.
Profile을 바꾸면 CPU/RAM/Disk는 새 profile default로 reset되고, 이후 사용자가 limit 안에서 다시 수정할 수 있다.

### Step 7. Cloud-init / Access

초기 seeded profile 공통 access recommendation:

- default user: `yoon`
- require SSH key: true
- password login: disabled/fixed
- user override: allowed

Access는 별도 selectable object가 아니다. Create VM Access section에서 username과 SSH public key를 편집한다.
기본 SSH public key는 backend environment 설정에서 올 수 있다. key가 없으면 preflight red block이다.

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
5. live Proxmox template
6. CPU/RAM/Disk
7. bridge / IP mode / static IP / prefix / gateway
8. legacy Terraform state path 또는 manifest/request storage path
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
checkout/pull -> generate manifest -> preflight -> plan -> review/approve -> commit -> proxmox native create-powered-off -> snapshot DB/artifacts
```

현재 구현 slice는 승인된 plan을 기준으로 `IaC` repo에 `VMInstance` manifest를 쓰고 local Git commit을 만드는 `gitops_commit_only` 단계를 연다.
실제 생성은 Proxmox API native 경로가 primary다. `proxmox-preview`는 승인 뒤에도 mutation하지 않고 clone/config/post-check payload artifact만 만들며, `proxmox-create`는 `manifest_commit_sha`와 `proxmox_mutation_acknowledged=true`가 없으면 실행하지 않는다.
Native create는 powered-off clone/config까지만 허용한다. clone UPID polling 뒤 cloned config에서 boot disk 크기를 확인하고, 요청 `disk_gb`가 더 크면 config 전 Proxmox disk resize를 호출한다. resize가 불필요하거나 완료된 뒤 config 적용, `/status/current` + `/config` post-check, `observed_after`/fingerprint artifact가 성공 기준이다.
Terraform plan/apply는 optional/deprecated legacy executor로 남기되 active UI 기본 경로가 아니다.
first power on과 Stage A smoke는 현재 native create 승인에 포함하지 않고 다음 slice의 별도 실행/검증 단계로 둔다.
Profile에는 power policy가 없다. VM start는 future Infra Explorer VM row action과 Jobs/Runs audit로 분리한다.

첫 구현 완료선은 powered-off VM 생성과 manifest/status 기록이다.
Stage A smoke까지의 완료선은 다음 create-readiness slice에서 달성한다.
Stage B minimal Ansible verify와 Runtime Target candidate/readiness API는 VM 생성 flow가 안정화된 뒤 별도 slice에서 붙인다.
Heimdall registry에는 어떤 경우에도 직접 write하지 않는다.

Legacy Terraform state는 optional executor에서만 사용한다. active native create의 source of truth는 Proxmox actual state이며, create 후 `observed_after` artifact와 manifest status commit을 남긴다.

단계별 모드:

- commit만 실행
- Proxmox native preview
- Proxmox native powered-off create/config/post-check 실행
- Terraform plan/apply 준비/실행: legacy optional
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
- Proxmox clone task가 `exitstatus=OK`로 끝났다.
- VM이 target node에 존재하고 `/status/current`가 `stopped`를 반환한다.
- `observed_after` artifact와 normalized fingerprint hash가 저장됐다.
- generated manifest와 observed Proxmox state/status가 연결된다.
- VMInstance manifest의 desired power state는 `stopped`다.
- 작업 artifact가 저장됐다.
- red risk가 남아 있지 않다.

다음 create-readiness slice의 추가 성공 기준:

- IP/guest-agent 상태를 확인했다.
- smoke 결과가 저장됐다.

## 5. general-vm bootstrap 단계화

`general-vm`의 주 목적은 일반 VM 생성 파이프라인을 빠르고 안전하게 검증하는 것이다.
Target에는 `runtime-server`와 `development-vm`도 seeded enabled profile로 추가되지만, bootstrap/package 설치는 여전히 powered-off create 성공 기준이 아니다.
따라서 초기 create 단계에서는 bootstrap을 최소화한다.

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
- Docker/Node/Python/uv/gh 설치는 powered-off create 범위가 아니라 추후 readiness/bootstrap slice에서 profile별로 다룬다.

이 구조는 어렵지 않다. Stage A의 smoke가 SSH와 IP를 이미 검증하므로, Stage B는 같은 접속 정보를 사용해 얇은 Ansible 검증을 추가하면 된다.

## 5.1 First boot gate

현재 powered-off create 정책에서는 첫 power on을 Proxmox native create 승인에 포함하지 않는다.
첫 power on은 native create/config 성공과 manifest status 확인 뒤, 별도 create-readiness slice에서 명시 승인/검증을 붙여 실행한다.

원칙:

- Proxmox native create는 template clone, hardware 설정, cloud-init/network 설정을 가능하면 powered-off 상태에서 끝낸다.
- provider/template 설정이 VM을 자동 부팅시키거나 post-check가 powered-on을 관측하면 success가 아니라 `needs_reconciliation`로 남긴다.
- Review & Confirm의 `first_power_on_included`는 현재 구현에서 `false`다.
- native create/config 단계가 실패하면 Gjallar는 첫 power on을 실행하지 않는다.
- 첫 power on 이후에 smoke를 실행한다. 이 단계는 현재 native create와 분리한다.
- Ansible 검증은 SSH가 필요하므로 첫 power on 이후에만 가능하다.
- 따라서 native create 실패 VM은 부팅하지 않을 수 있지만, Ansible 실패 VM은 이미 부팅된 상태에서 실패한 것으로 표시한다.
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

- Proxmox native create/config timeout 또는 실패는 `provision_failed_not_booted`로 표시하고 첫 power on을 실행하지 않는다.
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
