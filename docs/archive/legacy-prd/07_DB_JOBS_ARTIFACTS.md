# Gjallar DB / Jobs / Artifacts PRD

## 0. 목적

DB, job, artifact가 각각 무엇을 저장하는지 정의한다.

현재 DRS Advisor MVP의 세부 source-of-truth/data-boundary와 DB field usage는 [`docs/product/drs-advisor/`](../../product/drs-advisor/README.md)가 우선한다.
이 문서는 DB/jobs/artifacts 공통 원칙과 current DRS Advisor 개념 테이블 요약을 함께 둔다.

## 1. 저장소 역할

| 저장소 | 역할 |
|---|---|
| Manifest Git repo | desired state 원본 |
| Terraform state | optional/deprecated legacy executor state. Active Create VM success uses Proxmox observed state |
| Gjallar DB | job/approval/observed snapshot/artifact ref |
| Proxmox | actual VM 상태 |
| Artifact directory | plan/log/smoke 결과 원문, state backup/checksum ref |

DB는 manifest의 대체물이 아니다.
DB는 빠른 조회와 이력, 승인, 관측 snapshot을 담당한다.

## 1.1 Current DRS Advisor data boundary

DRS Advisor에서 Proxmox가 actual state의 source of truth다.
Gjallar DB는 Proxmox current inventory/metrics/task/HA/storage state를 대체하지 않는다.
추천과 final pre-check는 Proxmox current state에서 재구성해야 한다.

Proxmox current state로 확인해야 하는 값:

- VM 존재 여부
- VMID locator와 현재 node
- VM running state
- node online/offline
- CPU/Memory current, 15분 average, 15분 peak
- storage visibility/capacity
- HA state
- active task/UPID
- config lock
- passthrough evidence
- route feasibility
- cluster health/quorum

Gjallar DB가 저장하는 값:

- jobs/runs
- approvals
- artifact refs
- operation locks
- VM metadata/policy
- fingerprint assertion
- identity review decisions
- recommendation snapshots
- pre-check results
- Proxmox UPID tracking state
- reconciliation state
- audit trail
- optional observed snapshots for UI cache

DB observed snapshot은 UI cache와 과거 evidence다.
실행 허가에는 사용할 수 없으며, final pre-check를 대체하지 않는다.

Create VM도 같은 원칙을 따른다. 현재 active create success는 Terraform state가 아니라 Proxmox native post-check 결과다. `observed_after` artifact는 `/status/current`, `/config`, normalized fingerprint hash를 저장하며, VM missing/powered-on/task failure는 failed 또는 `needs_reconciliation`으로 남기고 manifest를 `applied`로 만들지 않는다.

Re-attachable 원칙:

- Gjallar restart 후 Proxmox current inventory/metrics/task state를 다시 읽는다.
- VMID는 identity가 아니라 locator로만 사용한다.
- metadata/policy는 fingerprint match 시에만 attach한다.
- same VMID + different fingerprint는 Identity Mismatch로 보고 모든 작업을 차단한다.
- unknown fingerprint는 Unclassified/identity unknown으로 보고 Confirm Identity 전 migration을 막는다.

## 1.2 DRS Advisor DB policy

DB 값이 code/validation에 미치는 핵심 정책:

- `identity_status=confirmed`와 current fingerprint match가 없으면 DRS 실행 후보가 아니다.
- metadata required fields가 없으면 metadata incomplete blocker다.
- `migration_policy=allowed`만 MVP migration 실행 가능하다.
- `migration_policy=restricted`는 metadata가 있어도 일반 DRS 실행에서 제외한다.
- `migration_policy=blocked`는 이동 금지다.
- active operation lock이 있으면 Approve & Migrate를 비활성화한다.
- `route_status=Unknown`은 migration 불가다.
- Check Now result는 참고용이며 실행 허가로 재사용하지 않는다.
- `precheck_type=final` 결과만 실행 직전 gate로 사용한다.
- Proxmox UPID/task tracking이 불명확하거나 30분 timeout이면 `needs_reconciliation`이다.
- lock stale/reconciliation_required는 Reconcile Now 전 자동 성공 release하지 않는다.

## 2. MVP DB 개념 테이블

