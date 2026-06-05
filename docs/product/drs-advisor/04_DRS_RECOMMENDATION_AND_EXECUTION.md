# DRS Recommendation and Execution

## 1. 현재 DRS recommendation/check status

현재 `backend/app/drs/advisor.py`는 backend-owned read-only recommendation을 만들고 `frontend/src/utils/drsAdvisor.js`는 이 endpoint를 소비한다.

현재 로직:

- node pressure = max(CPU current usage, Memory current usage)
- pressure >= 85 또는 red risk 있으면 Imbalanced
- pressure >= 70 또는 imbalance delta >= 25면 Watch
- source는 online이고 pressure >= 70인 node
- target은 online이고 가장 낮은 pressure node
- imbalance delta < 25면 recommendation 없음
- running, non-template VM만 후보
- VM에 red risk가 있으면 제외
- bridge evidence와 storage evidence를 확인
- blocker가 있어도 riskLevel은 yellow로 표시
- execution.available은 false
- read_only true, executable false, allowed_actions 빈 배열

현재 구현 상태: backend에는 identity/policy evidence, backend-owned criteria taxonomy, operation locks, local approval/job substrate, selected smoke/test VM을 위한 operator-only explicit candidate check/approval helper, narrow operator-only migration-job execute route, exact `drs_live_migration_acknowledged=true` request gate, UPID/task tracking, verified post-check, read-only reconcile preview가 있다. `/drs` frontend에는 recommendation/detail/check policy evidence, criteria taxonomy display, and local approval packet/job intent creation이 있다. Manual VM policy configuration은 VM Instances / DRS Policies(`/instances/drs-policies`)에 있다. Recommendation/check output은 계속 execution-closed이며 `read_only=true`, `executable=false`, `allowed_actions=[]`를 유지한다. Explicit test candidate helper는 normal top-3 shortlist만 우회하고 Proxmox mutation을 호출하지 않으며, arbitrary migration endpoint가 아니다. Live migration execute UI와 corrective reconcile UI는 아직 deferred다.

이 문서의 나머지 target guidance는 backend-backed, identity/policy aware, final pre-check gated, approval-gated execution model을 설명한다. Recommendation/check result 자체를 execution authority로 해석하면 안 된다.

### 1.1 Implemented criteria taxonomy

Recommendation/check responses expose the same backend vocabulary:

- `authority`: `gjallar_operational_gate`, `proxmox_final_technical_gate`, or `advisor_prefilter_signal`.
- `category`: `hard_gate`, `policy_gate`, `technical_gate`, `advisory`, or `warning`.
- `severity`: display/triage severity such as `blocking`, `warning`, `pending`, or `info`.
- `evidence_state`: explicit evidence state such as `observed`, `unknown`, `stale`, `unavailable`, `ambiguous`, or `not_collected`.
- `action_blocked`: `approval`, `execute`, `local_completion`, or `none`.

The flat `blockers` list remains the compatibility hard-gate subset. Advisor route/network/local-storage/passthrough evidence is returned as `advisory_signals` and `criteria_details` with `authority=advisor_prefilter_signal`, `category=advisory`, and `action_blocked=none`. Proxmox active task, HA state, and cluster quorum rows are explicit `not_collected` final technical gate evidence in recommendation/check output; live execution still collects final Proxmox technical evidence through the dedicated DRS execution path before mutation.

## 2. Target DRS model

MVP 추천은 CPU/Memory 중심이다.
Disk/storage/network/HA는 score driver가 아니라 criteria evidence다. In the current implementation, Advisor route/network/local-storage/passthrough evidence is advisory/pre-filter signal, while Proxmox live pre-check/migration preconditions remain the final technical gate before mutation.

Polling:

- resource metrics: 1분
- inventory: 5분
- HA state: 5분
- storage state: 5분

Metric window:

- recent 15m average
- recent 15m peak

Default thresholds:

```text
source_hot_threshold = 70%
source_critical_threshold = 85%
target_projected_warning_threshold = 75%
target_projected_block_threshold = 90%
min_pressure_delta = 20 percentage points
```

