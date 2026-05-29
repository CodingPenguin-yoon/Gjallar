# Placement / DRS Advisor

평가일: 2026-05-28

검증 기준: 2026-05-27에 backend `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests` -> 182 passed, 33 warnings, 29 subtests passed, frontend `node --test frontend/tests/*.mjs` -> 13 passed, `pnpm --dir frontend lint` -> passed, `pnpm --dir frontend build` -> passed, `git diff --check` -> passed를 기록했다.

## 구현 수준

현재 `/drs`는 read-only DRS Advisor recommendation seed와 safe execution readiness foundation이다. Backend DRS read model, DB-backed VM identity/fingerprint observation, migration policy memory, DB-backed operation lock lookup, read-only final pre-check contract가 구현되어 있지만 live migration execution flow는 구현되어 있지 않다.

## 구현 API/endpoints

DRS Advisor Phase 1 backend endpoint는 다음 `/api/v1` 조회를 제공한다.

- `GET /api/v1/drs/summary`
- `GET /api/v1/drs/recommendations`
- `GET /api/v1/drs/recommendations/{recommendation_id}`
- `POST /api/v1/drs/recommendations/{recommendation_id}/check`

모든 recommendation과 final pre-check result는 `read_only=true`, `executable=false`, `allowed_actions=[]`다. `/check`는 current inventory를 다시 읽고 `would_be_executable`을 계산하지만 실제 execution은 항상 닫혀 있다.

## 관련 파일

- Frontend: [frontend/src/components/DrsAdvisorScreen.jsx](../../../frontend/src/components/DrsAdvisorScreen.jsx), [frontend/src/utils/drsAdvisor.js](../../../frontend/src/utils/drsAdvisor.js), [frontend/src/services/apiV1.js](../../../frontend/src/services/apiV1.js), [frontend/src/App.jsx](../../../frontend/src/App.jsx)
- Backend: [backend/app/api/v1/router.py](../../../backend/app/api/v1/router.py), [backend/app/drs/advisor.py](../../../backend/app/drs/advisor.py), [backend/app/drs/identity.py](../../../backend/app/drs/identity.py), [backend/app/drs/operation_locks.py](../../../backend/app/drs/operation_locks.py), [backend/app/proxmox/inventory.py](../../../backend/app/proxmox/inventory.py), [backend/app/proxmox/models.py](../../../backend/app/proxmox/models.py), [backend/app/db/models.py](../../../backend/app/db/models.py)
- Tests: [frontend/tests/drsAdvisor.test.mjs](../../../frontend/tests/drsAdvisor.test.mjs), [frontend/tests/appNavigation.test.mjs](../../../frontend/tests/appNavigation.test.mjs), [backend/tests/contracts/test_api_v1_drs.py](../../../backend/tests/contracts/test_api_v1_drs.py), [backend/tests/drs/test_identity_resolution.py](../../../backend/tests/drs/test_identity_resolution.py), [backend/tests/drs/test_advisor_readiness.py](../../../backend/tests/drs/test_advisor_readiness.py), [backend/tests/db/test_drs_identity_schema.py](../../../backend/tests/db/test_drs_identity_schema.py), [backend/tests/proxmox/test_inventory_adapter.py](../../../backend/tests/proxmox/test_inventory_adapter.py)

## 현재 구현

`loadDrsAdvisorModel`은 DRS summary/recommendation endpoints를 읽고 backend에서 계산된 node pressure와 imbalance candidate를 표시한다. source pressure가 높고 target 여유가 있으면 candidate를 만든다.

현재 recommendation은 CPU/Memory current usage, bridge evidence, storage evidence, red risk exclusion, VM identity evidence, migration policy evidence를 사용한다. execution은 `available: false`, `readOnly: true`, `allowedActions: []`다.

VM identity foundation은 Proxmox inventory에서 SMBIOS UUID, VM generation ID, MAC addresses, disk volume IDs만 curated fingerprint evidence로 사용한다. node, VMID, name은 locator/supporting evidence이며 이것만으로 high confidence identity가 되지 않는다. Low/medium/unknown identity는 execution-blocking이고, policy는 high confidence identity 뒤에서만 의미 있게 평가된다.

Migration policy default는 `unknown`이며 execution-blocking이다. Canonical blockers는 `vm_identity_unknown`, `vm_identity_uncertain`, `migration_policy_unknown`, `migration_policy_restricted`, `migration_policy_blocked`, `drs_final_precheck_failed`를 사용하고, compatibility blockers such as `identity_unknown`, `metadata_missing`, `policy_unknown`, `final_precheck_not_run`도 필요한 곳에 남아 있다.

`operation_locks`는 `drs_migration` operation type만 다루는 Gjallar-local table이며 `/check`는 VM identity, Proxmox locator, route scope를 조회한다. `active`, `stale`, `reconciliation_required` lock은 `would_be_executable=false`로 막고, `released` lock은 막지 않는다. `/check`는 lock row를 생성/갱신/해제하지 않는다.

Read-only Proxmox conflict evidence는 현재 VM config의 curated `lock` 값만 지원한다. Config lock이 관찰되면 `vm_config_lock` blocker가 추가된다. Active task, HA state, cluster health/quorum evidence는 현재 adapter에서 수집하지 않으며 `not_collected`로 명시된다.

화면은 review model only notice를 표시하고, identity/policy evidence를 compact하게 표시한다. migration 실행 버튼은 제공하지 않는다.

## DRS Advisor 기준 gaps

[DRS recommendation/execution 목표](../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md) 대비 live migration execution authority가 없다. 15분 average/peak metric substrate, active task evidence, HA/quorum evidence, approval packet, migration job, UPID tracking, post-check, lock acquisition/release, reconciliation은 아직 구현되어 있지 않다.

Confirm modal, Proxmox live migration, UPID tracking, post-check, reconciliation이 없다.

## 리스크/메모

현재 DRS recommendation은 seed일 뿐 execution 판단이 아니다. `/check`는 read-only final pre-check model이며, operation lock과 config-lock conflict evidence를 조회하지만 `executable=false`, `allowed_actions=[]`를 유지한다.

## 다음 구현 slice

다음 slice는 approval packet and migration job substrate를 추가하되, Proxmox live migration mutation은 별도 승인/UPID/reconciliation 흐름이 준비될 때까지 열지 않는 것이다.
