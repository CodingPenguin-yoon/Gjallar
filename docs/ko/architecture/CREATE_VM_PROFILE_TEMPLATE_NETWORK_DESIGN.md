# Create VM Profile, Template, And Network Design

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 profile/template/network design](../../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md), [Current Create VM snapshot](../../current/top-tabs/04-create-vm.md), [Create VM architecture](../../architecture/create-vm/overview.md).

이 문서는 Create VM의 profile, template, network 선택 model을 분리해서 설명합니다. 일부는 target design이고, current implementation gap은 별도로 적습니다.

## 목적

세 가지 source of truth를 혼동하지 않는 것이 목표입니다.

| Concern | Target source of truth | Create VM behavior |
|---|---|---|
| Profile | Gjallar DB seed | operator-visible read-only preset |
| Template | Proxmox live inventory | operator가 live template 선택 |
| Network | Proxmox live bridge inventory | target node 선택 후 active bridge 선택 |

## Profiles

Profile은 Proxmox template 대체물이 아닙니다. Target에서는 Gjallar DB seed data이고 initial UI는 read-only입니다. Current는 transitional `static_seed`입니다.

Initial enabled profiles:

- `general-vm`: General VM, 범용 VM
- `runtime-server`: Runtime Server, 서비스 실행용 VM
- `development-vm`: Development VM, 개발/테스트용 VM

Profile은 CPU/memory/disk defaults와 min/max, template requirements, access recommendations를 가집니다. Target node, storage, network, bridge, static IP, template VMID/name, power policy, profile version은 포함하지 않습니다.

## Hardware defaults and limits

| Profile | CPU default/min/max | Memory default/min/max MB | Disk default/min/max GB |
|---|---|---|---|
| `general-vm` | 2 / 1 / 8 | 4096 / 1024 / 32768 | 50 / 50 / 500 |
| `runtime-server` | 4 / 2 / 16 | 8192 / 4096 / 65536 | 100 / 80 / 1000 |
| `development-vm` | 2 / 1 / 12 | 4096 / 2048 / 32768 | 50 / 50 / 500 |

Profile 변경 시 UI는 CPU/RAM/Disk를 새 profile default로 reset하고, selected template disk floor가 더 크면 disk floor를 올립니다. Backend preflight가 min/max를 authoritative하게 검증합니다.

## Templates

Template source of truth는 `/api/v1/templates`의 Proxmox live/fake inventory입니다. Target에는 Gjallar template catalog나 registration window가 없습니다.

모든 initial profile은 `require_cloud_init=true`, `require_qemu_guest_agent=true`입니다. UI는 live template을 모두 보여주되 requirements를 통과하지 못하는 option을 disabled reason과 함께 비활성화합니다. Backend preflight는 selected template이 requirement를 만족하지 않으면 red-block합니다. Missing or unknown capability evidence는 ready가 아닙니다.

Selected template disk가 requested disk보다 크면 preflight가 red risk를 반환합니다.

## Network

Create VM target networking은 `network_id` 또는 `server-net`를 source of truth로 사용하지 않습니다.

Current behavior:

- operator가 target node를 먼저 선택합니다.
- UI는 그 node의 active live bridge를 보여줍니다.
- Backend는 explicit `bridge_id`가 target node에서 active인지 확인합니다.
- Static mode는 `static_ip`, `prefix`, `gateway`를 모두 요구합니다.
- DHCP mode는 허용되지만 later discovery warning이 있습니다.
- Gateway와 prefix는 operator input입니다. Native create는 `.1` gateway나 `/24` prefix를 추론하지 않습니다.

Network tab policy는 current/legacy support 또는 future advisory evidence일 수 있지만, current Create VM authoritative red gate가 아닙니다.

## Access

Access section은 current 구현입니다. Username은 profile default `yoon`에서 시작하고 operator override가 가능합니다. SSH public key는 request 또는 backend env/file default에서 올 수 있습니다. Current profiles는 SSH key를 요구하고, missing/malformed/private-key-looking input과 password login true는 red preflight입니다.

Raw public key는 native Proxmox `sshkeys` config call에 transient하게만 사용됩니다. API response, plan/review/manifest/preview/observed artifact에는 presence/source/fingerprint만 남깁니다.

## Current implementation gap

Current code는 profile source가 DB seed가 아니라 `static_seed`인 점을 제외하면 세 profile, live template selection, template disabled state, explicit live bridge, static fields, access/SSH gate를 상당 부분 구현합니다. Profile management UI, first power-on, smoke, DRS identity reuse는 future입니다.
