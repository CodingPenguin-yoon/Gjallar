# Operations / Risks

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Operations / Risks snapshot](../../../current/top-tabs/07-risks-alerts.md), [영어 Risks/Alerts architecture](../../../architecture/risks-alerts/overview.md), [Current implemented state](../../../current/README.md).

Operations / Risks는 canonical `/operations/risks` route의 read-only risk projection 화면이며 legacy `/risks` deep link도 같은 화면을 렌더링합니다. 현재는 job status에 기록된 risks를 펼쳐 보여줍니다.

## 사용하는 API와 호출 위치

| API | 하는 일 | Frontend 호출 |
|---|---|---|
| `GET /api/v1/risks` | job status의 `risks` 배열을 risk rows로 반환 | [frontend/src/components/OperationalRiskDashboard.jsx](../../../../frontend/src/components/OperationalRiskDashboard.jsx), [risksScreen.js](../../../../frontend/src/utils/risksScreen.js) |

Backend 구현은 [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py)의 risk endpoint와 [backend/app/jobs/runs.py](../../../../backend/app/jobs/runs.py)의 job listing을 사용합니다.

## 구현 방식

Backend는 job records의 risk dict를 risk summary로 변환합니다. Row에는 `risk_id`, `job_id`, `job_type`, `job_status`, `level`, `code`, `message`, `detail`, `artifacts_url`이 들어갑니다. Frontend는 severity를 red, yellow, unknown, green 순으로 정렬합니다.

현재 주요 risk source는 Create VM preflight/plan입니다. 예: unknown profile, hardware limit 위반, template readiness 부족, storage/bridge/IP 문제, IaC readiness blocker, SSH key 문제 등입니다.

## 현재 하지 않는 일

Operations / Risks는 standalone alert engine이 아닙니다. Proxmox를 독립 polling하지 않고, DRS policy를 평가하지 않으며, alert lifecycle acknowledge/resolve를 저장하지 않습니다.

## Target gap

DRS Advisor에는 identity mismatch, unclassified VM, metadata incomplete, policy blocked/restricted, route unknown/blocked, stale lock, migration timeout, needs_reconciliation 같은 blocker taxonomy가 필요합니다. Identity Mismatch와 route Unknown은 warning처럼 취급하면 안 됩니다.
