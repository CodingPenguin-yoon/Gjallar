# Gjallar

[English](README.md) · **한국어**

**Proxmox의 VM·템플릿·모니터링·복구를 하나의 웹에서 관리합니다.**

갈랴르는 Proxmox VE를 위한 웹 운영 도구입니다. 자원 조회부터 변경 검토, 실행, 결과 확인까지 연결합니다. 실제 실행과 상태의 기준은 Proxmox이며, 갈랴르는 계정·승인·작업 이력·복구 기록을 관리합니다.

> **개발 중입니다.** 아래 기능은 현재 코드에 구현돼 있습니다. 기능과 지원 환경마다 실환경 검증 범위가 다르며, 구현이 모든 운영 흐름의 검증 완료를 뜻하지는 않습니다. 아래 검증 현황과 [로드맵](project-docs/roadmap.md)을 함께 확인하세요.

## 현재 구현된 기능

웹은 전체 현황·VM 관리·템플릿·모니터링·인프라·작업 이력의 여섯 영역으로 구성됩니다. 계정과 세션 관리는 계정 메뉴에서 접근합니다.

| 영역 | 현재 구현 |
|---|---|
| 설치·연결 | 관리형 Docker Compose 설치, 서비스 시작·상태·종료, DB schema가 같은 이미지로 업데이트. 웹에서 Proxmox 전용 토큰 발급 또는 기존 토큰 등록·검증·활성화 |
| 전체 현황·자원 조회 | 클러스터 요약, 노드 비교·상세, VM·템플릿·스토리지·네트워크 조회. 새 연결은 개별 자원 ID 입력 없이 현재·미래 자원을 발견하며, 허용할 변경 작업은 별도 선택 |
| VM 생성·전원 | 기존 Proxmox 템플릿 복제, 사양 직접 입력 또는 선택적 프리셋, 계획 검토·승인, 선택적 부팅과 guest agent·IP·cloud-init 확인. 결과 검증을 거치는 시작·정상 종료 |
| VM 설정 | 지원 조건에 맞는 정지 VM의 CPU 코어·메모리 변경, NFS `scsi0` 디스크 확장, 기존 NIC의 bridge·VLAN 변경, 원본·보존 자원을 확인하는 full clone·명시적 삭제 |
| 웹 콘솔 | 실행 중인 QEMU VM의 인증된 noVNC 화면 콘솔, 명시적 연결·종료 |
| 템플릿 | 준비된 정지 VM의 템플릿 전환, 고정된 AlmaLinux 9.8 GenericCloud x86_64 카탈로그 기반 제작, 소유 템플릿·업로드 원본의 명시적 정리, 테스트 배포 검사와 운영자가 확인한 접속 결과 기록 |
| 모니터링 | 노드·VM·스토리지 현재 지표, hour/day/week/month/year PVE 추이, 임계 초과·해제 구간, 작업 실패·복구 이력, 위험·준비 상태·용량·배치 Insights |
| 백업·복원 | 백업 목록 조회와 지원하는 정지 VM의 명시적 NFS 백업, 별도 VMID로 NIC 연결을 끊은 상태의 복원, 원본 보존·설정·후속 부팅/guest agent 관찰 검사 |
| 유지보수·호스트 설정 | 공유 NFS를 사용하는 지원 정지 VM의 수동 노드 이동, 노드 유지보수 준비 보고서, 기존 directory storage 등록·수정, 제한된 VM용 Linux bridge 생성·수정과 노드 전체 네트워크 반영 |
| 작업·계정 | Operation 상태·이벤트·증거·생성 이력·지원 작업의 복구 관찰, 외부 실행 방식 Guided `qm unlock`, 로컬 로그인·세션·`viewer`/`operator`/`admin` 권한 |

기능별 상세 지원 조건과 실행 절차는 [아키텍처](project-docs/architecture.md)와 [운영 Runbook](project-docs/development.md)에서 관리합니다.

## 검증 현황과 지원 제한

기록된 실환경 검증에는 macOS 관리형 설치, 기존 토큰 등록, 전체 클러스터 조회, 템플릿 기반 생성과 부팅·DHCP·guest agent·cloud-init 확인, 전원 작업, CPU·메모리 변경, 디스크 확장, NIC 변경, full clone, 삭제, 콘솔 연결·종료가 포함됩니다. 모니터링도 실제 PVE 지표·이력과 대조했습니다. 특정 환경과 대상을 확인한 결과이며 모든 지원 조합의 검증 완료를 뜻하지 않습니다.

