# Placement / DRS Advisor

평가일: 2026-05-31

검증 기준: 2026-05-31에 backend focused DRS/API/DB validation `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/db` and frontend focused validation `node --test frontend/tests/drsAdvisor.test.mjs frontend/tests/apiV1Client.test.mjs frontend/tests/authFlow.test.mjs`를 통과했다.

## 구현 수준

현재 `/drs`는 DRS Advisor recommendation/check, manual VM policy configuration, local approval packet/job intent creation, safe execution readiness foundation, first narrow approval-gated live migration execution slice, and backend post-check/reconciliation slice다. Backend DRS read model, DB-backed VM identity/fingerprint observation, manual migration policy memory/audit events, operation lock lookup/acquisition/release, read-only final pre-check contract, local approval packet/job intent substrate, dedicated DRS Proxmox migration client, UPID/task metadata persistence, verified post-check completion, reconciliation events, and read-only Reconcile preview가 구현되어 있다. Automatic DRS, bulk migration, corrective reconciliation mutation, background reconciliation automation, live DRS smoke evidence, and live execute/corrective reconcile UI는 구현하지 않았다.

## 구현 API/endpoints

DRS Advisor backend endpoint는 다음 `/api/v1` 조회, local evidence, and narrow operator execution endpoint를 제공한다.

- `GET /api/v1/drs/summary`
- `GET /api/v1/drs/recommendations`
- `GET /api/v1/drs/recommendations/{recommendation_id}`
- `POST /api/v1/drs/recommendations/{recommendation_id}/check`
- `GET /api/v1/drs/policies`
- `GET /api/v1/drs/policies/{vm_identity_id}`
- `PUT /api/v1/drs/policies/{vm_identity_id}`
- `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets`
- `POST /api/v1/drs/migration-jobs/{job_id}/execute`
- `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview`

모든 recommendation과 final pre-check result는 `read_only=true`, `executable=false`, `allowed_actions=[]`다. `/check`는 current inventory를 다시 읽고 `would_be_executable`을 계산하지만 mutation authority는 제공하지 않는다.

`/drs/policies`는 current non-template VM의 policy coverage를 `vm_identity_id` 기준으로 표시한다. `PUT /drs/policies/{vm_identity_id}`는 operator-only Gjallar-local manual update이며 `expected_observation` guard, `policy_change_acknowledged=true`, trusted session actor, and audit event row를 요구한다. `allowed`는 DRS prerequisite only이고 migration approval이 아니다. `unknown`, `restricted`, `blocked`는 계속 DRS-blocking이다.

`/approval-packets`는 operator-only local evidence endpoint다. Passing final pre-check, high-confidence identity, allowed migration policy, no open operation lock, and warning acknowledgement gates are required before it writes a compact approval packet and pending `drs_migration` job intent. It does not call Proxmox mutation APIs; the job intent remains `runnable=false`, `proxmox_mutation_enabled=false`, and `side_effects=[]`.

`/migration-jobs/{job_id}/execute`는 operator-only execution endpoint다. It loads stored `DrsMigrationJobRecord` + `DrsApprovalPacketRecord`, rejects missing/stale/cancelled/already-executed bindings, reruns a fresh advisor final pre-check, collects live Proxmox evidence through the dedicated DRS client, transactionally acquires VM identity, Proxmox locator, and route operation locks, and only then POSTs Proxmox QEMU migrate. It does not expose recommendation aliases such as `/migrate` or `/live-migrate`.

## 관련 파일

