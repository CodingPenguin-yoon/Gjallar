# Gjallar Safety / Preflight PRD

## 0. 목적

VM/Proxmox 작업에서 치명적 실수를 막기 위한 risk, approval, preflight 정책을 정의한다.

## 1. Risk Level

### Red

실행 금지. 사용자 승인으로도 우회하지 않는다.

예:

- `proxmox_vmid`/name/IP 충돌
- static IP가 허용 범위 밖
- reserved IP 사용
- target node/storage 없음
- storage 부족
- Terraform state lock 또는 state 불일치
- Proxmox credential 오류
- destroy/delete plan 포함
- template 불일치

### Yellow

Review & Confirm 필요.

예:

- 리소스 여유가 낮음
- guest-agent 응답 지연
- 오래된 observed snapshot
- smoke 일부 실패지만 VM 자체는 접근 가능
- node 선택이 권장과 다름

### Green

자동 진행 가능.
읽기, 조회, dry-run, schema validation은 green이면 자동 가능하다.

## 2. Approval 정책

| 작업 | 정책 |
|---|---|
| 읽기/상태 조회 | 자동 가능 |
| VM 생성 dry-run/preflight | 자동 가능 |
| VM 생성 실행 | 사용자 승인 필요 |
| 독립 power on | 2차 power-action slice. 일반 Confirm 필요 |
| 독립 graceful shutdown/reboot | 2차 power-action slice. 일반 Confirm 필요 |
| hard stop/reset | MVP 제외. 2차 typed confirmation 후보 |
| 스냅샷 생성 | 2차. 사용자 승인 또는 설정 기반 주기 실행 |
| 스냅샷 rollback | 반드시 승인 |
| VM 삭제 | 반드시 승인 |
| 디스크 삭제 | 반드시 승인 |
| node/storage/network 정책 변경 | 반드시 승인 |

## 2.1 VM 생성 Review & Confirm 정책

VM 생성은 일반 Confirm 버튼으로 승인한다.
yellow risk가 있으면 경고 체크박스를 명시적으로 체크해야 한다.
red risk는 승인으로도 우회할 수 없으며 approve/execute 버튼을 비활성화한다.

Review & Confirm에 반드시 표시할 것:

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

VM 삭제, snapshot rollback, disk delete 같은 destructive 작업은 2차 기능이며 typed confirmation을 반드시 요구한다.

## 2.2 독립 전원 제어 정책 — deferred power-action slice

현재 powered-off create slice에서 VM 생성 승인과 Terraform apply 승인은 첫 power on을 포함하지 않는다.
첫 power on은 apply/config 성공 후 별도 create-readiness slice에서 명시 확인을 붙여 실행한다.
이미 존재하는 VM의 전원 작업은 별도 action으로 본다.
첫 구현 MVP에서는 이 별도 action을 구현하지 않는다.

2차 power-action slice 허용 action:

- power on: 일반 Confirm
- graceful shutdown: 일반 Confirm
- reboot: 일반 Confirm

항상 제외 또는 destructive 2차 검토 action:

- hard stop
- reset
- kill/power off 강제 중단

Risk 처리:

- red risk가 있으면 전원 action을 차단한다.
- yellow risk가 있으면 경고 요약과 체크박스를 요구한다.
- 사용자가 어떤 VM에 어떤 전원 action을 실행하는지 VM name/VMID/node/IP를 확인하게 한다.
- hard stop/reset은 2차에서 typed confirmation 대상으로 재검토한다.

## 3. Preflight 단계

VM 생성 전 최소 검사:

1. profile schema 검증
2. template 존재/상태 검증
3. target node 존재/online 검증
4. storage 존재/여유 검증
5. 선택 target node의 NetworkProfile bridge mapping 검증
6. 선택 target node에 mapped bridge가 실제 존재하는지 Proxmox live inventory 검증
7. `proxmox_vmid`/name 중복 검증
8. CPU/RAM/Disk profile limit 검증
9. 요청 디스크가 선택 템플릿 디스크보다 작지 않은지 검증
9. static IP allowed range 검증
10. reserved IP 검증
11. 기존 VM/IP 충돌 검증
12. Terraform state lock 검증
13. plan에 destroy/delete 포함 여부 검증
14. Proxmox credential scope 검증
15. Runtime Target 등록 조건 검증은 첫 구현 MVP에서 제외하고 Runtime Target slice에서 추가

Network/Bridge/IP 결정:

- NetworkProfile은 `yoonmanserver2`, `yoonmanserver3` 두 target node의 bridge mapping을 가진다.
- 초기 fixture 후보는 두 노드 모두 `vmbr0`이다.
- bridge는 선택 target node 기준으로 resolve 한다.
- mapping 누락 또는 live inventory상 bridge 없음은 red risk다.
- IP mode는 `dhcp`, `static` 둘 다 지원하고 기본/추천값은 `static`이다.

