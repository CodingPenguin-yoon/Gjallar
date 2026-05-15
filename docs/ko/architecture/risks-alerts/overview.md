# Risks / Alerts Architecture

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Risks/Alerts architecture](../../../architecture/risks-alerts/overview.md), [Risks/Alerts snapshot](../../../current/top-tabs/07-risks-alerts.md), [Current implemented state](../../../current/README.md).

Risks/Alerts는 `/risks` route의 read-only view입니다. 현재는 job status records에서 파생된 risks를 보여줍니다.

## Current route and implementation

| Concern | Current implementation |
|---|---|
| Route | `/risks` |
| Component | [OperationalRiskDashboard.jsx](../../../../frontend/src/components/OperationalRiskDashboard.jsx) |
| View model | [risksScreen.js](../../../../frontend/src/utils/risksScreen.js), `buildRisksViewModel()` |
| Backend source | `GET /api/v1/risks` in [router.py](../../../../backend/app/api/v1/router.py) |
| Mutation controls | None |

## Current risk shape

Rows include `risk_id`, `job_id`, `job_type`, `job_status`, `level`, `code`, `message`, `detail`, `artifacts_url`. Frontend는 red, yellow, unknown, green 순으로 정렬합니다.

Current risk source는 주로 Create VM preflight/plan입니다. Red risk는 approval/create를 막고 yellow risk는 acknowledgement가 필요할 수 있습니다.

## Not a standalone engine

현재 Risks/Alerts는 Proxmox를 독립 polling하지 않고, DRS policy를 평가하지 않으며, alert lifecycle을 저장하지 않고, remediation을 실행하지 않습니다.

## Target blockers

DRS target에는 `identity_mismatch`, `unclassified_vm`, `metadata_incomplete`, `policy_restricted`, `policy_blocked`, `route_unknown`, `route_blocked`, `stale_lock`, `migration_timeout`, `needs_reconciliation` 같은 blocker taxonomy가 필요합니다.
