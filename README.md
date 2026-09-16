# Gjallar

Gjallar는 Proxmox의 VM과 클러스터 상태를 관찰하고, 위험과 원인을 설명하며, 필요한 작업의 실행 결과를 검증하는 **Observe-first Operations Intelligence with Verified Actions**입니다.

Proxmox가 VM·node·task의 실제 상태와 실행을 소유합니다. Gjallar는 관찰 출처·시점, 운영 맥락, 작업 의도와 검증 증거를 연결합니다.

- 현재 구현 확인일: `2026-09-07`
- 기술 구성: React SPA, FastAPI, PostgreSQL/Alembic, Proxmox VE API
- 기준 runtime: Python `3.13`, Node.js `24`, pnpm `10.34.5`

## 현재 제공 기능

| 영역 | 현재 동작 |
|---|---|
| Overview · Workloads | 클러스터·node·VM·template·storage·network 관찰, VM 상세와 최근 작업 연결 |
| Insights | Risks, VM readiness, Capacity, Placement의 원인·근거·관찰 상태 설명 |
| Create VM | DB profile과 기존 Proxmox template을 선택하고 검토·승인 후 복제, disk 확장·설정, 선택적 부팅·검증 |
| VM lifecycle | acknowledgement와 idempotency를 요구하는 Start, 강제 종료 fallback 없는 graceful Shutdown |
| Guided `qm unlock` | 제한된 명령 안내, 사용자의 외부 실행 사실 기록, Proxmox API로 결과 검증 |
| Operations | 공통 작업 목록·event timeline, Job history, 네 action의 GET-only recovery |
| Account · Users & sessions | local user/session, `viewer < operator < admin` 권한과 계정 관리 |

실제 Proxmox inventory가 있으면 `PARTIAL` 상태에서도 정상적으로 관찰된 데이터를 표시합니다. Create VM 화면과 VM 생성·시작·종료는 complete `LIVE`를 요구합니다. snapshot이 없으면 관련 화면에 연결 안내를 표시하며, Operations·저장된 risk·계정 화면은 자체 데이터와 권한에 따라 유지됩니다. product runtime은 fake inventory로 대체하지 않습니다.

Recovery는 Create VM, Start, Shutdown, Guided `qm unlock`을 지원합니다. background runner는 기본 비활성이며, 허용된 작업은 Operation 상세에서 다시 관찰할 수 있습니다. recovery는 Proxmox GET과 로컬 기록 정리만 수행하고 원래 mutation이나 명령을 다시 실행하지 않습니다.

현재 VM 생성은 **기존 template 복제만 지원**합니다. ISO 설치, 빈 VM 생성, DRS·VM migration, 자동 remediation, arbitrary shell/SSH 실행은 제공하지 않습니다. 독립 Network readiness 화면은 제거됐고 network inventory와 생성 전 network 검토는 유지합니다.

## 합의한 다음 방향

현재 단계의 생성 범위는 template 복제로 유지합니다. template을 먼저 선택하는 폼, 선택적 profile, 검토 단계의 DB 쓰기와 중복 저장 축소를 후속 방향으로 합의했습니다. **현재 코드는 여전히 DB profile과 기존 request/Jobs/Operation 저장 구조를 사용합니다.** 결정과 미구현 범위는 [ADR-008](project-docs/decisions/adr-008-template-based-create-and-persistence-simplification.md)에서 구분합니다.

## 시작하기

처음 실행할 때는 [운영 Runbook](project-docs/operations/runbook.md)의 환경 준비·DB 초기화·계정 생성 절차를 따릅니다. 준비된 로컬 환경에서는 저장소 root에서 실행합니다.

```bash
pnpm run dev
```

기본 접속 주소는 frontend `http://127.0.0.1:5173`, backend `http://127.0.0.1:8000`입니다. Docker 시작 시 migration·profile seed·선택적 admin bootstrap이 수행되므로 기존 DB 적용 절차도 Runbook에서 확인합니다.

## 문서

공동 기준 문서는 [문서 홈](project-docs/README.md)에서 목적별로 찾습니다.

- [현재 구조](project-docs/architecture/overview.md) · [API 계약](project-docs/api/current-api-v1.md) · [DB와 소유권](project-docs/database/current-schema-and-ownership.md)
- [실행·검증·장애 대응](project-docs/operations/runbook.md)
- [결정 기록](project-docs/decisions/README.md) · [구현 계획과 이력](project-docs/plans/README.md)
- [Backend 안내](backend/README.md) · [Frontend 안내](frontend/README.md)

과거 Plan과 [live-smoke evidence](project-docs/evidence/legacy-live-smoke/README.md)는 당시의 구현·검증 기록입니다. 현재 동작이나 새 live 작업의 승인으로 해석하지 않습니다.
