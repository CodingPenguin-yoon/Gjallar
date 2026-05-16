# DRS Advisor Data, DB, And Identity

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 data/db/identity](../../../product/drs-advisor/03_DATA_DB_AND_IDENTITY.md), [Data identity architecture](../../../architecture/data-identity/overview.md), [Current implemented state](../../../current/README.md).

## 왜 identity 도메인이 필요한가

Migration은 "VMID 101을 옮긴다"가 아니라 "우리가 알고 있는 바로 그 VM을, 현재도 같은 VM임을 확인하고, 허용된 정책 안에서 옮긴다"여야 합니다. VMID는 locator일 뿐 identity가 아닙니다. VMID 재사용이나 metadata 오연결은 잘못된 VM을 이동시키는 위험을 만듭니다.

## Source of truth

Proxmox actual state가 VM existence, locator, running state, node online, CPU/Memory, storage/network, HA, task, config lock, quorum, route evidence의 기준입니다. Gjallar DB는 actual state를 대체하지 않고 jobs, approvals, artifact refs, operation locks, metadata/policy, fingerprint assertions, recommendation snapshots, pre-check results, UPID tracking, reconciliation state, audit trail을 저장합니다.

## Current implemented substrate

현재는 DB-backed DRS tables가 없습니다. 대신 read-only inventory dataclasses, fake/live inventory adapter, DB-backed job status/artifacts, Create VM draft/preflight/plan/approval/native flow, `/api/v1/jobs`, `/api/v1/risks`가 있습니다.

Create VM `observed_after` artifact는 fingerprint evidence를 남기지만 DRS identity DB record가 아닙니다.

## VMID is not identity

Target rule:

- same VMID + same fingerprint: metadata attach 가능.
- same VMID + different fingerprint: Identity Mismatch, metadata 자동 적용 금지, 모든 작업 차단.
- new VMID + known/similar fingerprint: operator review 필요.
- unknown fingerprint: Confirm Identity 전 migration 불가.

Primary fingerprint evidence는 SMBIOS UUID, vmgenid, MAC address list, disk volume id list입니다. Name, tag, IP, owner, profile은 단독 identity 근거가 될 수 없습니다.

## Target metadata/policy

Required metadata: owner, environment, sensitivity, migration_policy, identity_status confirmed. MVP에서 execution 가능한 policy는 Allowed뿐입니다. Restricted는 metadata는 있지만 일반 DRS 실행 제외이고, Blocked는 이동 금지입니다.

## Target tables and validation usage

Target concepts include `vm_identity_assertions`, `vm_metadata`, `observed_nodes`, `observed_vms`, `drs_recommendations`, `drs_prechecks`, `operation_locks`, jobs/operations/reconciliation records.

중요한 validation usage:

- recommendation builder는 confirmed identity가 아니면 VM을 제외합니다.
- current primary fingerprint hash가 다르면 metadata attach를 금지합니다.
- metadata incomplete는 blocker입니다.
- route Unknown/Blocked는 실행 불가입니다.
- final pre-check는 observed DB row가 아니라 live Proxmox state를 다시 읽습니다.
