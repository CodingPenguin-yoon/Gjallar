# Gjallar TDD Contract Plan

> Current MVP product source of truth is `drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.
> This create-first test plan is historical/supporting capability context only. It must not define the next MVP success line or implementation order.

## 0. 목적

Gjallar 재구현은 테스트를 먼저 작성한다.
AI가 구현 후 자기 코드에 맞춘 무의미한 테스트를 만드는 것을 막는다.

Create VM profile/template/network target contract은
[`../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md)를 따른다.
현재 code는 아직 built-in profiles, `general-vm` only enabled 상태다. Create
VM networking은 explicit active live bridge와 static
`static_ip`/`prefix`/`gateway`를 사용하며, incoming `network_id`/`networkId`는
transition compatibility로 ignore한다. 남은 profile/template/access target
tests는 구현 update와 함께 RED부터 추가한다.

## 1. 테스트 원칙

1. PRD/API/manifest 계약을 테스트로 고정한다.
2. 구현 전에 실패하는 테스트를 만든다.
3. 최소 구현으로 통과시킨다.
4. 리팩터 후 다시 전체 테스트를 돌린다.
5. 구현 세션과 별도 fresh review를 수행한다.

## 2. 테스트 계층

### Manifest schema tests

- DB seed has enabled `general-vm`, `runtime-server`, and `development-vm`
- `general-vm` hardware defaults/limits are CPU 2 default, 1-8; memory 4096 default, 1024-32768; disk 50 default, 50-500
- `runtime-server` hardware defaults/limits are CPU 4 default, 2-16; memory 8192 default, 4096-65536; disk 100 default, 80-1000
- `development-vm` hardware defaults/limits are CPU 2 default, 1-12; memory 4096 default, 2048-32768; disk 50 default, 50-500
- all initial profiles require cloud-init and qemu guest agent
- all initial profiles recommend `default_user=yoon`, require SSH key, disable password login, and allow username override
- profile seed rejects target node, storage, network/network_id, bridge, static IP, template VMID/name, power policy, and profile version fields
- hardware override over profile max rejected
- hardware override under profile min rejected
- changing selected profile resets CPU/RAM/Disk to the new profile defaults
- unknown live template rejected
- template failing selected profile cloud-init requirement rejected
- template failing selected profile qemu guest-agent requirement rejected
- requested disk below selected live template disk rejected
- target node bridge selection uses active live bridge inventory
- create plan rejects bridge not present on selected target node
- target Create VM draft rejects `network_id`
- static mode without `static_ip`, `prefix`, or `gateway` rejected
- `dhcp` and `static` IP modes are both accepted; default is `static`
- DHCP mode returns warning for later guest-agent/inventory discovery
- first create MVP does not expose Runtime Target create option; Runtime Target readiness tests are added in the deferred Runtime Target slice

### Safety/preflight tests

- duplicate `proxmox_vmid` red
- stale Proxmox nextid resolved `proxmox_vmid` red
- manual VMID input rejected or hidden in MVP create flow
- Terraform state lock blocks apply
- Terraform state/manifest `proxmox_vmid` mismatch red
- Terraform state path under `/mnt/hermes_data/IaC-state/gjallar/<manifest_id>/terraform.tfstate`
- duplicate IP red
- reserved IP red
- storage insufficient red
- required SSH key missing red
- password login true rejected for initial profiles
- profile-owned power policy rejected
- yellow requires approval
- red cannot be overridden by approval

### API contract tests

- dashboard summary shape
- nodes list shape
- VMs list/detail shape
- create draft/preflight/plan/approve/execute state transition
- `GET /profiles` returns the three enabled target profile seeds with hardware, template requirements, and access recommendations
- `GET /templates`/template selector is backed by live Proxmox inventory, not a Gjallar template catalog
- failing templates are returned disabled in the UI model and red-blocked in preflight
- plan response includes Review & Confirm payload and checksum
- approve request verifies plan artifact id and review summary checksum
- jobs artifact links
- Runtime Target read-only shape is deferred until the Runtime Target slice
- no Heimdall registry write endpoint in MVP
- independent power on/shutdown/reboot confirm request tests are deferred until the power-action slice
- hard-stop/reset endpoints do not exist in MVP

### UI tests

- red risk disables approve/execute
- yellow risk shows review and requires warning checkbox
- VM create uses normal Confirm, not typed confirmation
- profile list shows `general-vm`, `runtime-server`, and `development-vm`
- profile change resets CPU/RAM/Disk controls to new defaults
- profile hardware controls enforce min/max
- template selector shows live Proxmox templates and disables templates that fail selected profile requirements
- target node selection filters bridge options to active live bridges on that node
- static mode requires static IP, prefix, and gateway fields
- DHCP mode shows discovery warning
- Create VM access section defaults username to `yoon`, can prefill public key from environment-backed backend config, and keeps password login disabled
- no-key state shows red blocker when selected profile requires SSH key
- API/artifacts never include private key, password, or token secret values
- Review & Confirm shows VM name, VMID, profile, node, storage, live template, hardware, access username/key presence, bridge, IP mode, static IP/prefix/gateway when used, Terraform state path or manifest path, first power on, smoke timeout, risk summary, plan artifact link, git diff summary
- profile first, advanced hardware collapsed
- Infra Explorer shows Nodes/VMs/Detail in one flow
- start VM action remains absent until future Infra Explorer row action slice with Jobs/Runs audit
- VM Detail power action confirm modal tests are deferred until the power-action slice
- yellow risk on power action tests are deferred until the power-action slice
- hard stop/reset actions are not shown in MVP

## 3. 금지 테스트

아래는 테스트로도 만들지 않는다.

- 앱 deploy 성공 테스트
- DB migration 실행 테스트
- raw shell 실행 테스트
- Proxmox credential 노출 테스트 외 실제 secret 출력

## 4. CI 기본 명령 후보

구현 repo에서 확정한다.

```bash
pytest
pnpm test
pnpm typecheck
pnpm lint
```

명령은 실제 repo 구조 확인 후 수정한다.