템플릿 전환·이미지 제작·정리, 백업 생성·복원, 정지 VM 노드 이동, 호스트 storage·bridge 변경은 실제 변경 검증이 남아 있습니다. 신규 Proxmox 로그인·토큰 발급과 나머지 설치·인증 조합도 추가 검증이 필요합니다. 콘솔 연결 확인은 게스트 로그인 성공을 뜻하지 않으며, 실제 SSH 로그인과 일부 알림 발생·해제/복구 사례도 미검증입니다. 근거와 남은 작업은 [로드맵의 진행 상태](project-docs/roadmap.md#진행-상태)를 따릅니다.

- 제품 업무는 웹에서 수행합니다. 로컬 `gjallar` 도구는 `bootstrap`, `service start/status/stop`, `upgrade`만 유지하며 사용자 CLI·TUI 작업은 제거했습니다.
- VM 생성에는 기존 Proxmox 템플릿이 필요합니다. ISO 설치와 빈 VM 생성은 지원하지 않습니다.
- 설정 변경·복제·백업·복원·이동은 지정된 VM·스토리지·네트워크 조합을 지원합니다. 디스크 축소, 실행 중 hotplug, live migration, 자동 DRS는 현재 범위에 포함하지 않습니다.
- 모니터링은 요청 시 PVE 관찰·이력을 읽습니다. 별도 시계열 저장소·상시 collector·외부 알림 발송은 제공하지 않습니다.
- 복원은 원본 VM과 백업을 보존하고 새 VM을 NIC 연결이 끊긴 정지 상태로 둡니다. 부팅·접속 확인은 별도 단계입니다.
- 호스트 설정은 기존 directory storage와 VM용 Linux bridge로 제한합니다. 관리망 IP·gateway 변경, 물리 NIC 재배치, 디스크 포맷, Ceph 관리는 지원하지 않습니다.

### 실제 상태와 결과를 구분합니다

- Proxmox 연결이 없거나 실패하면 그대로 표시합니다. 실제 환경의 조회 실패를 가짜 데이터로 대체하지 않습니다.
- 일부만 관찰된 경우에도 확인된 데이터와 한계를 함께 표시합니다. Create 입력·검토는 partial base snapshot에서도 가능하며, 실행에는 source별·action별 추가 검사가 적용됩니다.
- 복구 관찰은 Proxmox 상태를 다시 조회하고 로컬 기록을 정합화합니다. 원래 변경을 무작정 재실행하지 않습니다. 백그라운드 복구 관찰은 기본 비활성입니다.
- 모니터링은 Proxmox 관찰과 제공 이력을 사용하며 별도 시계열 저장소를 운영하지 않습니다. VM 실행 상태만으로 내부 애플리케이션의 정상 동작을 보장하지 않습니다.

## 현재 애플리케이션 실행하기

관리형 bootstrap 설치 도구를 제공합니다. 의존성 설치, 환경 설정, PostgreSQL 초기화와 계정 생성은 [운영 Runbook](project-docs/development.md)을 따릅니다.

### 관리형 설치

Python 설치 도구가 Docker Compose로 앱과 PostgreSQL을 실행합니다. Python **3.13 이상**, Docker, Compose **2.20 이상**, 이 저장소에서 빌드한 앱 이미지가 필요합니다. 공개 release registry와 서명된 배포 manifest는 아직 제공하지 않습니다.

Runbook의 [설치 도구 준비](project-docs/development.md#설치-도구-준비와-웹-접속)와 [새 설치 절차](project-docs/development.md#새-로컬-설치-별도-실행-승인검증-대상)를 사용합니다. 기본 웹 바인딩은 loopback이며, 다른 컴퓨터에서 접속할 신규 설치에는 `--bind-address 0.0.0.0`을 명시할 수 있습니다. DB port는 외부에 공개하지 않으며 TLS proxy는 별도 구성합니다.

관리형 설치는 초기화를 명시적으로 분리합니다. 일반 서비스 시작은 migration이나 관리자 재생성을 수행하지 않습니다. `upgrade`는 DB schema가 같은 이미지 사이에서만 전환하며 기존 DB migration은 Runbook의 별도 절차를 따릅니다.

설치 후 브라우저에서 로그인하고 **인프라 → Proxmox 연결**에서 연결을 등록합니다. 사용할 작업을 선택하고 검증·활성화한 뒤 Runbook에 따라 모든 갈랴르 서버 프로세스를 재시작합니다. 기존 환경 변수 기반 Proxmox 연결도 지원합니다.

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

Runbook의 container 절차를 따릅니다. 기존 수동 배포용 container entrypoint는 시작 시 migration·프리셋 seed·선택적 관리자 bootstrap을 수행하며 관리형 서비스 시작과 동작이 다릅니다. 기존 설치의 DB에 연결하기 전에는 기존 DB 적용 절차를 확인합니다.

## 개발과 검증

React frontend, FastAPI backend, PostgreSQL/Alembic 저장 계층과 Proxmox API adapter로 구성됩니다.

| 위치 | 역할 |
|---|---|
| `frontend/` | 웹 인터페이스 |
| `backend/app/` | API, 관찰, 작업 실행과 Proxmox 연동 |
| `backend/alembic/` | DB migration |
| `backend/tests/` | Backend·계약·통합 테스트 |
| `client/` | 로컬 설치·서비스 도구와 테스트, 기존 package 경로 유지 |
| `project-docs/` | 제품·개발 공동 기준 문서 |

설치 도구·backend·frontend 개발 의존성 설치 후 로컬 검증:

```bash
pnpm run verify
```

설치 도구·backend 테스트, frontend 테스트, ESLint, frontend production build를 실행합니다. PostgreSQL 통합 검사는 Runbook에 따라 별도의 폐기 가능한 테스트 DB를 준비해야 합니다.

Docker를 사용할 수 있는 환경에서 container 기준 검증:

```bash
pnpm run verify:container
```

설치 도구·backend 테스트 이미지와 production image를 빌드합니다. 앱 서비스 기동이나 실제 Proxmox 변경은 포함하지 않습니다.

## 문서

상세 프로젝트 문서는 현재 한국어로 관리합니다.

- [문서 홈](project-docs/README.md)
- [제품 방향과 범위](project-docs/prd.md)
- [현재 아키텍처](project-docs/architecture.md)
- [설치·운영·장애 대응](project-docs/development.md)
- [로드맵](project-docs/roadmap.md) · [작업 기록](project-docs/work/README.md)
- [Backend 안내](backend/README.md) · [Frontend 안내](frontend/README.md)
