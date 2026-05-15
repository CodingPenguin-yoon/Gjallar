# 현재 구현 상태 빠른 안내

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [Current implemented state](../current/README.md), [top-tab snapshots](../current/top-tabs/README.md), [system overview](../architecture/system/overview.md).

이 문서는 현재 구현을 빠르게 파악하기 위한 입구입니다. 자세한 설명은 [current/README.md](current/README.md)와 [current/top-tabs/README.md](current/top-tabs/README.md)를 봅니다.

## 현재 구현 한 줄 요약

Gjallar는 현재 Proxmox 운영자가 클러스터 상태, VM 배치, network policy, job/artifact, risk를 확인하고, 승인 기반으로 powered-off VM을 생성할 수 있게 하는 Proxmox Operations & Risk Console입니다. DRS Advisor가 다음 MVP 목표지만 현재 backend DRS 실행 시스템은 없습니다.

## 현재 active surface

| 화면 | 현재 역할 | 자세한 한국어 문서 |
|---|---|---|
| `/` Dashboard | read-only 운영 요약, partial-load summary | [Dashboard](current/top-tabs/01-dashboard.md) |
| `/infra` Infra Explorer | read-only VM/node inventory | [Infra Explorer](current/top-tabs/02-infra-explorer.md) |
| `/networks` Networks | live bridge view + IaC policy write | [Networks](current/top-tabs/03-networks.md) |
| `/create` Create VM | draft/preflight/plan/approval/native create | [Create VM](current/top-tabs/04-create-vm.md) |
| `/placement` Placement | frontend-only read-only placement seed | [Placement / DRS Advisor](current/top-tabs/05-placement-drs-advisor.md) |
| `/jobs` Jobs/Runs | file-backed job/artifact inspection | [Jobs/Runs](current/top-tabs/06-jobs-runs.md) |
| `/risks` Risks/Alerts | job-derived risk projection | [Risks/Alerts](current/top-tabs/07-risks-alerts.md) |

## 반드시 지킬 현재 경계

- Active backend prefix는 `/api/v1`입니다.
- Proxmox inventory는 read-only입니다.
- 실제 VM/node/task/storage/network 상태의 기준은 Proxmox current state입니다.
- `POST /api/v1/vm-create/{draft_id}/execute`는 manifest commit only입니다.
- 실제 Create VM live mutation은 `POST /api/v1/vm-create/{draft_id}/proxmox-create`입니다.
- Current `/placement`는 frontend-only/read-only입니다. 현재 `/api/v1/drs/*` route는 없습니다.
- Create VM 성공은 powered-off/stopped VM 관찰까지입니다. first boot, cloud-init completion, SSH, Ansible, DRS identity registration은 포함하지 않습니다.

## 더 읽을 곳

- [한국어 현재 구현 상세](current/README.md)
- [한국어 API 상세](architecture/api/current-api-v1.md)
- [한국어 Create VM 상세](architecture/create-vm/overview.md)
- [한국어 DRS Advisor 제품 방향](product/drs-advisor/README.md)
