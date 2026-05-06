# Gjallar

> Proxmox용 **Operations & Risk Console**

Gjallar는 Proxmox에 기업형 운영 가시성과 안정성 레이어를 얹는 운영 콘솔이다.
짧게 말하면:

```text
Proxmox용 vCenter 보조 레이어 + 운영 리스크 대시보드
```

Gjallar는 GitLab CI/CD 도구도, staging deploy 도구도 아니다.
현재 방향성은 다음처럼 고정한다.

```text
Gjallar = Observe / Govern / Act for Proxmox
```

---

## 전체 홈랩에서의 위치

```text
사용자 / Discord
  ↓ 자연어 요청
Hermes
  ↓ 판단 / 계획 / 승인 / 검토 / 보고
Gjallar
  ↓ Proxmox VM/LXC/node/storage 운영, provisioning, risk evidence
Proxmox Cluster / PBS / NAS
```

Heimdall과 함께 사용할 때는 이렇게 나눈다.

```text
Gjallar = Proxmox 인프라를 준비하고 안전하게 운영하는 계층
Heimdall = 준비된 인프라 위에서 agent/devops 작업을 실행하는 계층
Hermes = 두 계층을 조합해서 판단하고 사용자에게 보고하는 자연어 운영자
```

---

## Gjallar가 담당하는 것

### 1. Observe — 현재 상태를 정확히 보여준다

- Proxmox node inventory
- VM / LXC / template inventory
- storage / network / bridge 정보
- VM power state, IP, guest agent signal
- task/log tracking
- resource usage summary

### 2. Govern — 운영 리스크와 표준 위반을 찾는다

- backup coverage / backup recency risk
- 오래된 snapshot risk
- qemu guest agent 없음/미응답 risk
- storage usage risk
- owner / environment / tag 누락 risk
- 장기 stopped VM risk
- optional read-only SSH guest evidence gap risk
- production VM explicit backup/RPO profile compliance risk

### 3. Act — 승인 기반으로 안전하게 조치한다

- VM create/provision
- start / shutdown / reboot / stop
- destructive action typed confirmation
- Terraform/Ansible 기반 bootstrap
- task log / verification report
- 향후 승인 기반 remediation

처음부터 무제한 자동수정을 목표로 하지 않는다.
기본 루프는 다음이다.

```text
Observe → Detect → Recommend → Approve → Fix → Verify → Report
```

---

## Gjallar가 담당하지 않는 것

| 영역 | 담당 프로젝트 | 이유 |
|---|---|---|
| Git repo / issue / branch / PR 작업 | Heimdall | 개발·배포 실행 계층의 책임 |
| Codex/Claude/OpenCode worker task orchestration | Heimdall | agent 작업 실행과 로그는 Heimdall 책임 |
| GitLab/GitHub CI/CD pipeline 관리 | Heimdall 또는 별도 CI | Gjallar는 인프라 운영 콘솔 |
| source repository 기반 app deploy | Heimdall | 앱 배포는 DevOps 실행 문제 |
| LLM provider/context/memory/agent loop | Hermes | Gjallar는 자체 Hermes가 되지 않는다 |
| Proxmox UI 내부 플러그인 의존 | 현재 비추천 | 업그레이드/보안/유지보수 리스크가 큼 |

---

## Heimdall과의 연계

Heimdall이 worker VM이나 staging 실행 환경이 필요하면, 장기적으로 VM을 직접 만들지 않고 Gjallar API를 사용한다.

```text
Hermes
  → Heimdall: worker capacity / staging 환경 필요 확인
  → Gjallar: VM 생성 plan 요청
  → Gjallar: node/template/storage/network/resource risk preflight
  → 사용자 승인
  → Gjallar: Proxmox VM 생성 및 bootstrap
  → Heimdall: worker 또는 staging target 등록
  → Heimdall: repo 작업, test/build, deploy verification 실행
```

### 소유권 원칙

```text
VM 생성/삭제/리소스 변경/lifecycle/Proxmox risk state → Gjallar
repo/agent task/test/build/PR/staging verification → Heimdall
자연어 판단/승인 조율/최종 보고 → Hermes
```

Terraform state도 장기적으로 Gjallar 쪽에 모은다.
한 VM을 Heimdall과 Gjallar가 각각 다른 Terraform state로 동시에 관리하지 않는다.

---

## 현재 구현 상태

### Phase 1 — VM Operations Console MVP

완료된 핵심:

- Proxmox inventory / instance list / monitoring baseline
- VM provisioning flow 정리
- `/api/provision` 중심 생성 flow
- readiness / resource / template preflight
- lifecycle action 안전장치
- task/log UX 개선
- 실제 Create VM end-to-end smoke
- template disk size가 요청 disk보다 클 때 preflight에서 차단

