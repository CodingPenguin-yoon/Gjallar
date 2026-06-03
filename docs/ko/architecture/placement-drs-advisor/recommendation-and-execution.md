# Target DRS Recommendation And Execution

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 target DRS recommendation/execution](../../../architecture/placement-drs-advisor/recommendation-and-execution.md), [DRS recommendation/execution product doc](../../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md), [Target DRS API](../../../architecture/api/target-drs-api.md).

이 문서는 Phase 1 이후 target execution을 설명합니다. 현재 backend DRS recommendation read model, manual policy API, local approval/job substrate, narrow migration route, UPID/post-check, read-only reconcile preview는 구현되어 있습니다.

## Current baseline

Current `/drs`는 `/api/v1/drs/summary`, `/api/v1/drs/recommendations`, detail, `/check`, `GET/PUT /api/v1/drs/policies*`, and `approval-packets`를 사용합니다. Recommendation/check result는 계속 `read_only=true`, `executable=false`, `allowed_actions=[]`입니다. Local approval packet/job intent creation은 있지만 live migration execute UI와 corrective reconcile UI는 없습니다.

## Target recommendation model

Target DRS recommendation은 backend-owned record/read model이어야 합니다. 필요한 field groups: recommendation identity, VM identity, candidate move, CPU/Memory evidence, storage/network/HA/task evidence, policy, blockers/warnings, execution availability.

## Approval and final pre-check

Approval은 exact recommendation evidence version을 기록해야 하며 migration을 바로 시작하지 않습니다. Migration 직전 backend가 current Proxmox state와 Gjallar identity/policy/lock state를 다시 읽어 final pre-check를 수행해야 합니다.

Final pre-check가 fail 또는 unknown이면 migration을 시작하지 않습니다.

## Execution and jobs/risks

Backend narrow execution substrate는 operation record, lock acquisition, Proxmox migration, UPID storage, task polling, post-check, completed/failed/`needs_reconciliation` record를 구현합니다. Approved VMID `140` live DRS smoke evidence도 기록됐습니다. Broad UI, blocker taxonomy display, corrective/background reconciliation은 아직 남아 있습니다.

Jobs/Runs는 `drs_migration`을 first-class job으로 보여주고, Risks/Alerts는 DRS blockers를 source, blocked action, VM identity, evidence artifact와 함께 보여줘야 합니다.
