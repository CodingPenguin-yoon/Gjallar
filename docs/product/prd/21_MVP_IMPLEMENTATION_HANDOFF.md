# Gjallar MVP Implementation Handoff

> Superseded/historical create-first handoff:
> Current MVP product source of truth is `drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.
> This create-first material is historical/supporting capability context only. It must not define the next MVP success line or implementation order.
> Do not use this document as the next handoff. Next implementation work should follow `drs-advisor/05_IMPLEMENTATION_PLAN.md`.

이 문서는 PRD 기준으로 첫 MVP 구현에 바로 들어가기 위한 실행 handoff다.
구현자는 먼저 `19_MVP_DECISION_LOCK.md`를 읽고, 이 문서 순서대로 진행한다.

## 0. 구현 원칙

- Historical create-first PRD path: `/mnt/hermes_data/프로젝트/Gjallar/PRD/`
- Current MVP product source of truth: `drs-advisor/`
- 구현 전 질문 금지. `20_REMAINING_DECISIONS.md`의 live inventory 항목은 도구로 조회한다.
- TDD 우선: contract/schema/preflight 테스트를 먼저 만든다.
- destructive action 금지: delete/snapshot rollback/hard stop/reset/kill 구현하지 않는다.
- secret 출력 금지: token id/secret, password, private key는 테스트 fixture에도 넣지 않는다.

## 1. Historical create-first MVP 구현 목표

과거 create-first MVP는 `general-vm` 하나를 안전하게 생성하는 것이었다.
현재 다음 MVP success line은 DRS Advisor migration recommendation, approval, execution, tracking, and reconciliation이다.

```text
read-only inventory
-> create draft
-> preflight
-> plan
-> Review & Confirm
-> GitOps commit/push guard
-> Terraform/Proxmox apply powered-off
-> first power on
-> smoke
-> job/artifact 저장
```

## 2. 고정 fixture / 기본값

```yaml
profile_id: general-vm
vm_name_pattern: gjallar-vm-<YYYYMMDD>-<short_job_id>
hardware:
  cpu: 2
  memory_mb: 4096
  disk_gb: 50
access:
  cloud_init_user: yoon
  ssh_key_source: operator_default_public_key
  password_login: disabled
target_node_candidates:
  - yoonmanserver2
  - yoonmanserver3
network_profile: server-net
node_bridges:
  yoonmanserver2: vmbr0
  yoonmanserver3: vmbr0
ip_modes:
  allowed:
    - dhcp
    - static
  default: static