### Current DRS Advisor concept tables

아래 테이블은 DRS Advisor MVP의 현재 우선 개념이다.
기존 create-first 테이블은 보조 capability로 남긴다.

#### vm_identity_assertions

- `assertion_id`
- `vm_metadata_id`
- `proxmox_cluster_id`
- `last_seen_vmid`
- `primary_fingerprint_hash`: SMBIOS UUID/vmgenid/MAC list/disk volume id list 기반
- `secondary_fingerprint_hash`: VM name, CPU/RAM/disk config hash 기반
- `identity_status`: unknown | confirmed | mismatch | retired_candidate
- `confirmed_by`
- `confirmed_at`
- `retired_at`
- `retire_reason`

code/validation:

- recommendation builder는 `identity_status=confirmed`가 아니면 VM을 제외한다.
- current primary fingerprint가 다르면 metadata attach를 금지한다.
- same VMID + different fingerprint는 Identity Mismatch critical risk를 만든다.
- retired assertion은 Treat as New VM 이후 기존 metadata 자동 재사용을 막는다.

#### vm_metadata

- `vm_metadata_id`
- `owner`
- `environment`
- `sensitivity`: normal | sensitive | critical
- `migration_policy`: allowed | restricted | blocked
- `service_name`
- `preferred_node`
- `notes`
- `metadata_status`

code/validation:

- owner/environment/sensitivity/migration_policy가 없으면 metadata incomplete blocker다.
- sensitivity critical은 warning이며 blocker는 아니다.
- migration_policy allowed만 Approve & Migrate 후보가 된다.
- restricted는 MVP 일반 DRS 실행 제외다.
- blocked는 recommendation과 execution 모두 차단한다.
- preferred_node는 warning/tie-breaker evidence일 뿐 final pre-check를 대체하지 않는다.

#### observed_nodes

- `node_id`
- `online`
- `cpu_current_percent`
- `cpu_15m_avg_percent`
- `cpu_15m_peak_percent`
- `memory_current_percent`
- `memory_15m_avg_percent`
- `memory_15m_peak_percent`
- `storage_summary_ref`
- `ha_summary_ref`
- `active_task_count`
- `collected_at`

code/validation:

- Dashboard node row와 recommendation snapshot input에 사용한다.
- resource polling 기본값은 1분이다.
- final pre-check에서는 live Proxmox state를 다시 확인한다.
- stale `collected_at`은 warning evidence다.

#### drs_recommendations

- `recommendation_id`
- `vm_locator_vmid`
- `vm_metadata_id`
- `identity_assertion_id`
- `source_node_id`
- `target_node_id`
- `score`
- `rank`
- `reason_codes`
- `metric_window`: 최근 15분 average + peak
- `route_status`: Feasible | Warning | Blocked | Unknown
- `blockers`
- `warnings`
- `generated_at`
- `expires_at`
- `status`

code/validation:

- Dashboard top 1~3 추천과 DRS Advisor full table을 렌더링한다.
- blockers가 있으면 Approve & Migrate disabled다.
- route_status Unknown/Blocked이면 실행 불가다.
- recommendation snapshot은 approval review에 표시하지만 실행 허가 근거가 아니다.

#### drs_prechecks

- `precheck_id`
- `recommendation_id`
- `job_id`
- `precheck_type`: check_now | final
- `result`: pass | warning | blocked | unknown
- `checks_json_ref`
- `blockers`
- `warnings`
- `artifact_id`
- `created_at`

code/validation:

- check_now는 선택적 참고용이다.
- final만 execution gate다.
- 이전 pre-check 결과는 Approve & Migrate 실행 허가에 재사용하지 않는다.
- final result blocked/unknown이면 migration job을 만들지 않는다.
- final result warning이면 confirm modal에서 acknowledgement가 필요하다.

#### operation_locks

- `lock_id`
- `scope_type`: vm | node | route
- `scope_key`
- `job_id`
- `status`: active | released | stale | reconciliation_required
- `acquired_at`
- `expires_at`
- `released_at`
- `release_reason`

code/validation:

- no operation lock은 final pre-check 필수 항목이다.
- active lock이 있으면 Approve & Migrate disabled다.
- timeout/worker crash 후 lock은 stale 또는 reconciliation_required로 남긴다.
- Reconcile Now가 current Proxmox state를 확인한 뒤 release 여부를 결정한다.

#### jobs

- `job_id`
- `job_type`: drs_migration | vm_create | vm_power_action | preflight | smoke | inventory_sync
- `recommendation_id`
- `target_type`
- `target_locator`
- `vm_metadata_id`
- `identity_assertion_id`
- `source_node_id`
- `target_node_id`
- `actor`
- `approved_by`
- `status`: queued | prechecking | running | success | failed | needs_reconciliation
- `risk_level`
- `started_at`
- `finished_at`
- `timeout_at`

code/validation:

- same VM의 running job은 active conflicting task blocker다.
- Jobs/Runs는 status와 artifact refs로 실행 상태를 보여준다.
- timeout 기본값은 30분이며 명확하지 않으면 needs_reconciliation이다.

#### proxmox_tasks

- `task_id`
- `job_id`
- `upid`
- `node_id`
- `task_type`
- `status`
- `exitstatus`
- `started_at`
- `ended_at`
- `last_polled_at`
- `task_log_artifact_id`

code/validation:

- worker는 UPID를 polling해 Proxmox task 상태를 추적한다.
- Proxmox task success만으로 job success를 확정하지 않고 VM target node/fingerprint를 다시 확인한다.
- UPID가 확인되지 않거나 결과가 애매하면 needs_reconciliation이다.

#### reconciliation_events

- `reconciliation_id`
- `job_id`
- `reason`: timeout | restart | upid_missing | state_mismatch | manual_reconcile
- `observed_vmid`
- `observed_node_id`
- `expected_source_node_id`
- `expected_target_node_id`
- `observed_task_status`
- `decision`: mark_success | mark_failed | keep_needs_reconciliation | release_lock
- `artifact_id`
- `decided_at`

code/validation:

- Reconcile Now 결과를 감사 가능하게 저장한다.
- target node running + fingerprint match가 확인되어야 success 전환 가능하다.
- 확인이 불충분하면 needs_reconciliation과 lock reconciliation_required를 유지한다.

### Legacy/create-first concept tables

아래 항목은 기존 create-first PRD에서 온 개념 테이블이다.
Create VM, powered-off apply, smoke, runtime target 후보 같은 보조 capability를 설명하기 위해 보존한다.
DRS Advisor 실행 안전성 판단에서는 위의 DRS Advisor concept tables와 Proxmox current state 재확인이 우선한다.

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

## 3.1 Legacy Terraform state 저장 정책

현재 active Create VM은 Proxmox native post-check를 성공 기준으로 사용한다. Terraform local backend는 optional/deprecated executor에서만 사용한다.

기본 경로:

```text
/mnt/hermes_data/IaC-state/gjallar/<manifest_id>/terraform.tfstate
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

## 4. Snapshot/cache 정책

Gjallar는 live Proxmox 상태를 주기적으로 수집해 DB 또는 cache에 snapshot으로 저장할 수 있다.
이 snapshot은 화면 응답 속도, 추세 계산, audit evidence를 위한 보조 데이터다.

원칙:

- UI는 DB/cache snapshot으로 빠르게 렌더링할 수 있다.
- DRS recommendation은 recent snapshot/metric window를 사용할 수 있다.
- 위험 작업 전에는 live Proxmox read 기반 final pre-check를 반드시 재실행한다.
- snapshot, Check Now, recommendation snapshot은 실행 허가가 아니다.
- snapshot이 오래되면 stale warning/risk로 표시한다.
- partial inventory는 VM 삭제, identity 해소, metadata attach, lock release 근거가 될 수 없다.

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
- failed_stage: native_create | proxmox_config | first_power_on | cloud_init | guest_agent | ip | ssh | ansible
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

Proxmox native create/config 실패로 첫 power on이 생략된 경우:

- readiness_state: provision_failed_not_booted
- boot_skipped: true
- failed_stage: native_create | proxmox_config

삭제/cleanup 실행 이력은 MVP 범위 밖이며, 2차 기능에서 typed confirmation과 승인 이력을 별도 저장한다.