### Phase 2 — Operational Risk Dashboard

완료된 핵심:

- read-only `/api/operations/risks`
- Risk Dashboard UI
- guest agent risk
- backup task history / backup schedule coverage evidence
- PBS restore readiness evidence
- PBS datastore health/capacity evidence
- restore drill record evidence
- VM별 RPO/RTO profile reporting
- snapshot age risk
- storage capacity risk
- owner/environment/tag governance risk
- Gjallar DB 기반 VM state history
- 장기 stopped VM 탐지 기반
- safe action suggestion metadata/links (`proposal_only`, `requires_approval=true`)
- lower-level fail-closed VM state reconciliation guards for partial/node-scoped/legacy cached inventory

최근 핵심 커밋:

```text
05f0f41 Add operational risk dashboard
7c2ca71 Add backup schedule risk evidence
854cd15 [verified] Add VM state history risk evidence
4c29afe [verified] Add PBS restore readiness evidence
Set 1~5: verified-but-uncommitted operational risk hardening; commit/push requires explicit approval
```

---

## 아키텍처 원칙

### 1. 외부 운영 콘솔 우선

초기 Gjallar는 Proxmox 노드 내부 플러그인으로 들어가지 않는다.
외부 서버에서 Proxmox API, Gjallar DB, 향후 PBS API를 조합한다.

```text
Gjallar backend
  → Proxmox API: 현재 상태 evidence
  → Gjallar DB: 시간 이력 / 정책 / 예외 / 설정
  → Risk Engine: 운영 리스크 판단
  → Frontend: 운영 콘솔 UI
```

### 2. read-only risk부터 시작

Risk Dashboard는 기본적으로 read-only evidence를 사용한다.
조치 기능은 별도의 승인과 task log를 거친다.

### 3. Proxmox API 한계는 Gjallar DB로 보완

Proxmox API는 “현재 상태”에는 강하지만, “언제부터 그랬는가”, “운영자가 예외 처리했는가”, “우리 표준에 맞는가” 같은 판단은 Gjallar가 저장해야 한다.

예:

```text
Proxmox API: VM이 현재 stopped인지 알려준다.
Gjallar DB: 언제부터 stopped였는지 저장한다.
Risk Engine: 30일/90일 기준을 넘었는지 판단한다.
```

---

## 다음 우선순위

1. **threshold config/UI**
   - backup/snapshot/storage/stopped 기준을 운영자가 설정할 수 있게 만든다.
2. **stale state cleanup + VMID reuse guard**
   - 삭제된 VM state row 정리
   - VMID 재사용 시 오래된 이력 상속 방지
3. **risk acknowledge/suppress**
   - 의도된 예외를 운영자가 숨기거나 보류 처리
4. **owner/tag taxonomy check**
   - owner, env, service, backup-policy 표준화
5. **PBS direct API / restore readiness**
   - 백업이 있는지를 넘어 복구 가능성까지 확인
6. **RPO/RTO profile reporting**
   - VM metadata 기반 profile로 restore point, restore drill, backup recency 기준을 설명 가능하게 만든다.
7. **Policy / Compliance baseline**
   - prod/production VM은 explicit backup/RPO profile metadata를 요구하는 read-only compliance risk를 제공한다.

---

## Repository layout

```text
backend/        FastAPI backend
frontend/       React/Vite frontend
infra/          Terraform/Ansible provisioning assets
backend/app/domains/proxmox/  Proxmox API, provisioning, risk logic
backend/app/domains/task/     Task status/log APIs
docs/           Repo-local docs. Shared storage remains the product source of truth.
```

---

## 문서 source of truth

제품 방향과 현재 상태는 shared storage를 먼저 본다.

```text
/mnt/hermes_data/프로젝트/Gjallar
/mnt/hermes_data/프로젝트/AI_Homelab_Control_Plane_방향성.md
```

읽는 순서:

1. `/mnt/hermes_data/프로젝트/Gjallar/README.md`
2. `/mnt/hermes_data/프로젝트/Gjallar/CURRENT_STATE.md`
3. `/mnt/hermes_data/프로젝트/Gjallar/TASKS.md`
4. `/mnt/hermes_data/프로젝트/Gjallar/DECISIONS.md`
5. `/mnt/hermes_data/프로젝트/Gjallar/ROADMAP.md`
6. `/mnt/hermes_data/프로젝트/Gjallar/RUNBOOK.md`
7. `/mnt/hermes_data/프로젝트/헤임달/README.md`

Repo-local docs는 [docs/README.md](docs/README.md)에서 시작한다.

---

## 한 줄 결론

```text
Gjallar는 Proxmox 인프라의 운영 가시성·거버넌스·안전한 조치 계층이고,
Heimdall은 그 인프라 위에서 agent/devops 작업을 실행하는 계층이다.
```
