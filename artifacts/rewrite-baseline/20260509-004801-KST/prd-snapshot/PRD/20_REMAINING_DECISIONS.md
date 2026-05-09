# Gjallar PRD Remaining Decisions

이 문서는 `19_MVP_DECISION_LOCK.md` 이후에도 남은 항목만 관리한다.
랜덤 Drill 질문 금지. 아래 순서대로만 처리한다.

## 0. 현재 상태

PRD의 제품/안전/흐름 결정은 대부분 잠겼다.
남은 것은 크게 두 종류다.

1. **구현 직전 live inventory 확인값** — 질문이 아니라 실제 Proxmox/IaC를 조회해서 채울 값.
2. **첫 구현 slice 착수 전 운영 기본값** — 기본값을 정하면 바로 구현 가능한 값.

## 1. 구현 직전 live inventory 확인값

질문으로 해결하지 않는다. 구현 시작 시 도구로 확인한다.

- Proxmox API에서 보이는 실제 node id
- `yoonmanserver2`, `yoonmanserver3`의 실제 bridge 목록
- 선택 가능한 storage 이름과 여유량
- Ubuntu template VMID/name/storage
- template cloud-init 가능 여부
- template guest-agent capability
- `192.168.2.140-150` 중 실제 사용 가능한 IP
- Proxmox API Token 권한 범위

## 2. 첫 구현 slice 착수 전 운영 기본값 — 기본값으로 확정

사용자가 별도 변경을 요구하지 않는 한 아래 값으로 구현을 시작한다.
질문으로 다시 막지 않는다.

### D1. `general-vm` 기본 hardware — 확정 기본값

기본값:

```yaml
cpu: 2
memory_mb: 4096
disk_gb: 40
```

이유: 일반 VM smoke와 추후 runtime/dev 확장 전 단계로 충분하고, 홈랩 리소스 부담이 낮다.

### D2. `general-vm` 기본 cloud-init user — 확정 기본값

기본값:

```yaml
cloud_init_user: yoon
ssh_key_source: operator_default_public_key
password_login: disabled
```

secret/password 저장 금지 원칙과 맞는다.

### D3. DHCP/static UX

이미 둘 다 지원으로 결정됨.

- 기본 선택: static
- DHCP 선택 가능
- runtime target 후보 체크 시 static IP 또는 안정적 접근 주소 필요 경고

### D4. 구현 착수 순서

1. 현재 코드 inventory / keep-drop-park
2. API contract tests
3. manifest schema tests
4. Proxmox read-only inventory
5. create draft/preflight/plan
6. Review & Confirm
7. GitOps commit/push guard
8. Terraform apply powered-off
9. first power on + smoke
10. job/artifact UI

## 3. 다음 질문 정책

현 상태에서 PRD를 막는 추가 질문은 없다.
구현 중 live inventory로 확인해야 하는 값은 질문하지 않고 조회한다.
새 질문은 `19_MVP_DECISION_LOCK.md`의 질문 규칙을 통과할 때만 한다.