이 값은 MVP 기본 정책이다.
현재 manual VM migration policy UI/API는 VM Instances / DRS Policies에서 per-VM policy를 다루며, threshold/rule controls는 config/default로 유지할 수 있다. Bulk policy selection/edit and richer policy rule/full metadata editor are deferred.

## 3. Recommendation candidate rules

후보 조건:

1. source node online
2. source node hot 또는 imbalanced
3. target node online
4. VM is running on source
5. VM is not template
6. identity_status confirmed
7. current fingerprint matches assertion
8. metadata complete
9. migration_policy allowed
10. no active operation lock
11. no active conflicting job/task at execution live pre-check
12. target projected CPU/Memory below block threshold
13. Advisor route/storage/network/passthrough signal visible as advisory/pre-filter evidence
14. no blocker

추천 제외:

- Identity Mismatch
- Unclassified/identity unknown
- metadata incomplete
- migration policy restricted
- migration policy blocked
- stopped VM
- VM not found
- VM moved from source
- target offline
- quorum unhealthy
- active conflicting task at execution live pre-check
- config lock
- Advisor passthrough signal visible as advisory evidence
- Advisor route blocked/unknown signal visible as advisory evidence

Missing or malformed `drs_live_migration_acknowledged=true` is not a
recommendation exclusion. It is execute request validation only, enforced by the
stored-job execute route before DRS service/client/lock/migration work.

## 4. Route Status

Route Status는 특정 source -> target 경로의 가능성이다.

- Feasible: known blocker 없음
- Warning: 불완전하거나 주의할 evidence가 있지만 contradiction 없음
- Blocked: known blocker 있음
- Unknown: 필요한 evidence가 없어 실행 허가 불가

Current Advisor Unknown is not execution authority and is surfaced as advisory/pre-filter evidence. It does not by itself grant or deny mutation. The stored execute path must still run the final Proxmox technical live pre-check; unavailable, ambiguous, conflicting, or failing live route/precondition evidence blocks before mutation.

## 5. Check Now and final pre-check

Check Now:

- 운영자 참고용이다.
- route evidence를 미리 볼 수 있다.
- 결과가 stale이면 warning이다.
- 실행 허가에 재사용하지 않는다.

Final pre-check:

- 실행 직전의 유일한 authoritative gate다.
- stored job execute마다 fresh gates and Proxmox live pre-check evidence are collected before mutation.
- 이전 final pre-check도 재사용하지 않는다.

Final pre-check 10개:

1. identity confirmed
2. metadata complete
3. migration policy allowed
4. no operation lock
5. VM still on source node
6. VM running
7. target node online
8. cluster health/quorum OK
9. no active conflicting task
10. Proxmox live migration preconditions pass before mutation

각 check의 source:

- identity confirmed: live fingerprint + vm_identity_assertions
- metadata complete: vm_metadata
- migration policy allowed: vm_metadata.migration_policy
- no operation lock: operation_locks
- VM still on source node: live Proxmox inventory
- VM running: live Proxmox inventory
- target node online: live Proxmox node state
- cluster health/quorum OK: live Proxmox cluster status
- no active conflicting task: live Proxmox tasks + jobs
- Proxmox live migration preconditions: live storage/network/HA/config/quorum/task evidence collected by the dedicated DRS execution client

## 6. Blockers

Blocked 기준:

- identity mismatch
- unclassified / identity unknown
- metadata incomplete
- policy blocked
- policy restricted
- active operation lock
- stale lock requiring reconciliation
- VM not found
- VM not running
- VM not on approved source node
- target offline
- cluster quorum unhealthy
- active conflicting task at execution live pre-check
- config lock
- Proxmox migration precondition blocked/unavailable/ambiguous
- final pre-check unknown

## 7. Warnings

Warning examples:

- sensitivity critical
- high memory >= 64GB
- target near threshold after migration
- recent source/target metric volatility
- backup status unknown
- guest agent unavailable
- route evidence incomplete but not contradicted
- preferred node differs from target
- Check Now result stale
- recent failed job on same VM

