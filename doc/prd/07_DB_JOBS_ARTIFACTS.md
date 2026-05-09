# Gjallar DB / Jobs / Artifacts PRD

## 0. 목적

DB, job, artifact가 각각 무엇을 저장하는지 정의한다.

## 1. 저장소 역할

| 저장소 | 역할 |
|---|---|
| Manifest Git repo | desired state 원본 |
| Terraform state | 실제 리소스 매핑. MVP local backend |
| Gjallar DB | job/approval/observed snapshot/artifact ref |
| Proxmox | actual VM 상태 |
| Artifact directory | plan/log/smoke 결과 원문, state backup/checksum ref |

DB는 manifest의 대체물이 아니다.
DB는 빠른 조회와 이력, 승인, 관측 snapshot을 담당한다.

## 2. MVP DB 개념 테이블

### observed_nodes

- node_id
- status
- cpu_total / cpu_used
- memory_total / memory_used
- storage summary
- collected_at

### observed_vms

- vmid
- name
- node
- power_state
- ip
- guest_agent_state
- profile_id
- risk_level
- collected_at

### jobs

- job_id
- job_type: vm_create | vm_power_action | preflight | smoke | inventory_sync
- target_type
- target_id
- actor
- status
- risk_level
- approval_required
- started_at
- finished_at

### approvals

- approval_id
- job_id
- requested_by
- approved_by
- decision
- reason
- approval_type: vm_create_confirm | vm_power_confirm | destructive_typed_confirm | scheduled_policy
- plan_artifact_id
- review_summary_checksum
- yellow_risk_acknowledged
- typed_confirmation_value: VM 생성은 null, destructive 작업만 사용
- decided_at

### job_artifacts

- artifact_id
- job_id
- type
- path
- checksum
- created_at

### risk_events

- risk_id
- target_type
- target_id
- risk_code
- level
- message
- evidence_ref
- created_at
- resolved_at

### runtime_targets — deferred after first create MVP

첫 구현 MVP DB migration은 이 테이블을 생략할 수 있다.
`general-vm` 생성, Stage A smoke, job/artifact 추적이 안정화된 뒤 Runtime Target slice에서 추가한다.
추가하더라도 Gjallar가 Heimdall registry에 write하는 용도가 아니라 read-only candidate/readiness 조회용이다.

- target_id
- vmid
- name
- ip
- profile_id
- status
- readiness_state
- active: false
- blocked_reason
- last_smoke_status
- risk_level

Runtime Target slice status 값:

- candidate
- candidate_ready
- blocked

MVP 및 Runtime Target slice에서는 `active=true`를 만들지 않는다. active 전환 정책은 2차 기능이다.
Gjallar는 Heimdall deploy target registry에 직접 write하지 않는다.
`runtime_targets`는 외부 시스템이 조회할 수 있는 Gjallar 내부 candidate/readiness 상태다.

## 3. Artifact 저장

권장 경로:

```text
/var/lib/gjallar/runs/<job_id>/
  request.json
  preflight.json
  plan.txt
  plan.json
  review_summary.json
  approval.json
  apply.log
  bootstrap.log
  smoke.json
  observed_after.json
  state_checksum.txt
  state_backup_ref.json
```

공용 스토리지로 옮길지는 운영 정책에서 결정한다.

## 3.1 Terraform state 저장 정책

MVP에서는 Terraform local backend를 사용한다.

기본 경로:

```text
/mnt/hermes_data/공통/iac-state/gjallar/<manifest_id>/terraform.tfstate
```

DB에는 state 원문을 저장하지 않는다.
저장 가능한 참조 정보:

- state_backend_type: local
- state_path
- state_checksum
- state_last_verified_at
- state_lock_status
- state_vm_mapping: manifest_id / proxmox_vmid / name

Artifact에는 state 원문 대신 checksum과 backup reference를 남긴다.
state backup 원문을 보존해야 하는 경우에도 Proxmox token, SSH key, env secret 원문이 포함되면 안 된다.
state와 manifest의 `proxmox_vmid`/name 매핑이 다르면 red risk로 기록한다.

## 4. Snapshot 정책

Gjallar는 live Proxmox 상태를 주기적으로 수집해 DB에 snapshot으로 저장한다.

원칙:

- UI는 DB snapshot으로 빠르게 렌더링
- 위험 작업 전에는 live check 재실행
- snapshot이 오래되면 stale risk 표시

## 5. Secret 정책

DB와 artifact에는 Proxmox token, SSH private key, env secret을 저장하지 않는다.
필요 시 secret manager 또는 OS credential file 경로만 참조한다.

Proxmox 접근은 API Token 방식으로 고정한다.
DB에는 token 값이 아니라 아래 같은 비밀이 아닌 상태만 저장할 수 있다.

- credential_configured: true/false
- credential_type: api_token
- endpoint_host_hash 또는 redacted endpoint label
- last_verified_at
- last_verification_status
- missing_permission 목록

로그와 artifact에는 token id/secret, SSH key, env secret 원문을 남기지 않는다.

## 6. 생성 후 실패 VM 메타데이터

VM 생성은 성공했지만 smoke/cloud-init/SSH/guest-agent/Ansible 검증이 실패한 경우 VM을 자동 삭제하지 않는다.
DB에는 아래 같은 비밀이 아닌 상태를 저장할 수 있다.

- readiness_state: created_but_not_ready
- cleanup_candidate: true/false
- cleanup_reason: smoke_failed | expired_test_vm | user_cancelled_after_create
- failed_stage: terraform_apply | proxmox_config | first_power_on | cloud_init | guest_agent | ip | ssh | ansible
- retryable: true/false
- runtime_target_active: false
- timeout_policy_snapshot:
  - first_power_on_task_timeout: 5m
  - cloud_init_timeout: 15m
  - guest_agent_timeout: 5m
  - ip_discovery_timeout: 5m
  - ssh_timeout: 5m
  - minimal_ansible_verify_timeout: 5m
- timed_out: true/false
- timeout_stage: first_power_on | cloud_init | guest_agent | ip | ssh | ansible | null

Terraform/Proxmox apply/config 실패로 첫 power on이 생략된 경우:

- readiness_state: provision_failed_not_booted
- boot_skipped: true
- failed_stage: terraform_apply | proxmox_config

삭제/cleanup 실행 이력은 MVP 범위 밖이며, 2차 기능에서 typed confirmation과 승인 이력을 별도 저장한다.
