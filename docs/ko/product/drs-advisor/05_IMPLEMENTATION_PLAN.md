# DRS Advisor Implementation Plan

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 implementation plan](../../../product/drs-advisor/05_IMPLEMENTATION_PLAN.md), [Current implemented state](../../../current/README.md), [Engineering current work plan](../../../engineering/GJALLAR_CURRENT_WORK_PLAN.md).

## 구현 원칙

DRS Advisor는 현재 코드를 갈아엎는 것이 아니라 확장합니다. `/api/v1` envelope, read-only inventory adapter, Placement seed logic, job/artifact storage, risk display, Create VM approval/artifact/checksum pattern, native UPID/post-check lesson, redaction, cleanup guard를 재사용합니다.

하지만 frontend-only recommendation을 execution source로 쓰거나, Create VM preflight를 DRS final pre-check로 그대로 쓰거나, VMID를 identity로 쓰면 안 됩니다.

## Phase 1: Backend DRS read model

목표는 mutation 없이 backend-owned recommendation read API를 추가하는 것입니다. Candidate endpoints: `GET /api/v1/drs/summary`, `GET /api/v1/drs/recommendations`, `GET /api/v1/drs/recommendations/{recommendation_id}`, `POST /api/v1/drs/recommendations/{recommendation_id}/check-now`.

Identity/policy tables가 없으면 execution은 disabled로 명시합니다.

## Phase 2: Metrics, identity, metadata

SMBIOS UUID, vmgenid, MAC address list, disk volume id list evidence를 수집하고 15분 average/peak metric substrate를 추가합니다. Confirm Identity, Confirm Same VM, Treat as New VM, allowed/restricted/blocked policy validation이 필요합니다.

## Phase 3: UI transition

`/placement` label을 DRS Advisor로 바꾸고 full table + detail drawer, Dashboard top 1-3 recommendations, identity/policy/route fields, reference-only Check Now를 추가합니다.

## Phase 4: Final pre-check and approval

Final pre-check, confirm modal, warning acknowledgement, operation locks를 구현합니다. Check Now는 authorize하지 않고, blocked/unknown은 migration job을 만들지 않는 contract를 테스트해야 합니다.

## Phase 5: Proxmox migration execution

Read-only inventory adapter와 분리된 DRS migration client를 추가합니다. UPID 저장, task status/log polling, post-check, lock release, secrets redaction을 구현합니다.

## Phase 6: Reconciliation and restart safety

Restart scan, Reconcile Now endpoint/action, stale/reconciliation_required lock handling, metadata reattach only by fingerprint match, timeout after 30m rules를 구현합니다.

## Deferred

Automatic DRS, scheduled rebalance, restricted exception approval, node drain, maintenance automation, affinity editor, backup/snapshot orchestration, artifact cleanup, VMware compatibility language are deferred/out of scope.
