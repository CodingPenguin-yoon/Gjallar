# Gjallar Frontend

Gjallar의 React + Vite 운영 UI입니다. `/api/v1`의 상태·근거·허용된 action을 표시하며 cookie-based auth를 사용합니다.

- 현재 구현 확인일: `2026-09-07`
- 기준 runtime: Node.js `24`, pnpm `10.34.5`
- 전체 안내: [문서 홈](../project-docs/README.md)

## 현재 화면

| 영역 | canonical route | 현재 기능 |
|---|---|---|
| Overview | `/` | cluster summary와 dashboard |
| Workloads · Inventory | `/instances`, `/instances/:vmid` | VM inventory·대상 상세와 gated Start/Shutdown |
| Create VM | `/instances/create` | DB profile·template 선택부터 검토·승인·복제 생성까지의 wizard |
| Insights | `/insights` 및 category route | risk/readiness/capacity/placement의 finding과 evidence |
| Operations · All operations | `/operations`, `/operations/:operationId` | 공통 작업 목록·상세 evidence timeline·recovery 관찰 |
| Guided `qm unlock` | `/operations/guided-qm/vm-unlock` | 제한된 명령 안내·attestation·API verification |
| Job history | `/operations/jobs` | 기존 job projection 조회 |
| Risks | `/operations/risks` | 기존 job-derived risk 조회용 호환 경로 |
| Account | `/settings/account` | 계정과 password 변경 |
| Users & sessions | `/settings/admin/users` | admin-only user/session 관리 |

Workloads 하위 메뉴는 Inventory와 Create VM입니다. Insights는 Summary, Risks, VM readiness, Capacity, Placement이며 `/insights`, `/insights/risks`, `/insights/readiness`, `/insights/capacity`, `/insights/placement`로 연결됩니다. Operations는 All operations와 Job history를 제공하며 Guided `qm unlock`은 목록 상단 버튼과 VM 문맥에서 진입합니다. Settings는 Account와 admin 전용 Users & sessions를 제공하고, Account만 사용할 수 있으면 하위 메뉴를 생략합니다.

독립 Network readiness 화면은 제거됐습니다. `/instances/networks`와 `/networks`는 로그인 후 `/instances`로 redirect하며 network inventory API, Create VM network preflight와 Insights의 VM readiness는 유지합니다. 그 밖의 지원되는 legacy deep-link alias도 별도 폐기 결정 전 유지합니다.

## 상태와 실행 경계

Overview와 Workloads inventory·VM 상세는 authoritative inventory가 있으면 partial observation에서도 확인할 수 있습니다. snapshot이 없는 `unconfigured`/`degraded`에서는 Workloads navigation을 숨기고 관련 direct route에 연결 안내를 표시합니다. Create VM 화면은 complete `live` observation을 요구하며 VM mutation에는 `operator+` 권한도 필요합니다.

Insights는 저장된 risk와 inventory source별 unknown/unavailable을 구분합니다. Operations, Job history, legacy Risks, Account, Users & sessions도 기존 권한에 따라 사용할 수 있습니다. 내장 mock/demo inventory와 DRS 실행 화면은 없습니다.

Operation 상세에는 intent/plan digest, checksum-linked event, target lock, 네 action의 recovery와 Create readiness evidence를 표시합니다. backend가 허용한 `다시 관찰`만 operator/admin에게 제공하며, 이 기능은 원래 생성·시작·종료·명령을 재실행하지 않습니다. background recovery는 기본 비활성입니다.

현재 생성은 기존 template clone 전용이고 DB profile 선택이 필요합니다. template 우선 폼·선택적 profile·검토 단계 저장 축소는 [ADR-008의 합의한 후속 방향](../project-docs/decisions/adr-008-template-based-create-and-persistence-simplification.md)이며 현재 화면에 구현된 기능과 구분합니다.

## 코드와 실행

`src/app`은 route·navigation·전역 gate, `pages`는 화면 조합, `features`는 기능 흐름, `entities`와 `shared`는 공통 model·API·UI를 맡습니다. `components`, `utils`와 일부 compatibility export에는 기존 Create/Jobs/Admin 코드가 남아 있습니다. 상세 경계는 [현재 아키텍처](../project-docs/architecture/overview.md)를 봅니다.

환경 준비와 검증은 [운영 Runbook](../project-docs/operations/runbook.md)을 따릅니다. 준비된 환경에서는 저장소 root에서 `pnpm run frontend`를 실행합니다. Vite는 root·frontend env를 읽고 `/api`를 `VITE_BACKEND_URL` 또는 `BACKEND_PORT`의 backend로 proxy합니다. API client는 cookie session을 위해 credentials를 포함합니다.

frontend test는 `tests/*.mjs`를 순서대로 실행하며 일부는 source contract 검사입니다. production Docker build는 frontend test·lint·build를 수행한 뒤 `dist`를 FastAPI image에 포함합니다. 문서의 검증 명령 목록은 해당 검사를 현재 실행했다는 뜻이 아닙니다.

UI는 backend의 role·freshness·executability·evidence 의미를 보존합니다. canonical route와 API 계약은 [현재 API 문서](../project-docs/api/current-api-v1.md)를, 변경·승인 경계는 [프로젝트 프로필](../project-docs/project-profile.md)을 따릅니다.
