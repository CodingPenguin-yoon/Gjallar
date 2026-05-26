# DRS Recommendation And Execution

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 DRS recommendation/execution](../../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md), [Target DRS architecture](../../../architecture/placement-drs-advisor/recommendation-and-execution.md), [Target DRS API](../../../architecture/api/target-drs-api.md).

## 왜 recommendation/execution 도메인이 필요한가

부하가 높은 node와 여유 있는 node를 찾는 것만으로는 migration을 시작할 수 없습니다. 실제 운영에서는 identity confirmed, policy allowed, no lock, route feasible, target safe, current Proxmox state still matching, post-check/reconciliation이 필요합니다.

## Current DRS Advisor Phase 1 baseline

현재 [frontend/src/utils/drsAdvisor.js](../../../../frontend/src/utils/drsAdvisor.js)는 backend DRS read-only endpoint를 소비합니다. Node pressure는 CPU/Memory current usage의 max이고, source pressure와 imbalance delta로 candidate를 만듭니다. Red-risk VM은 제외하고 bridge/storage/passthrough/target pressure evidence를 보지만 execution은 `available: false`입니다.

이 로직은 Phase 1 recommendation read model이지만 execution authority가 아닙니다. 화면 구현은 [DrsAdvisorScreen.jsx](../../../../frontend/src/components/DrsAdvisorScreen.jsx), 테스트는 [drsAdvisor.test.mjs](../../../../frontend/tests/drsAdvisor.test.mjs)를 봅니다.

## Target recommendation rules

MVP recommendation은 CPU/Memory 중심입니다. Disk/storage/network/HA는 score driver가 아니라 route feasibility, blocker, warning evidence입니다.

Candidate requires source online/hot, target online, VM running and not template, identity confirmed, fingerprint match, metadata complete, migration_policy allowed, no active operation lock/task, target projected pressure below block threshold, route feasible/warning, no blocker.

Recommendation excludes Identity Mismatch, Unclassified, metadata incomplete, restricted/blocked policy, stopped VM, VM not found, source changed, target offline, quorum unhealthy, active conflicting task, config lock, passthrough, route blocked, route unknown.

## Route status and Check Now

Route Status:

- Feasible: known blocker 없음.
- Warning: 주의 evidence가 있지만 contradiction 없음.
- Blocked: known blocker 있음.
- Unknown: 필요한 evidence가 없어 실행 허가 불가.

Check Now는 참고용입니다. 실행 허가로 재사용하지 않습니다. Final pre-check만 execution gate입니다.

## Final pre-check

Approve & Migrate마다 final pre-check를 새로 수행합니다. Checks: identity confirmed, metadata complete, migration policy allowed, no operation lock, VM still on source node, VM running, target node online, cluster health/quorum OK, no active conflicting task, route feasible/warning.

Blocked/Unknown이면 migration job을 만들지 않습니다. Warning이면 confirm modal에서 acknowledgement가 필요합니다.

## Execution and UPID tracking

Target execution flow: poll Proxmox state, attach metadata only by fingerprint match, compute mobility/route/recommendation, Approve & Migrate, final pre-check, confirm, acquire lock, create `drs_migration` job, call Proxmox live migration, store UPID, poll task, post-check target node/running/fingerprint, release lock or mark reconciliation required.

Proxmox task success만으로 DRS success를 확정하면 안 됩니다. Target node, running state, expected fingerprint, no active conflicting task, lock release까지 확인해야 합니다.

## Timeout and reconciliation

Default timeout은 30분 target입니다. Timeout, worker restart, UPID missing, ambiguous location, task success but fingerprint mismatch, stale lock은 `needs_reconciliation` 조건입니다. Reconcile Now는 Proxmox current inventory와 task log를 다시 읽고 success/failed/keep needs_reconciliation을 결정해야 합니다.
