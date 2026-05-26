# DRS Advisor Product Direction

## 1. 제품 정체성

Gjallar는 백업 제품이 아니다.
Gjallar는 Proxmox 클러스터를 운영하는 사람이 노드 부하, VM mobility, migration/HA/storage risk, 실행 이력, 재조정 상태를 한 곳에서 보고 안전하게 조작하는 Proxmox 엔터프라이즈 운영 플랫폼이다.

현재 MVP 핵심은 DRS Advisor다.

```text
Gjallar DRS Advisor = Proxmox-native migration advisor and control tower
```

금지 표현:

- VMware DRS replacement
- VMware DRS compatible
- automatic DRS for Proxmox
- backup product

허용 표현:

- Proxmox-native migration/HA 관찰
- CPU/Memory 중심 migration recommendation
- approval-gated live migration
- Proxmox task/UPID tracking
- operation audit and reconciliation
- advisor/control tower

## 2. 현재 코드 기반을 활용하는 방향

현재 코드는 create-first PRD를 따라 상당 부분 구현되어 있다.
새 MVP는 이를 버리지 않고 DRS Advisor 중심으로 재배치한다.

재사용할 기반:

- Dashboard의 `/api/v1` aggregation과 node/VM/storage/risk summary
- DRS Advisor Phase 1의 backend-owned read-only recommendation view model
- Jobs/Runs의 DB-backed job/artifact status substrate
- Risks/Alerts의 job-derived risk display
- Proxmox read-only inventory adapter
- Create VM의 approval, artifact, Proxmox native acknowledgement/post-check gate
- secret redaction과 forbidden legacy endpoint guard

현재 방향으로 바꿔야 하는 점:

- `/drs` DRS Advisor Phase 1 화면은 실행 없이 recommendation evidence를 보여준다.
- read-only recommendation은 identity/policy/final pre-check authority로 확장한다.
- recommendation 실행은 Allowed VM에 한해 manual approved live migration까지 포함한다.
- Jobs/Runs는 `vm_create`뿐 아니라 `drs_migration`을 1급 job으로 다룬다.
- Risks/Alerts는 identity, policy, lock, route, reconciliation blocker를 표시해야 한다.
- Create VM은 보조 capability로 유지한다.

## 3. MVP 포함

- Dashboard node row 중심 화면
- Dashboard 상위 1~3개 DRS 추천 요약
- `/drs` route의 DRS Advisor 화면
- DRS Advisor full recommendation table
- CPU/Memory 중심 recommendation
- 최근 15분 average + peak evidence
- resource metrics polling 1분
- inventory/HA/storage polling 5분
- VM identity/fingerprint reattachment
- VM metadata/policy validation
- Allowed VM 대상 manual approved live migration
- Approve & Migrate flow
- final pre-check
- Confirm modal
- operation lock
- Proxmox migration task/UPID tracking
- Jobs/Runs artifact/log
- success/failed/needs_reconciliation
- Reconcile Now
- Gjallar restart 후 Proxmox current state 재구성

## 4. MVP 제외

- 자동 DRS
- 야간 자동 리밸런싱
- restricted 예외 승인
- node drain
- maintenance mode 자동화
- affinity/anti-affinity policy editor
- policy exception workflow
- automatic rollback
- backup orchestration
- snapshot/backup product 기능
- job/artifact 자동 삭제
- VMware DRS 호환성 주장

## 5. Create VM의 위치

Create VM Proxmox native flow는 보조 기능으로 유지한다. Legacy Terraform executor와 GitOps execute/archive route/helper code는 active contract에서 제거됐다.
현재 구현은 다음 capability를 제공하므로 DRS Advisor 작업에서도 재사용할 설계 힌트를 준다.

- draft
- non-destructive preflight
- artifact-backed plan
- review summary checksum
- approval gate
- yellow risk acknowledgement
- Proxmox native preview/create acknowledgement
- UPID polling and observed_after/fingerprint artifact pattern
- job status and artifact publication
- secret redaction

하지만 현재 MVP의 success line은 새 VM 생성이 아니라 DRS Advisor migration recommendation, approval, execution, tracking, reconciliation이다.

## 6. 성공 기준

- Dashboard가 노드 행 단위 CPU/Memory/Disk/VM 상태를 보여준다.
- Dashboard가 상위 1~3개 DRS 추천을 보여준다.
- `/drs`가 DRS Advisor 화면으로 보인다.
- DRS Advisor table이 CPU/Memory 15분 average/peak evidence를 보여준다.
- Allowed VM만 Approve & Migrate 가능하다.
- Restricted/Blocked/Unclassified/Identity Mismatch는 실행되지 않는다.
- final pre-check 10개가 실행 직전에 새로 수행된다.
- Check Now 결과를 실행 허가로 재사용하지 않는다.
- manual approved live migration이 Proxmox UPID tracking으로 진행된다.
- Jobs/Runs가 `drs_migration` success/failed/needs_reconciliation을 표시한다.
- timeout 30분 후 needs_reconciliation으로 전환된다.
- Reconcile Now가 current Proxmox state 기반으로 job/lock 상태를 정리한다.
- restart 후 metadata/policy는 fingerprint match 시에만 재연결된다.
- same VMID + different fingerprint mismatch가 감지되고 모든 작업을 차단한다.

## 7. Demo scenarios

Normal DRS migration:

1. source node가 CPU/Memory hot 상태다.
2. target node가 online이고 여유가 있다.
3. VM identity confirmed, metadata complete, policy allowed다.
4. Dashboard top recommendation에서 DRS Advisor로 이동한다.
5. Approve & Migrate를 누른다.
6. final pre-check가 통과한다.
7. confirm modal에서 승인한다.
8. operation lock이 잡힌다.
9. Proxmox migration UPID가 저장되고 polling된다.
10. target node running + fingerprint match 후 success가 된다.

Identity protection:

1. metadata 없는 VM은 Unclassified warning이다.
2. Approve & Migrate가 disabled다.
3. same VMID + different fingerprint는 Identity Mismatch critical이다.
4. 기존 metadata 자동 attach가 금지된다.
5. Confirm Same VM 또는 Treat as New VM flow로 이동한다.

Timeout reconciliation:

1. migration job이 시작되고 UPID가 저장된다.
2. 30분 안에 명확한 완료 상태를 얻지 못한다.
3. job은 needs_reconciliation이 된다.
4. lock은 reconciliation_required로 남는다.
5. Reconcile Now가 Proxmox current state와 task log를 확인한다.
6. target node running + fingerprint match이면 success, 불명확하면 needs_reconciliation 유지다.
