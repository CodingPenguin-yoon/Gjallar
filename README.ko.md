# Gjallar

[English](README.md) · **한국어**

**Proxmox 운영을 한곳에서 끝내세요.**

갈랴르는 템플릿 준비, VM 관리, 인프라 모니터링과 문제 복구를 더 쉽게 연결하는 도구를 만들고 있습니다. Proxmox 관리 화면을 오가지 않고, 갈랴르의 웹에서 일상 운영을 끝내는 것이 목표입니다.

실제 서버를 움직이는 엔진과 상태의 기준은 Proxmox입니다. 갈랴르는 현재 상태를 이해하고, 필요한 변경을 수행하고, 결과를 확인하는 과정을 연결합니다.

> **개발 중입니다.** 제품 업무는 웹에 집중합니다. 사용자 CLI·TUI는 제거하고 로컬 설치·서비스 관리·동일 schema 이미지 전환 명령만 유지합니다. 구현 범위와 남은 실환경 검증은 아키텍처·로드맵을 따릅니다.

## 중요하게 생각하는 것

- **시작이 쉽다.** 설치와 Proxmox 연결 과정을 간단하게 만듭니다.
- **일을 끝낼 수 있다.** 준비·관리·모니터링·복구를 하나의 흐름으로 연결합니다.
- **결과를 믿을 수 있다.** 무엇이 바뀌었고, 성공했는지, 무엇을 더 확인해야 하는지 보여줍니다. 요청이 접수됐다는 이유만으로 성공으로 판단하지 않습니다.

지금은 개인 운영자와 소규모 팀이 매일 사용할 기본 도구를 탄탄하게 만드는 데 집중합니다. 기업용 기능과 AI 지원은 그 기반 위에 확장합니다.

## 만들고 있는 사용 경험

| 영역 | 목표 |
|---|---|
| 설치·연결 | macOS·Linux 간편 부트스트랩, 연결 검사와 명확한 설정 안내 |
| 템플릿 | 재사용할 VM 템플릿의 등록·준비·검증·관리 |
| VM 관리 | 생성·복제·삭제, 시작·정상 종료, 사양 변경과 VM 콘솔 접속 |
| 모니터링 | 노드·VM·스토리지 상태, 자원 사용량·추이와 실패한 작업 확인 |
| 복구 | 실패 원인 확인, 백업 관리, VM 복원과 결과 검증 |
| 인프라 | 일상 운영에 필요한 노드·스토리지·네트워크 조회와 관리 |
| 웹 운영 | 웹에서 지원하는 업무의 실행과 결과 확인 |

**우선순위의 기준은 “어떤 순간에 갈랴르를 떠나 Proxmox를 열어야 하는가?”입니다.** 기능 수를 늘리기 전에 지원하는 업무를 끝까지 처리하도록 만듭니다. Proxmox 자체의 비상 관리 경로는 유지합니다.

위 표는 이미 제공하는 기능 목록이 아닌 제품 목표입니다. 합의한 방향과 현재 구현 경계는 [프로젝트 명세](project-docs/prd.md)에서 확인할 수 있습니다.

## 현재 제공하는 기능

| 기능 | 현재 지원 범위 |
|---|---|
| 자원 조회 | 노드·VM·템플릿·스토리지·네트워크 관찰, VM 상세와 최근 작업 연결 |
| Insights | 위험·준비 상태·용량·배치에 대한 근거와 관찰 시점·최신성 표시 |
| VM 생성 | 기존 Proxmox 템플릿 복제, 사양 직접 입력 또는 선택적 프리셋, 계획 검토·승인, 선택적 부팅·검증 |
| 전원 관리 | 사전 검사와 결과 검증을 거치는 시작·정상 종료 |
| Guided unlock | 운영자가 외부에서 실행하는 제한된 `qm unlock` 절차 안내와 API 결과 검증 |
| 작업 이력 | 상태·이벤트·증거·Job history와 지원 작업의 복구 관찰 |
| 계정 | 로컬 인증·세션, `viewer`·`operator`·`admin` 권한 |

### 실제 상태와 결과를 구분합니다

- Proxmox 연결이 없거나 실패하면 그대로 표시합니다. 실제 환경의 조회 실패를 가짜 데이터로 대체하지 않습니다.
- 일부만 관찰된 경우에도 확인된 데이터와 한계를 함께 표시합니다. Create 입력·검토는 partial base snapshot에서도 가능하며, 실행에는 source별·action별 추가 검사가 적용됩니다.
- 복구 관찰은 Proxmox 상태를 다시 조회하고 로컬 기록을 정합화합니다. 원래 변경을 무작정 재실행하지 않습니다. 백그라운드 복구 관찰은 기본 비활성입니다.
- 모니터링은 Proxmox 관찰과 제공 이력을 사용하며 별도 시계열 저장소를 운영하지 않습니다. VM 실행 상태만으로 내부 애플리케이션의 정상 동작을 보장하지 않습니다.

VM·템플릿·모니터링·백업/복원·인프라 흐름은 구현됐으며 기능별 실환경 검증 범위는 로드맵을 따릅니다. 현재 VM 생성에는 기존 Proxmox 템플릿이 필요하며, ISO 설치와 빈 VM 생성은 지원하지 않습니다.

## 현재 애플리케이션 실행하기

관리형 bootstrap 설치 도구를 제공합니다. 의존성 설치, 환경 설정, PostgreSQL 초기화와 계정 생성은 [운영 Runbook](project-docs/development.md)을 따릅니다.

### 로컬 개발

필요 환경: Python **3.13**, Node.js **24**, pnpm **10.34.5**, PostgreSQL. 인프라 기능에는 Proxmox VE API 접근이 필요합니다.

Runbook의 준비 절차를 완료한 뒤 저장소 루트에서 실행합니다.

```bash
pnpm run dev
```

기본 로컬 접속 주소:

- 웹 UI: <http://127.0.0.1:5173>
- Backend: <http://127.0.0.1:8000>

### Docker

Dockerfile을 제공합니다. Production image는 빌드된 웹 UI와 FastAPI backend를 함께 제공하며 PostgreSQL은 별도로 구성합니다.

Runbook의 container 절차를 따릅니다. Container 시작 시 DB migration, 선택적 생성 프리셋 seed와 설정에 따른 관리자 bootstrap이 수행됩니다. 기존 설치의 DB에 연결하기 전에는 기존 DB 적용 절차를 확인합니다.

## 개발과 검증

React frontend, FastAPI backend, PostgreSQL/Alembic 저장 계층과 Proxmox API adapter로 구성됩니다.

| 위치 | 역할 |
|---|---|
| `frontend/` | 웹 인터페이스 |
| `backend/app/` | API, 관찰, 작업 실행과 Proxmox 연동 |
| `backend/tests/` | Backend·계약 테스트 |
| `project-docs/` | 제품·개발 공동 기준 문서 |

개발 의존성 설치 후 로컬 검증:

```bash
pnpm run verify
```

Docker를 사용할 수 있는 환경에서 container 기준 검증:

```bash
pnpm run verify:container
```

## 문서

상세 프로젝트 문서는 현재 한국어로 관리합니다.

- [문서 홈](project-docs/README.md)
- [제품 방향과 범위](project-docs/prd.md)
- [현재 아키텍처](project-docs/architecture.md)
- [설치·운영·장애 대응](project-docs/development.md)
- [로드맵](project-docs/roadmap.md) · [작업 기록](project-docs/work/README.md)
- [Backend 안내](backend/README.md) · [Frontend 안내](frontend/README.md)
