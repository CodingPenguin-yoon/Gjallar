# Gjallar PRD Remaining Decisions

> Superseded/historical create-first note:
> Current MVP product source of truth is `drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.
> This create-first material is historical/supporting capability context only. It must not define the next MVP success line or implementation order.
> Next implementation work should follow `drs-advisor/05_IMPLEMENTATION_PLAN.md`.
> Current implemented state is [`../../current/README.md`](../../current/README.md).
> Current Create VM profiles are three enabled read-only `static_seed` profiles:
> `general-vm`, `runtime-server`, and `development-vm`; template and network
> selection use live Proxmox inventory. Current Create VM architecture is
> summarized in
> [`../../architecture/create-vm/profile-template-network.md`](../../architecture/create-vm/profile-template-network.md).

이 문서는 `19_MVP_DECISION_LOCK.md` 이후에도 남은 항목만 관리한다.
랜덤 Drill 질문 금지. 아래 순서대로만 처리한다.

## 0. 현재 상태

PRD의 제품/안전/흐름 결정은 대부분 잠겼다.
남은 것은 크게 두 종류다.

1. **구현 직전 live inventory 확인값** — 질문이 아니라 실제 Proxmox/IaC를 조회해서 채울 값.
2. **첫 구현 slice 착수 전 운영 기본값** — 기본값을 정하면 바로 구현 가능한 값.

2026-05-14 Create VM profile/template/network target design은
[`../../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md)를 따른다.
Current implementation gap: DB seeded profile source는 아직 target/future다.
Current Create VM uses three enabled `static_seed` profiles. Create VM
networking은 explicit active live bridge와 static `static_ip`/`prefix`/`gateway`를
사용하며, incoming `network_id`/`networkId`는 transition compatibility로
ignore한다.

## 1. 구현 직전 live inventory 확인값

질문으로 해결하지 않는다. 구현 시작 시 도구로 확인한다.

- Proxmox API에서 보이는 실제 node id
- `yoonmanserver2`, `yoonmanserver3`의 실제 bridge 목록
- 선택 가능한 storage 이름과 여유량
- Ubuntu template VMID/name/storage
- template cloud-init 가능 여부
- template guest-agent capability
- target node별 active live bridge 목록
- `192.168.2.140-150` 중 실제 사용 가능한 IP
- Proxmox API Token 권한 범위

## 2. 첫 구현 slice 착수 전 운영 기본값 — 기본값으로 확정

사용자가 별도 변경을 요구하지 않는 한 아래 값으로 구현을 시작한다.
질문으로 다시 막지 않는다.

### D1. Create VM seeded profile hardware — 확정 기본값

Target source of truth는 Gjallar DB seed이며 초기 UI에서는 read-only다.

```yaml
profiles:
  general-vm:
    display_name: General VM
    display_name_ko: 범용 VM
    enabled: true
    cpu: { default: 2, min: 1, max: 8 }
    memory_mb: { default: 4096, min: 1024, max: 32768 }
    disk_gb: { default: 50, min: 50, max: 500 }
  runtime-server:
    display_name: Runtime Server
    display_name_ko: 서비스 실행용 VM
    enabled: true
    cpu: { default: 4, min: 2, max: 16 }
    memory_mb: { default: 8192, min: 4096, max: 65536 }
    disk_gb: { default: 100, min: 80, max: 1000 }
  development-vm:
    display_name: Development VM
    display_name_ko: 개발/테스트용 VM
    enabled: true
    cpu: { default: 2, min: 1, max: 12 }
    memory_mb: { default: 4096, min: 2048, max: 32768 }
    disk_gb: { default: 50, min: 50, max: 500 }
```

All initial profiles require cloud-init and qemu guest agent capable templates.
Profile은 target node, storage, network/network_id, bridge, static IP, template
VMID/name, power policy, profile version을 포함하지 않는다.

### D2. Create VM access recommendation — 확정 기본값

기본값:

```yaml
default_user: yoon
require_ssh_key: true
allow_password_login: false
allow_user_override: true
```

Access는 별도 selectable object가 아니다. Create VM Access section에서
username과 SSH public key를 편집한다. 기본 key는 environment-backed backend
설정에서 올 수 있고, key가 없으면 red block이다.

### D3. DHCP/static UX

이미 둘 다 지원으로 결정됨.

- 기본 선택: static
- DHCP 선택 가능
- static mode는 `static_ip`, `prefix`, `gateway` 필수
- DHCP 선택 시 later guest-agent/inventory discovery warning 표시
- runtime target 후보 체크 시 static IP 또는 안정적 접근 주소 필요 경고

### D4. 구현 착수 순서

1. 현재 코드 inventory / keep-drop-park
2. API contract tests
3. manifest schema tests
4. Proxmox read-only inventory
5. profile DB seed and `GET /profiles`
6. Proxmox live template selector with profile requirement disable reasons
7. target node -> active live bridge selector
8. create draft/preflight/plan with no target `network_id`
9. Review & Confirm
10. GitOps commit/push guard
11. Proxmox native create powered-off/stopped
12. first power on + smoke in a separate create-readiness slice

Historical create-first order retained old Terraform-first language. Target
enterprise path is Proxmox API native; Terraform remains optional/deprecated
legacy support.

## 3. 다음 질문 정책

현 상태에서 PRD를 막는 추가 질문은 없다.
구현 중 live inventory로 확인해야 하는 값은 질문하지 않고 조회한다.
새 질문은 `19_MVP_DECISION_LOCK.md`의 질문 규칙을 통과할 때만 한다.
