# DRS Advisor UI and Flows

## 1. 현재 UI baseline

현재 frontend는 다음 route를 갖고 있다.

- Dashboard: `/`
- Infra Explorer: `/infra`
- Networks: `/networks`
- Create VM: `/create`
- DRS Advisor: `/drs`
- Jobs/Runs: `/jobs`
- Risks/Alerts: `/risks`

현재 `/drs` route는 recommendation/detail/check, manual VM policy configuration, backend-owned criteria taxonomy display, and local approval packet/job intent creation을 제공한다. Recommendation/check output은 계속 `read_only=true`, `executable=false`, `allowed_actions=[]`다.

## 2. Dashboard

현재 구현:

- cluster/nodes/vms/storage/networks/jobs/risks를 병렬로 읽는다.
- node row에 CPU current, memory current, VM count, storage free, network bridge를 보여준다.
- summary tile에 node count, VM count, storage, risk count를 보여준다.
- Create VM과 Infra Explorer로 이동하는 action이 있다.

DRS Advisor 목표:

- Dashboard는 클러스터 카드보다 node row 중심이다.
- 각 node row는 current usage뿐 아니라 최근 15분 average와 peak를 보여준다.
- Dashboard에는 상위 1~3개 DRS recommendation summary를 추가한다.
- Dashboard에서 migration 실행은 시작하지 않는다.
- recommendation summary는 DRS Advisor 상세로 이동하는 entry point다.

Dashboard node row 표시:

- node name
- online/offline
- CPU current
- CPU 15m average
- CPU 15m peak
- Memory current
- Memory 15m average
- Memory 15m peak
- Disk/storage summary
- running VM count
- total VM count
- active Proxmox task count
- HA/storage warning summary
- blocker count

Top recommendation summary:

- VM name / VMID locator
- source node -> target node
- score/rank
- expected source relief
- route status
- blocker/warning summary
- action: open DRS Advisor

## 3. DRS Advisor screen

현재 구현:

- `DrsAdvisorScreen`은 recommendation/check result가 execution authority가 아니라는 safety notice를 보여준다.
- `loadDrsAdvisorModel`은 `/api/v1/drs/summary`, `/api/v1/drs/recommendations`, detail/check, `GET/PUT /api/v1/drs/policies*`, and `/approval-packets`를 사용한다.
- CPU/Memory current usage와 imbalance로 Balanced/Watch/Imbalanced를 계산한다.
- source pressure >= 70, source-target delta >= 25이면 recommendation 후보를 만든다.
- bridge/storage/network/passthrough evidence를 backend-owned criteria taxonomy로 표시한다.
- `blockers`는 hard Gjallar/Proxmox gate subset이고, route/network/local-storage/passthrough는 `advisor_prefilter_signal` advisory evidence다.
- recommendation/check execution은 `available: false`, `read_only: true`, `executable: false`이고 action list는 비어 있다.
- manual per-VM migration policy configuration과 local approval packet/job intent creation은 current UI에 있다. Live migration execute UI와 corrective reconcile UI는 없다.

목표:

- 화면 제목은 `DRS Advisor`다.
- read-only notice는 "recommendation은 execution gate가 아니며 final pre-check가 권위"라는 설명으로 바꾼다.
- 카드 중심 recommendation은 full table + detail drawer로 확장한다.
- Allowed policy만으로 migration action이 활성화되지 않는다. Current UI는 local approval packet/job intent creation only이고 live execute UI는 deferred다.

주요 섹션:

- Cluster load summary
- Node load table
- Full recommendation table
- Recommendation detail drawer
- VM identity/metadata status
- VM Mobility
- Route Status
- Check Now result
- final pre-check result
- Local approval packet / job intent action
- Recent DRS jobs

Recommendation table fields:

- rank
- recommendation_id
- VM name
- VMID locator
- identity status
- metadata completeness
- migration policy
- sensitivity
- source node
- target node
- CPU 15m average/peak evidence
- Memory 15m average/peak evidence
- source pressure
- target projected pressure
- route status
- blockers
- warnings
- generated_at
- action availability

## 4. VM Mobility와 Route Status

VM Mobility는 VM 자체의 이동 정책/정체성 상태다.

- Unclassified: warning, metadata 없음 또는 identity unknown, 작업 불가
- Identity Mismatch: critical, 모든 작업 불가
- Allowed: final pre-check 통과 시 migration 가능
- Restricted: metadata는 있지만 일반 DRS 실행 제외
- Blocked: 이동 금지

