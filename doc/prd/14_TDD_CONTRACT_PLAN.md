# Gjallar TDD Contract Plan

## 0. 목적

Gjallar 재구현은 테스트를 먼저 작성한다.
AI가 구현 후 자기 코드에 맞춘 무의미한 테스트를 만드는 것을 막는다.

## 1. 테스트 원칙

1. PRD/API/manifest 계약을 테스트로 고정한다.
2. 구현 전에 실패하는 테스트를 만든다.
3. 최소 구현으로 통과시킨다.
4. 리팩터 후 다시 전체 테스트를 돌린다.
5. 구현 세션과 별도 fresh review를 수행한다.

## 2. 테스트 계층

### Manifest schema tests

- valid `general-vm` profile accepted
- MVP create draft rejects disabled/future profiles such as `runtime-server`, `dev-server`, `db-server`
- default `general-vm` hardware is 2 vCPU / 4096MB / 40GB
- hardware override over max rejected
- unknown template rejected
- unknown network rejected
- network profile resolves bridge by selected target node
- create plan supports both `yoonmanserver2` and `yoonmanserver3` when mapped bridge exists
- create plan rejects node/network combinations with missing bridge mapping
- `dhcp` and `static` IP modes are both accepted; default is `static`
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
- yellow requires approval
- red cannot be overridden by approval

### API contract tests

- dashboard summary shape
- nodes list shape
- VMs list/detail shape
- create draft/preflight/plan/approve/execute state transition
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
- create draft defaults access to cloud-init user `yoon`, operator default public key, password login disabled
- API/artifacts never include private key, password, or token secret values
- Review & Confirm shows VM name, VMID, node, storage, template, hardware, network/IP, Terraform state path, first power on, smoke timeout, risk summary, plan artifact link, git diff summary
- profile first, advanced hardware collapsed
- Infra Explorer shows Nodes/VMs/Detail in one flow
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