IP 충돌 검사의 MVP evidence는 `Network Profile manifest + Proxmox observed state`다.
충돌 감지가 부족하면 DHCP/ARP/라우터 lease 조회를 read-only evidence로 추가한다.
별도 IP inventory 또는 Gjallar 자체 IPAM은 MVP 범위 밖이다.

`proxmox_vmid`/name 정책:

- MVP `proxmox_vmid`는 Proxmox `nextid` 기반으로 자동 할당한다.
- 사용자의 직접 VMID 입력은 MVP 기본 UI에 노출하지 않는다.
- plan/preflight에서 resolved 된 `proxmox_vmid`라도 apply 직전 다시 중복 확인한다.
- `proxmox_vmid`/name 충돌은 red risk이며 승인으로 우회할 수 없다.
- profile별 reserved VMID range는 2차 기능으로 둔다.

Terraform state 정책:

- MVP backend는 local backend다.
- state 위치는 `/mnt/hermes_data/IaC-state/gjallar/<manifest_id>/terraform.tfstate`다.
- state는 Git에 넣지 않는다.
- plan/apply 전 per-`proxmox_vmid` lock과 Terraform state lock을 확인한다.
- state에 기록된 `proxmox_vmid`/name과 manifest resolved `proxmox_vmid`/name이 다르면 red risk다.
- state 파일 누락, 파싱 실패, lock 잔존, state drift는 red/yellow risk로 표시하고 원인 evidence를 남긴다.
- apply 후 state backup/checksum과 observed snapshot을 저장한다.

## 4. Smoke 단계

VM 생성 후 최소 검사:

- VM power status
- guest-agent 응답
- IP 확인
- SSH 접근 가능 여부
- cloud-init 완료 여부
- profile별 bootstrap 결과
- Runtime Target slice가 구현된 경우 candidate/readiness 조건 충족 여부

Smoke 실패 시 VM은 남길 수 있지만, runtime target은 active가 되지 않는다.
Gjallar는 smoke/cloud-init/SSH/guest-agent/Ansible 실패 VM을 자동 삭제하지 않는다.
실패한 VM은 `created_but_not_ready` 상태와 cleanup 후보로 표시하고, 삭제는 2차 기능에서 명시 승인 후 처리한다.

첫 power on은 apply/config 성공 뒤에만 실행한다.
Terraform/Proxmox apply 또는 cloud-init/network 설정 단계가 실패하면 첫 power on은 생략한다.
Terraform/provider/template 설정이 VM을 자동 부팅시키는 경우 preflight 또는 plan review에서 위험으로 표시한다.
Ansible 검증은 Stage B에서 붙인다. SSH가 필요하므로 첫 power on 이후에만 실행 가능하며, 실패 시 추가 reboot/power action 없이 not-ready로 표시한다.

MVP readiness timeout 기본값:

- first power on task: 5분
- cloud-init: 15분
- guest-agent: 5분
- IP 발견: 5분
- SSH: 5분
- minimal Ansible verify: 5분, Stage B를 붙인 뒤 사용

Timeout은 위험을 숨기지 않고 실패 stage로 기록한다.
first power on 이후 timeout은 `created_but_not_ready`로 표시하고, apply/config 단계 timeout은 `provision_failed_not_booted`로 표시한다.

## 5. 치명 실패 목록

아래 실패는 모두 PRD 설계에서 우선 방어해야 한다.

- 잘못된 VM 삭제
- 잘못된 노드에 VM 생성
- IP 충돌
- storage 부족 상태에서 생성 진행
- cloud-init/bootstrap 실패를 성공으로 오판
- Terraform state 꼬임
- Proxmox API credential 노출
- 잘못된 VM을 runtime target으로 노출
- 사용자가 위험한 작업인지 모르고 승인

## 6. UI 표시 원칙

위험은 숨기지 않는다.

- red: 실행 버튼 disabled + 이유 표시
- yellow: 경고 요약 + 상세 펼치기 + 명시 승인
- green: 자동 진행 가능하지만 artifact는 남김

사용자에게 “무엇이 바뀌는지”를 plan diff로 보여줘야 한다.

## 7. Proxmox Credential 정책

Gjallar MVP는 Proxmox API Token 방식으로 고정한다.

원칙:

- Proxmox root/password 또는 개인 계정 password 저장 방식은 사용하지 않는다.
- token id/secret은 Git, PRD, manifest, Terraform state, DB, artifact, 로그, UI/API 응답에 저장하지 않는다.
- backend runtime secret으로만 주입한다.
- MVP에서는 `.env` 또는 OS credential file을 사용할 수 있으나, `.env`는 gitignored 상태여야 하며 commit하면 안 된다.
- token scope는 VM 조회/생성/전원/guest-agent 확인에 필요한 최소 권한으로 제한한다.
- readiness/preflight는 token 값이 아니라 설정 여부, endpoint 접근 여부, 권한 검증 결과만 보여준다.
