# DRS Advisor Data, DB, and Identity

## 1. Source of truth

Proxmox가 actual state의 source of truth다.
Gjallar DB는 Proxmox actual state를 대체하지 않는다.

DRS recommendation과 final pre-check는 Proxmox current inventory/metrics/task/HA/storage state에서 재구성해야 한다.
DB observed snapshot은 UI cache와 audit evidence일 뿐 실행 허가가 아니다.

Proxmox current state로 확인할 값:

- VM 존재 여부
- VMID locator와 현재 node
- VM running state
- node online/offline
- CPU/Memory current metrics
- CPU/Memory 15분 average/peak series
- storage visibility/capacity
- HA state
- active task/UPID
- config lock
- passthrough evidence
- cluster health/quorum
- route feasibility

Gjallar DB가 저장할 값:

- jobs/runs
- approvals
- artifact refs
- operation locks
- VM metadata/policy
- fingerprint assertions
- identity review decisions
- recommendation snapshots
- pre-check results
- Proxmox UPID tracking state
- reconciliation state
- audit trail
- optional observed snapshots

## 2. 현재 구현된 데이터 기반

현재 코드에는 Goals 2-6을 위한 DB migration 기반 DRS substrate가 있다.
현재 구현된 substrate는 다음과 같다.

- `backend/app/proxmox/models.py`: read-only inventory dataclasses
- `backend/app/proxmox/inventory.py`: fake/live read-only adapter
- `backend/app/jobs/runs.py`: DB-backed job status metadata
- `backend/app/jobs/artifacts.py`: DB-backed artifact writer
- `backend/app/drs/identity.py`: compact DRS identity/fingerprint observation evidence
- `backend/app/drs/operation_locks.py`: DRS operation lock lookup/acquisition/release
- `backend/app/drs/approval.py`: local approval packet and pending migration job intent substrate
- `backend/app/drs/execution.py`: narrow operator-only execution, UPID/task tracking, verified post-check, reconciliation state, read-only reconcile preview
- `backend/app/vm_create/*`: Create VM draft/preflight/plan/approval/native Proxmox flow
- `/api/v1/jobs` and `/api/v1/risks`: read-only job/risk views

현재 inventory model은 disk volume id, storage id, tags, IP/guest-agent evidence와 DRS fingerprint용 SMBIOS UUID, vmgenid, MAC address list, normalized disk volume id list를 제공한다.
Recommendation/check output은 Proxmox-read-only이며 `read_only=true`, `executable=false`, `allowed_actions=[]`를 유지한다. Approval packet creation은 local approval/job/artifact만 쓰고 migration을 시작하지 않는다. Live migration은 stored approval/job, fresh gates, live Proxmox evidence, operation locks를 통과한 dedicated execute route에서만 가능하다.

## 3. VMID는 identity가 아니다

VMID는 locator다.
VMID는 metadata attach의 단독 근거가 될 수 없다.

정책:

- same VMID + same fingerprint: metadata attach 가능
- same VMID + different fingerprint: Identity Mismatch, metadata 자동 적용 금지, 모든 작업 차단
- new VMID + known/similar fingerprint: possible identity move/change, operator review 필요
- unknown fingerprint: identity_status unknown, Confirm Identity 전 migration 불가

## 4. Fingerprint

Primary fingerprint:

- SMBIOS UUID
- vmgenid
- MAC address list
- disk volume id list

Secondary fingerprint:

- VM name
- CPU/RAM/disk config hash

단독 identity 근거가 될 수 없는 값:

- name
- tag
- IP
- owner
- profile

Primary evidence는 정렬/정규화해서 hash를 만든다.
MAC과 disk volume id list는 순서 차이를 흡수하되, 누락/추가는 confidence와 mismatch 판단에 반영한다.

## 5. Identity states and review

Identity status:

- unknown
- confirmed
- mismatch
- retired_candidate

Mismatch resolution:

- Confirm Same VM
- Treat as New VM

Confirm Same VM:

- 운영자가 evidence를 검토한다.
- current fingerprint assertion을 metadata에 연결한다.
- actor/time/reviewed evidence checksum을 audit에 남긴다.
- 이후 confirmed가 될 수 있다.

Treat as New VM:

