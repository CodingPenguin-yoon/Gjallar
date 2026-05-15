# 남은 작업 빠른 안내

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [Current implemented state](../current/README.md), [DRS Advisor implementation plan](../product/drs-advisor/05_IMPLEMENTATION_PLAN.md), [Create VM profile/template/network design](../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md), [current work plan](../engineering/GJALLAR_CURRENT_WORK_PLAN.md).

이 페이지는 현재 구현과 product target 사이의 남은 일을 빠르게 정리합니다. 자세한 work plan은 [engineering/GJALLAR_CURRENT_WORK_PLAN.md](engineering/GJALLAR_CURRENT_WORK_PLAN.md)와 [product/drs-advisor/05_IMPLEMENTATION_PLAN.md](product/drs-advisor/05_IMPLEMENTATION_PLAN.md)를 봅니다.

## 큰 남은 작업

| 영역 | 남은 일 |
|---|---|
| Create VM profiles | Current `static_seed`를 target DB seed source로 전환할지 결정하고 구현. |
| DRS read model | `/api/v1/drs/summary`, recommendations 같은 backend read-only API 추가. |
| Metrics | 1분 resource polling, 15분 average/peak, stale evidence warning. |
| Identity | fingerprint 수집, identity assertions, metadata/policy validation. |
| Final pre-check | 실행 직전 authoritative reread와 blocker/warning artifact. |
| Migration execution | Proxmox live migration client, UPID tracking, post-check. |
| Locks | VM/source/target operation lock과 stale/reconciliation_required 상태. |
| Reconciliation | timeout/restart/ambiguous state를 Proxmox actual state로 정리. |
| Jobs/Risks | `drs_migration` job type과 DRS blocker taxonomy. |
| Create VM deferred | first boot, cloud-init smoke, guest-agent discovery, SSH, Ansible, start action. |

## 문서 관리 원칙

- `docs/ko`는 설명 계층이며 canonical behavior를 새로 정의하지 않습니다.
- archive, history, legacy PRD, old PRD를 current truth처럼 인용하지 않습니다.
- endpoint/path/method/profile id/artifact type은 English 그대로 둡니다.
- Current와 target을 분리해서 씁니다.
