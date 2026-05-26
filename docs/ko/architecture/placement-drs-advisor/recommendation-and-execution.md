# Target DRS Recommendation And Execution

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 target DRS recommendation/execution](../../../architecture/placement-drs-advisor/recommendation-and-execution.md), [DRS recommendation/execution product doc](../../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md), [Target DRS API](../../../architecture/api/target-drs-api.md).

이 문서는 Phase 1 이후 target execution을 설명합니다. 현재 backend DRS recommendation read model은 구현되어 있지만 migration execution path는 없습니다.

## Current baseline

Current `/drs`는 `/api/v1/drs/summary`, `/api/v1/drs/recommendations`, detail, `/check` read-only endpoint를 읽습니다. Approval button, migration execution, DRS operation state는 없습니다.

## Target recommendation model

Target DRS recommendation은 backend-owned record/read model이어야 합니다. 필요한 field groups: recommendation identity, VM identity, candidate move, CPU/Memory evidence, storage/network/HA/task evidence, policy, blockers/warnings, execution availability.

## Approval and final pre-check

Approval은 exact recommendation evidence version을 기록해야 하며 migration을 바로 시작하지 않습니다. Migration 직전 backend가 current Proxmox state와 Gjallar identity/policy/lock state를 다시 읽어 final pre-check를 수행해야 합니다.

Final pre-check가 fail 또는 unknown이면 migration을 시작하지 않습니다.

## Execution and jobs/risks

Target execution은 operation record, lock acquisition, Proxmox migration, UPID storage, task polling, post-check, completed/failed/`needs_reconciliation` record로 구성됩니다.

Jobs/Runs는 `drs_migration`을 first-class job으로 보여주고, Risks/Alerts는 DRS blockers를 source, blocked action, VM identity, evidence artifact와 함께 보여줘야 합니다.
