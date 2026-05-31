# 현재 구현 상태 빠른 안내

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [Current implemented state](../current/README.md), [top-tab snapshots](../current/top-tabs/README.md), [system overview](../architecture/system/overview.md).

이 문서는 현재 구현을 빠르게 파악하기 위한 입구입니다. 자세한 설명은 [current/README.md](current/README.md)와 [current/top-tabs/README.md](current/top-tabs/README.md)를 봅니다.

## 현재 구현 한 줄 요약

Gjallar는 현재 Proxmox 운영자가 클러스터 상태, DRS Advisor 추천/체크 증거, network readiness/migration pre-check, job/artifact, risk를 확인하고, 승인 기반으로 VM을 생성할 수 있게 하는 Proxmox Operations & Risk Console입니다. 기본 생성은 powered-off이고, 선택하면 `boot_and_verify`로 first boot/IP/cloud-init까지 확인합니다. DRS frontend는 recommendation/check, manual policy configuration, local approval packet creation을 제공하고, backend에는 별도 operator-only migration-job execute route와 read-only reconcile preview가 있습니다.

## 현재 active surface

| 화면 | 현재 역할 | 자세한 한국어 문서 |
|---|---|---|
| `/` Dashboard | read-only 운영 요약, partial-load summary | [Dashboard](current/top-tabs/01-dashboard.md) |
| `/infra` Infra Explorer | read-only VM/node inventory | [Infra Explorer](current/top-tabs/02-infra-explorer.md) |
| `/networks` Networks | read-only live bridge readiness / migration pre-check | [Networks](current/top-tabs/03-networks.md) |
| `/create` Create VM | draft/preflight/plan/approval/native create | [Create VM](current/top-tabs/04-create-vm.md) |
| `/drs` DRS Advisor | recommendation/check, manual policy configuration, local approval packet creation; live execute/corrective reconcile controls 없음 | [Placement / DRS Advisor](current/top-tabs/05-placement-drs-advisor.md) |
| `/jobs` Jobs/Runs | DB-backed job/artifact inspection | [Jobs/Runs](current/top-tabs/06-jobs-runs.md) |
| `/risks` Risks/Alerts | job-derived risk projection | [Risks/Alerts](current/top-tabs/07-risks-alerts.md) |

## 반드시 지킬 현재 경계

- Active backend prefix는 `/api/v1`입니다.
- Proxmox inventory는 read-only입니다.
- Networks는 YAML/file/DB/API write path나 DRS 실행 권한이 없는 read-only readiness view입니다.
- 실제 VM/node/task/storage/network 상태의 기준은 Proxmox current state입니다.
- 실제 Create VM live mutation은 `POST /api/v1/vm-create/{draft_id}/proxmox-create`입니다.
- Current `/drs` UI는 backend DRS read/check endpoint, manual policy endpoint, local approval packet endpoint를 사용합니다. 모든 recommendation/check result는 `executable=false`, `allowed_actions=[]`입니다. Local approval packet creation은 migration을 시작하지 않습니다. Live migration은 UI가 아니라 별도 operator-only `/api/v1/drs/migration-jobs/{job_id}/execute` route에서만 fresh gates 후 가능합니다.
- Create VM 성공은 선택한 power policy 검증까지입니다. 기본 `stopped`는 powered-off/stopped VM 관찰, `boot_and_verify`는 first boot, guest-agent IP, cloud-init completion까지 포함합니다. SSH, Ansible, DRS identity registration은 포함하지 않습니다.

## 더 읽을 곳

- [한국어 현재 구현 상세](current/README.md)
- [한국어 API 상세](architecture/api/current-api-v1.md)
- [한국어 Create VM 상세](architecture/create-vm/overview.md)
- [한국어 DRS Advisor 제품 방향](product/drs-advisor/README.md)
