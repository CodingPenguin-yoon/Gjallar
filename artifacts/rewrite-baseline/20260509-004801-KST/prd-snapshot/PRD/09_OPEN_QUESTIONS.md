# Gjallar Open Questions

이 문서는 PRD 확정 전 사용자에게 더 확인해야 할 질문을 모은다.
대화에서는 한 번에 하나씩만 묻는다.

## 1. 바로 필요한 질문

### Q1. MVP 실제 생성 profile은 무엇인가? — 결정됨

후보:

- `general-vm`: 일반 VM 생성용 기본 profile
- `runtime-server`: 앱 실행용 runtime VM. 2차
- `dev-server`: Docker/Node/Python/uv/gh 포함 개발 VM. 2차
- `db-server`: DB 전용 VM. 2차

결정: MVP 실제 생성 profile은 `general-vm` 하나만 둔다.

의미:

- Gjallar VM 생성 파이프라인을 가장 작고 안전하게 검증한다.
- preflight → plan → approve → create → guest-agent/IP/SSH/cloud-init smoke 흐름을 검증한다.
- `general-vm`은 template clone + hardware/network/cloud-init + smoke까지 되는 기본 VM이다.
- Docker/Node/Python/uv/gh, DB, runtime bootstrap은 MVP `general-vm`에 넣지 않는다.
- `runtime-server`, `dev-server`, `db-server`는 2차 profile 후보로 남긴다.

### Q2. 실제 Proxmox inventory 이름 — 부분 결정됨

결정:

- target node 후보: `yoonmanserver2` 또는 `yoonmanserver3`
- NetworkProfile은 두 target node를 모두 지원한다.
- bridge는 전역 단일 값이 아니라 `node_bridges` mapping으로 관리한다.
- 초기 fixture 후보는 두 노드 모두 `vmbr0` 매핑이다.
- 사용자가 생성 노드를 선택하면 Gjallar는 해당 노드의 bridge mapping을 사용한다.
- 구현/실행 전 Proxmox live inventory로 선택 노드에 해당 bridge가 실제 존재하는지 검증한다.
- IP mode는 `dhcp`와 `static`을 둘 다 지원하되, 기본/추천값은 `static`이다.
- template 계열: Ubuntu template
- MVP 생성 테스트 IP range: `192.168.2.140-150`

구현 직전 live inventory 확인값:

- Proxmox API에서 보이는 node id가 `yoonmanserver2`/`yoonmanserver3`와 다른지 확인
- storage 이름
- template VMID/name
- node별 실제 bridge 목록

위 항목은 사용자에게 다시 질문할 PRD 결정이 아니다. 구현 시작 시 Proxmox live inventory로 조회해서 채운다.

### Q3. IaC repo 실제 위치 — 결정됨

결정:

```text
/mnt/hermes_data/공통/iac
  manifests/
  terraform/
  ansible/
  generated/

/mnt/hermes_data/공통/iac-state
  gjallar/<manifest_id>/terraform.tfstate
  # MVP Terraform local backend. Git에는 넣지 않음.
```

원칙:

- IaC는 Git repo로 관리한다.
- Gjallar 또는 작업자는 로컬 checkout/job workspace에서 manifest/generated 변경을 만든다.
- schema validation / preflight / plan / review & approval 후 commit/push한다.
- apply/bootstrap/smoke는 승인된 Git desired state를 기준으로 실행한다.
- Terraform/Ansible engine code는 사람이 리뷰해서 수정한다.

### Q4. Proxmox credential 관리 — 결정됨

결정:

- Gjallar MVP는 Proxmox API Token 방식을 사용한다.
- root/password 또는 개인 계정 password 저장 방식은 사용하지 않는다.
- token id/secret은 Git, PRD, manifest, Terraform state, DB, artifact, 로그, UI/API 응답에 저장/노출하지 않는다.
- backend runtime secret으로만 주입한다. MVP에서는 `.env` 또는 OS credential file을 사용할 수 있으나, repo에는 commit하지 않는다.
- 구현 전 token 권한 scope를 VM 조회/생성/전원/guest-agent 확인에 필요한 최소 권한으로 검토한다.
- readiness/preflight는 token 값이 아니라 “설정 여부/권한 검증 결과”만 표시한다.

### Q5. IP source of truth — 결정됨

Network Profile manifest 외에 어떤 운영 evidence를 IP 충돌 검사에 사용할지 결정한다.

선택지:

A. MVP에서는 Network Profile manifest + Proxmox observed state만 사용
B. DHCP/ARP/라우터 lease 조회를 read-only evidence로 추가
C. 별도 IP inventory 파일/서비스를 나중에 정의
D. Gjallar 자체 IPAM은 2차 이후 별도 설계

