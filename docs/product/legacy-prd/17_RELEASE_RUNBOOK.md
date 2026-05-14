# Gjallar Release / Operation Runbook

> Current MVP product source of truth is `drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.
> This create-first runbook is historical/supporting capability context only. It must not define the next MVP success line or implementation order.

## 0. 목적

Gjallar를 단계적으로 릴리스/검증하는 방법을 정의한다.

## 1. Stage 0 — Docs / Contract only

- PRD 검토
- API contract 검토
- manifest schema 검토
- TDD plan 검토

실제 Proxmox write 없음.

## 2. Stage 1 — Skeleton

- backend/frontend skeleton
- tests 실행
- mock data UI
- API shape 검증

## 3. Stage 2 — Read-only Proxmox

- Proxmox credential read-only scope 확인
- nodes 조회
- VMs 조회
- VM detail 조회
- observed snapshot 저장

검증:

- credential secret 미노출
- UI 응답 시간 확인
- stale 표시 확인

## 4. Stage 3 — Manifest / Preflight only

- profile/template/network manifest 로딩
- create draft
- preflight
- red/yellow/green 표시

실제 VM 생성 없음.

## 5. Stage 4 — Plan only

- job workspace 생성
- Terraform plan 또는 Proxmox plan equivalent 생성
- Terraform local backend state path 확인
- state lock / manifest-state `proxmox_vmid` 매핑 확인
- artifact 저장
- approval flow 확인

apply 금지.

## 6. Stage 5 — General VM create

제한 조건:

- 테스트 node/IP만 사용
- 사용자 승인 필수
- destroy/delete plan 금지
- Terraform state는 `/mnt/hermes_data/IaC-state/gjallar/<manifest_id>/terraform.tfstate` local backend 사용
- apply 전 state lock과 manifest/state `proxmox_vmid`/name 일치 확인
- Terraform/Proxmox apply/config 성공 전 첫 power on 금지
- apply 후 smoke 필수

검증:

- VM 생성됨
- 첫 power on은 apply/config 성공 후에만 실행됨
- IP 확인됨
- guest-agent 확인됨
- smoke artifact 저장됨
- state backup/checksum 저장됨
- DB observed snapshot 갱신됨

## 6.1 Stage 6 — Independent Power Actions, after first create MVP

제한 조건:

- power on / graceful shutdown / reboot만 제공
- 일반 Confirm 필수
- red risk 차단
- yellow risk 경고 체크박스 필수
- hard stop/reset endpoint와 버튼 없음

검증:

- Confirm 없이 power action이 실행되지 않음
- VM name/VMID/node/IP/current state/action이 확인 화면에 표시됨
- red risk VM은 action disabled
- yellow risk VM은 체크박스 없이는 실행 불가

## 7. Rollback / Recovery

MVP에서 자동 rollback은 제공하지 않는다.
실패 시:

1. job status failed
2. artifact 저장
3. 위험 표시
4. 수동 정리 runbook 제시
5. VM 삭제가 필요하면 별도 승인 절차로 처리

## 8. Release gate

다음이 모두 통과해야 다음 stage로 간다.

- tests pass
- secret scan pass
- PRD checklist pass
- red risk 차단 확인
- artifact 저장 확인
