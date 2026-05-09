# Gjallar

Gjallar의 제품/구현 source of truth는 `PRD/`이고, cron/Set-runner 운영 source of truth는 이 루트 운영 문서들이다.

Last updated: 2026-05-09 03:05 KST

## 한 줄 정의

**Gjallar는 Proxmox를 VMware처럼 쓰게 해주는 VM/인프라 운영 콘솔이다.**

1차 관심사는 앱 배포가 아니라 Proxmox 클러스터, 노드, VM, 템플릿, 네트워크, 리스크, preflight, smoke, 작업 이력이다.

## 읽는 순서

1. `/mnt/hermes_data/00_START_HERE.md`
2. `/mnt/hermes_data/문서운영/작업전_필수_확인.md`
3. `README.md`
4. `PRODUCT.md`
5. `CURRENT_STATE.md`
6. `TASKS.md`
7. `DECISIONS.md`
8. `ARCHITECTURE.md`
9. `RUNBOOK.md`
10. `PRD/README.md`
11. `PRD/19_MVP_DECISION_LOCK.md`
12. `PRD/21_MVP_IMPLEMENTATION_HANDOFF.md`
13. `PRD/22_CODEBASE_REWRITE_EXECUTION_PLAN.md`

## 현재 실행 계획

- 실행 계획: [`PRD/22_CODEBASE_REWRITE_EXECUTION_PLAN.md`](PRD/22_CODEBASE_REWRITE_EXECUTION_PLAN.md)
- Current Set: `Set 7 — Review & Confirm / approval policy`
- 운영 방식: Set-runner worker + read-only heartbeat
- 실제 코드 repo: `codex-vm:/home/yoon/projects/Gjallar`

## 폴더

- `PRD/`: 제품/API/schema/구현 기준 문서
- `plans/`: 운영/Set 계획 보조 문서
- `specs/`: PRD 외 상세 명세가 필요할 때만 사용
- `logs/`: 리뷰/검증/cron 실행 기록
- `archive/`: 과거/보류 문서. 현재 실행 대상 아님
- `references/`: 참고자료

## 핵심 안전 원칙

- PRD → contract/schema test → 구현 → fresh review 순서로 진행한다.
- commit/push/delete/Terraform apply/Proxmox write/power action은 사용자 명시 승인 전 금지한다.
- cron은 Gjallar repo/docs/lock만 다룬다. 다른 프로젝트는 read-only 확인만 허용한다.
