# DRS Advisor Product Direction

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 product direction](../../../product/drs-advisor/01_PRODUCT_DIRECTION.md), [DRS Advisor index](../../../product/drs-advisor/README.md), [Current implemented state](../../../current/README.md).

## 제품 정체성

Gjallar는 백업 제품이 아닙니다. Gjallar는 Proxmox 클러스터를 운영하는 사람이 노드 부하, VM mobility, migration/HA/storage risk, 실행 이력, 재조정 상태를 한 곳에서 보고 안전하게 조작하는 Proxmox enterprise operations platform입니다.

DRS Advisor의 허용 표현:

- Proxmox-native migration/HA 관찰.
- CPU/Memory 중심 migration recommendation.
- approval-gated live migration.
- Proxmox task/UPID tracking.
- operation audit and reconciliation.
- advisor/control tower.

금지 표현: VMware DRS replacement, VMware DRS compatible, automatic DRS for Proxmox, backup product.

## 왜 이 도메인이 필요한가

현재 Dashboard/Placement는 운영자가 부하와 배치를 볼 수 있게 하지만, 실행 가능한 migration system은 아닙니다. 실제 운영에서는 VM identity, policy, current source/target state, active task, route evidence, approval, lock, post-check, reconciliation이 모두 필요합니다. DRS Advisor는 이 전체 safety chain을 제품 success line으로 둡니다.

## 현재 코드 기반 재사용 방향

재사용할 기반:

- Dashboard의 `/api/v1` aggregation.
- Placement의 read-only recommendation seed.
- Jobs/Runs의 DB-backed job/artifact substrate.
- Risks/Alerts의 risk display pattern.
- Proxmox read-only inventory adapter.
- Create VM의 approval/artifact/job/native acknowledgement/post-check pattern.
- Secret redaction과 forbidden legacy endpoint guard.

재사용하면 안 되는 방식:

- Frontend-only recommendation을 execution authority로 쓰기.
- Create VM preflight를 DRS final pre-check로 그대로 쓰기.
- VMID를 identity로 취급하기.
- DB observed snapshot을 execution source of truth로 쓰기.

## MVP 포함/제외

포함: Dashboard top 1-3 recommendation, DRS Advisor table, 15분 average/peak evidence, identity/fingerprint reattachment, metadata/policy validation, Allowed VM 대상 manual approved live migration, final pre-check, operation lock, UPID tracking, Jobs/Runs artifacts, success/failed/`needs_reconciliation`, Reconcile Now.

제외: 자동 DRS, nightly rebalance, restricted exception approval, node drain, maintenance mode automation, affinity editor, automatic rollback, backup orchestration, job/artifact auto deletion, VMware compatibility claim.

## 성공 기준

Allowed VM만 Approve & Migrate 가능해야 합니다. Restricted/Blocked/Unclassified/Identity Mismatch는 실행되지 않아야 합니다. Check Now 결과는 실행 허가가 아니며 final pre-check가 직전에 다시 수행되어야 합니다. Migration은 UPID tracking과 post-check를 거쳐 success/failed/needs_reconciliation으로 남아야 합니다.
