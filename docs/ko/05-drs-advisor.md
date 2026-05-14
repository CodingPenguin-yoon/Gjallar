# 제품 방향: DRS Advisor

기준 문서: [DRS Advisor product direction](../product/drs-advisor/README.md), [Placement and target DRS Advisor](../architecture/placement-drs-advisor/overview.md), [target DRS API](../architecture/api/target-drs-api.md), [target DRS flow](../architecture/flows/drs-approve-migrate-reconcile.md). 이 문서는 한국어 설명용이며 source of truth가 아닙니다.

DRS Advisor는 Gjallar의 다음 MVP product target입니다. 현재 구현은 아직 DRS Advisor backend가 아니라 read-only Placement seed입니다.

## 제품 목표

목표 표현:

```text
Gjallar DRS Advisor = Proxmox-native migration advisor and control tower
```

DRS Advisor는 Proxmox-native inventory, metrics, HA/storage/task evidence를 보고 CPU/Memory 중심 recommendation을 만들며, operator 승인 후 Proxmox live migration을 실행/추적하는 방향입니다.

금지해야 할 표현:

- VMware DRS replacement.
- VMware DRS compatible.
- automatic DRS for Proxmox.
- backup product.

MVP target에 포함되는 큰 기능:

- Dashboard top 1-3 DRS recommendation summary.
- `/placement` route의 DRS Advisor label/flow 전환.
- backend-owned DRS recommendation read model.
- 15분 average/peak CPU/Memory evidence.
- identity/fingerprint reattachment와 metadata/policy validation.
- Allowed VM 대상 manual approved live migration.
- final pre-check, confirm modal, operation lock.
- Proxmox migration UPID tracking.
- Jobs/Runs artifact/log.
- success/failed/needs_reconciliation.
- Reconcile Now.
- restart 후 Proxmox current state 기반 재구성.

## 현재 상태: Placement

현재 `/placement`는 frontend read-only Placement screen입니다.

- backend DRS endpoint가 없습니다.
- 화면 label도 아직 `Placement` 기준입니다.
- `frontend/src/utils/placement.js`가 inventory/jobs/risks를 조합해 read-only recommendation seed를 계산합니다.
- execution은 `available: false`, `readOnly: true`, `allowedActions: []`입니다.
- migration button이 없습니다.

현재 사용하는 API:

- `GET /api/v1/cluster/summary`
- `GET /api/v1/nodes`
- `GET /api/v1/vms`
- `GET /api/v1/storage`
- `GET /api/v1/networks`
- `GET /api/v1/risks`
- `GET /api/v1/jobs`

현재 계산은 CPU/Memory current usage, node imbalance, bridge/storage evidence, red risk exclusion을 사용합니다. 이것은 operator 참고용 read model이며 migration 실행 판단이 아닙니다.

## 아직 없는 backend DRS API

다음 target APIs는 후보 문서에만 있으며 현재 구현되어 있지 않습니다.

- `GET /api/v1/drs/summary`
- `GET /api/v1/drs/recommendations`
- `GET /api/v1/drs/recommendations/{recommendation_id}`
- `POST /api/v1/drs/recommendations/{recommendation_id}/check-now`
- `POST /api/v1/drs/recommendations/{recommendation_id}/precheck`
- `POST /api/v1/drs/recommendations/{recommendation_id}/approve-migrate`
- `GET /api/v1/drs/jobs/{job_id}`
- `POST /api/v1/drs/jobs/{job_id}/reconcile`
- DRS policy/lock inspection and update APIs.

따라서 현재 `/placement` 추천을 실행 허가로 해석하면 안 됩니다.

## 정체성 gap: Identity와 fingerprint

DRS에서는 VMID가 identity가 아니라 locator입니다.

Target identity rule:

- same VMID + same fingerprint: metadata attach 가능.
- same VMID + different fingerprint: Identity Mismatch, metadata 자동 적용 금지, 모든 작업 차단.
- unknown fingerprint: identity unknown, Confirm Identity 전 migration 불가.

Target primary fingerprint evidence:

- SMBIOS UUID.
- vmgenid.
- MAC address list.
- disk volume id list.

현재 Create VM `observed_after` artifact는 fingerprint evidence를 남기지만, 이것은 DB identity record가 아닙니다. DRS용 identity assertion table, metadata table, review decision/audit flow는 아직 없습니다.

## 최종 pre-check gap

Check Now는 target에서도 operator 참고용입니다. 실행 허가로 재사용하지 않습니다.

Final pre-check는 Approve & Migrate 직전에 매번 새로 수행해야 하는 authoritative gate입니다. Target checks:

1. identity confirmed.
2. metadata complete.
3. migration policy allowed.
4. no operation lock.
5. VM still on source node.
6. VM running.
7. target node online.
8. cluster health/quorum OK.
9. no active conflicting task.
10. route feasible/warning.

현재 backend에는 이 final pre-check route와 state가 없습니다.

## 마이그레이션 실행 gap

Target execution은 "approve means migrate"가 아닙니다.

Target sequence:

```text
recommendation selected
-> final pre-check
-> confirm modal with warning acknowledgement
-> acquire operation lock
-> create drs_migration job
-> call Proxmox live migration
-> store UPID
-> poll task
-> post-check target node/running/fingerprint
-> success, failed, or needs_reconciliation
```

현재는 Proxmox live migration client, DRS mutation route, UPID task tracking, DRS post-check가 없습니다. Create VM native runner는 clone/config runner이며 DRS migration executor가 아닙니다.

## 잠금과 재조정 gap: Lock과 reconciliation

Target DRS는 operation lock이 필요합니다.

- VM-level lock by cluster + VM locator or identity assertion.
- optional source/target route lock.
- active lock은 execution을 막습니다.
- timeout이나 worker crash는 stale 또는 `reconciliation_required`가 될 수 있습니다.

Target reconciliation은 Proxmox current state와 job/UPID/lock record를 다시 읽어 success/failed/keep needs_reconciliation을 결정합니다. 현재 DRS reconciliation worker나 `POST /api/v1/drs/jobs/{job_id}/reconcile` endpoint는 없습니다.

## 작업 이력과 위험 목표: Jobs/Runs와 Risks

현재 Jobs/Runs와 Risks/Alerts substrate는 재사용할 수 있습니다. 다만 DRS MVP에는 다음 확장이 필요합니다.

- `drs_migration` job type.
- recommendation id, VM locator, identity assertion id, source/target node.
- approver, UPID, lock id/status, timeout.
- final-precheck, migration task log, post-check, reconciliation artifacts.
- DRS blocker taxonomy: `identity_mismatch`, `unclassified_vm`, `metadata_incomplete`, `policy_blocked`, `route_unknown`, `operation_lock_active`, `migration_timeout`, `needs_reconciliation` 등.

현재 `/api/v1/risks`는 job-derived risk projection이므로, DRS blocker engine으로 overclaim하면 안 됩니다.
