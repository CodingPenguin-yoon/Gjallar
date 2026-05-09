# Gjallar Implementation Roadmap PRD

## 0. 목적

PRD 확정 후 구현 순서를 정의한다.

## 1. 현재 결정

기존 코드를 그대로 확장하지 않는다.
새 PRD 기준으로 재설계한다.
방향은 “대부분 새로, 유용한 테스트/문서/경험만 검증 후 보존”이다.

## 2. 구현 전 필수 단계

1. PRD 검토 완료
2. 사용자 답변 필요한 open question 정리
3. UI 화면 계약 확정
4. API contract 확정
5. Manifest schema 확정
6. 기존 코드 fresh inventory
7. Keep / Drop / Park 분류
8. 첫 slice 테스트 작성

첫 구현 MVP 완료선은 Phase 4의 `general-vm` 생성 + Stage A smoke + job/artifact 추적까지다.
Phase 5 독립 power actions와 Phase 6 Runtime Target read-only는 core create flow 안정화 후 이어 붙인다.

## 3. Phase 0 — PRD Freeze

목표:

- Gjallar 제품 정체성 고정
- 외부 도구 내용 축소
- MVP/out-of-scope 고정
- 문서 source of truth를 PRD로 단일화

완료 기준:

- `PRD/`와 루트 `README.md`만 활성 문서로 남음
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

- profile/template/network/vm manifest parser
- MVP enabled profile은 `general-vm` 하나만 지원
- future profile(`runtime-server`, `dev-server`, `db-server`)은 create/apply 차단
- schema tests
- preflight engine
- risk model
- plan-only job

## 7. Phase 4 — Create VM Apply

목표:

- Review & Confirm: VM 이름, VMID, node/storage/template, hardware, network/IP, Terraform state path, first power on, smoke timeout, risk summary, plan artifact, git diff 요약
- 일반 Confirm 승인과 yellow risk 경고 체크박스
- job workspace
- manifest commit
- apply
- bootstrap
- smoke
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