결정:

- MVP는 A로 시작한다.
- 즉, `Network Profile manifest + Proxmox observed state`를 1차 source로 사용한다.
- 실제 충돌 감지가 부족하면 B, 즉 DHCP/ARP/라우터 lease 조회를 read-only evidence로 추가한다.
- 별도 IP inventory 또는 Gjallar 자체 IPAM은 MVP 범위 밖으로 둔다.

### Q6. VM 이름/VMID 할당 — 결정됨

결정:

- MVP는 Proxmox `nextid`를 사용한다.
- `general-vm` 기본 이름은 `gjallar-vm-<YYYYMMDD>-<short_job_id>` 형식으로 추천한다.
- MVP에서는 사용자가 VMID를 직접 입력하는 UI를 기본 제공하지 않는다.
- plan/preflight 단계에서 resolved `proxmox_vmid`를 만들고, apply 직전 다시 중복 확인한다.
- stale nextid 또는 `proxmox_vmid`/name 충돌 시 실행하지 않고 plan refresh를 요구한다.
- profile별 reserved VMID range는 2차 기능으로 둔다.

### Q7. Terraform state/backend 정책 — 결정됨

결정:

- MVP는 Terraform local backend를 사용한다.
- state는 Git에 넣지 않는다.
- 기본 경로는 `/mnt/hermes_data/공통/iac-state/gjallar/<manifest_id>/terraform.tfstate`다.
- Gjallar job은 per-`proxmox_vmid` lock과 Terraform state lock을 확인한다.
- apply 전 state와 manifest의 `proxmox_vmid`/name 매핑이 다르면 red risk로 막는다.
- apply 후 state backup/checksum과 observed snapshot을 남긴다.
- S3/MinIO remote backend와 state migration은 2차 기능으로 둔다.

### Q8. VM 생성 Review & Confirm 화면 — 결정됨

결정:

- VM 생성은 일반 Confirm 버튼으로 승인한다.
- yellow risk가 있으면 경고 체크박스를 명시적으로 요구한다.
- red risk가 있으면 approve/execute 버튼을 비활성화한다.
- VM 생성에는 typed confirmation을 요구하지 않는다.
- typed confirmation은 VM 삭제, snapshot rollback, disk delete 같은 destructive 작업에만 사용한다.

Review & Confirm 필수 표시 항목:

1. 생성될 VM 이름
2. VMID
3. target node
4. storage
5. template
6. CPU/RAM/Disk
7. network / IP
8. Terraform state path
9. 첫 power on 포함 여부
10. smoke timeout 요약
11. red/yellow risk summary
12. plan artifact link
13. Git commit 예정 diff 요약

### Q9. Heimdall ↔ Gjallar 연결 경계 — 결정됨

결정: MVP는 느슨한 연결로 시작하고, 2차에서 자동 등록/공용 manifest를 재검토한다.

MVP:

- Gjallar는 VM candidate/readiness/risk를 read-only API로 제공한다.
- Gjallar는 Proxmox/VM 상태의 source of truth다.
- Heimdall은 deploy target registry를 소유한다.
- Heimdall은 배포 전 Gjallar readiness/risk를 조회할 수 있다.
- Gjallar는 Heimdall registry에 직접 write하지 않는다.
- Hermes/user가 Gjallar candidate를 보고 Heimdall target 승격 여부를 결정한다.

2차 재검토:

- Gjallar가 Heimdall target registry에 자동 등록할지
- 공용 runtime-target manifest를 둘지
- active target 승격 정책을 어떻게 둘지

### Q10. 독립 전원 제어 정책 — 결정됨

결정:

- VM 생성 flow의 첫 power on은 VM 생성 승인 1회에 포함한다.
- 이미 존재하는 VM의 power on / graceful shutdown / reboot는 일반 Confirm을 요구한다.
- red risk가 있으면 차단한다.
- yellow risk가 있으면 경고 체크박스를 요구한다.
- hard stop/reset은 MVP에서 제외하고, 2차에서 typed confirmation 대상으로 재검토한다.

## 2. 2차 질문

- snapshot 생성/주기 백업 정책
- VM 삭제 UX와 typed confirmation 문구
- runtime target active 전환 정책은 2차에서 별도 결정
- hard stop/reset typed confirmation 문구
- profile별 bootstrap 수준
- legacy code에서 살릴 테스트/모듈 기준

## 3. 지금 묻지 않아도 되는 질문

- 멀티 tenant RBAC
- VM console 방식
- Kubernetes/OpenStack 지원
- 앱 배포/로그/DB migration
