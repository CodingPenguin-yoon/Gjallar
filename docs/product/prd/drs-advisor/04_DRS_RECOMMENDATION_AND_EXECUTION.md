# DRS Recommendation and Execution

## 1. 현재 Placement recommendation baseline

현재 `frontend/src/utils/placement.js`는 read-only recommendation을 만든다.

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
- readOnly true, allowedActions 빈 배열

이 구현은 DRS Advisor의 첫 계산/화면 seed로 재사용한다.
하지만 MVP 목표는 backend-backed, identity/policy aware, final pre-check gated, approval-executable recommendation이다.

## 2. Target DRS model

MVP 추천은 CPU/Memory 중심이다.
Disk/storage/network/HA는 score driver가 아니라 route feasibility, blocker, warning evidence다.

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
MVP에서는 policy editor를 만들지 않고 config/default로 고정할 수 있다.

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
11. no active conflicting job/task
12. target projected CPU/Memory below block threshold
13. route status Feasible 또는 Warning
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
- active conflicting task
- config lock
- passthrough blocker
- route blocked
- route unknown

## 4. Route Status

Route Status는 특정 source -> target 경로의 가능성이다.

- Feasible: known blocker 없음
- Warning: 불완전하거나 주의할 evidence가 있지만 contradiction 없음
- Blocked: known blocker 있음
- Unknown: 필요한 evidence가 없어 실행 허가 불가

Unknown은 migration 불가다.
Unknown은 warning과 다르다.
final pre-check가 Unknown을 Feasible/Warning으로 확정하기 전까지 실행할 수 없다.

## 5. Check Now and final pre-check

Check Now:

- 운영자 참고용이다.
- route evidence를 미리 볼 수 있다.
- 결과가 stale이면 warning이다.
- 실행 허가에 재사용하지 않는다.

Final pre-check:

- 실행 직전의 유일한 authoritative gate다.
- Approve & Migrate마다 새로 수행한다.
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
10. route feasible/warning

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
- route feasible/warning: live storage/network/HA/config evidence

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
- active conflicting task
- config lock
- passthrough device
- route blocked
- route unknown
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

Warning은 migration을 막지 않을 수 있다.
단 confirm modal에서 명시적 acknowledgement가 필요하다.

## 8. Execution flow

```text
poll Proxmox state
-> build current inventory/metrics view
-> attach metadata only by fingerprint match
-> compute VM Mobility
-> compute route status
-> create recommendation snapshot
-> render Dashboard top 1-3 and DRS Advisor table
-> Approve & Migrate
-> final pre-check
-> confirm modal
-> acquire operation lock
-> create drs_migration job
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
- Jobs/Runs에 Reconcile Now 표시

Needs reconciliation 조건:

- timeout
- worker restart during migration
- UPID missing or no longer queryable
- task ended but VM location ambiguous
- task success but fingerprint mismatch
- lock stale and state unknown

Reconcile Now:

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