- 기존 metadata는 retired candidate로 보존한다.
- 새 VM에는 기존 owner/policy를 자동 적용하지 않는다.
- 새 metadata 필수값 입력을 요구한다.
- Confirm Identity 전 migration 불가다.

## 6. VM metadata and policy

Required metadata:

- owner
- environment
- sensitivity: normal | sensitive | critical
- migration_policy: allowed | restricted | blocked
- identity_status: confirmed

Optional metadata:

- service name
- notes
- preferred node

Policy behavior:

- Allowed: final pre-check 통과 시 manual approved live migration 가능
- Restricted: metadata는 있지만 MVP 일반 DRS 실행 제외
- Blocked: 이동 금지

MVP에서 실행 가능한 policy는 Allowed뿐이다.

## 7. DB concept tables and validation usage

### 7.1 vm_identity_assertions

Fields:

- assertion_id
- vm_metadata_id
- proxmox_cluster_id
- last_seen_vmid
- primary_fingerprint_hash
- primary_fingerprint_json_ref
- secondary_fingerprint_hash
- secondary_fingerprint_json_ref
- identity_status
- confidence
- confirmed_by
- confirmed_at
- retired_at
- retire_reason
- created_at
- updated_at

Code/validation usage:

- recommendation builder는 confirmed가 아니면 VM을 제외한다.
- current primary fingerprint hash가 다르면 metadata attach를 금지한다.
- same VMID + different hash는 Identity Mismatch risk를 만든다.
- retired assertion은 metadata 자동 재사용을 막는다.

### 7.2 vm_metadata

Fields:

- vm_metadata_id
- owner
- environment
- sensitivity
- migration_policy
- service_name
- preferred_node
- notes
- metadata_status
- created_by
- updated_by
- created_at
- updated_at

Code/validation usage:

- owner/environment/sensitivity/migration_policy가 없으면 metadata incomplete blocker다.
- sensitivity critical은 warning이다.
- migration_policy allowed만 Approve & Migrate 후보가 된다.
- restricted는 MVP DRS 실행 제외다.
- blocked는 recommendation과 execution 모두 차단한다.
- preferred_node는 warning/tie-breaker evidence일 뿐 final pre-check 대체값이 아니다.

### 7.3 observed_nodes

Fields:

- node_id
- cluster_id
- online
- cpu_current_percent
- cpu_15m_avg_percent
- cpu_15m_peak_percent
- memory_current_percent
- memory_15m_avg_percent
- memory_15m_peak_percent
- storage_summary_ref
- ha_summary_ref
- active_task_count
- collected_at

Code/validation usage:

- Dashboard node row와 recommendation snapshot input이다.
- resource polling 기본값은 1분이다.
- final pre-check에서는 live Proxmox state를 다시 읽는다.
- stale collected_at은 warning evidence다.

### 7.4 observed_vms

Fields:

- cluster_id
- vmid
- name
- node_id
- power_state
- running
- smbios_uuid
- vmgenid
- mac_list_hash
- disk_volume_id_list_hash
- config_hash
- guest_agent_state
- collected_at

Code/validation usage:

- identity candidate discovery와 historical evidence에 사용한다.
- running=false면 recommendation 후보에서 제외한다.
- node_id는 final pre-check의 VM still on source node 검증 대상이다.
- final gate는 observed row가 아니라 live Proxmox read를 사용한다.

### 7.5 drs_recommendations

Fields:

- recommendation_id
- vm_locator_vmid
- vm_metadata_id
- identity_assertion_id
- source_node_id
- target_node_id
- score
- rank
- reason_codes
- metric_window
- source_metrics_ref
- target_metrics_ref
- route_status
- blockers
- warnings
- policy_snapshot_ref
- generated_at
- expires_at
- status

Code/validation usage:

- Dashboard top 1~3과 DRS Advisor full table을 렌더링한다.
- approval review에 recommendation snapshot을 표시한다.
- blockers가 있으면 Approve & Migrate disabled다.
- route_status Unknown/Blocked이면 실행 불가다.
- snapshot은 실행 허가가 아니며 final pre-check가 필요하다.

### 7.6 drs_prechecks

Fields:

- precheck_id
- recommendation_id
- job_id
- precheck_type: check_now | final
- source_node_id
- target_node_id
- result: pass | warning | blocked | unknown
- checks_json_ref
- blockers
- warnings
- artifact_id
- created_at

