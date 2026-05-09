# Gjallar PRD

이 폴더가 Gjallar 재설계의 단일 source of truth다.

## 제품 한 줄 정의

**Gjallar = Proxmox를 VMware처럼 쓰게 해주는 VM/인프라 운영 콘솔**

Gjallar는 Proxmox 클러스터/노드/VM을 사람이 안전하게 이해하고 조작하기 위한 제품이다.
Terraform/Ansible 실행기는 내부 수단일 뿐, 제품 정체성이 아니다.

## 작성 원칙

1. Gjallar 중심으로 쓴다.
2. 외부 배포 도구와의 연계는 최소 계약만 남긴다.
3. 앱 빌드/배포/로그/DB migration은 Gjallar PRD에 넣지 않는다.
4. 사람 화면을 먼저 정의하고, 그 화면을 만족하는 API를 정의한 뒤 구현한다.
5. 기존 코드는 보존 전제가 아니라 검증 후 일부만 살린다.
6. PRD가 확정되기 전 코드 재작성에 들어가지 않는다.

## 문서 목록

| 문서 | 역할 |
|---|---|
| `01_MASTER_PRD.md` | 제품 정체성, MVP, 범위, 핵심 정책 |
| `02_EXTERNAL_BOUNDARIES.md` | 외부 시스템과의 최소 경계. Gjallar 주객전도 방지 |
| `03_MANIFEST_GITOPS.md` | VM/Profile/Template/Network manifest와 IaC 저장 방식 |
| `04_SAFETY_PREFLIGHT.md` | risk, approval, preflight 정책 |
| `05_CREATE_VM_FLOW.md` | VM 생성 wizard, 원터치/단계별 실행 흐름 |
| `06_UI_SCREENS.md` | 사람 기준 화면 구성 |
| `07_DB_JOBS_ARTIFACTS.md` | DB, job, artifact 저장 역할 |
| `08_IMPLEMENTATION_ROADMAP.md` | PRD 이후 구현 순서 |
| `09_OPEN_QUESTIONS.md` | 사용자에게 더 물어볼 결정 사항 |
| `10_CODE_INVENTORY.md` | 기존 코드 재검증 정책. 과거 inventory를 source of truth로 보지 않음 |
| `11_KEEP_DROP_PARK.md` | 기존 코드 살릴 것/버릴 것/보류할 것의 판단 기준 |
| `12_UI_API_CONTRACT.md` | MVP 화면을 만족하는 API 계약 |
| `13_MANIFEST_SCHEMA.md` | manifest schema 초안 |
| `14_TDD_CONTRACT_PLAN.md` | 테스트 우선 구현 계획 |
| `15_FIRST_IMPLEMENTATION_SLICE.md` | 첫 구현 slice |
| `16_REVIEW_CHECKLIST.md` | 구현/리뷰 체크리스트 |
| `17_RELEASE_RUNBOOK.md` | 단계별 릴리스/운영 runbook |
| `18_PRD_AUDIT_CORRECTIONS.md` | 이번 PRD 정정 내역 |
| `19_MVP_DECISION_LOCK.md` | 확정된 MVP 결정 잠금 요약. 질문 전 반드시 확인 |
| `20_REMAINING_DECISIONS.md` | 남은 결정/구현 직전 확인값. 랜덤 질문 방지 |
| `21_MVP_IMPLEMENTATION_HANDOFF.md` | PRD 기준 첫 MVP 구현 handoff |

## 확정 결정

- Gjallar는 **Proxmox 운영 콘솔**이다.
- 최종 사용자는 우선 홈랩/소규모 운영자이며, 제품화 가능성을 고려한다.
- 첫 구현 MVP는 노드/VM 조회, `general-vm` 생성, VM 생성 flow 안의 first power on, IP/guest-agent, 리스크, preflight, Stage A smoke, job/artifact 작업 이력이다.
- MVP 실제 생성 profile과 화면 선택지는 `general-vm` 하나만 둔다. `runtime-server`, `dev-server`, `db-server`는 2차 profile 후보다.
- MVP NetworkProfile은 `yoonmanserver2`, `yoonmanserver3` 두 target node를 모두 지원하고, node별 bridge mapping으로 bridge를 결정한다. 초기 fixture는 두 노드 모두 `vmbr0`이다.
- MVP IP mode는 DHCP/static 둘 다 지원한다. 기본/추천값은 static이다. Runtime Target 후보 조건은 Runtime Target slice에서 다시 검증한다.
- 기존 VM 대상 독립 전원 제어, Runtime Target API/manifest, VM 삭제, 스냅샷, 리소스 변경, 템플릿 관리, Hermes 승인 큐, hard stop/reset은 2차다.
- VM 콘솔 접근은 3차다.
- VM/profile manifest는 필요하다. DB snapshot만 source of truth로 두지 않는다.
- Terraform/Ansible 코드는 공용 스토리지/IaC repo에서 관리한다.
- MVP에서는 Gjallar가 직접 실행하되, runner 분리 가능성을 구조에 남긴다.
- 위험 작업은 Review & Confirm을 거친다. red risk는 승인으로도 우회하지 않는다.
- Runtime Target은 첫 구현 MVP에서 만들지 않는다. 이후 slice에서도 후보/readiness 표시까지만 다루고, active 확정은 2차로 미룬다.
- Heimdall 연계는 MVP에서 read-only 조회까지만 허용한다. Gjallar는 Heimdall registry에 직접 write하지 않는다.

## PRD에서 의도적으로 줄인 것

외부 앱 운영 콘솔과의 연동은 미래에 필요하지만, Gjallar PRD의 중심이 아니다.
따라서 이 PRD에서는 외부 시스템을 “Gjallar readiness/risk를 읽는 소비자”로만 다룬다.
