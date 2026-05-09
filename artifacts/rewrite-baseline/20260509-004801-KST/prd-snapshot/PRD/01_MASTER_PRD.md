# Gjallar Master PRD

## 0. 목적

이 문서는 Gjallar 재설계의 최상위 PRD다.
코드 구현 지시서가 아니라 **제품 정체성, MVP 범위, 안전 원칙, 구현 전제**를 고정한다.

## 1. 제품 정체성

Gjallar는 **Proxmox를 VMware처럼 사용할 수 있게 해주는 VM/인프라 운영 콘솔**이다.

핵심 표현:

> Gjallar = Proxmox-as-VMware Console

Gjallar는 단순 VM 생성 스크립트 UI가 아니다.
사용자가 Proxmox 클러스터, 노드, VM, 템플릿, 네트워크, 리스크, 작업 이력을 한 화면에서 이해하고 안전하게 조작하게 해주는 제품이다.

## 2. 사용자와 제품화 방향

초기 사용자는 홈랩/소규모 인프라 운영자다.

단기 목표:

- 3-node Proxmox 홈랩 운영 가시화
- VM 생성/상태/위험/검증 표준화
- 사람과 자동화가 함께 쓸 수 있는 안정적 API 기반 마련

중장기 목표:

- 회사 내부 인프라 운영자 또는 소규모 팀용 제품화 가능성 고려
- MVP에서는 단일 사용자 중심
- 단, 데이터 모델에는 `owner`, `actor`, `requested_by`, `approved_by` 확장 여지를 남김

## 3. Gjallar가 소유하는 것

- Proxmox cluster/node/VM 인벤토리
- VM 생성
- VM 일반 전원 제어: power on / graceful shutdown / reboot, 단 첫 구현 MVP에서는 VM 생성 flow 안의 first power on만 구현
- VM IP와 qemu-guest-agent 상태
- 노드 CPU/RAM/Disk 상태
- Proxmox 리스크/헬스/readiness
- VM/Profile/Template/Network/Storage manifest
- VM 생성 전 preflight
- VM 생성 후 smoke 검증
- Terraform/Ansible/Proxmox 작업 이력
- 위험 작업 Review & Confirm

## 4. Gjallar가 소유하지 않는 것

- 앱 빌드/배포/restart/log/health
- 앱 컨테이너 이미지 tag/release 운영
- 앱 DB migration
- Kubernetes/OpenStack 관리
- 임의 shell 실행 플랫폼
- 멀티 tenant RBAC

외부 앱 운영 도구가 Gjallar를 참고할 수는 있다.
하지만 Gjallar PRD의 중심은 외부 배포가 아니라 **VM/Proxmox 계층**이다.

Heimdall 연계 MVP 경계:

- Gjallar는 VM candidate/readiness/risk를 read-only API로 제공한다.
- Gjallar는 Proxmox/VM 상태의 source of truth다.
- Heimdall은 deploy target registry를 소유한다.
- Heimdall은 배포 전 Gjallar readiness/risk를 조회할 수 있다.
- Gjallar는 MVP에서 Heimdall registry에 직접 write하지 않는다.
- Gjallar candidate를 Heimdall target으로 승격할지는 Hermes/user가 결정한다.
- 자동 등록, 공용 runtime-target manifest, active target 승격 정책은 2차에서 재검토한다.

## 5. MVP 범위

### 포함

- Proxmox 노드 목록 보기
- VM 목록 보기
- VM 상세 상태 보기
- VM 생성
- VM 생성 flow 안의 first power on
- VM IP / qemu-guest-agent 상태 확인
- 노드 CPU/RAM/Disk 상태
- 리스크/경고 표시
- 생성 전 preflight 검증
- 생성 후 smoke 검증
- Terraform/Proxmox 작업 이력, Ansible 이력은 Stage B 이후 추가

### 2차 기능

- VM 삭제
- 기존 VM 대상 독립 power on / graceful shutdown / reboot
- hard stop / reset
- 스냅샷 생성/복구
- VM 리소스 변경
- 템플릿 생성/관리
- Hermes 승인 대기/요청 이력
- 주기적 백업/스냅샷 정책

### 3차 기능

- VM 콘솔 접근

## 6. 핵심 사용자 플로우

### 6.1 Dashboard

