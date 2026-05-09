# PRODUCT

Last updated: 2026-05-09 00:42 KST

## 제품 정체성

Gjallar는 **Proxmox를 VMware처럼 쓰게 해주는 VM/인프라 운영 콘솔**이다.

Terraform/Ansible/IaC는 내부 구현 수단이고, 제품 중심은 사람이 이해하고 승인할 수 있는 VM/노드/리스크/작업 화면이다.

## MVP 사용자 가치

- Proxmox 클러스터/노드/VM/템플릿/네트워크 상태를 읽는다.
- `general-vm` 생성 요청을 draft/preflight/plan으로 안전하게 만든다.
- Review & Confirm에서 리스크와 산출물을 보고 승인 여부를 결정한다.
- powered-off 생성, first power on, Stage A smoke 결과를 job/artifact로 추적한다.

## MVP 포함

- Dashboard / Infra Explorer
- Nodes / VMs / VM Detail read-only
- `general-vm` 생성 flow
- preflight / plan / Review & Confirm
- risk/red-yellow-green policy
- job/run/artifact 저장
- first power on + cloud-init/guest-agent/IP/SSH smoke

## MVP 제외

- VM 삭제, snapshot/rollback, hard stop/reset/kill
- 기존 VM 독립 power action
- Runtime Target write/active 전환
- 앱 deploy, DB migration, 임의 shell
- Gjallar의 Heimdall registry 직접 write

## 기준 문서

- `PRD/01_MASTER_PRD.md`
- `PRD/19_MVP_DECISION_LOCK.md`
- `PRD/21_MVP_IMPLEMENTATION_HANDOFF.md`
