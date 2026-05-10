# Gjallar MVP Decision Lock

이 문서는 PRD 진행 중 이미 확정된 결정을 한 곳에 잠그기 위한 요약이다.
새 질문을 만들기 전에 반드시 이 문서를 먼저 확인한다.

## 1. 제품 정체성

- Gjallar는 **Proxmox를 VMware처럼 쓰게 해주는 VM/인프라 운영 콘솔**이다.
- Terraform/Ansible/IaC는 내부 구현 수단이다.
- 제품 중심은 사람이 이해하고 승인할 수 있는 VM/노드/리스크/작업 화면이다.
- Heimdall 보조 플러그인이 아니다. Heimdall은 MVP에서 read-only consumer다.

## 2. MVP 범위

MVP 포함:

- Dashboard / Infra Explorer
- Nodes / VMs / VM Detail
- `general-vm` 생성
- VM 생성 flow 안의 first power on
- guest-agent/IP/SSH/cloud-init smoke
- 리스크/경고 표시
- preflight / plan / Review & Confirm
- Terraform/Proxmox job/run 이력, Ansible 이력은 Stage B 이후 추가
- artifact 저장

MVP 제외:

- 기존 VM 대상 독립 power on / graceful shutdown / reboot는 power-action slice로 연기
- VM 삭제 자동화
- snapshot / rollback
- live resource resize
- template 관리
- VM console
- hard stop / reset / kill
- multi-tenant RBAC
- Kubernetes/OpenStack 관리
- 임의 shell 실행
- Gjallar가 Heimdall registry에 직접 write
- Runtime Target manifest/API/checkbox는 Runtime Target slice로 연기
- Runtime Target `active=true` 자동 전환

## 3. MVP 실제 생성 profile

- MVP 실제 생성 profile과 화면 선택지는 `general-vm` 하나다.
- `general-vm`은 일반 VM 생성용 기본 profile이다.
- 목적: template clone + hardware/network/cloud-init + first power on + smoke까지 되는 기본 VM 생성 파이프라인 검증.
- `runtime-server`, `dev-server`, `db-server`는 2차 profile 후보다.
- Docker/Node/Python/uv/gh, DB, app runtime bootstrap은 `general-vm`에 넣지 않는다.

## 4. 첫 fixture / live inventory 경계

PRD fixture 후보:

```yaml
profile_id: general-vm
target_node_candidates:
  - yoonmanserver2
  - yoonmanserver3
network_profile: server-net
node_bridges:
  yoonmanserver2: vmbr0
  yoonmanserver3: vmbr0
ip_modes:
  allowed:
    - dhcp
    - static
  default: static
template_family: ubuntu
mvp_create_ip_range: 192.168.2.140-150
```

구현 직전 live inventory로 확인할 값:

- Proxmox API의 실제 node id
- node별 실제 bridge 목록
- storage 이름/여유량
- Ubuntu template VMID/name/storage/cloud-init/guest-agent capability
- 사용 가능한 IP

## 5. Network / IP 결정

- NetworkProfile이 node별 bridge mapping의 source of truth다.
- bridge는 VM 생성 요청에서 raw 값으로 받지 않는다.
- Gjallar는 `node_id` + `network_id`로 `NetworkProfile.node_bridges[node_id]`를 resolve 한다.
- 선택 target node에 mapping이 없거나 live inventory상 bridge가 없으면 red risk로 실행 차단한다.
- DHCP/static 둘 다 지원한다.
- 기본/추천 IP mode는 static이다.
- Runtime Target 후보 slice에서는 static IP 또는 안정적 접근 주소가 필요하다. 첫 구현 MVP preflight blocker는 아니다.
- DHCP 생성은 허용하지만 smoke에서는 guest-agent/IP discovery가 필수 evidence다.
- IP 충돌 검사의 MVP evidence는 NetworkProfile manifest + Proxmox observed state다.
- DHCP/ARP/router lease 조회는 필요 시 read-only evidence로 추가한다.
- 별도 IPAM은 MVP 제외다.

## 6. IaC / Manifest / State

- IaC repo/source of truth: `/mnt/hermes_data/IaC`
- Terraform state 후보: `/mnt/hermes_data/IaC-state/gjallar/<manifest_id>/terraform.tfstate`
- IaC는 Git-backed desired state다.
- Flow:

```text
remote IaC repo -> local checkout/job workspace -> manifest/generated change -> schema/preflight/plan -> Review & Confirm -> commit -> push -> apply/create-powered-off -> first power on -> Stage A smoke -> DB/artifacts
```

Stage B minimal Ansible verify와 Runtime Target manifest/API는 VM 생성 flow 안정화 후 별도 slice에서 붙인다.

- commit/push는 apply 전에 완료한다.
- Gjallar write allowlist:
  - `manifests/vms/**`
  - `generated/**`
