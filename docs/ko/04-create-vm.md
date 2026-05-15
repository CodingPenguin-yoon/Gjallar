# VM 생성 빠른 안내

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [Create VM architecture](../architecture/create-vm/overview.md), [native create flow](../architecture/create-vm/native-create-flow.md), [VM provisioning contract](../architecture/VM_PROVISIONING_CONTRACT.md), [profile/template/network design](../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md).

Create VM은 live Proxmox template에서 powered-off VM을 만들기 위한 operator-reviewed workflow입니다. DRS Advisor MVP의 success line은 아니지만 approval, artifact, job progress, Proxmox mutation acknowledgement 같은 substrate를 제공합니다.

자세한 설명은 [architecture/create-vm/overview.md](architecture/create-vm/overview.md), [architecture/create-vm/native-create-flow.md](architecture/create-vm/native-create-flow.md), [architecture/flows/create-vm-review-to-create.md](architecture/flows/create-vm-review-to-create.md)를 봅니다.

## 현재 흐름

```text
load options
-> draft
-> preflight
-> plan artifacts + review
-> approve
-> execute manifest commit
-> proxmox-preview
-> proxmox-create
-> Jobs/Runs에서 progress 확인
```

## 현재 선택 source

- Profile: transitional `static_seed`의 `general-vm`, `runtime-server`, `development-vm`.
- Template: `GET /api/v1/templates`의 Proxmox live/fake inventory.
- Target node/storage/bridge: `nodes`, `storage`, `networks` read-only inventory.
- Network: selected target node의 active live bridge와 explicit `static_ip`, `prefix`, `gateway`.
- Access: cloud-init username과 SSH public key. Raw public key는 transient Proxmox config call에만 사용됩니다.

## 성공 범위

성공은 Proxmox post-check에서 target node의 VM이 `stopped`로 관찰되고 `observed_after` artifact가 있는 powered-off 생성입니다. first power-on, cloud-init smoke, guest-agent discovery, SSH, Ansible, app deploy, DRS identity registration은 현재 성공 범위가 아닙니다.

## 주의할 경계

- NetworkPolicy는 current Create VM authoritative red gate가 아닙니다.
- Incoming `network_id`/`networkId`는 transition compatibility로 무시됩니다.
- Static mode는 `static_ip`, `prefix`, `gateway`를 모두 요구합니다.
- Native create는 `.1` gateway나 `/24` prefix를 추론하지 않습니다.
- `execute`는 manifest commit only입니다.