- Frontend: [frontend/src/components/DrsAdvisorScreen.jsx](../../../frontend/src/components/DrsAdvisorScreen.jsx), [frontend/src/utils/drsAdvisor.js](../../../frontend/src/utils/drsAdvisor.js), [frontend/src/services/apiV1.js](../../../frontend/src/services/apiV1.js), [frontend/src/App.jsx](../../../frontend/src/App.jsx)
- Backend: [backend/app/api/v1/router.py](../../../backend/app/api/v1/router.py), [backend/app/drs/advisor.py](../../../backend/app/drs/advisor.py), [backend/app/drs/policies.py](../../../backend/app/drs/policies.py), [backend/app/drs/approval.py](../../../backend/app/drs/approval.py), [backend/app/drs/execution.py](../../../backend/app/drs/execution.py), [backend/app/drs/identity.py](../../../backend/app/drs/identity.py), [backend/app/drs/operation_locks.py](../../../backend/app/drs/operation_locks.py), [backend/app/proxmox/drs_migration.py](../../../backend/app/proxmox/drs_migration.py), [backend/app/proxmox/inventory.py](../../../backend/app/proxmox/inventory.py), [backend/app/proxmox/models.py](../../../backend/app/proxmox/models.py), [backend/app/db/models.py](../../../backend/app/db/models.py)
- Tests: [frontend/tests/drsAdvisor.test.mjs](../../../frontend/tests/drsAdvisor.test.mjs), [frontend/tests/apiV1Client.test.mjs](../../../frontend/tests/apiV1Client.test.mjs), [frontend/tests/authFlow.test.mjs](../../../frontend/tests/authFlow.test.mjs), [backend/tests/contracts/test_api_v1_drs.py](../../../backend/tests/contracts/test_api_v1_drs.py), [backend/tests/drs/test_policy_management.py](../../../backend/tests/drs/test_policy_management.py), [backend/tests/drs/test_identity_resolution.py](../../../backend/tests/drs/test_identity_resolution.py), [backend/tests/drs/test_advisor_readiness.py](../../../backend/tests/drs/test_advisor_readiness.py), [backend/tests/drs/test_execution.py](../../../backend/tests/drs/test_execution.py), [backend/tests/db/test_drs_identity_schema.py](../../../backend/tests/db/test_drs_identity_schema.py), [backend/tests/proxmox/test_inventory_adapter.py](../../../backend/tests/proxmox/test_inventory_adapter.py), [backend/tests/proxmox/test_mutation_client.py](../../../backend/tests/proxmox/test_mutation_client.py)

## 현재 구현

`loadDrsAdvisorModel`은 DRS summary/recommendation endpoints를 읽고 backend에서 계산된 node pressure와 imbalance candidate를 표시한다. source pressure가 높고 target 여유가 있으면 candidate를 만든다.

현재 recommendation은 CPU/Memory current usage, bridge evidence, storage evidence, red risk exclusion, VM identity evidence, migration policy evidence를 사용한다. execution은 `available: false`, `readOnly: true`, `allowedActions: []`다.

VM identity foundation은 Proxmox inventory에서 SMBIOS UUID, VM generation ID, MAC addresses, disk volume IDs만 curated fingerprint evidence로 사용한다. node, VMID, name은 locator/supporting evidence이며 이것만으로 high confidence identity가 되지 않는다. Low/medium/unknown identity는 execution-blocking이고, policy는 high confidence identity 뒤에서만 의미 있게 평가된다.

Migration policy default는 `unknown`이며 execution-blocking이다. Canonical blockers는 `vm_identity_unknown`, `vm_identity_uncertain`, `migration_policy_unknown`, `migration_policy_restricted`, `migration_policy_blocked`, `drs_final_precheck_failed`를 사용하고, compatibility blockers such as `identity_unknown`, `metadata_missing`, `policy_unknown`, `final_precheck_not_run`도 필요한 곳에 남아 있다.

Manual policy configuration is attached only to Gjallar `vm_identity_id`. The shared policy review modal is used by both `/drs` policy configuration and Infra Explorer VM rows. It shows current locator and observation guard evidence, blocks policy writes for uncertain identities, requires a deliberate policy select, reason, acknowledgement, and does not send actor/source/operator fields from the browser.

`operation_locks`는 `drs_migration` operation type만 다루는 Gjallar-local table이다. `/check`는 VM identity, Proxmox locator, route scope를 조회한다. `active`, `stale`, `reconciliation_required` lock은 `would_be_executable=false`로 막고, `released` lock은 막지 않는다. `/check`는 lock row를 생성/갱신/해제하지 않는다. `/execute`는 mutation 전 같은 세 scope에 active lock을 transactionally 생성하며, acquisition이 막히면 Proxmox mutation을 호출하지 않는다.