Code/validation usage:

- check_now는 참고용이다.
- final만 execution gate다.
- 이전 pre-check 결과는 재사용하지 않는다.
- final result blocked/unknown이면 migration job을 만들지 않는다.
- final result warning이면 warning acknowledgement가 필요하다.

### 7.7 operation_locks

Fields:

- lock_id
- scope_type: vm | node | route
- scope_key
- job_id
- status: active | released | stale | reconciliation_required
- acquired_by
- acquired_at
- expires_at
- released_at
- release_reason

Code/validation usage:

- final pre-check의 no operation lock 검증에 사용한다.
- active lock이 있으면 Approve & Migrate disabled다.
- timeout/worker crash 후 stale 또는 reconciliation_required로 남긴다.
- 현재 구현은 read-only reconcile preview로 current Proxmox state를 확인한다. Corrective Reconcile Now/release action은 future work다.

### 7.8 jobs

Fields:

- job_id
- job_type: drs_migration
- recommendation_id
- target_type
- target_locator
- vm_metadata_id
- identity_assertion_id
- source_node_id
- target_node_id
- actor
- approved_by
- status: queued | prechecking | running | success | failed | needs_reconciliation
- risk_level
- started_at
- finished_at
- timeout_at
- created_at

Code/validation usage:

- Jobs/Runs list와 detail의 source다.
- same target running job은 active conflicting task blocker다.
- identity_assertion_id는 실행 당시 승인한 identity를 감사한다.
- needs_reconciliation은 Risks/Alerts와 Dashboard warning에 표시한다.

### 7.9 approvals

Fields:

- approval_id
- job_id
- recommendation_id
- requested_by
- approved_by
- decision
- approval_type: drs_manual_migration_confirm
- review_summary_checksum
- warning_acknowledged
- confirmed_source_node_id
- confirmed_target_node_id
- confirmed_vmid_locator
- decided_at

Code/validation usage:

- migration은 approval 없이는 시작하지 않는다.
- approval은 final pre-check를 대체하지 않는다.
- final pre-check에서 source/target/vmid가 달라지면 실행을 막고 refresh를 요구한다.
- warning이 있는데 acknowledged=false면 confirm disabled다.

### 7.10 proxmox_tasks

Fields:

- task_id
- job_id
- upid
- node_id
- task_type
- status
- exitstatus
- started_at
- ended_at
- last_polled_at
- task_log_artifact_id

Code/validation usage:

- worker가 UPID를 polling한다.
- Proxmox task success만으로 Gjallar job success를 확정하지 않는다.
- VM target node/running/fingerprint post-check를 통과해야 success다.
- UPID 결과가 애매하면 needs_reconciliation이다.

### 7.11 job_artifacts

Fields:

- artifact_id
- job_id
- type
- path
- checksum
- created_at

Code/validation usage:

- pre-check, recommendation snapshot, Proxmox task log, worker log, reconciliation original evidence를 링크한다.
- DB에는 큰 log 원문을 넣지 않고 artifact ref를 저장한다.
- checksum으로 review summary와 original artifact 불일치를 감지한다.
- MVP 자동 삭제는 없다.

### 7.12 reconciliation_events

Fields:

- reconciliation_id
- job_id
- reason: timeout | restart | upid_missing | state_mismatch | manual_reconcile
- observed_vmid
- observed_node_id
- expected_source_node_id
- expected_target_node_id
- observed_task_status
- decision: mark_success | mark_failed | keep_needs_reconciliation | release_lock
- decided_by
- decided_at
- artifact_id

Code/validation usage:

- 현재 구현은 read-only reconcile preview와 reconciliation event evidence를 저장/조회한다. Corrective Reconcile Now decision 저장은 future work다.
- target node running + fingerprint match가 확인되어야 success 전환 가능하다.
- 확인이 불충분하면 needs_reconciliation과 lock reconciliation_required를 유지한다.

## 8. Secret and artifact policy

DB와 artifact에는 다음 값을 저장하지 않는다.

- Proxmox token secret
- SSH private key
- env secret
- raw credential

현재 Create VM code가 사용하는 redaction 원칙을 DRS Advisor에도 적용한다.
Proxmox task log와 worker log는 inline summary와 original artifact를 분리해 저장한다.
MVP 자동 삭제는 없다.
