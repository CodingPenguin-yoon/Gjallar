# Profile, Template, And Network Model

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Profile/Template/Network model](../../../architecture/create-vm/profile-template-network.md), [profile/template/network design](../../../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md), [Current Create VM snapshot](../../../current/top-tabs/04-create-vm.md).

이 문서는 current selection model과 target DB/access extension을 분리합니다.

## Current profiles

Current profiles는 [backend/app/manifests/loader.py](../../../../backend/app/manifests/loader.py)의 transitional read-only `static_seed` data이며 `GET /api/v1/profiles`로 노출됩니다.

| Profile | Display | Enabled | Source | Management |
|---|---|---:|---|---|
| `general-vm` | General VM | true | `static_seed` | `read_only` |
| `runtime-server` | Runtime Server | true | `static_seed` | `read_only` |
| `development-vm` | Development VM | true | `static_seed` | `read_only` |

DB seed와 profile management UI는 current가 아니라 target/future입니다.

## Hardware defaults and limits

| Profile | CPU default/min/max | Memory default/min/max MB | Disk default/min/max GB |
|---|---|---|---|
| `general-vm` | 2 / 1 / 8 | 4096 / 1024 / 32768 | 50 / 50 / 500 |
| `runtime-server` | 4 / 2 / 16 | 8192 / 4096 / 65536 | 100 / 80 / 1000 |
| `development-vm` | 2 / 1 / 12 | 4096 / 2048 / 32768 | 50 / 50 / 500 |

UI에서 profile을 바꾸면 hardware가 default로 reset되고, selected template disk floor가 더 크면 disk가 올라갑니다. Backend preflight가 final authority입니다.

## Template requirements

모든 current profiles는 cloud-init readiness와 qemu guest agent readiness를 요구합니다. Template source는 `GET /api/v1/templates`입니다.

UI는 모든 template을 보여주되 failed requirement가 있으면 disabled reason을 표시합니다. Backend preflight는 selected template이 requirement를 만족하지 않으면 red-block합니다. Missing capability evidence는 ready가 아닙니다.

## Network source

Current Create VM target networking은 live bridge inventory와 explicit operator input을 사용합니다.

| Field | Current source |
|---|---|
| Target node | `GET /api/v1/nodes` |
| Bridge | `GET /api/v1/networks`에서 selected node active bridge |
| IP mode | operator selects `static` or `dhcp` |
| Static IP | operator input |
| Prefix | operator input |
| Gateway | operator input |

Current Create VM path는 `NetworkPolicy`, `network_id`, `server-net`를 source of truth로 사용하지 않습니다.

## Static and DHCP rules

Static mode는 `static_ip`, `prefix`, `gateway` 모두가 필요합니다. Gateway는 절대 추론하지 않습니다. DHCP mode는 허용되지만 later guest-agent/IP discovery warning이 붙습니다.

## Access and SSH

Current profiles는 SSH public key를 요구하고 password login을 disabled로 고정합니다. Backend는 request key 또는 `GJALLAR_DEFAULT_SSH_PUBLIC_KEY` / `GJALLAR_DEFAULT_SSH_PUBLIC_KEY_FILE` default를 사용할 수 있습니다.

Preflight는 missing key, private-key-looking value, malformed OpenSSH public key, password login true를 red-block합니다. Evidence는 username, disabled password login, key presence/source/fingerprint만 기록합니다.
