# 남은 작업 빠른 안내

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [Current implemented state](../current/README.md), [DRS Advisor implementation plan](../product/drs-advisor/05_IMPLEMENTATION_PLAN.md), [Create VM profile/template/network design](../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md), [current work plan](../engineering/GJALLAR_CURRENT_WORK_PLAN.md).

이 페이지는 현재 구현과 product target 사이의 남은 일을 빠르게 정리합니다. 자세한 work plan은 [engineering/GJALLAR_CURRENT_WORK_PLAN.md](engineering/GJALLAR_CURRENT_WORK_PLAN.md)와 [product/drs-advisor/05_IMPLEMENTATION_PLAN.md](product/drs-advisor/05_IMPLEMENTATION_PLAN.md)를 봅니다.

## 큰 남은 작업

| 영역 | 남은 일 |
|---|---|
| Create VM profiles | DB seed 기반 read-only profile은 구현됨. 남은 일은 profile 관리 UI/운영 정책 결정. |
| DRS Advisor UI/execution | identity/fingerprint/policy, final pre-check, approval, locks, narrow backend execution, UPID/post-check, read-only reconcile preview는 구현됨. `/drs`에는 manual VM policy configuration과 local approval packet/job intent creation이 있음. 남은 일은 live execute UI, corrective reconcile UI, live DRS smoke. |
| DRS policy/metadata | `GET/PUT /api/v1/drs/policies*` 기반 manual VM migration policy UI/API는 구현됨. 남은 일은 richer policy rule/full metadata editor. |
| Metrics | 1분 resource polling, 15분 average/peak, stale evidence warning. |
| Read-only DRS evidence | 더 깊은 active task/HA/quorum collection. 현재 일부 evidence는 `not_collected`로 남고 execution route는 별도 live gate를 수행함. |
| Reconciliation | Corrective reconciliation mutation과 background reconciliation automation. |
| Jobs/Risks | DRS blocker taxonomy의 `/api/v1/risks` 통합과 live DRS smoke evidence. |
| Goal 8 readiness | Minimal local-only post-create readiness evidence recorder는 구현됨. Live readiness checks, SSH, Ansible, app bootstrap은 deferred. |
| Goal 9 account/session polish | Admin local account list/create/role/disable/reset-password, session inventory/revocation UI, self password change, sanitized audit metadata는 구현됨. Disable/reset-password는 target sessions를 revoke하고 role change는 revoke하지 않음. |

## 문서 관리 원칙

- `docs/ko`는 설명 계층이며 canonical behavior를 새로 정의하지 않습니다.
- archive, history, legacy PRD, old PRD를 current truth처럼 인용하지 않습니다.
- endpoint/path/method/profile id/artifact type은 English 그대로 둡니다.
- Current와 target을 분리해서 씁니다.