클러스터 상태, 노드 상태, 주요 리스크, 최근 작업을 확인한다.

### 6.2 Infra Explorer

Nodes, VMs, VM Detail을 한 화면에서 이어서 본다.

표시 항목:

- 노드 CPU/RAM/Disk
- VM power status
- VM IP
- guest-agent 상태
- owner/role/profile
- risk 상태
- 최근 작업 이력

### 6.3 Create VM

VM 생성은 profile 기반 wizard로 진행한다.
MVP에서 실제 생성 가능한 profile은 `general-vm` 하나다.
`general-vm`은 일반 VM 생성용 기본 profile이며, 앱 실행 서버/개발 서버/DB 서버 bootstrap은 포함하지 않는다.
`runtime-server`, `dev-server`, `db-server`는 2차 profile 후보로 남기되 MVP 화면 선택지에는 노출하지 않는다.

기본 흐름:

1. VM profile 선택
2. target node 선택
3. template 확인
4. network profile 선택
5. IP mode 선택: DHCP 또는 static
   - 기본/추천값은 static
   - bridge는 선택 target node와 NetworkProfile의 node_bridges mapping으로 결정
   - MVP target node `yoonmanserver2`, `yoonmanserver3`를 모두 지원
6. CPU/RAM/Disk 기본값 확인 또는 제한 내 override
   - 기본값: 2 vCPU / 4096MB RAM / 40GB disk
   - profile limit 안에서만 override 허용
7. cloud-init access 기본값 확인
   - user: `yoon`
   - SSH key: operator default public key
   - password login: disabled
8. preflight
9. plan
10. Review & Confirm
11. manifest commit
12. Terraform/Proxmox apply: clone + hardware/cloud-init 설정을 powered-off 상태로 완료
13. apply/config 성공 시 첫 power on
14. smoke 검증: cloud-init/guest-agent/IP/SSH
15. Stage B minimal Ansible 검증은 Stage A smoke 안정화 후 별도 slice에서 추가
16. Runtime Target 후보 표시는 VM 생성 flow 안정화 후 별도 slice에서 추가

MVP VM 이름/`proxmox_vmid` 정책:

- `general-vm` 기본 이름은 `gjallar-vm-<YYYYMMDD>-<short_job_id>` 형식으로 추천한다.
- MVP UI에서는 VMID를 사용자가 직접 입력하게 하지 않는다.
- `proxmox_vmid`는 Proxmox `nextid`를 기준으로 plan/preflight 단계에서 자동 할당한다.
- 생성될 VM manifest에는 apply 전 resolved `proxmox_vmid`를 기록한다.
- apply 직전 `proxmox_vmid`/name 중복을 다시 확인하고, 충돌하면 실행을 막고 plan refresh를 요구한다.
- profile별 reserved VMID range 정책은 2차 기능으로 둔다.

MVP readiness timeout 기본값:

- first power on task timeout: 5분
- cloud-init timeout: 15분
- guest-agent timeout: 5분
- IP 발견 timeout: 5분
- SSH timeout: 5분
- minimal Ansible verify timeout: 5분

Timeout은 실패 원인을 명확히 표시하기 위한 기본값이며, 나중에 Settings/Profile에서 조정 가능하게 둘 수 있다.

### 6.4 Jobs / Runs

Terraform/Ansible/Proxmox 작업 이력을 확인한다.

### 6.5 Risks / Alerts

가장 중요한 화면 중 하나다.

표시 대상:

- 잘못된 VM 삭제 가능성
- 잘못된 노드 선택
- IP 충돌
- storage 부족
- cloud-init/bootstrap 실패
- Terraform state 불일치
- Proxmox API credential 문제
- 잘못된 VM을 외부 runtime target으로 쓰는 문제
- 사용자가 위험한 작업인지 모르고 승인하는 문제

## 7. VM 생성 방향

원래 목적은 **원터치 VM 생성 + 기본 세팅 + 운영 가능한 VM 준비**다.

중요 원터치 작업:

- VM 생성
- VM 기본 세팅
- 앱 실행 대상 후보가 될 수 있는 VM 준비

MVP에서는 두 실행 방식을 모두 지원한다.

### 기본 모드

사용자가 입력/승인하면 끝까지 자동 진행한다.