template_family: ubuntu
mvp_create_ip_range: 192.168.2.140-150
terraform_state_path: /mnt/hermes_data/IaC-state/gjallar/<manifest_id>/terraform.tfstate
iac_repo: /mnt/hermes_data/IaC
```

## 3. 구현 직전 live inventory 조회

질문하지 말고 조회한다.

- Proxmox API node id 목록
- 각 node bridge 목록
- storage 목록/여유량
- Ubuntu template VMID/name/storage
- template cloud-init/qemu-agent readiness
- `192.168.2.140-150` 중 사용 가능한 IP
- API Token 권한이 read/create/power/agent query에 충분한지

조회 결과가 PRD fixture와 다르면 PRD를 바꾸기 전에 `live_inventory_report.json` artifact로 남기고 Review & Confirm에서 risk로 표시한다.

## 4. 구현 순서

### Slice 1 — 현재 코드 inventory

목표:

- 현재 Gjallar repo 구조 파악
- 살릴 코드/버릴 코드/보류 코드 분류
- 기존 느린 backend 원인 후보 기록

산출물:

- `10_CODE_INVENTORY.md` 업데이트
- `11_KEEP_DROP_PARK.md` 업데이트

### Slice 2 — Contract/schema tests

먼저 실패 테스트를 만든다.

필수 테스트:

- `general-vm` profile schema accepts defaults
- future profiles are not create/apply enabled
- NetworkProfile requires node_bridges
- `yoonmanserver2` and `yoonmanserver3` resolve to `vmbr0`
- DHCP/static both accepted, default static
- hardware default is 2/4096/50
- cloud-init user default is `yoon`
- password login disabled
- secrets never serialized

### Slice 2.5 — Minimum job/artifact substrate

목표:

- preflight/plan/approval 이전에 job과 artifact 참조를 저장할 최소 구조를 먼저 만든다.
- `plan_artifact_id`와 `review_summary_checksum`이 실제 저장된 artifact를 가리키게 한다.

필수 최소 구현:

- jobs: `job_id`, `job_type`, `status`, `target_id`, `risk_level`, `started_at`, `finished_at`
- approvals: `job_id`, `plan_artifact_id`, `review_summary_checksum`, `yellow_risk_acknowledged`, `decision`
- job_artifacts: `artifact_id`, `job_id`, `type`, `path`, `checksum`, `created_at`
- artifact directory: `/var/lib/gjallar/runs/<job_id>/`

필수 artifact:

- `preflight_report.json`
- `plan.json`
- `review_summary.json`
- `approval.json`
- `planned_git_diff.txt`

금지:

- secret 원문 저장
- Terraform state 원문 저장
- artifact 없이 approval checksum만 만드는 임시 구현

### Slice 3 — Read-only inventory API

목표:

- nodes list
- VMs list
- VM detail
- node bridge/storage/template inventory
- observed snapshot 저장

금지:

- create/apply/delete 없음
- Heimdall write 없음

### Slice 4 — Create draft / preflight / plan

목표:

- `POST /vm-create/drafts`
- `POST /vm-create/{draft_id}/preflight`
- `POST /vm-create/{draft_id}/plan`

Preflight 필수 checks:

- profile schema
- template 존재/상태
- target node online
- storage 존재/여유
- selected node bridge mapping
- mapped bridge live existence
- `proxmox_vmid`/name collision
- hardware limit
- static IP allowed range/reserved/IP collision
- Terraform state lock
- destroy/delete plan blocker
- credential scope
- Runtime Target 조건은 첫 구현 MVP preflight blocker가 아니다. Runtime Target slice에서 별도 검증으로 추가한다.

### Slice 5 — Review & Confirm

Plan response는 아래를 포함한다.

- VM name
- VMID
- target node
- storage
- template
- CPU/RAM/Disk
- network/IP
- Terraform state path
- first power on included
- smoke timeout summary
- red/yellow risk summary
- plan artifact link
- planned Git diff summary

Approval request:

```json
{
  "plan_artifact_id": "artifact_plan_xxx",
  "review_summary_checksum": "sha256:...",
  "yellow_risk_acknowledged": false
}
```

정책:

- red risk는 execute disabled
- yellow risk는 ack 필요
- typed confirmation 없음

### Slice 6 — GitOps guard

목표:

- job workspace 생성
- IaC repo checkout/pull
- allowlist path만 변경
- generated/manifest 생성
- repo clean check
- commit/push before apply
- non-fast-forward/push failure면 apply 차단

### Slice 7 — Terraform/Proxmox apply powered-off

목표:

- powered-off clone/config
- hardware/cloud-init/network config
- apply/config 성공 전 first power on 금지
- state local backend 사용
- state checksum/backup metadata 저장

실패 상태:

```yaml
readiness_state: provision_failed_not_booted
boot_skipped: true
failed_stage: terraform_apply | proxmox_config
```

### Slice 8 — First power on + smoke

목표:

- first power on
- cloud-init wait
- guest-agent wait
- IP discovery
- SSH check
- smoke report 저장

실패 상태:

```yaml
readiness_state: created_but_not_ready
boot_skipped: false
failed_stage: first_power_on | cloud_init | guest_agent | ip | ssh
```

자동 삭제/reboot/rollback 금지.

### Slice 9 — Optional minimal Ansible verify

Stage A 안정화 후 붙인다.

- inventory 생성
- ansible ping/facts
- 최소 운영 패키지 확인 또는 설치
- Docker/Node/Python/uv/gh 금지

Ansible 실패도 post-boot 실패이므로 `created_but_not_ready`다.

### Slice 10 — UI + artifact expansion

주의:

- approval에 필요한 최소 job/artifact substrate는 Slice 2.5에서 이미 구현되어 있어야 한다.
- 여기서는 UI 노출과 apply/smoke 이후 artifact 확장을 다룬다.

화면:

- Dashboard
- Infra Explorer: Nodes/VMs/VM Detail 한 흐름
- Create VM wizard
- Review & Confirm
- Jobs/Runs
- Risks/Alerts

Artifact 최소 목록:

- Slice 2.5의 approval 필수 artifact 전체
- `terraform_plan.txt/json`
- `terraform_apply.log`
- `state_checksum.json`
- `observed_snapshot.json`
- `smoke_report.json`
- `ansible_verify.json` optional

## 5. 완료 기준

MVP 완료 조건:

- `general-vm` draft 생성 가능
- preflight red/yellow/green 표시 가능
- Review & Confirm에 13개 항목 표시
- 승인 후 Git commit/push 완료 전에는 apply 안 함
- apply/config 성공 전 VM이 부팅되지 않음
- first power on 이후 smoke 결과 저장
- 실패 VM 자동 삭제 없음
- job/artifact로 원인 추적 가능
- hard stop/reset/delete/snapshot/rollback endpoint 없음
- Heimdall registry write 없음

## 6. 구현 중 질문 조건

아래 경우에만 사용자에게 묻는다.

- PRD와 live inventory가 충돌하고, 안전한 기본값을 고를 수 없을 때
- destructive action이 필요할 때
- Git commit/push/delete 같은 사용자 승인 대상 작업이 필요할 때
- MVP 범위를 벗어나는 기능을 넣어야 할 때

그 외는 PRD 기본값으로 진행한다.