- 첫 구현 MVP에서는 `manifests/runtime-targets/**` write를 제외한다. Runtime Target manifest/API/checkbox는 VM 생성 flow 안정화 후 Phase 6/2차에서 재검토한다.
- Gjallar write denylist:
  - `terraform/modules/**`
  - `ansible/roles/**`
  - `ansible/playbooks/**`
  - `scripts/**`
- Terraform state는 Git에 넣지 않는다.
- per-`proxmox_vmid`/per-name/per-IP lock과 Terraform state lock을 사용한다.
- manifest `proxmox_vmid`/name과 state의 리소스 매핑 불일치는 red risk다.

## 7. Credential / Secret

- Proxmox 접근은 API Token 방식이다.
- root password / 개인 계정 password 저장은 금지한다.
- token id/secret 원문은 Git, PRD, manifest, Terraform state, DB, artifact, log, UI/API 응답에 저장/노출하지 않는다.
- secret은 backend runtime secret으로만 주입한다.

## 8. VM 생성 flow / first boot gate

- clone/hardware/cloud-init/network config는 가능하면 powered-off 상태에서 완료한다.
- Terraform/Proxmox apply/config 성공 후에만 first power on을 실행한다.
- apply/config 실패 시 first power on을 생략하고 `provision_failed_not_booted`로 표시한다.
- first power on 이후 smoke 실패는 `created_but_not_ready`다. Ansible 실패는 Stage B를 붙인 뒤 같은 정책을 적용한다.
- 실패 VM은 자동 삭제하지 않는다.
- 자동 reboot / rollback / cleanup도 하지 않는다.
- cleanup/delete는 2차 typed confirmation 대상이다.

## 9. Smoke / Ansible 단계

Stage A — smoke only:

- cloud-init 완료 확인
- guest-agent 응답 확인
- IP 확인
- SSH 접속 확인
- 별도 package 설치 없음

Stage B — minimal Ansible verification:

첫 구현 MVP에서는 Stage A smoke 안정화가 완료된 뒤에만 Stage B를 붙인다. 즉, Ansible verify는 초기 완료 기준이 아니라 optional/deferred slice다.

- Ansible inventory 생성 확인
- Ansible ping/facts 확인
- 최소 운영 패키지 존재 확인 또는 설치
- Docker/Node/Python/uv/gh 제외

기본 timeout:

- first power on task: 5m
- cloud-init: 15m
- guest-agent: 5m
- IP discovery: 5m
- SSH: 5m
- minimal Ansible verify: 5m, Stage B를 붙인 뒤 사용

## 10. Approval / Safety

- VM 생성은 일반 Confirm 버튼이다.
- yellow risk는 명시적 경고 체크박스가 필요하다.
- red risk는 approve/execute disabled이며 승인으로 우회할 수 없다.
- typed confirmation은 삭제/rollback/disk delete/hard stop/reset 같은 2차 destructive action 전용이다.
- Review & Confirm 필수 표시 항목:
  1. VM name
  2. VMID
  3. target node
  4. storage
  5. template
  6. CPU/RAM/Disk
  7. network/IP
  8. Terraform state path
  9. first power on 포함 여부
  10. smoke timeout summary
  11. red/yellow risk summary
  12. plan artifact link
  13. planned Git diff summary

## 11. Heimdall / Runtime Target 경계

- MVP에서 Gjallar는 VM candidate/readiness/risk를 read-only API로 제공한다.
- Gjallar는 Heimdall registry에 직접 write하지 않는다.
- Heimdall deploy target registry ownership은 Heimdall에 있다.
- Hermes/user가 Gjallar candidate를 보고 Heimdall target 승격 여부를 결정한다.
- Runtime Target status는 MVP에서 `candidate`, `candidate_ready`, `blocked`까지만 다룬다.
- `active=true` 자동 전환은 2차다.
- 첫 구현 MVP에서는 Runtime Target manifest/API/checkbox 구현을 요구하지 않는다. `active=true` 금지와 Heimdall registry write 금지만 테스트로 고정한다.

## 12. 독립 전원 제어 — deferred power-action slice

2차 power-action slice 허용:

- power on
- graceful shutdown
- reboot

단, 첫 구현 MVP에서는 VM 생성 flow 안의 first power on만 필수다. 기존 VM에 대한 독립 power on / graceful shutdown / reboot는 `general-vm` 생성과 smoke가 안정화된 뒤 다음 slice로 구현한다.

정책:

- 각 action은 일반 Confirm 필요
- red risk면 차단
- yellow risk면 경고 체크박스 필요
- `expected_current_power_state` guard 사용

MVP 제외:

- hard stop
- reset
- kill

## 13. 질문 규칙

앞으로 Drill 질문은 아래 조건을 모두 만족할 때만 한다.

1. 이 Decision Lock과 PRD 검색에서 결정이 없을 것.
2. 그 결정 없이는 첫 MVP 구현 slice가 막힐 것.
3. 질문이 PRD product/safety/flow 결정인지, 구현 직전 live inventory 확인값인지 구분될 것.
4. 한 번에 하나만 물을 것.

이미 결정된 항목은 다시 묻지 않는다.