DRS readiness output already surfaces reconciliation state through `approval_readiness.lock_evidence` and `approval_readiness.reconciliation`. A `reconciliation_required` operation lock reports matching lock ids and reasons and blocks approval/execution readiness.

Read-only Proxmox conflict evidence는 현재 VM config의 curated `lock` 값만 지원한다. Config lock이 관찰되면 `vm_config_lock` blocker가 추가된다. Active task, HA state, cluster health/quorum evidence는 현재 adapter에서 수집하지 않으며 `not_collected`로 명시된다.

DRS execution does not treat read-only `not_collected` Proxmox evidence as executable. Before mutation, the dedicated DRS client collects active task scan, cluster quorum, HA resource state, and Proxmox migration preconditions. Any unavailable, ambiguous, conflicting, missing, or failing live evidence blocks before mutation.

Local DRS approval packet substrate stores compact checksummed artifacts for exact recommendation evidence, final pre-check evidence, the approval packet, and a pending job intent. Warning acknowledgement fields are represented even though current checks emit no warnings. The `drs_migration` job shape now includes recommendation, final precheck, approval, job intent, operation lock, migration, task poll, and reconciliation stages.

Live migration uses only the dedicated DRS Proxmox client and calls `POST /nodes/{source_node}/qemu/{vmid}/migrate` with `{target: target_node, online: 1}`. Once Proxmox returns a UPID, Gjallar stores it immediately with compact task status/log evidence. Completion requires Proxmox task `OK` plus direct target-node status/config post-check, expected power-state evidence, matching DRS fingerprint, and no conflicting active task. Missing UPID, mutation uncertainty, failed/timeout/ambiguous task evidence, task OK without verified post-check, wrong target, unexpected power state, fingerprint mismatch, or unknown active-task evidence becomes `needs_reconciliation`; locks release only after verified post-check and otherwise become `reconciliation_required`.

`/reconcile-preview` is read-only. It re-reads task and direct post-check evidence and returns whether the job is a verified-completion candidate or still needs reconciliation. It does not run corrective mutation and returns `proxmox_mutation_enabled=false`, `corrective_mutation_enabled=false`, `allowed_actions=[]`, and `side_effects=[]`.

화면은 review model only notice, VM policy configuration panel, and compact identity/policy evidence를 표시한다. Broad migration 실행 UI는 제공하지 않는다.

## DRS Advisor 기준 gaps

[DRS recommendation/execution 목표](../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md) 대비 남은 gap은 15분 average/peak metric substrate, deeper read-only active task/HA/quorum collection, richer policy rule/full metadata editor, corrective reconciliation mutation, background reconciliation workflow, broad execution UI, and live DRS smoke evidence다.

Live execute confirm modal, broad UI execution controls, corrective reconciliation workflow가 없다. 현재 reconciliation surface는 backend read-only preview와 Jobs/Runs/operation-lock evidence에 한정된다.

## 리스크/메모

현재 DRS recommendation은 seed일 뿐 execution 판단이 아니다. `/check`는 read-only final pre-check model이며, operation lock과 config-lock conflict evidence를 조회하지만 `executable=false`, `allowed_actions=[]`를 유지한다. 실제 mutation 판단은 stored approval/job, fresh final pre-check, live Proxmox evidence, and acquired locks가 모두 통과한 `/migration-jobs/{job_id}/execute`에서만 한다.

## 다음 구현

Goal Check 01-06, Goal 7 UI/operations polish, [`Goal 7.5 DRS VM Policy Configuration`](../../goal/goal-07-5-drs-vm-policy-management.md), Goal 8, and Goal 9 are implemented.
Goal 10-12는 candidate/not-started follow-on이다. Goal 10은 사용자가 명시적으로 선택할 때만 다음 planned candidate이며, execute acknowledgement/evidence hardening and optional approved live DRS smoke baseline을 다룬다.
Goal 6 backend post-check/reconciliation은 현재 구현되어 있으며 task OK만으로 success 처리하지 않는다.
향후 live smoke가 승인되면 `192.168.2.140-150/24`는 테스트 VM 후보 범위로만 사용하고,
identity/fingerprint, current locator, policy, final pre-check, approval, operation lock,
verified post-check contract를 별도로 통과해야 한다.