### 고급/디버그 모드

각 단계를 따로 실행/재시도할 수 있다.

- Manifest 생성
- Preflight
- Plan
- Commit
- Apply/configure powered-off
- First power on
- Smoke
- Optional Ansible verify
- Runtime target 후보/readiness 표시

## 8. Template / Hardware 설정 원칙

VM은 template 기반으로 생성한다.

기본 순서:

1. template clone, 가능하면 powered-off 유지
2. CPU/RAM/Disk를 profile 기본값 또는 승인된 override로 설정
3. cloud-init/network 설정
4. Terraform/Proxmox apply/config 성공 여부 확인
5. 성공한 경우에만 첫 부팅
6. smoke
7. 필요 시 minimal Ansible 검증

Terraform/Proxmox apply 또는 cloud-init 설정 단계가 실패하면 Gjallar는 첫 power on을 실행하지 않는다.
first power on 이후 readiness timeout이 발생하면 VM은 자동 삭제하지 않고 `created_but_not_ready`로 표시한다.

CPU/RAM/Disk는 raw 입력을 먼저 보여주지 않는다.
사용자는 profile을 고르고, 필요할 때만 고급 설정을 펼친다.

## 9. Manifest 원칙

VM/profile manifest는 필요하다.
DB snapshot만 source of truth로 두면 재설계/복구/검증이 어려워진다.

- Git/IaC repo: desired state
- Job workspace: 실행 사본
- Terraform state: 실제 리소스 매핑 장부
- Gjallar DB: job history, approvals, observations, artifact references
- Proxmox: actual state

MVP Terraform state 정책:

- backend는 local backend를 사용한다.
- state 위치는 `/mnt/hermes_data/공통/iac-state/gjallar/<manifest_id>/terraform.tfstate`로 둔다.
- state는 Git에 넣지 않는다.
- Gjallar job은 per-`proxmox_vmid` lock과 Terraform state lock을 확인한 뒤 plan/apply한다.
- state와 manifest의 `proxmox_vmid`/name 매핑이 다르면 red risk로 실행을 막는다.
- apply 후 state backup/checksum과 observed snapshot을 남긴다.
- S3/MinIO remote backend와 state migration은 2차 기능으로 둔다.

## 10. 안전 승인 정책

- 읽기/상태 조회: 자동 가능
- VM 생성 dry-run/preflight: 자동 가능
- VM 생성 실행: 사용자 승인 필요
- 독립 power on: 2차 power-action slice에서 일반 Confirm 필요
- 독립 graceful shutdown/reboot: 2차 power-action slice에서 일반 Confirm 필요
- hard stop/reset: MVP 제외, 2차 typed confirmation 후보
- 스냅샷 생성: 2차. 사용자 승인 또는 설정 기반 주기 백업
- 스냅샷 rollback: 반드시 승인
- VM 삭제: 반드시 승인
- 디스크 삭제: 반드시 승인
- 노드/스토리지 변경: 반드시 승인

red risk는 승인으로도 우회하지 않는다.
yellow risk는 Review & Confirm 이후 실행 가능하다.

VM 생성 Review & Confirm에는 아래를 반드시 보여준다.

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

VM 생성은 일반 Confirm 버튼으로 승인한다.
yellow risk가 있으면 경고 체크박스가 필요하다.
VM 생성에는 typed confirmation을 요구하지 않고, 삭제/rollback/destructive 작업에만 typed confirmation을 요구한다.

독립 전원 제어 정책:

- VM 생성 flow의 첫 power on은 VM 생성 승인 1회에 포함한다.
- 이미 존재하는 VM의 power on / graceful shutdown / reboot는 2차 power-action slice에서 일반 Confirm을 요구한다.
- red risk가 있으면 차단한다.
- yellow risk가 있으면 경고 체크박스를 요구한다.
- hard stop/reset은 MVP에서 제외하고, 2차에서 typed confirmation 대상으로 재검토한다.

## 11. 구현 원칙

1. PRD 확정
2. 화면 정의
3. API 계약 정의
4. Manifest schema 정의
5. 테스트 작성
6. 구현
7. fresh review

기존 코드는 보존 전제가 아니다.
현재 방향은 “frontend/backend 대부분 새로, 유용한 테스트/문서만 검증 후 보존”이다.
