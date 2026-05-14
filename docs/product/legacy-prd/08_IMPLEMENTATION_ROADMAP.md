# Gjallar Implementation Roadmap PRD

> 2026-05-13 Create VM profile/template/network update: DRS Advisor remains the
> current MVP source of truth. If Create VM work resumes, use
> [`docs/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md).
> Older roadmap items for single `general-vm`, future `dev-server`/`db-server`,
> `server-net`/NetworkProfile mapping, template catalogs, and first-power-on as
> part of create success are superseded by that design.

## 0. 목적

PRD 확정 후 구현 순서를 정의한다.

## 1. 현재 결정

기존 코드를 그대로 확장하지 않는다.
새 PRD 기준으로 재설계한다.
방향은 “대부분 새로, 유용한 테스트/문서/경험만 검증 후 보존”이다.

현재 MVP 구현 우선순위는 [`drs-advisor/`](../drs-advisor/README.md)의 DRS Advisor다.
기존 create-first roadmap은 보조 capability와 역사적 계획으로 유지하되, 다음 실행 순서는 Dashboard node-load, DRS recommendation, metadata/identity/policy, final pre-check, manual approved live migration, Jobs/Runs reconciliation 흐름을 먼저 둔다.

## 2. 구현 전 필수 단계

1. PRD 검토 완료
2. 사용자 답변 필요한 open question 정리
3. UI 화면 계약 확정
4. API contract 확정
5. Manifest schema 확정
6. 기존 코드 fresh inventory
7. Keep / Drop / Park 분류
8. 첫 slice 테스트 작성

현재 첫 MVP 완료선은 DRS Advisor에서 Allowed VM 대상 manual approved live migration을 실행/추적하고, timeout/restart 상황을 `needs_reconciliation`과 Reconcile Now로 처리하는 것이다.
Create VM powered-off/stopped 생성 + job/artifact 추적은 보조 capability로 유지한다.

## 2.1 Current DRS Advisor implementation order

1. Proxmox current inventory/metrics 재구성: VMID는 locator로만 취급.
2. Dashboard node row load model: CPU/Memory 15분 average/peak, resource polling 1분.
3. VM fingerprint/identity/metadata/policy model: confirmed identity와 allowed policy 없이는 migration 불가.
4. DRS recommendation builder: CPU/Memory 중심, inventory/HA/storage polling 5분.
5. `/placement` 화면을 DRS Advisor로 전환: full recommendation table, VM Mobility, Route Status.
6. final pre-check 10개와 Confirm modal.
7. operation lock과 Proxmox live migration UPID tracking.
8. Jobs/Runs artifact/log/reconciliation: success/failed/needs_reconciliation, Reconcile Now.
9. restart 후 Proxmox actual state 재구성과 fingerprint match 기반 metadata reattachment 검증.

## 3. Phase 0 — PRD Freeze

목표:

- Gjallar 제품 정체성 고정
- 외부 도구 내용 축소
- MVP/out-of-scope 고정
- 역사적 create-first 문서 source of truth를 당시 PRD로 단일화

완료 기준:

- 당시 create-first 기준으로 루트 `README.md`와 당시 `PRD/`만 남기도록 정리함
- 현재 활성 제품 문서는 `docs/product/drs-advisor/`이며, 운영/상태 문서는 docs root split을 따른다
- PRD 내부에 앱 배포 중심 문구 없음
- Heimdall은 외부 consumer 예시로만 남음

## 4. Phase 1 — Contract Skeleton

목표:

- backend/frontend 빈 구조
- API route skeleton
- schema validation
- 테스트 환경

아직 실제 Proxmox write는 하지 않는다.

## 5. Phase 2 — Read-only Inventory

목표:

- Proxmox nodes 조회
- VMs 조회
- VM detail 조회
- observed snapshot DB 저장
- Dashboard/Infra Explorer 표시

## 6. Phase 3 — Manifest + Preflight

목표:

- VM manifest/job artifact parser
- Profile source는 Gjallar DB seed이며 enabled UI-visible profile은 `general-vm`, `runtime-server`, `development-vm`
- Profile은 target node/storage/network/template/power/version을 bind하지 않음
- Template source는 Proxmox live inventory이며 Gjallar template catalog 없음
- Network는 target node 선택 후 active live bridge 선택, `network_id`/`server-net` 사용 안 함
- static mode는 `static_ip`, `prefix`, `gateway` 필수, DHCP mode는 discovery warning과 함께 허용
- schema tests
- preflight engine
- risk model
- plan-only job

## 7. Phase 4 — Create VM Apply

목표:

- Review & Confirm: VM 이름, VMID, node/storage/template, hardware, bridge/IP fields, Terraform state path, power policy `stopped`, risk summary, plan artifact, git diff 요약
- 일반 Confirm 승인과 yellow risk 경고 체크박스
- job workspace
- manifest commit
- apply/configure powered-off
- first power-on, smoke, guest-agent discovery, SSH verification은 별도 follow-up stage
- artifact 저장

실제 VM 생성은 테스트용 IP/노드로 제한한다.

## 8. Phase 5 — Power + Risk UX

Deferred after first create MVP.

목표:

- 독립 power on / graceful shutdown / reboot
- 일반 Confirm 기반 approval 정책
- red risk 차단, yellow risk 경고 체크박스
- hard stop/reset은 MVP 제외
- Risks / Alerts 화면
- smoke 재시도

## 9. Phase 6 — Runtime Target Read-only

Deferred after first create MVP.

목표:

- Gjallar 내부 runtime target candidate/readiness API
- readiness/risk read-only 응답
- red risk면 target blocked
- Heimdall은 필요 시 조회만 가능

외부 시스템 전용 기능은 여기서도 최소화한다.
Gjallar가 Heimdall registry에 직접 write하는 자동 등록은 2차에서 별도 재검토한다.

## 10. Later

- VM 삭제
- snapshot/rollback
- resource resize
- template management
- approval queue
- VM console
- RBAC