Warning은 local approval packet/job intent creation을 막지 않을 수 있다.
단 backend-tracked approval warning acknowledgement가 필요하다.

## 8. Execution flow

```text
poll Proxmox state
-> build current inventory/metrics view
-> attach metadata only by fingerprint match
-> compute VM Mobility
-> compute route status
-> create recommendation snapshot
-> render Dashboard top 1-3 and DRS Advisor table
-> create local approval packet and pending drs_migration job intent
-> POST stored job execute with drs_live_migration_acknowledged=true
-> fresh final gates and Proxmox live pre-check
-> acquire operation lock
-> call Proxmox live migration
-> store UPID
-> poll Proxmox task
-> post-check target node/running/fingerprint
-> release lock or mark reconciliation_required
-> success/failed/needs_reconciliation
```

Operation lock scope:

- VM-level lock by cluster + vmid locator or identity assertion id
- optional route lock by source + target

Lock policy:

- active lock blocks execution
- confirm 후 migration job 시작 직전에 lock 획득
- lock 획득 실패 시 Proxmox migration을 호출하지 않는다.
- success/failure 후 release
- timeout/worker crash는 stale 또는 reconciliation_required

Execute acknowledgement:

- The backend route requires exact `drs_live_migration_acknowledged=true` before
  any DRS execution service, client factory, live pre-check, lock, or migration
  call.
- Missing payload, missing field, false/null/string/number values,
  camelCase-only acknowledgement, and Create VM acknowledgement return
  `DRS_EXECUTION_ACK_REQUIRED` with `proxmox_mutation_enabled=false` and
  `side_effects=[]`.
- This acknowledgement failure is request validation; it does not mark a pending
  DRS migration job blocked.

## 9. Proxmox task and UPID tracking

DRS migration execution은 Proxmox task/UPID를 저장해야 한다.

Tracking:

- migration request returns UPID
- `proxmox_tasks` row stores UPID, node, task type, status, exitstatus
- worker polls task status/log
- task log original artifact 저장
- worker log original artifact 저장
- inline summary는 Jobs/Runs에 표시

Success는 Proxmox task success만으로 결정하지 않는다.
아래 post-check가 필요하다.

- VM found on target node
- VM running
- current fingerprint matches expected assertion
- no active conflicting task remains
- lock released

## 10. Timeout and reconciliation

Job timeout 기본값은 30분이다.

Timeout result:

- job status: needs_reconciliation
- lock status: reconciliation_required 또는 stale
- Risks/Alerts에 migration_timeout과 needs_reconciliation 표시
- Jobs/Runs에 read-only reconciliation evidence/read-only preview availability 표시. Corrective Reconcile Now action은 deferred이며 current frontend control이 아니다.

Needs reconciliation 조건:

- timeout
- worker restart during migration
- UPID missing or no longer queryable
- task ended but VM location ambiguous
- task success but fingerprint mismatch
- lock stale and state unknown

Deferred corrective Reconcile Now:

1. Proxmox current inventory를 다시 읽는다.
2. UPID/task log 조회를 시도한다.
3. VM locator와 fingerprint를 확인한다.
4. source/target location을 확인한다.
5. success/failed/keep_needs_reconciliation을 결정한다.
6. lock release 가능 여부를 결정한다.
7. reconciliation artifact를 저장한다.

## 11. Proxmox docs/API assumptions

구현 전 공식 Proxmox docs와 live cluster response로 확인할 것:

- live migration endpoint와 parameter
- UPID response shape
- task polling endpoint와 terminal status/exitstatus
- VM config field for SMBIOS UUID
- VM config field for vmgenid
- MAC address extraction path
- disk volume id/reference normalization
- HA resource state endpoint
- cluster quorum/health endpoint
- active task representation
- config lock representation
- passthrough evidence
- storage shared/accessibility evidence
- Proxmox version별 migration 제약 차이

원칙:

- docs와 live response가 다르면 live response artifact를 남기고 contract를 갱신한다.
- final pre-check 직전 필요한 evidence를 다시 읽는다.
- stale DB row, stale Check Now, stale recommendation snapshot은 실행 허가가 아니다.
