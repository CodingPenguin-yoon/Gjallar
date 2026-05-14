# Gjallar Master PRD

## 0. 목적

이 문서는 Gjallar 재설계의 최상위 PRD다.
코드 구현 지시서가 아니라 **제품 정체성, MVP 범위, 안전 원칙, 구현 전제**를 고정한다.

현재 MVP 방향은 `drs-advisor/README.md`가 우선한다.
이 문서의 기존 create-first 내용은 보조 capability와 역사적 설계 맥락으로 유지하되, 현재 제품 중심은 DRS Advisor다.

2026-05-13 Create VM profile/template/network update:
Create VM의 현재 target design은
[`docs/engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md)다.
아래 create-first 설명 중 `general-vm` 단일 생성, `server-net`/NetworkProfile mapping, template catalog/manifest, first power-on 포함 흐름은 이 target design으로 대체한다.
DRS Advisor source-of-truth 우선순위는 그대로 유지한다.

## 1. 제품 정체성

Gjallar는 **Proxmox 엔터프라이즈 운영 플랫폼**이다.

핵심 표현:

> Gjallar = Proxmox Operations Control Tower with DRS Advisor

Gjallar는 백업 제품이 아니며, VMware DRS 대체라고 주장하지 않는다.
사용자가 Proxmox 클러스터, 노드, VM, migration/HA 상태, 리스크, 작업 이력을 한 화면에서 이해하고 안전하게 조작하게 해주는 제품이다.
MVP 핵심은 Proxmox-native migration/HA를 관찰하고, CPU/Memory 중심 추천을 만들고, 운영자 승인 후 live migration을 실행/추적하는 DRS Advisor다.
VM 생성은 삭제하지 않고 보조적인 기존 capability로 유지한다.

## 2. 사용자와 제품화 방향

제품 판단의 1차 기준은 엔터프라이즈 인프라 운영팀이다.
특히 VMware 운영 경험을 Proxmox로 옮긴 뒤, DRS/vCenter류 운영 지원이 약해지는 것을 보완하려는 팀을 우선한다.
홈랩 사용자는 빠른 검증과 실험 환경으로 중요하지만, 기능 충돌 시 엔터프라이즈 안정성, 감사, 재시작 복구성, 보수적 실행 정책을 우선한다.

단기 목표:

- 3-node Proxmox 홈랩에서 엔터프라이즈 운영 패턴 검증
- DRS Advisor 기반 노드 부하/VM 이동 추천/승인 실행 표준화
- VM 생성/상태/위험/검증 capability 유지
- 사람과 자동화가 함께 쓸 수 있는 안정적 API 기반 마련

중장기 목표:

- VMware에서 Proxmox로 이전했거나 이전을 검토하는 엔터프라이즈 운영팀용 제품화 가능성 고려
- Proxmox 운영팀이 백업 도구, HA, live migration, 리소스 정책, 작업 이력을 한 콘솔에서 검증하도록 확장
- MVP에서는 단일 사용자 중심
- 단, 데이터 모델에는 `owner`, `actor`, `requested_by`, `approved_by` 확장 여지를 남김

## 3. Gjallar가 소유하는 것

- Proxmox cluster/node/VM 인벤토리
- DRS Advisor recommendation, VM mobility 판단, route status 판단
- VM metadata/policy/fingerprint assertion
- operation lock, migration approval, Proxmox UPID 추적, reconciliation 상태
- VM 생성
- VM 일반 전원 제어: power on / graceful shutdown / reboot, 단 Create VM target은 생성 성공 시 powered-off/stopped로 완료하고 시작 action은 별도 follow-up으로 둔다
- VM IP와 qemu-guest-agent 상태
- 노드 CPU/RAM/Disk 상태
- Proxmox 리스크/헬스/readiness
- VM 생성 의도, profile seed, storage intent, VM manifest/job artifact. Template과 Network 실제 선택은 Proxmox live inventory에서 다시 읽는다.
- VM 생성 전 preflight
- VM 생성 후 follow-up smoke 검증
- Terraform/Ansible/Proxmox 작업 이력
- 위험 작업 Review & Confirm

주의: Gjallar가 Proxmox actual state의 원본은 아니다.
VM 존재 여부, 현재 노드, running 상태, task 상태, cluster health는 Proxmox current state에서 다시 읽어야 한다.
Gjallar DB는 운영 의도, 감사, 정책, fingerprint 승인, 작업 이력을 저장한다.

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
- Proxmox actual state는 Proxmox가 source of truth이며, Gjallar는 이를 읽어 운영 판단과 정책 상태를 제공한다.
- Heimdall은 deploy target registry를 소유한다.
- Heimdall은 배포 전 Gjallar readiness/risk를 조회할 수 있다.
- Gjallar는 MVP에서 Heimdall registry에 직접 write하지 않는다.
- Gjallar candidate를 Heimdall target으로 승격할지는 Hermes/user가 결정한다.
- 자동 등록, 공용 runtime-target manifest, active target 승격 정책은 2차에서 재검토한다.

## 5. MVP 범위

현재 MVP 기준 문서는 `drs-advisor/README.md`다.
아래 DRS Advisor 범위가 현재 우선이며, 기존 create-first 범위는 보조 capability와 후속 slice로 유지한다.

### 현재 MVP 포함

- Dashboard의 노드 행 단위 사용률 중심 화면
- Dashboard 상위 1~3개 DRS 추천 요약
- `/placement` route를 DRS Advisor 화면으로 전환
- DRS Advisor 전체 추천 테이블
- CPU/Memory 중심 추천: 최근 15분 평균 + peak
- resource polling 1분, inventory/HA/storage polling 5분
- VM metadata/policy/fingerprint 기반 실행 보호
- Allowed VM 대상 manual approved live migration
- final pre-check, Confirm modal, operation lock
- Proxmox UPID tracking
- Jobs/Runs 로그와 artifact
- success/failed/needs_reconciliation 및 Reconcile Now
- restart 후 Proxmox current state 재구성과 fingerprint match 기반 metadata/policy reattachment

### 보조/기존 capability

- Proxmox 노드 목록 보기
- VM 목록 보기
- VM 상세 상태 보기
- VM 생성
- VM 생성 결과 powered-off/stopped 확인. First power-on은 별도 follow-up action.
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
현재 target profile은 UI-visible, read-only Gjallar DB seed preset이다.
초기 enabled profile은 `general-vm`, `runtime-server`, `development-vm` 세 개다.
Profile은 CPU/RAM/Disk 기본값과 limit, template requirement, access recommendation만 제공하며 target node/storage/network/template/power/version을 bind하지 않는다.
`dev-server`, `db-server`는 초기 enabled profile이 아니다.

기본 흐름:

1. VM profile 선택
2. target node 선택
3. Proxmox live inventory에서 template 선택
   - Gjallar template catalog/registration window는 target에 없다.
   - 선택 profile requirement를 만족하지 못하는 template은 보이되 disabled 처리한다.
4. 선택 target node의 active live bridge 선택
   - Create VM target은 `network_id` 또는 `server-net`을 사용하지 않는다.
   - Network tab policy/subnet/range는 future integration이며 Create VM source of truth가 아니다.
5. IP mode 선택: DHCP 또는 static
   - static은 `static_ip`, `prefix`, `gateway`가 모두 필요하다.
   - DHCP는 허용하지만 guest-agent/inventory discovery가 나중에 필요하다는 warning을 표시한다.
6. CPU/RAM/Disk 기본값 확인 또는 제한 내 override
   - 선택 profile 기본값으로 reset하며 profile limit 안에서만 override 허용
7. cloud-init access 기본값 확인
   - user: `yoon`
   - SSH key: operator default public key
   - password login: disabled
8. preflight
9. plan
10. Review & Confirm
11. manifest commit
12. Terraform/Proxmox apply: clone + hardware/cloud-init 설정을 powered-off 상태로 완료
13. 생성 성공 상태는 powered-off/stopped다.
14. 첫 power-on, smoke, guest-agent discovery, SSH verification은 별도 follow-up stage다.
15. Runtime Target 후보 표시는 VM 생성 flow 안정화 후 별도 slice에서 추가

MVP VM 이름/`proxmox_vmid` 정책:

- `general-vm` 기본 이름은 `gjallar-vm-<YYYYMMDD>-<short_job_id>` 형식으로 추천한다.
- MVP UI에서는 VMID를 사용자가 직접 입력하게 하지 않는다.
- `proxmox_vmid`는 Proxmox `nextid`를 기준으로 plan/preflight 단계에서 자동 할당한다.
- 생성될 VM manifest에는 apply 전 resolved `proxmox_vmid`를 기록한다.
- apply 직전 `proxmox_vmid`/name 중복을 다시 확인하고, 충돌하면 실행을 막고 plan refresh를 요구한다.
- profile별 reserved VMID range 정책은 2차 기능으로 둔다.

Readiness timeout 기본값:

아래 timeout은 first power-on/smoke가 별도 follow-up stage로 구현될 때의 historical/default context다.
2026-05-13 Create VM target success 조건은 powered-off/stopped 생성 완료다.

- future first power-on task timeout: 5분
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
아래 first power-on/smoke 단계는 별도 follow-up stage이며, Create VM target success는 powered-off/stopped다.

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
- state 위치는 `/mnt/hermes_data/IaC-state/gjallar/<manifest_id>/terraform.tfstate`로 둔다.
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
9. power policy: `stopped`
10. smoke timeout 요약
11. red/yellow risk summary
12. plan artifact link
13. Git commit 예정 diff 요약

VM 생성은 일반 Confirm 버튼으로 승인한다.
yellow risk가 있으면 경고 체크박스가 필요하다.
VM 생성에는 typed confirmation을 요구하지 않고, 삭제/rollback/destructive 작업에만 typed confirmation을 요구한다.

독립 전원 제어 정책:

- 현재 Create VM target은 성공 시 powered-off/stopped로 완료한다.
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
