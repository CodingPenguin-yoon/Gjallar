# Top Tab Implementation Status

평가일: 2026-05-13

이 폴더는 현재 상단 탭별 구현 상태를 기록한다. 제품 방향의 최종 기준은 [DRS Advisor PRD](../../prd/drs-advisor/README.md)이며, 구현 baseline은 [current status](../current.md)를 따른다. 충돌 시 `docs/product/prd/drs-advisor/`가 제품 방향에서 우선하고, 과거 숫자형 PRD는 목표 또는 stale 문맥일 수 있다.

검증 기준: 2026-05-13에 backend `PYTHONPATH=backend pytest -q backend/tests` -> 100 passed, frontend `node --test frontend/tests/*.mjs` -> 11 passed, `pnpm --dir frontend lint` -> passed, `pnpm --dir frontend build` -> passed를 기록했다.

## 탭별 문서

- [Dashboard](01-dashboard.md)
- [Infra Explorer](02-infra-explorer.md)
- [Networks](03-networks.md)
- [Create VM](04-create-vm.md)
- [Placement / DRS Advisor](05-placement-drs-advisor.md)
- [Jobs/Runs](06-jobs-runs.md)
- [Risks/Alerts](07-risks-alerts.md)

## 전체 요약

현재 active UI route는 [frontend/src/App.jsx](../../../../frontend/src/App.jsx)의 `Dashboard`, `Infra Explorer`, `Networks`, `Create VM`, `Placement`, `Jobs/Runs`, `Risks/Alerts`다. active backend prefix는 [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py)의 `/api/v1`이다.

구현 baseline은 read-only Proxmox inventory, Dashboard aggregation, Infra Explorer, Networks bridge/policy view, read-only Placement seed, file-backed Jobs/Runs, job-derived Risks/Alerts, 그리고 Create VM supporting capability다.

DRS Advisor는 목표 제품 방향이다. 아직 backend DRS recommendation API, `/api/v1/drs/*`, identity/fingerprint DB model, 15분 average/peak metric substrate, final pre-check, approval-gated live migration, UPID tracking, operation lock, reconciliation은 구현되어 있지 않다.

Create VM은 강한 보조 capability지만 MVP success line이 아니다. 현재 active 생성 경로는 Terraform이 아니라 Proxmox API native create다. `execute`는 manifest commit-only이고, 실제 생성은 `proxmox-create`가 clone UPID polling, 필요한 boot disk resize, config, stopped post-check, `observed_after` artifact를 끝낸 뒤에만 applied로 기록한다. Terraform plan/apply는 optional/deprecated legacy executor로 남아 있고 active UI에서는 호출하지 않는다. first power-on과 smoke는 deferred다.
