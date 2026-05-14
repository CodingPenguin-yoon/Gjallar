# 남은 작업

기준 문서: [Current implemented state](../current/README.md), [DRS Advisor implementation plan](../product/drs-advisor/05_IMPLEMENTATION_PLAN.md), [Create VM profile/template/network design](../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md). 이 문서는 한국어 설명용이며 source of truth가 아닙니다.

이 페이지는 현재 구현과 product target 사이의 남은 일을 한국어로 정리합니다. 순서는 구현 권장 흐름에 가깝지만, 최종 우선순위는 product/architecture canonical 문서를 따릅니다.

## 프로필 DB seed: Create VM

현재 Create VM profiles는 `static_seed`입니다. Target은 Gjallar DB-seeded read-only profiles입니다.

남은 결정/작업:

- `general-vm`, `runtime-server`, `development-vm`를 DB seed로 넣을지, 언제 `static_seed`를 제거할지 결정.
- seed migration과 rollback story.
- profile management UI는 initial target에 넣지 않는다는 boundary 유지.
- API response의 `source`가 DB seed로 바뀌는 시점에 docs/tests 갱신.

## 읽기 모델 구축: DRS

현재 Placement는 frontend-only read model입니다. Target은 backend-owned DRS recommendation입니다.

남은 작업:

- `/api/v1/drs/summary`와 `/api/v1/drs/recommendations` 같은 read-only API contract.
- 현재 placement heuristic을 backend contract test로 옮기거나 mirror.
- identity, metadata, policy가 없을 때는 execution disabled로 명시.
- Dashboard top 1-3 recommendation summary.
- `/placement` label을 DRS Advisor로 전환하되 route compatibility 유지.

## 지표 기반: Metrics substrate

DRS target은 CPU/Memory current만으로 충분하지 않습니다.

남은 작업:

- resource metrics 1분 polling.
- 최근 15분 average/peak 계산.
- inventory/HA/storage 5분 polling.
- stale collected_at warning.
- final pre-check가 cached observed row가 아니라 live Proxmox state를 다시 읽는 boundary 유지.

## 정체성 관리: Identity와 fingerprint

VMID는 identity가 아니라 locator입니다. DRS execution에는 confirmed identity가 필요합니다.

남은 작업:

- inventory에서 SMBIOS UUID, vmgenid, MAC list, disk volume id list를 명시적으로 수집.
- normalized primary/secondary fingerprint hash.
- `vm_identity_assertions`와 `vm_metadata` 개념 구현.
- `unknown`, `confirmed`, `mismatch`, `retired_candidate` state.
- same VMID + different fingerprint를 Identity Mismatch로 차단.
- Confirm Same VM, Treat as New VM review/audit flow.
- owner, environment, sensitivity, migration_policy 필수 metadata validation.

## 최종 pre-check

Check Now는 참고용이고 execution authorization이 아닙니다. Approve & Migrate 직전 final pre-check가 필요합니다.

남은 작업:

- final pre-check endpoint와 artifact.
- identity confirmed, metadata complete, migration policy allowed.
- no operation lock.
- VM still on source node, VM running.
- target node online, cluster health/quorum OK.
- no active conflicting task.
- route feasible/warning.
- blocked/unknown이면 migration job을 만들지 않는 contract.
- warning이면 acknowledgement 요구.

## 마이그레이션 실행

현재 Create VM native create는 DRS migration executor가 아닙니다.

남은 작업:

- Proxmox live migration client를 read-only inventory adapter와 분리.
- approval-gated DRS mutation endpoint.
- `drs_migration` job creation.
- migration request UPID 저장.
- Proxmox task status/log polling.
- post-check: VM target node, running state, fingerprint match, no active conflicting task.
- task success만으로 job success를 확정하지 않는 rule.
- secrets/log redaction과 original artifact 분리.

## 잠금: Lock

DRS execution은 concurrent operation을 막아야 합니다.

남은 작업:

- VM-level lock.
- optional route/source-target lock.
- lock acquire 실패 시 Proxmox migration call 금지.
- success/failure 후 release.
- timeout/worker crash 시 stale 또는 `reconciliation_required`.
- lock 상태를 Jobs/Runs와 Risks/Alerts에 표시.

## 재조정: Reconciliation

불확실한 operation은 Proxmox actual state를 다시 읽어 정리해야 합니다.

남은 작업:

- 30분 timeout 후 `needs_reconciliation`.
- restart safety scan.
- `POST /api/v1/drs/jobs/{job_id}/reconcile` target endpoint.
- UPID/task log 조회 시도.
- VM locator, source/target location, fingerprint 확인.
- target node running + fingerprint match일 때만 success 전환.
- 불충분하면 `needs_reconciliation`과 lock `reconciliation_required` 유지.

## 작업 이력과 위험: Jobs/Runs와 Risks

현재 Jobs/Runs와 Risks/Alerts는 Create VM 중심입니다.

남은 작업:

- `drs_migration`, `drs_final_precheck`, `drs_reconciliation` 같은 job type.
- recommendation id, identity assertion id, source/target node, actor/approver, UPID, lock, timeout fields.
- DRS blocker code enum.
- `/api/v1/risks`가 Create VM risks와 DRS blockers를 source/action과 함께 표시하도록 확장.
- Identity Mismatch와 route Unknown을 warning처럼 취급하지 않는 UI/contract.

## 지연된 Create VM 작업

Create VM current success는 stopped VM 생성까지입니다.

남은 작업:

- first power-on.
- cloud-init completion/smoke.
- guest-agent IP discovery.
- SSH smoke.
- Ansible verification.
- Infra Explorer VM start action with Jobs/Runs audit.
- background reconciliation service for uncertain native create results.

## 문서 관리 원칙

한국어 문서는 설명 계층입니다. 기준 문서가 바뀌면 한국어 문서도 따라 갱신해야 합니다.

관리 원칙:

- `docs/ko`는 current/product/architecture를 쉽게 읽게 만드는 layer입니다.
- canonical behavior를 새로 정의하지 않습니다.
- archive, history, legacy PRD, old PRD를 current truth처럼 인용하지 않습니다.
- Terraform, DRS execution, Create VM first boot 같은 superseded 또는 future behavior를 current로 쓰지 않습니다.
- endpoint/path/method/profile id/artifact type은 English 그대로 둡니다.
- response schema를 장황하게 복사하지 말고 purpose, data source, side effect, frontend use, caveat 중심으로 설명합니다.
