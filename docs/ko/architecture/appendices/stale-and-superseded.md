# Stale And Superseded Statements

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 stale appendix](../../../architecture/appendices/stale-and-superseded.md), [Current implemented state](../../../current/README.md), [Architecture index](../../../architecture/README.md).

오래된 PRD, history, archive, 예전 architecture 문서를 읽을 때 아래 correction을 우선합니다.

## Create VM

| 오래된 주장 | 현재 correction |
|---|---|
| 단일 profile만 있다. | Current profiles are `general-vm`, `runtime-server`, `development-vm`. |
| `dev-server` 또는 `db-server`가 initial profile이다. | Current enabled profile ids는 `runtime-server`, `development-vm`입니다. |
| Profile은 DB seeded current이다. | DB seed는 target/future. Current는 `static_seed`. |
| Create VM network는 `network_id` 또는 `server-net`이다. | Current는 selected target node active live bridge와 explicit fields입니다. |
| `execute`가 VM을 만든다. | `execute`는 manifest commit only입니다. Live mutation은 `proxmox-create`입니다. |
| Create VM success includes first boot/smoke/SSH. | Current success is stopped/powered-off post-check with `observed_after`. |

## Network

| 오래된 주장 | 현재 correction |
|---|---|
| Networks tab이 Proxmox bridges를 mutate한다. | IaC policy only. Proxmox bridge mutation 없음. |
| Network policy가 Create VM required gate다. | Current Create VM source는 live bridge selection입니다. |

## Placement / DRS

| 오래된 주장 | 현재 correction |
|---|---|
| DRS Advisor backend가 구현되어 있다. | `/api/v1/drs/*` backend 없음. |
| Current `/placement` can approve/migrate. | Current `/placement` is frontend read-only. |
| Migration UPID tracking/locks/reconciliation exist. | Target-only. |
| DRS identity/fingerprint/policy DB exists. | Not implemented. |

## Jobs/Risks

| 오래된 주장 | 현재 correction |
|---|---|
| Jobs/Runs가 full workflow engine이다. | Current는 latest file-backed job status read-only UI입니다. |
| Risks/Alerts가 independent risk engine이다. | Current risks는 job-derived projection입니다. |
| DRS blocker taxonomy가 integrated current이다. | Not implemented. |