Route Status는 특정 source -> target 경로의 가능성이다.

- Feasible
- Warning
- Blocked
- Unknown

Current implementation에서 Advisor Route Status Unknown은 advisory/pre-filter signal이며 local approval packet creation을 직접 막는 hard gate가 아니다. It does not create execution authority. Stored job execution still reruns fresh Gjallar gates and then Proxmox live pre-check/migration preconditions immediately before mutation; those Proxmox final technical gates can block the migration request.

## 5. Local approval and stored execute flow

```text
recommendation selected
-> local approval packet creation requested
-> server reconstructs current Proxmox state
-> read-only final pre-check runs
-> hard gates blocked: show blockers, no local approval packet/job intent
-> hard gates pass: write local approval packet and pending job intent
-> separate backend execute route requires drs_live_migration_acknowledged=true
-> fresh gates and Proxmox live pre-check run
-> operation lock acquired
-> Proxmox live migration requested
-> UPID stored
-> worker tracks task
-> post-check verifies target node, running state, fingerprint
-> success/failed/needs_reconciliation
```

Approval/execution review must display:

- VM name
- VMID locator
- identity status
- fingerprint assertion summary
- source node
- target node
- migration policy
- sensitivity
- final pre-check result
- blockers/warnings
- criteria authority: Gjallar gate, Advisor signal, or Proxmox technical gate
- expected effect
- operation lock scope
- timeout: 30m
- Proxmox action summary

## 6. Jobs / Runs

현재 구현:

- read-only execution history다.
- selected job의 progress steps와 artifact links를 보여준다.
- live statuses는 2.5초 polling한다.
- retry/cancel/live-run/VM mutation control은 없다.
- backend job run은 DB-backed `job_runs`/`job_artifacts`로 저장된다.
- DRS `drs_migration` job details show compact read-only `drs_evidence` and artifact metadata only. Artifact payloads and local paths are not rendered.

DRS Advisor 목표:

- `drs_migration` job_type을 1급으로 표시한다.
- Proxmox UPID와 task status를 표시한다.
- operation lock 상태를 표시한다.
- final pre-check artifact를 표시한다.
- success/failed/needs_reconciliation을 구분한다.
- needs_reconciliation이면 post-check/lock/reconciliation evidence와 read-only preview availability를 표시한다. Current UI does not expose a corrective Reconcile Now action.

DRS job fields:

- job_id
- job_type: drs_migration
- recommendation_id
- VM locator
- identity assertion id
- source node
- target node
- actor/requested_by/approved_by
- status
- UPID
- lock id/status
- started_at
- timeout_at
- finished_at
- inline log summary
- artifact links

Jobs/Runs DRS panel must remain inspection-only:

- no frontend execute/reconcile/retry/cleanup/reverse-migration controls
- no recommendation-level migrate/live-migrate/execute aliases
- Proxmox task `OK` is historical task evidence only; Gjallar completion still requires post-check and lock/reconciliation evidence

## 7. Risks / Alerts

현재 구현:

- `/api/v1/risks`에서 job-derived risks를 읽는다.
- red/yellow/green/unknown summary를 보여준다.
- risk item detail과 artifact link를 보여준다.
- 정책 변경이나 실행 조작은 없다.

DRS Advisor 목표:

- DRS blocker와 warning을 별도 risk code로 보여준다.
- 각 risk가 막는 action을 명시한다.
- Identity Mismatch는 critical로 가장 위에 보인다.
- needs_reconciliation과 stale lock은 Dashboard와 Risks에 모두 드러난다.

DRS risk examples:

- identity_mismatch
- unclassified_vm
- metadata_incomplete
- policy_restricted
- policy_blocked
- operation_lock_active
- operation_lock_reconciliation_required
- vm_not_found
- vm_not_running
- vm_source_changed
- target_offline
- quorum_unhealthy
- active_conflicting_task
- config_lock
- passthrough_blocker
- route_unknown
- route_blocked
- migration_timeout
- needs_reconciliation

## 8. Create VM as secondary capability

Create VM 화면은 보조 capability로 유지한다.
현재 구현은 DRS Advisor와 별도 flow지만 다음 substrate를 공유한다.

- approval UX
- yellow risk acknowledgement
- artifact-backed plan/review
- job progress display
- Proxmox native mutation acknowledgement

DRS Advisor는 Create VM UI를 우회하지 않는다.
DRS Advisor의 migration execution은 별도 final pre-check와 operation lock을 사용한다.
