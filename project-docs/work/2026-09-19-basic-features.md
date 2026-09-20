# 기본 기능 완성 — M1~M6

- 상태: `APPROVED` — 사용자의 2026-09-19 구현·자동 검증·문서 갱신 지시. live 실행·운영 DB·설치·배포 승인은 포함하지 않는다.
- 기준: [PRD](../prd.md), [로드맵](../roadmap.md), [개발 안내](../development.md).

## 목표와 범위

관리형 연결의 정지 VM CPU 코어·메모리 변경을 웹 VM 상세와 CLI에서 대상 선택 → 현재/변경 값 확인 → 실행 → 실제 설정 확인까지 연결한다. M1 기존 연결·전원 흐름의 실사용 차단을 함께 확인한다. 대시보드 전체 구성, 기존 TUI와 완료된 기능을 보존한다.

첫 단위는 CPU `cores`와 메모리 MiB만 변경한다. socket topology·CPU 종류·balloon 설정 자체·실행 중 hotplug·자동 종료는 변경하지 않는다. 지원 조건과 입력 한계는 PVE 계약을 확인한 뒤 구현한다. 관리형 생성 권한 공백과 나머지 VM-02~06은 M2의 미완료 필수 항목으로 유지한다.

## 고위험 변경의 범위·검증·복구

- 권한: 선택 VM에 `VM.Config.CPU`, `VM.Config.Memory`만 추가하는 선택 feature를 도입한다. 기존 read/power 역할을 변경하지 않고 별도 고정 역할을 사용한다. read 또는 power만 선택한 기존 연결은 수정 권한을 얻지 않는다. runtime admission과 endpoint·필드 allowlist를 함께 검사한다.
- 기존 연결 갱신: 새 등록 → 정확한 권한 계획 확인 → 새 token 발급·검증 → 기존 CAS/drain 경계를 통한 명시적 전환 → 전체 서버 재시작을 재사용한다. 이전 revision/token은 보존한다. 기존 token ACL을 몰래 늘리거나 env로 우회하지 않는다. 전환·발급·폐기는 실환경 별도 승인 대상이다.
- 실행: 기존 Operation store·동일 VMID target lock·idempotency·GET-only recovery를 재사용한다. 변경 전/직전 정지 상태와 config digest를 확인하고, 변경 후 실제 config/status가 기대값인지 검증한다. 응답 유실·부분 반영·검증 실패는 성공으로 처리하거나 mutation을 자동 재전송하지 않는다.
- DB: 필요 변경은 새 migration으로만 작성하며 기존 migration·운영 DB를 수정하지 않는다. schema 변경이 필요하면 정확한 제약·격리 upgrade 검증·복구 제한을 이 문서에 먼저 보완한다.
- VM-01 DB 구체화: 새 `20260919_0031`은 `operation_locks` action check에 `vm_compute`만 추가한다. 기존 row·index·VMID 직렬화는 보존한다. downgrade는 새 action lock row가 있으면 거부해 기록을 삭제하지 않는다. 격리 SQLite migration·metadata와 PostgreSQL 검증을 수행하며 운영 적용은 대기한다.
- VM-01 admission은 같은 DB transaction에서 target lock·Operation·recovery item을 준비한다. crash로 복구 기록 없는 신규 잠금이 생기지 않도록 원자성을 검사한다. dispatch 직전 lease fence를 commit하고 기존 GET-only runner/수동 observe에 전용 handler를 추가한다. mutation 결과 불명은 조회가 원하는 값과 같아도 응답 완료 근거 없이는 자동 완료·해제하지 않는다.
- 실패 복구: 미확정 변경은 Operation·target lock을 보존하고 조회로 결과를 확인한다. 원래 값 복원도 새 명시적 변경이며 자동 보상하지 않는다. 코드 되돌림은 새 action 기록을 해석할 수 있는 버전으로 제한한다. credential 키·revision·이력은 삭제하지 않는다.

## 구현 순서와 완료 조건

1. M1 관리형 read/power 경로의 코드·테스트 및 웹 현재 화면 확인.
2. 선택적 CPU/메모리 권한과 웹/CLI 연결 갱신 경로, 거부 회귀 검사.
3. VM-01 입력·사전 검토·Operation·잠금·결과/복구 계약과 서버 구현.
4. VM 상세·CLI의 검토/실행/결과 흐름 및 사용자 안내.
5. 오류 입력·권한 부족·상태 drift·중복·부분 반영·단절·불명 결과 자동 검사, 브라우저 확인.
6. `git diff --check`, `pnpm run verify`, `pnpm run verify:container`; 승인된 첫 환경에서 별도 실사용 검증.

서버·웹/CLI·자동 검증·실환경 검증을 별도로 기록한다. 실환경 검증이 남으면 기능이나 Goal 전체를 완료 처리하지 않는다.

## 초기 조사와 제품 결정 대기

- 착수 시 `git status --short`, `git diff --stat` 출력은 비어 있었다. 기존 완료 코드를 보존한다.
- 관리형 연결은 실제로 read/선택 power만 지원하며 CPU/메모리·Create 권한은 없다.
- 관리형 request 경계가 `/access/permissions`만 허용하지만 기존 mutation client는 query string을 포함한 경로를 사용한다. 전원 사전 점검의 실제 차단 여부를 회귀 테스트로 확인한다.
- 현재 열린 Gjallar 브라우저 탭은 없다. 아직 실제 화면 평가는 수행하지 않았다.
- 질문 대기: 첫 지원 환경·테스트 자원, OPS-03 포함 여부, 로드맵의 제한된 M2~M6 범위 확정. 답변과 독립적인 VM-01 구현은 사용자 명시 범위로 진행한다.

## 재개 지점

### 사용자 범위 확정 (2026-09-19)

- M2~M6는 로드맵의 제한된 첫 범위로 진행한다. OPS-03은 첫 버전에 포함하며 변경 종류는 아래 사용자 위임 범위로 확정했다.
- 기존 Gjallar 서버는 없다. 신규 설치 대상·경로·포트·volume은 구현/격리 검증 후 별도 승인한다. 사용자는 추가 질의 없이 맡겨두기를 원한다.
- OPS-03은 사용자 위임에 따라 기존 디렉터리 PVE storage 등록·수정과 VM용 Linux bridge 생성·수정(VLAN-aware 포함)으로 진행한다. 관리망 IP/gateway 변경·물리 NIC 재배치·디스크 포맷·Ceph는 제외한다. 실제 호스트 반영은 별도 승인한다.
- 테스트 VMID 범위는 `40000~40010`. 이번 테스트로 만든 VM은 검증 후 삭제한다. 같은 범위의 기존 자원을 삭제하는 승인은 아니다.
- static IP는 ping과 기존 VM 설정/guest agent 관찰을 함께 사용한다. 후보 네트워크·gateway·node/storage/bridge·첫 서버 환경은 확인 대기이며 무응답만으로 미사용을 보장하지 않는다.
- 정확한 대상·side effect를 구체화하기 전 live 발급·mutation·삭제는 시작하지 않았다.

- 마지막 갱신: 2026-09-19, M1~M6 통합 대조·bridge 물리 장치 표시 판정 수정·독립 프로세스 보존 검증. 이 절의 초기 기록은 보존하며 문서 끝 최신 재개 지점을 따른다.
- 완료: 선택 `compute` feature·고정 최소권한 역할·관리형 endpoint/필드 제한, 기존 연결 갱신 안내, VM-01 domain/service·원자적 admission·GET-only recovery·신규 migration·HTTP route·웹 패널·CLI 검토 파일 흐름 작성.
- 수정 주요 파일: `backend/app/operations/vm_compute/`, `api/v1/vm_compute.py`, `setup_integration/`, `proxmox/client.py`, `20260919_0031_vm_compute_lock.py`, `frontend/src/features/workloads/detail/VmComputePanel.jsx`, `ProxmoxSetupPage.jsx`, `client/src/gjallar_client/compute_workflow.py`와 CLI 및 관련 tests.
- 검증: 등록·managed runtime 19 passed; client 등록/기존 workflow 28 passed. 첫 전체 `pnpm run verify`: client 85 passed; backend 828 passed/28 skipped/3 failed. 3건은 신규 route actor test와 action/recovery allowlist 기대값이며 수정 후 재검증 중. frontend/container/실환경 검증은 아직 완료하지 않았다.
- 환경: backend Python 3.13 venv에 cryptography가 없어 첫 collection 실패. 승인된 네트워크 접근으로 기존 lockfile 의존성을 설치했다. 로컬 Node 26은 지원 기준 Node 24와 다르며 container 검증 필요.
- 화면: 실제 컴포넌트를 외부 호출 없는 격리 Vite `127.0.0.1:5174`에서 확인. 연결 등록 전후와 기존 VM 상세를 시각 확인했다. 대시보드는 변경하지 않았고 VM 상세의 기존 요약/작업 영역을 유지하며 CPU·메모리 흐름을 그 안에 배치했다. 전체 앱 탐색 평가는 아직 남았다. 임시 `.gjallar-review.*`는 검토 종료 시 제거한다.
- 발견/수정: 기존 managed transport는 query string을 거부해 client 권한/active task 조회를 전달하지 못했다. 허용된 GET query만 정규화하며 VM 범위/중복 query/추가 필드를 거부한다. 현재 Start/Shutdown precheck가 해당 메서드를 직접 사용하는 것은 아니므로 기존 전원 작업 전체가 이 버그로 차단됐다고 단정하지 않는다. 암호화 변조 test는 우연히 원문과 같아지는 바이트 대체를 XOR로 수정했다.
- 외부 작업: 발급·mutation·운영 DB·설치·배포 없음, 외부 Operation 없음.
- 다음 행동: 전체 자동 검증 실패 기대값 수정 확인, migration/권한 갱신·경합 검증 강화, 웹 변경/결과 화면 직접 확인, 사용·아키텍처 문서 갱신. VM-01 검증 후 관리형 Create 권한과 VM-02 순서로 진행한다.

### VM-01 검증 묶음 갱신

- 사용자 env token 사용 지시에 따라 GET-only로 PVE 9.0.11, online node 3개, storage/bridge를 확인했다. 관찰 당시 VMID 40000~40010은 비어 있었다. PVE 변경·설치·운영 DB 접근은 하지 않았다. 일시 관찰은 실행 시점의 자원 예약이나 mutation 승인이 아니다.
- 웹 실제 컴포넌트의 격리 화면에서 준비 → 4 cores/4096 MiB 입력 → 검토 → 실행 → 관찰 결과·Operation 링크를 확인했다. fixture 응답이며 live 결과가 아니다. 대시보드는 보존했다.
- 관리형 권한 갱신·VM-01 집중 검사 26개, frontend tests/lint/build 통과. migration 보존·downgrade 거부 및 compute 단위 검사 16개 통과.
- PostgreSQL 17-alpine tmpfs 전용 테스트 컨테이너를 새로 만들었다. 첫 integration 실행은 사전 migration이 필요한 기존 검사 5개에서 실패했고, 해당 임시 DB만 head로 migration한 후 전체 30개 통과했다. 새 동시 요청 검사에서 발견한 공유 transaction의 IntegrityError 후 조회 실패를 lock 삽입 savepoint로 수정했다. 기존 전원/등록/복구 경합도 통과했다.
- 잠금 획득 직전에 다른 동일 요청이 완료된 경우에도 저장 결과를 다시 읽어 재실행하지 않는다. 이 경계의 추가 회귀와 전체 verify/container 검증을 이어간다.
- 다음 행동: 최종 경합 회귀 → 전체 로컬/기준 container 검사 → 임시 UI·DB 정리 → 관리형 Create 권한과 VM-02. 실환경 mutation·신규 설치 승인은 별도 대기이며 Goal/M2 완료 처리하지 않았다.

### VM-01 구현 검증과 다음 권한 단위

- 전체 `pnpm run verify` 통과: client 85, backend 835 passed/31 skipped, frontend tests/lint/build. `pnpm run verify:container` 통과: client 85, backend 835 passed/30 skipped, Node 24 frontend test/lint/build와 runtime 이미지 생성. container의 skip 수는 추가 PostgreSQL 늦은 replay 회귀 1개 작성 전 build snapshot 차이이며 제품 코드는 같다. 해당 추가 회귀 포함 집중 PostgreSQL 3개도 통과했다. `git diff --check` 통과.
- VM-01 구현 검증은 완료, 실환경 변경 검증은 미완료다. API·권한·복구 계약과 웹/CLI 사용법을 architecture/development에 반영했다.
- 다음 관리형 Create 권한 단위: 기존 `vmids`와 별도로 template 원본 ID·생성 대상 ID 목록을 검토한다. template에 Clone, 생성 VMID에 Allocate·필요 config/관찰/전원, 선택 storage에 AllocateSpace, bridge에 SDN.Use를 추가한다. 기존 read/power/compute만 선택한 연결 권한은 보존한다. 새 고정 역할과 새 연결 갱신 경로를 사용한다.
- 기존 boot_and_verify의 고정 cloud-init 조회는 PVE의 `VM.GuestAgent.Unrestricted`가 필요함을 공식 Agent.pm에서 확인했다. 생성 대상 VMID에만 부여하고 권한 계획과 웹/CLI에서 영향을 안내한다. Gjallar managed request는 기존 고정 조회 argv 외 guest-exec를 거부한다. 임의 shell 실행 경로를 도입하지 않는다.
- 실행은 기존 Create plan/승인/Operation/잠금/복구를 유지한다. 관리형 transport는 source template·destination VMID/node/storage/bridge와 config field를 검사한다. 새 DB migration·외부 mutation은 이 권한 단위에 없다. role/token 변경의 실제 적용은 별도 live 승인 뒤 가능하다.
- 자동 검증: 선택 범위 밖 source/target/storage/bridge·임의 config/guest command 거부, 예전 연결 호환, 등록 및 import 검증, 기존 create payload와 task/readiness 조회 전달. UI/CLI 등록·계획 확인과 전체 회귀를 이어간다.

### 관리형 Create 권한 검증 묶음

- 새 template_vmids/create_vmids와 create feature·고정 역할·request policy를 구현했다. 기존 TUI 질문은 유지하고 웹/CLI에만 신규 권한 선택을 추가했다. 선택한 생성 대상의 이후 시작·정상 종료도 동일 admission을 통과한다.
- 원본/대상/node/storage/bridge·임의 config/guest command 거부와 기존 mutation client 전달 23개 통과. 실제 template 확인과 미래 target ID 허용, 신규 등록→검증→전환→대상 admission 회귀를 추가했다. 등록 fixture의 기존 미완료 등록은 명시적으로 취소한 뒤 새 등록으로 검증했다.
- 실제 브라우저에서 등록 컴포넌트의 원본·대상·guest-agent 권한 설명을 확인했다. 외부 호출 없는 fixture이며 실제 token 발급은 아니다.
- 전체 로컬 verify 통과: client 86, backend 859 passed/31 skipped, frontend tests/lint/build. 별도 tmpfs PostgreSQL integration 31 passed. 신규 변경까지 포함한 기준 container 검증 진행 중. 사용·권한 문서를 반영했다.
- 다음: container 결과와 diff 확인 후 VM-02의 첫 storage/bus·task/실제 volume 크기 관찰·권한 계약을 구체화하고 구현한다. M1 live 설치와 모든 PVE mutation 검증은 별도 승인 대기로 유지한다.

### VM-02 구현 계약 (착수)

- 첫 지원: 정지된 VM의 `scsi0`, 선택한 NFS storage의 raw/qcow2 VM volume. source와 현재 volume ID를 고정하고 절대 GiB 크기로 확장한다. 축소·동일 크기·CDROM·공유/다른 VM 소유 volume·pending 변경·PVE lock·running VM은 거부한다. 게스트 partition/filesystem 확장은 수행하지 않는다.
- 권한: 선택 VM의 VM.Config.Disk와 선택 storage의 Datastore.Audit/AllocateSpace를 선택적 disk 기능으로 계획한다. 기존 권한은 자동 확대하지 않는다. 실제 token/ACL 적용은 별도 승인한다.
- PVE 공식 resize API는 digest를 받으며 UPID를 반환한다. 정확한 node/VMID/type의 UPID만 저장하고 terminal stopped/OK와 fresh config 및 storage volume info의 실제 bytes를 함께 확인한다. HTTP 접수·config size만으로 성공 처리하지 않는다.
- durable admission의 공통 부분만 operations의 재사용 가능한 adapter로 옮기며 기존 CPU·메모리 실행 의미는 보존한다. 새 action `vm_disk_resize`와 GET-only recovery를 추가한다. 새 migration `0032`로 lock action check만 확장하고 해당 action 이력이 있으면 downgrade를 거부한다.
- dispatch 전에 lock·Operation·recovery를 같은 transaction으로 준비한다. UPID 저장 전 응답 유실은 paused·잠금 유지, 저장 뒤 중단은 GET-only task/volume 관찰로 복구한다. 축소 보상·재dispatch·강제 종료는 없다. task가 끝나도 실제 크기·대상 확인 실패면 미확정으로 남긴다.
- 검증: 올바른 확장, 입력/상태/소유권·storage/bus 거부, 같은 요청 replay·충돌, task 실패/단절/응답 유실/lease fencing, 실제 bytes 불일치, restart 관찰, shared admission 회귀, 웹/CLI 검토·실행·결과와 전체 검증. 운영 DB 적용·live mutation은 수행하지 않는다.

### VM-02 재개 지점

- 관리형 Create 기준 container 검증도 통과(client 86, backend 859/31 skipped, frontend test/lint/build/runtime image). 해당 scope의 실환경 생성은 아직 미검증이다.
- VM-02 domain·PVE adapter·단일 dispatch/UPID task/실제 volume 관찰 service·recovery·route·0032 migration·선택 disk 권한을 작성했다. VM target admission은 `operations/vm_admission.py`로 분리해 CPU/디스크가 공유한다.
- CLI `vm disk show/plan/execute`와 0600 검토 파일을 연결했다. `resource_review.py`에 서버/profile binding·파일 생성·실행 확인을 공통화했고 기존 compute 테스트가 통과했다. 웹은 같은 검토/실행/Operation 확인 hook을 공유하되 입력·영향 설명은 기능별로 유지한다. 새 패널은 상세에서 lazy load해 dashboard 초기 bundle을 늘리지 않는다.
- 도메인/compute 회귀 36개, disk service/setup 75개, 추가 API/managed/migration 13개, client compute/disk 7개 통과. 전체 첫 disk verify는 client 86/backend 888 passed·31 skipped와 frontend test/lint/build 통과(추가 테스트 작성 전 snapshot). 최신 전체·PostgreSQL·container는 실행 중이다.
- 브라우저 fixture에서 동일 용량 20 GiB 거부 → 24 GiB 검토 → 실행 → 실제 24 GiB/Operation 링크 표시를 확인했다. 공통 hook 추출 뒤 CPU 4·memory 4096 변경 결과도 재확인했다. 실제 PVE 변경은 아니다. production build는 main 493 kB, resource panel 8.54 kB로 분리됐다.
- 다음: 추가 lease/중단 회귀·최신 전체 검증 결과 확인, 사용/계약 문서·로드맵 반영 후 VM-03 기존 NIC bridge/VLAN 변경. 임시 검토 파일/preview와 tmpfs DB는 아직 검증에 사용 중이며 종료 시 제거한다.

### VM-02 구현 검증 완료 / VM-03 착수

- 최신 전체 로컬 verify 통과(client 89, backend 890 passed/35 skipped, frontend test/lint/build). 동일 제품 코드의 기준 container 검증 통과. 추가된 disk lease 만료/dispatch 전 crash를 포함한 단위 9개도 별도 통과했다. tmpfs PostgreSQL integration 35개 통과: compute/disk 같은 요청·다른 요청·늦은 replay·두 action 간 충돌 포함. `git diff --check` 통과.
- VM-01·VM-02는 구현 검증 완료이며 실환경 변경 검증은 미완료다. 운영 DB migration·설치·token 발급/ACL·PVE 변경은 모두 미실행이다. 아키텍처·사용법을 갱신했다. M2 전체·Goal은 완료하지 않는다.
- VM-03 첫 범위: 정지 VM의 기존 `net0`에서 Linux bridge와 단일 VLAN tag(1~4094 또는 untagged)만 변경한다. 모델/MAC·나머지 NIC 옵션은 보존하며 새 NIC/모델 변경·trunk 설정·관리망/호스트 bridge 변경은 제외한다. 선택 bridge의 존재·active/type·VLAN-aware 조건을 직접 확인한다. 결과는 PVE 설정 재조회까지이며 게스트 통신 성공은 별도로 표시한다.
- 선택 `network` 권한은 VM.Config.Network와 선택 bridge의 SDN.Audit/Use이며 기존 연결은 자동 확대하지 않는다. config digest와 current/pending/status를 검토하고 동일 VMID lock·단일 PUT·동기 응답 근거·GET-only recovery를 사용한다. 공통 동기 config 작업 orchestration만 추출해 compute와 network가 공유하고 compute의 입력/실패 의미는 유지한다.
- 새 `vm_network` lock action과 recovery는 새 migration `0033`으로 확장하며 이전 이력과 check를 보존한다. 해당 action 이력 존재 시 downgrade를 거부한다. 실환경 token/ACL·VM 변경은 별도 승인이다. MAC/옵션 보존·VLAN 조건·잘못된 bridge·drift·중복·부분 반영/응답 유실·권한·복구, compute 회귀 및 웹/CLI 전체 흐름을 검증한다.

### VM-03 공통 실행·관찰 재개 지점

- 동기 config 변경의 잠금/idempotency/단일 dispatch/ack/GET-only 확인을 `vm_config.application`으로 추출했다. compute의 공개 요청·Operation identity·오류·이벤트 의미는 유지했다. 기존 compute 15개와 신규 network domain/service·managed·migration 묶음 59개가 통과했다.
- NIC 변경 domain/service/API/recovery·0033 migration을 작성했다. MAC/model/나머지 net0 옵션을 보존하고 trunk·running/pending/잠긴 VM, 권한 없는 bridge, 비 VLAN-aware tag를 거부한다. 선택 network feature와 기존 연결 갱신 경로를 연결 중이다.
- PVE 공식 Network index는 host 미적용 diff를 `data` 바깥 `changes`로 반환한다. 두 HTTP transport에서 해당 GET envelope를 보존하고 managed 선택 bridge 필터를 유지했다. 외부 diff 본문은 UI/Operation에 노출하지 않고 pending 여부만 사용한다. metadata를 잃은 legacy response는 차단한다.
- 환경 토큰으로 세 노드 network GET만 재확인했다. 모두 pending_changes=false, active Linux bridge를 관찰했다. 실제 PVE 9.0.11 virtual bridge에는 optional `exists`(physical 존재 표시)가 없으므로 존재 판단은 조회된 `iface/type=bridge/active=1`에 근거한다. host/VM 변경은 하지 않았다.
- 다음: metadata/권한 회귀 추가, 웹·CLI 연결 및 브라우저 확인, 전체 local/container·PostgreSQL 검증, 현재 문서 반영. M1~M6 전체와 live 검증은 계속 미완료다.

### VM-03 구현 검증 완료 / VM-04 착수 재개 지점

- 전체 로컬·기준 container 검증 통과: client 96, backend 928 passed/40 skipped, frontend test/lint/build. 이후 추가한 host pending drift·MAC 불일치·bridge Audit만 있는 경우를 포함한 network/managed 24개도 통과했다. tmpfs PostgreSQL integration 40개 통과: network same/different key·late replay, compute/disk/network 간 경합 포함. diff check 통과.
- 실제 브라우저 fixture에서 비 VLAN-aware tag 거부 → vmbr1/VLAN 100 검토 → 실행 → 동일 MAC·관찰값·Operation 링크를 확인했다. 실제 PVE NIC 변경 검증은 아니다. CLI는 tag/untagged를 명시해야 하며 동일 검토 파일·요청 ID를 유지한다. 사용/계약 문서를 반영했다.
- VM-01~03 구현 검증 완료, 실환경 mutation 검증 미완료. M2 전체와 Goal은 미완료. 다음 VM-04 full clone 계약 및 구현으로 이어간다.

### VM-04 구현 계약 (첫 범위·위험·검증)

- 정지된 일반 VM의 full clone, 같은 node의 선택 NFS → NFS raw/qcow2 scsi0 한 개를 첫 조합으로 지원한다. net0 한 개와 선택적인 cloud-init CDROM을 지원하고, 추가 disk/NIC·snapshot 지정·passthrough·EFI/TPM 상태·외부 ISO/host 경로는 제외한다. 원본 onboot=0을 요구해 복제본의 자동 시작도 방지한다. VMID·이름·target storage·복사되는 guest identity/network 위험을 명시적으로 검토하고 원본을 보존한다. guest IP·hostname·SSH host key 재발급은 자동 수행하지 않는다.
- 공식 PVE clone API는 full=1과 target storage를 받고 qmclone UPID는 **원본 VMID**에 바인딩된다. config digest parameter는 없다. dispatch 직전 source digest·정지 상태를 재검증하고 완료 뒤 source digest/volume 보존과 destination의 새 VMID·name·정지 상태·독립 volume bytes·새 MAC/SMBIOS UUID 및 주요 설정을 확인한다. 외부 PVE 변경과 완전한 원자적 compare-and-clone은 보장하지 않으며 drift는 미확정으로 보존한다.
- 원본과 새 VMID 두 잠금을 같은 admission transaction에서 VMID 순으로 확보한다. canonical Operation target은 복제 대상이며 source는 별도 evidence다. recovery에 두 exact lock ID/owner/cluster/VMID를 결합하고 단일 fence commit에서 함께 완료·해제한다. 기존 한 대상 작업의 계약은 유지한다. 일부 lock 유실·binding 변조·lease 만료 시 성공/해제를 거부한다. 신규 vm_clone action/check는 새 0034 migration, 이력 존재 시 downgrade 거부다.
- 선택 clone 기능과 기존 source vmids·새 clone_vmids를 구분한다. 최소 권한은 원본 VM.Audit/Clone, 새 VMID VM.Allocate/Audit, 선택 storage Audit/AllocateSpace, 선택 bridge Audit/Use다. 새 대상에 불필요한 전원/guest-exec 권한을 함께 부여하지 않는다. scope 검사와 기존 연결 갱신 경로를 동일하게 적용한다.
- 한 번만 clone POST, UPID 저장 전 응답 유실/미확정 task/부분 자원은 paused와 두 잠금을 보존한다. recovery는 task/config/volume GET만 수행한다. 자동 재복제·실패 잔여물 삭제·원본 수정은 없다. PVE 자체 clone failure cleanup은 PVE 권위로 남기고 Gjallar는 잔여 여부를 관찰한다. 정확한 live target·storage 소모·복사 영향·테스트 생성 자원 삭제는 별도 승인 뒤 검증한다.
- 검증: 허용 조합/소유권·정지·원본 변경·target 점유·IP/identity 경고, 두 lock atomic rollback/동시 역순 경합·late replay·부분 binding 유실·lease fence, exact UPID source binding·부분/응답 유실·GET-only recovery, 웹·CLI 검토/명시적 실행/원본과 결과 확인, 이전 M1/VM-01~03 전체 회귀 및 PostgreSQL 검증.

### VM-04 두 대상 조정 기반 재개 지점

- 복제의 source·destination을 VMID 순으로 같은 transaction에서 잠그고, 두 exact binding을 Operation/recovery에 기록하도록 admission을 확장했다. 단일 대상 API는 유지한다. 두 ledger의 binding·실제 owner/type/cluster/VMID 중 하나라도 불일치하면 결과 확정·전체 해제를 거부한다. 미확정 시 두 잠금을 함께 reconciliation 상태로 보존한다.
- SQLite test-only connection guard의 동일 transaction 내 재진입을 지원했다. 기존 BEGIN IMMEDIATE를 두 번 실행하는 실패를 새 테스트로 재현했으며 실제 PostgreSQL advisory transaction lock 경로는 유지했다.
- 새 0034 lock action migration을 작성해 이 작업의 tmpfs PostgreSQL에만 적용했다. 운영 DB는 미접근이다. 신규 multi-target/기존 compute·disk·network/setup 묶음 115개 통과. PVE UPID task 공통 흐름을 `vm_config.task_application`으로 추출한 뒤 disk/두 target 단위 17개 통과했다.
- PostgreSQL 신규 두 요청 경합 자체는 한 요청/두 잠금으로 직렬화됐으나 테스트의 최종 관찰까지 barrier가 걸린 실패를 발견해 테스트 hook 범위를 수정했다. 수정 뒤 기존 action admission과 함께 재검증 중이다. 성공으로 아직 기록하지 않는다.
- VM-04는 기반 구현 중이며 복제 domain/adapter/권한·API·웹/CLI/recovery 등록은 아직 남아 있다. 전체 검증은 VM-03 완료 snapshot과 구분한다. 다음은 제한된 NFS scsi0 full clone의 입력·실제 volume/identity 결과 검증과 scope를 연결한다.

### VM-04 웹·CLI 연결 / 최종 검증 재개 지점

- full clone domain/service/PVE adapter/recovery/API·관리형 clone scope와 새 대상 최소 역할·웹·CLI 검토/실행을 연결했다. source VMID로 qmclone UPID를 검사하고 canonical Operation target은 새 VMID다. destination description에 Operation marker를 기록해 결과의 소유 근거도 확인한다. 원본 설명은 그대로다.
- 복제 domain/service·기존 disk·multi-lock·route 묶음 44개, 관리형 clone/create scope 37개, CLI resource 흐름 18개, clone API auth/validation 1개 통과. 기존 연결의 compute/disk/network/clone 갱신을 같은 회귀로 확장했고 등록 15개 통과했다. 원본·대상을 뒤집은 PostgreSQL 두 lock 경합과 기존 action admission 29개 통과했다.
- 전체 로컬 verify 통과: client 100, backend 971 passed/42 skipped, frontend tests/lint/build. 전체 tmpfs PostgreSQL integration 42개 통과. 현재 동일 snapshot의 기준 container 검증 진행 중이다. diff check 통과.
- 실제 브라우저 fixture에서 새 VMID·이름·NFS storage 입력 → guest identity ack → full clone 검토 → 정지된 복제본·새 MAC·Operation/복제본 링크를 확인했다. 실제 PVE 복제는 하지 않았다. 아키텍처·운영 사용법을 반영했고 VM-04는 container 결과 확인이 남아 있다.
- 다음: container 결과 확인 후 VM-05 삭제 계약을 확정한다. 공식 PVE DELETE는 VM-specific ACL/firewall도 제거하고 purge=false이면 HA/replication을 차단한다. 권한 제거 뒤 단순 VM GET 실패를 삭제 증거로 오인하지 않도록 VMID 점유·정확한 volume 부재 확인을 조사 중이다. live mutation·설치·운영 DB 적용은 계속 별도 승인 대기다.

### VM-04 구현 검증 완료 / VM-05 착수

- 기준 container 검증 완료: client 100, backend 971 passed/42 skipped, frontend test/lint/build/runtime image. 동일 코드의 로컬 전체 검증과 PostgreSQL integration 42개, 격리 브라우저 검증이 완료됐다. VM-01~04는 구현 검증 완료이며 실제 PVE mutation 검증은 미완료다. M2 전체와 Goal은 완료하지 않는다.
- VM-05 첫 범위는 정지된 일반 VM의 명시적 전체 삭제다. 첫 storage 조합은 선택 NFS의 자기 VMID 소유 raw/qcow2 scsi0와 선택적 ide2 cloud-init으로 제한한다. template·protection·lock·pending·snapshot·추가/unused disk·passthrough·외부 ISO는 차단한다. 삭제할 config/연결 volume/VM 전용 ACL·방화벽과 보존할 backup·unreferenced volume·외부 HA/replication/backup job 설정을 검토한다.
- DELETE는 purge=0, destroy-unreferenced-disks=0으로만 실행하며 skiplock·강제 종료·보호 해제는 없다. PVE는 HA/replication 설정이 있으면 이 요청을 거부한다. 기존 backup과 미참조 disk를 삭제하지 않는다. 복구할 자동 역연산은 없고, 복구는 별도 backup restore 흐름이다. 대상 VMID/이름 입력과 삭제 ack, expected config digest 및 resource manifest를 요청 의도에 결합한다.
- PVE DELETE에는 digest 조건부 인자가 없다. Gjallar 공유 VM 잠금을 유지하고 최초 DELETE 직전 config·정지 상태·resource manifest를 다시 확인한다. 외부 PVE 관리자가 동시에 설정을 변경하는 것을 원자적으로 막지는 못한다. 승인 범위는 해당 VM과 그 소유의 연결 자원 전체이며 이 제한을 실행 검토/사용 문서에 명시한다. PVE가 실제 사용/소유 자원과 보호/전원 상태를 최종 판단한다.
- qmdestroy UPID를 exact node/VMID/type으로 저장하고 task stopped/OK 이후 삭제를 관찰한다. VM-specific ACL이 삭제되므로 VM GET 403/404나 권한 필터된 빈 inventory만으로 부재를 인정하지 않는다. 모든 인증 사용자가 호출 가능한 공식 GET /cluster/nextid?vmid=<exact ID>가 해당 ID를 반환해야 VMID 부재를 인정한다. 선택 storage의 images/vmid content 목록에서 삭제 manifest의 정확한 volume이 없고 검토된 미참조 volume이 남는지 확인한다. 조회 불가/불명확/재사용/잔여물은 paused·잠금 유지다.
- 선택 delete 기능은 VM.Allocate와 기존 VM Audit, 선택 storage Audit로 제한한다. 새 vm_delete action/GET-only recovery와 0035 check migration을 추가하며 해당 이력 존재 시 downgrade를 거부한다. 자동 재DELETE·잔여물 정리·백업 제거는 없다. 실환경 삭제·운영 DB 적용은 정확한 target/영향의 별도 승인 뒤에만 수행한다.
- 검증: typed 대상/ack·보호·상태·resource drift·추가 disk/snapshot·권한, 원자적 admission·같은 key replay·응답 유실·task 실패·VMID 재사용·삭제 ACL 이후 관찰·volume 잔여/보존·lease/recovery, 웹·CLI의 삭제 영향/결과 및 이전 기능 회귀. 성공·실환경 상태는 별도 기록한다.

### VM-05 부재 관찰 기반 재개 지점

- 공식 Cluster nextid·Storage content source를 확인하고 exact VMID 미사용 확인, snapshot 목록, 특정 storage/images/VMID 목록, 제한된 DELETE client 메서드를 추가했다. managed scope 밖 VMID·node·storage·content 종류와 전체 목록 호출은 거부한다. DELETE 자체는 아직 runtime capability/domain/API에 연결하지 않았다.
- 환경 토큰으로 GET /cluster/nextid?vmid=40000만 호출했다. 실제 PVE 9.0.11은 명세의 integer를 JSON 숫자 문자열 `"40000"`으로 반환했다. int 또는 정확한 canonical 숫자 문자열만 인정하며 bool·다른 ID·선행 0·object는 거부한다. 현재 시점에 40000 미사용을 읽기 관찰한 것이며 VMID 예약/생성/삭제는 아니다.
- managed 범위와 scalar 오판 방지를 포함한 단위 22개 통과했다. VM-04 기준 container 완료 이후의 이 추가 변경은 아직 전체 검증 전이다. 다음은 삭제 resource manifest와 명시적 확인·qmdestroy/부재 검증 service, 선택 delete 권한, 웹·CLI 및 전체 회귀를 이어간다.


### VM-05 웹·CLI 연결 / 검증 재개 지점 (2026-09-19 02:49 KST)

- 삭제 domain/service/adapter/API/recovery·0035 migration과 선택 delete 권한을 연결했다. CLI delete show/plan/execute와 서버/profile에 묶인 0600 검토 파일, 웹의 삭제·보존 목록·VMID/이름 입력·ack·최종 실행을 구현했다. 삭제 성공 후 이전 VM 상세와 다른 작업 버튼은 제거하고 결과와 Operation을 유지한다.
- 삭제/clone/disk/route/migration 집중 68개, 삭제/API/managed 52개, CLI 삭제/등록 12개, 기존 관리형 연결 갱신 16개 통과했다. 격리 브라우저에서 잘못된 VMID 차단 → 정확한 이름/ack → 최종 검토 → 삭제·보존 volume 결과를 확인했다. fixture이며 PVE 삭제는 하지 않았다.
- 전체 로컬 verify 통과(client 107, backend 1010 passed/42 skipped, frontend test/lint/build). 이후 추가한 delete 연결 갱신과 삭제·compute/disk/network 경합을 포함한 tmpfs PostgreSQL integration 48개 통과했다. 새 0035는 이 작업의 격리 tmpfs DB에만 적용했다. 운영 DB는 미접근이다.
- 동일 최신 코드의 기준 container 검증 진행 중이다. architecture/development/PRD 현재 구현을 반영했다. VM-05 실환경 mutation 검증은 미완료다. 다음은 container 결과·최종 diff 확인 후 VM-06 인증된 웹 콘솔 계약과 구현으로 이어간다. Goal/M2 전체는 미완료이며 live mutation·설치·배포·운영 DB 적용은 별도 승인 대기다.

### VM-05 구현 검증 완료 / VM-06 착수 계약 (2026-09-19 02:54 KST)

- 최신 기준 container 검증 통과: client 107, backend 1011 passed/48 skipped, Node 24 frontend test/lint/build/runtime image. 추가 delete 연결 갱신 1개와 PostgreSQL 선택 테스트 6개가 이전 local snapshot보다 증가했다. tmpfs integration 48개와 diff check도 통과했다. VM-01~05는 구현 검증 완료 / 실환경 mutation 검증 미완료다.
- VM-06은 실행 중인 일반 QEMU VM의 웹 화면 콘솔과 CLI 웹 진입 안내다. serial-only/none VGA·템플릿·정지 상태는 명시적으로 거부하며 자동 시작하지 않는다. 선택 console feature는 정확한 VM의 VM.Console만 기존 Audit에 추가한다. 게스트 화면·키보드/마우스 입력 권한이며 호스트 shell·PVE 관리자 세션·클립보드 자동 공유는 제공하지 않는다.
- 공식 Qemu.pm의 vncproxy POST·vncwebsocket GET, HTTPServer/AnyEvent의 Authorization token 처리와 RESTHandler의 allowtoken 기본값을 확인했다. token·VNC ticket은 서버에서만 PVE로 전송한다. noVNC RFB에 필요한 짧은 연결 password만 인증된 WebSocket 초기 메시지로 전달하고 브라우저 메모리에서만 사용한다. URL·DB·Operation·로그에 저장하지 않는다. 실제 PVE 9.0.11 콘솔 handshake 지원은 별도 live 검증으로 남긴다.
- 기존 Gjallar cookie session·operator 이상을 WebSocket upgrade에서 직접 확인하고 Origin은 기존 허용 목록에 반드시 있어야 한다. PVE 권한/VM 상태를 조회한 뒤 같은 WebSocket 안에서 한 번만 임시 proxy를 요청한다. secret-bearing query를 브라우저 URL에 넣는 별도 bearer 접속권은 만들지 않는다. PVE 연결은 CA/hostname 검증·DNS 고정·proxy/redirect 금지로 보호한다. 관리형 설정 변경 시 기존 pin 계약으로 연결을 끊고 재시작을 요구한다.
- 콘솔은 VM configuration 변경 작업/복구 queue가 아닌 짧은 인증된 streaming 연결이다. 신규 DB schema·durable target lock은 추가하지 않는다. 서버 process별 연결 수(전체 32/사용자 2)와 15분 최대 수명, 5초 이내 로그인 만료/폐기·권한 감소 확인, 종료/브라우저 이탈/통신 오류 시 양쪽 socket 정리를 구현한다. 자동 재연결·자동 전원 변경·임의 PVE URL/port 입력을 허용하지 않는다.
- noVNC를 화면 렌더링 dependency로 lazy load하고 이미 잠긴 backend websockets dependency를 직접 선언한다. 기존 대시보드 bundle/기존 route는 유지한다. 검증은 세션·Origin·feature/scope·TLS/redirect·만료/종료·한 번만 dispatch·비밀정보 비노출·binary relay와 fixture RFB 화면 handshake, 웹/CLI 안내·기존 기능 회귀다. 실제 콘솔 접속(임시 PVE proxy 생성)과 키 입력은 정확한 target의 별도 승인 뒤 검증한다.

### VM-06 인증·화면 연결 재개 지점 (2026-09-19 03:05 KST)

- `backend/app/console/`과 console review HTTP/인증된 WebSocket route를 작성했다. cookie/Origin/operator·선택 console scope, 실행 중 화면 VM·PVE Console 권한, TLS/DNS 고정·redirect/proxy 금지, 15분 수명·5초 로그인/연결 재확인, 연결 수 제한과 양쪽 socket 정리를 연결했다. PVE token/ticket은 서버에 유지하고 임시 RFB password만 WebSocket 초기 메시지로 전달한다. DB/Operation에 화면·입력·ticket/password를 기록하지 않는다.
- 관리형 console 선택 및 기존 연결 갱신을 웹·CLI 등록에 추가했다. CLI `vm console`은 검토 후 `/instances/<VMID>#console` 주소와 별도 브라우저 로그인 안내만 출력한다. 기존 TUI는 질문이 늘어나지 않는다.
- noVNC 1.7.0 공식 ESM package를 고정했다. capability detection의 top-level await를 해당 lazy chunk에 보존하도록 Vite 설정을 추가했고 기존 메인 변환 target은 유지했다. production build 통과: main 496.63 kB, resource panel 25.41 kB, RFB 181.85 kB 별도 파일. 콘솔은 최신 브라우저의 secure context가 필요하다.
- 로그인/Origin/권한 거부·binary relay·잘못된 frame·만료/폐기·proxy 실패·중복 연결 제한·응답 validation과 managed 등록/범위 묶음 68개 통과했다. 추가 TLS 고정 transport 테스트는 처음 asyncio 공통 socket을 잘못 대체한 테스트 fixture 오류를 수정해 재검증 중이다.
- 격리 브라우저에서 대상/입력 영향 검토 → 실제 noVNC RFB handshake → 합성 framebuffer 세 색상 렌더링 → 명시적 종료 표시를 확인했다. 첫 fixture의 WebSocket subclass가 noVNC raw-channel 검사와 맞지 않아 native instance 반환으로 고쳤다. 실제 PVE proxy 생성이나 VM 키 입력은 하지 않았다.
- Vite 재시작 후 이전 탭의 연결 오류 페이지가 남아 새 격리 탭에서 확인했다. preview와 합성 RFB server는 이 작업의 임시 검증용이다. 다음은 추가 인증 감소/연결 전환/transport 오류 검증, 전체 local/container, 사용·계약 문서 반영 후 M3 템플릿 전환으로 이어간다. VM-06 실환경 handshake 검증 및 M1 설치·PVE mutation·운영 DB 적용은 별도 승인 대기다.

### VM-06 구현 검증 완료 / TPL-01 착수 계약 (2026-09-19 03:13 KST)

- VM-06 최신 local/container 전체 검증 통과: client 109, backend 1044 passed/48 skipped, frontend test/lint/build와 runtime image. 별도 tmpfs PostgreSQL integration 48개는 VM-05 완료 snapshot이며 콘솔은 DB 변경이 없다. 합성 framebuffer 접속·종료, 인증 감소/연결 전환 종료·TLS 고정·redirect 금지·WebSocket DEBUG 비밀정보 비노출을 확인했다. 실제 PVE console handshake는 미검증이다.
- TPL-01은 준비된 정지 VM의 제자리 템플릿 전환이다. 첫 조합은 선택 NFS의 자기 VMID raw/qcow2 scsi0와 ide2 cloud-init, guest agent 활성 설정이다. 실행 중·이미 template·lock/pending/snapshot·추가/unused disk·EFI/TPM·passthrough·custom hook/cloud-init은 차단한다. 기존 disk를 base image로 바꾸며 VMID/이름은 유지한다. 원본 VM을 직접 부팅할 수 없고 자동 역변환은 제공하지 않는다.
- 계정/키·machine-id/SSH host key·cloud-init 상태·고정 IP 등 게스트 준비는 운영자 확인으로 별도 표시한다. 전환은 게스트 내부를 청소하거나 배포 적합성을 증명하지 않는다. TPL-03 테스트 배포로 확인한다. 설정 원문/키/비밀번호는 Operation에 저장하지 않고 설정 fingerprint와 제한된 volume 증거만 남긴다.
- 공식 PVE template POST는 VM.Allocate와 qmtemplate UPID를 사용한다. 전체 변환만 허용하며 disk 부분 전환·skiplock·shell은 없다. digest 조건부 인자가 없으므로 최종 조회 후 외부 변경 경쟁 제한을 명시한다. task 실패 전에도 template flag/일부 volume이 바뀔 수 있어 자동 재요청/역변환하지 않는다.
- 기존 단일 VM target lock·idempotency·lease와 비동기 task 흐름을 재사용한다. 0036은 vm_template lock action만 추가하고 이력이 있으면 downgrade를 거부한다. recovery는 UPID·template flag·정지 상태·base volume 소유/크기/형식·cloud-init 및 관련 설정 보존을 GET으로 확인하며 미확정 시 잠금을 유지한다. 신규 template feature는 기존 선택 VM의 Allocate와 storage Audit만 추가하고 기존 역할·연결은 자동 확대하지 않는다. 생성용 template scope 편입도 명시적 연결 갱신을 거친다.
- 검증: 준비 확인·권한/상태/자원 drift·UPID·부분 전환·중복/응답 유실·GET-only recovery·다른 VM 작업과 경합·웹/CLI 검토 및 결과, local/container/격리 DB. 실제 PVE 전환·운영 DB 적용은 정확한 target/영향의 별도 승인 대기다. 다음은 서버 전환 domain/adapter/API와 관리형 권한을 구현한다.

### TPL-01 웹·CLI 및 격리 검증 재개 지점 (2026-09-19 03:25 KST)

- `operations/vm_template/` domain/adapter/service/recovery, HTTP 검토/실행 API와 선택 template role/scope·기존 연결 갱신, 0036 action check migration을 구현했다. CLI template show/plan/execute와 두 준비 확인·0600 검토 파일, VM 상세의 검토·실행·결과 화면을 연결했다. 원문 guest config/키/비밀번호는 저장하지 않는다.
- 집중 backend 82개, client 신규 전환/등록 13개 통과. fixture 브라우저에서 잘못된 VMID 차단 → 게스트 준비/원본 영향 두 확인 → 최종 검토 → 실제 컴포넌트의 base volume/유지 cloud-init 결과와 배포 미검증 안내를 확인했다. PVE mutation은 하지 않았다.
- 새 0036은 이 작업의 tmpfs PostgreSQL에만 적용했다. 템플릿 동시 요청/동일 key/완료 직후 replay 및 compute/disk/network/delete 경합을 추가한 PostgreSQL integration 55개 통과. 이전 Operations/Jobs/Artifacts 보존 회귀 포함이다.
- 첫 전체 local은 신규 recovery handler 목록 기대값 한 곳 누락으로 backend 1076 passed/55 skipped/1 failed였다. 목록을 보완했고 최종 local/container 전체 검사 진행 중이다. frontend lint/build는 통과했다. architecture와 개발 사용법을 갱신했다.
- 다음은 최종 검사 확인·diff 점검 후 TPL-02 공식 cloud image 한 종류의 출처/무결성·PVE API import 경로를 확정한다. TPL-01 실환경 전환, console handshake, M1 설치와 실제 VM 수정·운영 DB 적용은 별도 승인 대기다. Goal은 active다.

### TPL-01 구현 검증 완료 / TPL-02 조사 재개 지점 (2026-09-19 03:29 KST)

- 최종 local/container 모두 통과: client 117, backend 1077 passed/55 skipped, frontend test/lint/build와 runtime image. 별도 tmpfs PostgreSQL integration 55개, fixture 브라우저와 diff check 통과. TPL-01 구현 검증 완료 / 실환경 전환 미완료로 로드맵을 갱신했다.
- TPL-02 공식 image 준비 경로를 조사 중이다. Ubuntu 24.04 공식 manifest에는 cloud-init/openssh-server는 있지만 qemu-guest-agent가 없었다. 임의 host shell로 설치를 우회하지 않고 guest agent를 갖춘 공식 이미지의 빌드 정의를 추가 확인한다. OS는 아직 확정하지 않았다.
- PVE download-url은 storage AllocateTemplate 외 host network 접근 권한(구버전 Sys.Modify on / 또는 신규 Sys.AccessNetwork)을 요구한다. 최소권한을 위해 Gjallar에서 고정 공식 HTTPS 출처/체크섬을 검증하고 PVE upload(import) API를 사용하는 경로를 조사한다. upload는 선택 storage의 AllocateTemplate만 요구한다. 아직 다운로드 실행·권한 확대·PVE upload/import는 하지 않았다.
- 다음: 공식 image/체크섬 출처·게스트 준비, streaming upload와 PVE import-from의 크기/시간/실패 잔여 경계를 확정하고 이 work에 고위험 계약을 추가한 뒤 TPL-02를 구현한다. 기존 mutation/설치/운영 DB 승인 대기는 유지한다.

### TPL-02 첫 제작 경로와 위험 계약 (2026-09-19 03:35 KST)

- 첫 OS는 AlmaLinux 9.8 GenericCloud x86_64, 공식 `AlmaLinux-9-GenericCloud-9.8-20260810.x86_64.qcow2`로 고정한다. 공식 빌드 정의는 guest-agent 설치와 BIOS/UEFI 공통 부팅을 포함한다. 패키지 포함은 실제 PVE guest-exec 성공을 보장하지 않으며 TPL-03에서 따로 확인한다. upstream 최신 alias를 실행 중 따라가지 않는다.
- 공식 HTTPS 저장소에서 CHECKSUM·CHECKSUM.asc·AlmaLinux 9 공개키만 읽었다. 격리 /tmp keyring으로 분리 서명 검증이 통과했고 fingerprint `BF18AC2876178908D6E71267D36CB86CB86B3716`을 공식 AlmaLinux 문서와 대조했다. 고정 이미지 SHA-256은 `6bdab6376d46d42e4203ace3733efafc7c5d37c7cb443a6cc74750097002d74b`, 배포 파일 bytes는 589299712이다. 이미지 본체 다운로드·실행은 아직 하지 않았다. runtime은 고정된 hash를 직접 검증하며 새 이미지 추가/교체는 catalog 코드·출처 검토를 거친다.
- Gjallar는 고정 공식 HTTPS URL만 streaming download하고 공개 IP DNS 고정·인증서/hostname·redirect/proxy 금지, exact bytes/상한·SHA-256·qcow2 header의 backing file 없음/암호화 없음/virtual size 상한을 검사한다. 고유 0600 임시 파일을 context 종료 때 제거한다. host shell·image mount·virt-customize·임의 URL/명령은 제공하지 않는다. 다운로드는 제한된 동시 실행·deadline·lease heartbeat 안에서 수행한다.
- PVE mutation은 선택 storage의 import upload → 새 VMID import-from 생성 → 전체 template 전환 순서다. 기존 VMID와 분리한 image_vmids와 image_build feature를 추가한다. VM별 Allocate/Audit·필요 config 권한, 선택 storage Audit/AllocateTemplate/AllocateSpace, bridge Audit/Use만 계획한다. 루트 Sys.Modify·PVE download-url·SSH executor를 추가하지 않는다. 첫 storage 조합은 import content를 사전에 활성화한 dir/NFS staging과 NFS images target이다. 호스트 storage content 설정을 자동 변경하지 않는다.
- upload 이름은 Operation·VMID에 묶인 전용 파일명이며 업로드 전 기존 파일 부재를 확인한다. PVE upload 자체는 overwrite를 허용하므로 외부 동시 변경을 중지해야 한다. 반환 imgcopy UPID(node/type/빈 VMID)와 task 완료를 기록한 후 volume metadata를 확인한다. 다음 단계에서 소스 이미지 교체를 원자적으로 막을 수 없으므로 해당 staging 자원을 외부에서 변경하지 않는 조건을 명시한다.
- 한 제작 Operation/VMID 잠금에서 각 단계 dispatch 직전과 UPID를 durable 기록한다. import 생성은 새 VMID·고정 BIOS/virtio 구성·cloud-init·guest-agent 설정·onboot=0·Operation description으로 만들며 부팅하지 않는다. qmcreate/정지된 실제 config·자기 소유 volume을 확인한 뒤 qmtemplate으로 전환하고 base volume/설정 보존을 확인한다. 다운로드만 끝난 경우를 성공 처리하지 않는다.
- 복구는 기록된 task·자원 GET만 한다. 중간 단계에서 멈췄으면 남은 mutation을 자동 시작하거나 이미 dispatch한 upload/create/convert를 재전송하지 않는다. paused와 잠금·단계·잔여 staging/VM 증거를 보존한다. PVE 자체의 실패 정리는 PVE 권위로 남긴다. staging 파일은 제작 성공 후에도 provenance와 함께 표시하고 자동 삭제하지 않으며, 테스트 자원 정리는 exact 소유 근거와 별도 명시적 흐름에서 처리한다. 전환된 template 제거는 기존 일반 VM 삭제 범위 밖이므로 정리 기능도 TPL-02의 필수 후속 구현이다.
- 신규 0037이 필요하면 vm_image_build action check만 추가하고 해당 이력 downgrade를 거부한다. 기준 DB schema/Operation 상태 전이는 바꾸지 않는다. 검증: source/hash/size/header·TLS/SSRF·stream cleanup·권한 범위·단계별 crash/lease/응답 유실·UPID/자원 검증·중복/경합·웹/CLI 전체 흐름, local/container/격리 PostgreSQL. 실제 제작·storage 변경·template/staging 삭제·운영 DB 적용은 별도 승인 대기다.

### TPL-02 출처·stream·최소권한 기반 재개 지점 (2026-09-19 03:43 KST)

- `cloud_images/catalog.py`에 공식 AlmaLinux 9.8 고정 URL·SHA-256·서명 지문·배포 파일 크기를 기록했다. 공식 서버가 Range 206/104 bytes를 반환한 header만 읽어 QCOW2 v3·10 GiB 가상 크기·incompatible feature 0을 확인했다. 전체 이미지 본체 다운로드·실행은 아직 하지 않았다.
- `cloud_images/download.py`는 공개 IP DNS 고정·TLS·redirect/proxy 금지, exact bytes/hash/virtual size와 qcow2 backing/encryption/snapshot 제한, 600초 deadline·lease heartbeat·process별 동시 2개를 검사한다. 익명 임시 파일을 사용해 Unix process 종료 시에도 원본 이미지 파일이 남지 않으며 context 예외에서도 닫는다. 호출자의 upload/lease 오류를 다운로드 오류로 덮어쓰지 않는다.
- 기존 검증된 PVE TLS transport를 `_send`로 공유하고 `upload_import`의 bounded multipart streaming(64 KiB), exact Content-Length·SHA-256·고정 import content·Operation 소유 파일명·heartbeat를 추가했다. scope 밖 upload나 임의 HTTP body 경로는 만들지 않았다.
- image_build/image_vmids와 별도 최소 역할·PVE create/template allowlist를 구현했다. 미래 제작 ID는 기존/생성/복제/템플릿 scope와 분리한다. 시작·force·archive·args·임의 import 파일/다른 Operation의 파일은 거부한다. import 목록은 해당 feature의 선택 미래 VMID에 묶인 파일만 반환한다. 등록 UI/CLI와 제작 서비스에는 아직 연결 전이다.
- download/header/cleanup·upload·등록/기존 transport·managed scope 집중 116개 통과, diff check 통과. 이는 TPL-01 전체 검증 이후 추가 기반 변경이며 TPL-02 완료가 아니다. API/단계별 Operation/recovery·0037·웹/CLI 제작·소유 자원 정리가 남아 있다. 다음은 upload→qmcreate→qmtemplate 단계별 durable 기록과 GET-only 복구를 연결한다.

### TPL-02 단계별 제작·API 재개 지점 (2026-09-19 03:53 KST)

- `operations/vm_image_build/`에 download 검증 → imgcopy upload → qmcreate import → qmtemplate의 단일 Operation/잠금·단계별 UPID 기록과 GET-only 복구를 구현했다. 중간 단계 성공 뒤 중단되어도 다음 mutation을 자동 시작하지 않으며 응답 유실·불완전 결과는 잠금과 증거를 보존한다. 최종 성공은 세 단계 근거·원본 hash·실제 template/base volume·설정 보존을 요구한다.
- 신규 0037 migration은 작성만 했으며 아직 격리 DB에도 적용 전이다. 제작 adapter는 관리형 revision/scope·미사용 VMID·storage 종류/content/여유 공간·권한·bridge/pending·고유 staging 부재를 검사한다. 공식 이미지 목록/제작 검토/실행 API를 추가했다.
- service/출처/계약/migration 집중 73개 통과. API registry 새 경로 정렬 누락을 수정했고 HTTP/operator/registry 3개 통과했다. recovery의 stage/UPID binding 테스트 중 누락을 발견해 단계 checkpoint에 recovery UPID와 단계 digest를 같이 기록하도록 수정했다.
- 설정 웹·CLI에 image_build와 독립 image_vmids 선택을 추가했고 CLI 제작 catalog/show/plan/execute를 연결 중이다. TUI의 기본 질문은 유지한다. 새 UI/CLI·adapter/복구 추가 검사·격리 PostgreSQL·전체 검증은 아직 남았다. 템플릿/staging 소유 자원 정리와 TPL-03도 미완료다. 실제 PVE 변경·설치·운영 DB 적용은 미실행이며 Goal은 active다.

### TPL-02 제작 웹·CLI 검증 / 정리 조사 재개 지점 (2026-09-19 04:03 KST)

- `ImageBuildPage`와 `/instances/templates/build`, CLI `vm image-build catalog/show/plan/execute`, 설정의 image_build/image_vmids 선택을 연결했다. 기존 dashboard와 TUI 질문은 유지한다. 브라우저 fixture에서 실제 입력·조건 검토·잘못된 VMID 확인 차단·성공 후 base/cloud-init volume과 보존 staging·배포 미검증·다음 단계 링크를 확인했다. 실제 PVE 제작은 하지 않았다.
- client 신규 제작/등록 13개, backend 기존 연결 갱신 19개, 단계별 recovery/lease/중단 21개, PVE adapter 조건/소유권 15개 통과. 전체 local verify는 client 125, backend 1165 passed/57 skipped, frontend test/lint/build 통과(새 adapter 15개는 뒤에 별도 추가·통과). 기준 container 검증 진행 중이다.
- 0037을 이 작업의 tmpfs PostgreSQL에만 적용했다. 기존 integration 55개 통과, 신규 2개는 테스트 digest 입력과 진행 중 같은-key busy 기대값을 기존 계약에 맞춰 고친 뒤 2개 통과했다. 모든 이력/운영 DB는 보존했다. diff check 통과.
- architecture/사용법에 제작 경로와 미완료 정리를 구분했다. TPL-02 전체 완료는 아니다. 다음은 제작 Operation 소유의 template/staging 정리 계약이다. PVE import 파일 DELETE는 AllocateSpace가 아닌 **Datastore.Allocate**를 요구함을 공식 Storage Content에서 확인했다. 제작 기본권한에 조용히 추가하지 않고 별도 선택 정리 권한과 정확한 자원 검토를 설계한다. template의 linked clone/base 보호와 부분 실패 관찰을 확인 중이다.
- 실환경 변경·console handshake·설치·운영 DB 적용·M3 테스트 배포와 M4~M6는 미완료. Goal active, commit/push 없음.

### PVE volume 조회 최소 권한 보완 계약 (2026-09-19 04:06 KST)

- 정리 조사 중 공식 `PVE::Storage::check_volume_access`에서 images/rootdir 조회는 storage Audit 외 해당 VM의 **VM.Config.Disk**를 요구함을 확인했다. 기존 VM-04 clone 원본/대상, VM-05 delete, TPL-01 template 권한 계획에 이 조건이 빠져 있었다. fixture 성공은 실환경 성공을 의미하지 않았으며, 실제 volume 조회 시 거부될 차단 요인으로 처리한다.
- 실제 volume 검증을 생략하거나 Datastore.Allocate로 우회하지 않는다. 좁은 exact VMID의 VM.Config.Disk를 추가하는 새 V2 role을 사용하고 기존 V1 role은 수정하지 않는다. PVE 권한 자체가 disk 변경도 허용함을 설정/사용법에서 알린다. Gjallar managed transport의 변경 allowlist는 늘리지 않는다. 기존 연결은 새 등록·검증·전환·전체 재시작이 필요하다.
- clone/delete/template 사전 검사와 최소 권한/기존 연결 회귀 fixture를 보완한다. 권한 부족 실패를 명시적으로 검사하고 실제 변경은 별도 승인 대기를 유지한다. 이는 승인된 기능을 PVE 조회 계약에 맞추는 구현 보완이며 role/ACL을 실환경에 적용하는 승인이 아니다.

- 추가로 VM DELETE는 VM 전용 ACL도 제거한다. 이후 storage content 목록은 VM.Config.Disk가 없으면 해당 volume을 숨길 수 있으므로 빈 목록만으로 잔여 disk 부재를 판정하면 안 된다. VM-05는 삭제 전후 선택 storage의 **Datastore.Allocate**를 요구해 ACL 제거 후에도 전체 목록의 정확한 소유 volume 부재를 검증한다. 이 권한은 storage 내용 삭제/설정까지 가능한 PVE 권한이므로 등록 검토에 명시한다. Gjallar는 기존 reviewed VM DELETE 외 storage 변경을 허용하지 않는다. 불필요한 VM.Config.Disk를 delete role에 중복 추가하지 않고 VM 삭제 V1은 유지하며 별도 GjallarVmDeleteStorageV1만 선택 storage에 추가한다. clone/template은 앞서 정한 V2 Config.Disk를 사용한다.

### TPL-02 소유 자원 정리 구현 계약 (2026-09-19 04:10 KST)

- 정리는 성공한 vm_image_build Operation이 만든 template와 staging 원본을 각각 검토·명시 실행하는 두 독립 작업으로 제공한다. 한 버튼으로 연쇄 삭제하지 않는다. 부모 제작 기록·원래 cluster/node/VMID/name·고정 image/hash·원래 volume manifest를 결합하고, 현재 실제 config/volume과 일치해야 한다. 미확정 제작의 잠금은 강제 해제하지 않으며 자동 잔여물 삭제는 제공하지 않는다.
- 제작이 끝난 VMID는 기존 관리 vmids로 새 등록한다. 별도 image_cleanup feature와 image_cleanup_storages(기존 storages의 명시적 부분집합)를 선택한다. 이 storage에만 Datastore.Allocate를 계획하고 해당 VMID에 Audit/Allocate를 부여한다. 생성 원본 template_vmids와 기존 vmids는 함께 지정할 수 있으므로 테스트 배포와 이후 정리를 위한 연결을 한 번에 검토할 수 있다. 이미지 제작 image_vmids는 미래 ID 전용으로 유지한다. 기존 token/role을 자동 변경하지 않는다.
- template 정리는 정지·보호/잠금/pending/snapshot/원본 변경 없음과 제작 소유 manifest를 재검증한다. target NFS의 images 목록을 Datastore.Allocate로 조회해 다른 VM의 parent reference를 검사한다. 필터된 조회를 참조 없음으로 처리하지 않으며 runtime은 선택한 base에 대한 의존 근거만 상위에 전달한다. 공식 PVE도 NFS base의 linked clone 사용을 거부하지만, 실패/일부 disk 잔여를 성공으로 처리하지 않고 삭제 후 VMID 부재·승인 volume 부재·미참조 volume 보존까지 관찰한다.
- staging 정리는 부모 Operation의 정확한 전용 import 파일명만 허용하고 현재 format/size와 목록을 확인한다. DELETE content는 delay 없이 imgdel UPID를 받으며 task ID의 storage binding을 검증한다. 성공 task와 해당 파일의 부재를 모두 확인한다. 임의 URL/path·다른 Operation/VM의 파일·force/purge/미참조 disk 삭제는 허용하지 않는다.
- 두 정리 요청은 공통 TaskChangeService·동일 VMID admission으로 vm_image_cleanup Operation/단일 task/GET-only recovery를 사용한다. 신규 0038은 action check만 추가하며 이력 downgrade를 거부한다. VM 삭제 후 ACL이 사라져도 source 정리는 storage 권한으로 관찰한다. 각 실행 전 변경 감지·대상 입력·삭제 영향 동의를 요구하고 결과 불명 시 재DELETE하지 않는다.
- 검증: 부모/현재 자원 소유 불일치·권한/범위 밖·보호/linked clone·snapshot·staging 변경·same key/경합·task 응답 유실/실패/부분 삭제·ACL 제거 뒤 부재/보존 증거, 웹/CLI 검토/결과와 전체 회귀. 실제 template·staging 삭제는 정확한 대상/영향의 별도 승인 후에만 한다.

### TPL-02 출처 실다운로드 검증 / 정리 권한 기반 재개 지점 (2026-09-19 04:16 KST)

- 제품 `verified_download`로 공식 이미지 전체 589299712 bytes를 실제 내려받았다. 고정 SHA-256 `6bdab6376d46d42e4203ace3733efafc7c5d37c7cb443a6cc74750097002d74b`·10 GiB virtual size·qcow2 조건이 모두 통과했으며 익명 임시 파일은 context 종료로 닫혔다. PVE upload·image 부팅·VM 생성은 하지 않았다. 출처 다운로드 검증과 PVE 실환경 제작 검증을 구분한다.
- volume 조회·삭제 후 권한 보완의 집중 142개와 추가 삭제/전환 58개 통과. 최종 local/container 모두 client 125, backend 1183 passed/57 skipped, frontend test/lint/build·runtime image 통과. 이는 아래 정리 기반 변경 전 snapshot이다. 실제 role/ACL 변경 없이 V2 clone/template role과 별도 VM-delete storage role·사용자 권한 경고를 반영했다.
- 정리 기반: `cloud_images/cleanup_contracts.py`, 관리형 image_cleanup feature·image_cleanup_storages subset·별도 역할을 추가했다. future 제작 image_vmids와 기존 정리 vmids를 분리한다. 정확한 선택 VM DELETE와 자기 VMID의 전용 staging DELETE만 허용하며 delay/force/purge/다른 파일은 거부한다. 기본 제작 토큰은 정리 권한을 자동 얻지 않는다.
- `ManagedRequests.image_base_dependents`는 선택 NFS base와 명시적 정리 storage에 대해 Datastore.Allocate를 확인한 뒤 backing reference 전체 목록을 읽고 해당 base의 의존 개수만 반환한다. Audit만으로 필터된 목록을 참조 부재 근거로 사용하지 않는다. source GET 목록도 선택된 정리 VMID의 전용 파일만 반환한다. scope/역할/기존 연결 집중 50개 통과, diff check 통과.
- 다음은 위 정리 계약의 service/adapter·0038/recovery·API·웹/CLI 연결과 실패/실제 잔여 검증이다. 현재 권한 기반만 추가됐으며 삭제 API/정리 기능은 아직 사용할 수 없다. TPL-02 전체·TPL-03·M4~M6와 실환경 검증은 미완료, Goal active다.

### TPL-02 정리 service/API 기반 재개 지점 (2026-09-19 04:18 KST)

- `operations/vm_image_cleanup/` domain/service/adapter/facade/recovery와 operator 검토·실행 API를 작성했다. 완료된 동일 cluster/node/VMID 제작 Operation·원본 무결성 증거를 확인하고 template/source를 독립 요청으로 정리한다. 정확한 VMID/이름/종류 확인, 현재 manifest 변경 감지, 단일 DELETE/UPID, 실제 부재와 미참조 volume 보존 확인을 공통 TaskChangeService로 처리한다.
- template adapter는 제작 당시 config fingerprint/volume·소유 description과 현재 상태를 비교하고 보호/linked clone을 거부한다. source는 부모의 전용 import 파일과 size/format을 검사한다. source DELETE는 imgdel의 storage, template DELETE는 qmdestroy의 VMID까지 바인딩한다. GET-only recovery에도 해당 task 종류/대상을 검사한다.
- Template/Deletion facade에 정리용 공개 관찰 helper를 추가했다. 정리 관찰은 선택 storage Allocate를 요구해 VM Config.Disk를 중복 부여하지 않는다. 기존 전환 관찰의 Config.Disk 요구와 삭제 후 무권한/필터 목록 차단은 유지한다.
- 신규 0038 migration·action check·recovery 등록을 작성했다. 아직 격리 PostgreSQL에도 적용하지 않았다. migration/기존 image adapter·template 집중 52개, 신규 cleanup service/기존 shutdown recovery 19개, API registry/operator 경계 2개 통과했다. cleanup adapter의 실제 protocol fixture, 실패·lease/partial/권한 회귀, 설정 웹/CLI·정리 웹/CLI와 전체 검증은 남아 있다.
- 다음: cleanup adapter/부모 기록 검증 보완 → 설정 image_cleanup/image_cleanup_storages와 제작 결과에서 정리 진입 → CLI·브라우저 검토/삭제 결과 → tmpfs PostgreSQL/전체 검증. 실제 정리는 미실행이며 M3/Goal 완료로 표시하지 않는다.

### TPL-02 정리 웹·CLI/격리 검증 재개 지점 (2026-09-19 04:27 KST)

- 정리 설정 웹/CLI·`vm image-cleanup show/plan/execute`·`ImageCleanupPage`를 연결했다. 제작 화면/결과에서 정리로 진입하고 template/source를 각각 명시적으로 검토한다. 동일 컴포넌트에서 다른 resource로 이동할 때 form을 새로 구성한다. 공통 useVmChange에 미제출 검토 초기화만 추가했으며 기존 단일 dispatch/미확정 처리 계약을 유지했다.
- cleanup adapter 14개, client 정리/등록 14개, cleanup service+추가 GET-only recovery·lease·wrong-task 14개 통과. 브라우저 fixture에서 삭제/보존 manifest → 잘못된 resource 확인 거부 → 최종 삭제 → 부재/보존 결과 → 별도 source 검토 진입을 확인했다. 실제 PVE 삭제는 하지 않았다.
- 0038은 이 작업의 tmpfs PostgreSQL에만 적용했고 integration 59개 통과했다. 제작/정리의 동일·다른 key 동시 요청과 단계 transaction, 기존 설치/등록/DRS 이력 보존 포함이다. local verify 통과: client 133, backend 1210 passed/59 skipped, frontend test/lint/build. 추가 cleanup recovery 6개는 뒤에 집중 검증으로 통과했다. 기준 container 최종 검증 진행 중이다.
- architecture/사용법에 exact 소유 증거, 넓은 PVE storage 권한과 좁은 Gjallar allowlist, template/source 독립 정리, 원격 source hash 재계산 없음, 미확정/부분 실패 및 live 승인 경계를 반영했다. 다음은 container 결과·최종 diff/회귀 검토 후 TPL-02 구현 검증 상태를 정리하고 TPL-03 테스트 배포·검사·명시적 테스트 VM 정리 흐름으로 이어간다. Goal active, 실제 PVE 변경·설치·운영 DB 적용·commit/push 없음.

### TPL-02 구현 검증 완료 / TPL-03 계약과 재개 지점 (2026-09-19 04:34 KST)

- 기준 container 검증도 통과했다: client 133, backend 1210 passed/59 skipped, frontend test/lint/build·runtime image. 이후 추가한 cleanup recovery 6개는 별도 집중 검사 통과다. diff check 통과. TPL-02 제작/정리의 구현 검증 완료, 실제 PVE upload/import/전환/삭제는 미검증이다.
- TPL-03은 기존 template 생성의 `boot_and_verify`와 정상 종료·삭제 흐름을 재사용한다. 별도 VM 실행 엔진·SSH executor·자동 정리를 도입하지 않는다. 템플릿 전환/제작 결과에서 원본을 미리 선택한 생성 화면으로 연결하고 새 VMID·사용자 공개키·네트워크·실행 동의를 기존 검토 절차에서 받는다.
- 생성 Operation에 원본 template 식별자·power policy만 추가 보존하고, 읽기 보고서에 부팅/cloud-init/guest agent/IP 관찰과 운영자 접속 확인을 분리한다. IP 관찰은 외부 연결이나 SSH 로그인을 증명하지 않으며 보고서에 한계를 표시한다. 중단·실패·미실행을 성공으로 승격하지 않는다. 기존 `post-create-readiness-evidence`의 actor·artifact·정확한 생성 Operation 연결을 재사용해 운영자 접속 결과만 기록한다. 새로운 인증·DB schema·실행 잠금/복구 계약 변경은 없다.
- 보고서는 생성 당시 역사적 증거이며 현재 VM 상태/동일 VMID 재사용 증명이 아니다. 정리는 VM 상세에서 현재 상태·설정·volume을 재검토한 후 정상 종료와 별도 명시적 삭제로 진행하고 삭제 Operation의 실제 부재 증거를 확인한다. 테스트 원본 템플릿/업로드 소스는 별도 정리한다.
- 검증은 보고서의 대상 불일치·미실행/실패 구분·조정 미완료 차단·접속 증거 소유 검증·비밀정보 비수집, API operator 경계, 웹/CLI 생성 진입·결과·정리 동선, 기존 생성/증거 기록 회귀를 포함한다. 실제 배포·접속·정리는 exact target/영향 승인 대기로 유지한다.

### TPL-03 웹·CLI 검사 흐름 재개 지점 (2026-09-19 04:48 KST)

- 역사적 생성 검사 GET `/operations/{operation_id}/template-test`, 생성 원본/power policy 기록, `TemplateTestPage`와 `vm template-test show/record-access`를 구현했다. 기존 생성/접속 증거 기록/종료/삭제 경로를 재사용하며 새 schema·PVE mutation API는 없다. 부팅/cloud-init/agent/IP 관찰과 운영자 접속 증거를 분리하고 생성 미성공·조정 미완료는 전체 확인 완료로 표시하지 않는다.
- 공식 제작/전환 결과에서 원본을 지정한 테스트 생성에 진입하고 생성 작업 상세에서 검사·접속 기록·정리 동선으로 이동한다. 브라우저 fixture에서 다섯 검사 항목·동의 전 기록 차단·접속 결과 저장/재조회·현재 VM 상세 링크를 확인했다. 원본 자동 대체 금지·별도 VMID·사양·부팅 검사 기본 선택도 확인했다. 사전 선택 원본의 CPU/메모리가 비는 문제를 발견해 실제 metadata 초기화를 보완했고 재검증했다.
- backend 신규 보고서/기존 증거·생성·API 집중 29개, client 신규 9개 통과. local 전체 client 142, backend 1227 passed/59 skipped, frontend test/lint/build 통과. 이후 사양 초기화·aria-pressed만 추가했다. PostgreSQL 검사는 sandbox loopback 차단으로 첫 시도 실패했으며 동일 전용 tmpfs DB 접근으로 재실행해 59개 통과했다. 기준 container 검증은 진행 중이다. diff check 통과.
- architecture·development에 역사적 보고서/직접 접속 증거/정리 단계와 CLI 사용법을 추가했다. 실제 템플릿 배포·guest-exec·SSH 접속·VM 정리는 미실행이다. 다음은 최종 frontend/container 검사·원본 부재 차단 확인 후 TPL-03 구현 상태 갱신, 이어 M4 PVE 이력과 제품 내부 이상/알림 이력을 구현한다. Goal active다.

### M4 OBS-01~02 조사·구현 계약 재개 지점 (2026-09-19 04:54 KST)

- 환경변수 토큰으로 PVE RRD **GET만** 조회했다. node `yoonmanserver`, 정지 VM `100`, storage `local`의 hour/day/week/month/year 15개 응답을 확인했다. 관찰 metadata만 `/tmp/gjallar-rrd-observation.json`(0600)에 남겼다. VM/호스트 변경·guest command는 없다.
- PVE 9.0.11 실제 반환은 hour 60초/60점, day 60초/1440점, week 1800초/336점, month 21600초/121점, year 21600초/1140점이었다. 요청 기간 전체 보존을 보장하지 않고 실제 start/end/해상도·누락을 표시한다. 정지 VM의 최근 CPU/mem/IO 값은 키 자체가 없었다. 이를 0으로 채우지 않는다. [PVE의 RRD 변경 기록](https://lists.proxmox.com/pipermail/pve-devel/2025-July/072936.html)과 공식 qemu/storage API 소스를 대조했다.
- 첫 지원은 node CPU·메모리·네트워크, QEMU VM CPU·메모리·네트워크·disk IO, storage 사용/전체 공간이다. 현재 상태 GET과 PVE `rrddata` AVERAGE를 요청 시 읽는다. hour/day/week/month/year만 제공하고 raw 임의 경로·시계열 쓰기·collector·scheduler·TSDB는 추가하지 않는다. CPU 비율은 percent, 메모리/공간은 bytes, IO는 bytes/s로 계약한다. 실제 sample timestamp와 응답 수신 시점·관찰 누락을 구분한다.
- 관리형 연결은 기존 선택 node/VM/storage와 Sys.Audit/VM.Audit/Datastore.Audit만 사용한다. RRD GET·고정 query 및 storage status GET을 기존 transport의 선택 범위 allowlist에 추가한다. 미선택 자원·임의 query·mutation은 차단하고 token/ACL을 확대하지 않는다. env 우회 fallback은 없다.
- HTTP·도메인 정규화·PVE adapter를 분리하고 current/history 부분 실패를 각각 명시한다. 웹 Insights 추이 화면과 VM 상세 진입, CLI 같은 보고서를 연결한다. 데이터 없음·권한 거절·단절·stale sample·malformed/NaN/중복 timestamp와 chart 결측 구간을 자동/브라우저 검증한다. OBS-03 발생/해제 기록은 다음 단계에서 별도 transaction·중복·보존 계약을 이 work에 정하고 구현한다.

### M3 구현 검증 완료 재개 지점 (2026-09-19 04:56 KST)

- TPL-01~03의 웹·CLI 구현 검증을 완료했다. 최종 local/container client 142, backend 1227 passed/59 skipped, frontend test/lint/build, 격리 PostgreSQL integration 59개 통과. 최종 frontend 변경(사양 초기화·원본 부재 차단·aria-pressed)도 local frontend 전체 및 최종 container에서 통과했다.
- 브라우저에서 원본이 사라졌을 때 다른 템플릿을 선택하지 않고 조회 불가·다음 단계 차단을 확인했다. 제작/전환→기존 생성→항목별 검사/직접 접속 증거→현재 VM 재확인·정상 종료·삭제 검토 동선을 제공한다. 원본 정보가 없는 과거 작업은 미기록으로 표시하고 현재 VM 재사용·정리 완료를 추정하지 않는다.
- 로드맵/PRD/architecture 상태를 구현 검증 완료 / 실환경 검증 대기로 구분했다. 실제 PVE 전환·upload/import·테스트 생성/부팅/guest-exec/접속/정리는 전부 승인 대기다. M1 설치/재시작과 M2 실제 변경도 미완료다. 전체 Goal은 active이며 다음은 위 계약에 따른 M4 OBS-01~02 구현이다.

### M4 OBS-01~02 서버·웹·CLI 기반 재개 지점 (2026-09-19 05:00 KST)

- `monitoring/`에 읽기 service·숫자/시각 정규화·PVE adapter를 분리하고 노드/VM/storage 지표 API 3개를 연결했다. 기존 읽기 scope에서 고정 기간 AVERAGE RRD·storage status만 허용한다. bool/NaN/무한/음수 지표는 결측, 잘못된/중복/역행 timestamp·과도한 응답은 명시적 오류다. 현재 IO 누적 카운터를 초당 속도로 오해하지 않는다.
- 웹 Insights 사용량·추이 페이지와 VM 상세 링크, `metrics node/vm/storage` CLI를 연결했다. 차트 결측/시간 gap을 연결하지 않고 시각 선택·최근 20개 표·실제 범위·해상도·지표별 누락/최신 관찰을 표시한다. 현재/이력 부분 실패를 각각 표시한다. dashboard와 기존 TUI는 변경하지 않았다.
- 신규 domain/managed scope/API 집중 backend 61개, client 8개, frontend test/lint/build 통과. 아직 전체 local/container과 실제 브라우저 flow 검증은 남아 있다. OBS-03은 아직 미구현이다.
- 제품 `MonitoringService`/PVE adapter로 env 연결의 node `yoonmanserver`, VM `100`, storage `local` 현재 상태·hour RRD를 GET만 읽었다. 세 대상 모두 현재/이력 응답 정상·60개·60초 해상도. 정지 VM CPU/mem/IO는 정확히 null/60개 누락으로 표시하고 메모리 한도만 관찰했다. 읽기 결과는 `/tmp/gjallar-monitoring-readonly-results.json`(0600), 스크립트는 `/tmp/gjallar-monitoring-readonly.py`다. 실제 관리형 등록·설치된 웹/CLI 환경 검증으로 간주하지 않는다.
- 다음: 격리 화면에서 결측 구간·지표 선택·부분 오류·재조회 확인, 문서 정리 후 OBS-03 임계/작업 실패 발생·해제·보존 계약과 구현. 실제 mutation/운영 DB/설치/배포는 계속 승인 대기다.

### M4 OBS-01~02 화면 검증 재개 지점 (2026-09-19 05:03 KST)

- 브라우저 fixture에서 대상/기간 조회→실제 범위·60초 해상도→0과 결측 구분→끊어진 그래프→지표 전환 시 전체 누락→기간 변경 시 이전 결과 제거→현재 값 정상/이력 실패의 부분 상태를 확인했다. 차트와 현재 값 layout도 screenshot으로 확인했다. query node/VM 링크와 keyboard 지원 시각 선택을 제공한다.
- architecture·development에 지원 지표/단위·실제 해상도·조회 권한·CLI 사용법·누락과 정지 VM 해석을 기록했다. 현재 backend 집중 61개·client 8개·frontend test/lint/build 통과이며 M4 전체 검증은 OBS-03과 함께 진행한다. 운영 DB 변경·PVE mutation은 없다.

### M4 OBS-03 임계·작업 실패 이력 계약 (2026-09-19 05:06 KST)

- 첫 OBS-03은 PVE RRD 평균 이력과 기존 append-only Operation events를 읽어 이상/해제 이력을 투영한다. 별도 DB table·시계열·collector·scheduler·외부 알림을 추가하지 않는다. 현재 API 요청이 없는 동안에도 PVE가 기록한 구간과 Gjallar Operation에 기록된 실패를 다음 조회에서 계산할 수 있다. 평균 사이의 순간 초과나 PVE 보존 밖의 상태를 검출했다고 주장하지 않는다.
- 임계값은 CPU/메모리 사용률 warning 70%, critical 85%, storage 사용률 warning 80%, critical 90%다. 지원 node/VM/storage 종류의 관찰 가능한 지표만 적용한다. PVE AVERAGE sample별 상태 변화만 기록하고 동일 상태 연속 표본은 합쳐 중복을 줄인다. 조회 구간 첫 표본이 초과면 정확한 발생 시점을 알 수 없는 ‘구간 시작 시 이미 높음’으로 표시한다.
- null·관찰 중단·불규칙 해상도·stale를 정상/해제로 처리하지 않는다. 열린 초과 구간 중 결측은 상태 미확인으로 남기고 이후 실제 정상 표본이 나왔을 때 관찰된 해제 시각을 기록한다. 마지막 상태도 최신 관찰을 확보한 경우만 정상/초과로 표시한다. interval ID는 target·rule version·최초 관찰 시각으로 안정화한다. 원본 RRD 재집계에 따라 보고서가 달라질 수 있으며 별도 불변 알림 저장소라고 주장하지 않는다.
- 작업 실패는 기존 Operations 목록을 최신 제한 개수(기본 20, 최대 50)로 읽고 exact Operation events의 failed/needs_reconciliation 발생과 이후 succeeded 해제를 표시한다. 사전 blocked/rejected는 실행 실패로 취급하지 않는다. 오류 메시지 raw 내용·토큰·명령 출력 대신 operation ID/type/status/time과 고정 안내만 반환한다. 목록이 한도에 도달하면 이전 작업 누락 가능성을 표시하고 전체 Operations로 연결한다. 기존 event 보존 정책을 변경하지 않는다.
- 임계 이력은 각 사용량 보고서와 CLI에 포함하고 웹에는 명확한 미관찰·열린 구간·해제/불명 시각을 표시한다. Insights 알림 이력은 작업 실패 목록과 대상별 임계 이력 진입을 제공한다. 확인/정리는 조회 동선이며 자동 복구·재실행·삭제는 없다. 테스트는 경계값·중복·심각도 변경·결측/중단·현재 stale·첫 구간·서로 다른 대상 ID·부분 조회 실패·작업 복구를 검증한다.

### M4 OBS-03 구현·화면 검증 재개 지점 (2026-09-19 05:19 KST)

- `monitoring/thresholds.py`에서 현재 임계 상태·평균 표본의 초과/해제 구간을 계산하고 `operation_alerts.py`에서 기존 실패/복구 events를 읽는다. 자원별 최근 100구간/20심각도 변화, 최신 20~50작업에서 최근 100실패 구간으로 응답을 제한하고 잘림·부분 실패를 명시한다. DB schema·외부 알림·자동 복구를 추가하지 않았다.
- `/insights/metrics` 임계 표와 `/insights/alerts`, CLI `metrics`·`alerts --limit`을 연결했다. 브라우저 fixture에서 초과 후 결측의 관찰 불명·실제 정상 후 해제·첫 초과 이전 상태 불명·실패 후 성공/재확인 필요·한도·개별 조회 실패·조회 개수 변경과 빈 상태를 확인했다. 화면 layout도 직접 확인했다. 실제 서버 알림 이력 검증은 아니다.
- focused backend 44개·frontend 검사 통과. CLI 오류 검증에서 이 저장소 Parser가 SystemExit 대신 ClientError를 반환하는 테스트 기대를 바로잡았다. 최종 local verify client 151, backend 1272 passed/59 skipped, frontend test/lint/build 통과. 기준 container 검사 진행 중이며 새 DB 변경이 없어 M3의 tmpfs PostgreSQL 59개 결과와 구분한다. diff check 통과.
- architecture·development에 임계값·중복/결측·PVE 보존 한계·작업 범위·읽기 사용법을 기록하고 PRD 현재 상태를 갱신했다. M4 관리형 설치 환경의 웹/CLI 검증은 대기다. 다음은 container 결과 확인 후 M4 상태 갱신, 이어 M5 PVE 백업/별도 VMID 복원 계약·권한·실패 복구 구현이다. mutation·설치·운영 DB·commit/push 없음.

### M4 구현 검증 완료 / M5 조사 재개 지점 (2026-09-19 05:21 KST)

- M4 최종 기준 container도 client 151, backend 1272 passed/59 skipped, frontend test/lint/build·runtime image 통과했다. 로드맵에 OBS-01~03 구현 검증 완료 / 관리형 설치 환경 검증 대기를 반영했다. 실제 PVE 지표/RRD GET은 앞선 env 연결 관찰 결과이며 실제 관리형 등록·웹/CLI 배포 검증으로 확장 해석하지 않는다.
- M5는 공식 PVE VZDump API/구현·storage volume 접근·QEMU restore 코드를 조사 중이다. VM.Backup + 선택 backup storage의 Datastore.AllocateSpace가 백업 목록/생성에 필요하다. 목록이 권한 때문에 필터될 수 있으므로 사전 권한 확인 없이 빈 목록을 부재 증거로 사용하지 않는다. PVE 백업 기본값의 hook·prune·알림 부작용을 명시적으로 차단하는 계약을 다음에 확정한다.

### M5 BAK-01 백업 생성·조회 구현 계약 (2026-09-19 05:24 KST)

- 첫 지원은 정지·잠금/대기 변경/snapshot 없는 QEMU VM의 scsi0 + ide2 cloud-init, 활성 NFS backup storage다. 기존 첫 지원 VM 사양을 따르며 passthrough·외부 script·backup=0 disk는 거부한다. 목록은 선택 node/storage/원본 VMID에 한정하고 archive 시점·크기·형식·원본 VMID를 표시한다. PBS·dir 생성·running VM 백업·자동 삭제/보존 정책·주기 실행은 제외한다.
- env token GET으로 node `yoonmanserver`의 `nas-server` NFS와 `local` dir backup 지원·기본값을 관찰했다. 두 storage의 VM100 backup 목록은 비어 있었고 hook 없음, 기본 remove=1/notification auto였다. 관찰은 `/tmp/gjallar-backup-readonly-observation.json`(0600), 실제 백업은 실행하지 않았다. 첫 지원 구현은 NFS에만 적용한다.
- PVE `POST /nodes/{node}/vzdump`를 단일 VMID·선택 storage·snapshot mode·zstd·remove=0·legacy-sendmail + 빈 mailto로 고정한다. mode snapshot은 정지 사전 조건 이후 외부에서 부팅한 VM을 임의로 정지시키지 않도록 선택한다. 성공 판단에는 원래 정지 상태 유지가 필요하다. Sys.Audit로 defaults를 읽고 hook script가 있거나 기본값을 확인할 수 없으면 거부한다. storage prune 정책 자체는 수정하지 않으며 remove=0으로 이 요청의 삭제를 끈다. Operation ID를 notes-template으로 기록해 다른 동시 백업과 결과를 구분한다. 기본 hook/설정의 외부 동시 변경은 중지하도록 경고한다.
- 관리형 `backup` opt-in, 기존 vmids·명시적 `backup_storages` subset을 추가한다. 역할은 VM.Backup(선택 원본 VM), Datastore.AllocateSpace(선택 백업 storage), 기존 VM.Audit/Sys.Audit/Datastore.Audit를 사용한다. root role·Datastore.Allocate·Sys.Modify를 요구하지 않는다. GET defaults·정확한 backup 목록/선택 archive·고정 POST 외에는 허용하지 않는다. 새 역할/ACL은 기존 재등록·검토·갱신 경로로만 적용한다. 실제 권한 변경은 승인 대기다.
- 공통 TaskChangeService·동일 VMID admission을 재사용한 `vm_backup` Operation/`vm_backup_observation` recovery를 추가한다. 신규 migration 0039는 lock action check만 추가하며 과거 이력을 보존한다. 요청 ID·review digest(설정/volume/기존 backup 식별자/defaults) 재검증, task의 node/type/vmid binding, GET-only recovery, 응답 유실 시 자동 재백업 금지를 유지한다. 성공은 exact task OK와 단일 신규 notes marker archive·양수 size·원본 설정/volume/정지 상태·기존 archive 보존으로 검증한다. 압축률·실제 디스크 쓰기를 예측하지 못하므로 검토 공간은 보수적 가상 크기+여유 기준이며 PVE task 실패도 분리한다.
- 검증: 최소 권한·선택 범위·후킹/삭제/외부 알림 차단, 상태 변경·공간 부족·백업 제외 disk·동시/중복·marker/VMID/UPID 불일치·부분 실패·기존 archive 소실·GET-only 복구·lease, 웹/CLI 목록→검토→생성→실제 결과, local/container/격리 PostgreSQL. 실제 백업은 exact VM/storage/영향 별도 승인 뒤 수행한다. 실패 후 임의 백업 삭제·재실행 대신 Operation/task/archive/원본을 조회한다. BAK-02 별도 VM 복원은 이어서 격리 네트워크·권한·검증 계약을 정한다.

### M5 BAK-01 서버·웹·CLI 기반 재개 지점 (2026-09-19 05:33 KST)

- `backups/`의 고정 PVE 요청/목록/원본 검사와 `operations/vm_backup/`의 검토·단일 실행·실제 archive 확인·GET-only recovery를 추가했다. 최소 VM.Backup/storage AllocateSpace와 기존 읽기 권한으로 구현하며 source disk는 config의 소유 volume/가상 용량·fingerprint로 확인한다. 게스트 disk 내용 무결성 검증이라고 주장하지 않는다. 알림 off·remove=0·fleecing off·다른 백업 기다리지 않는 lockwait=0을 고정했다.
- 관리형 backup feature·명시적 backup_storages subset·기존 연결 갱신 경로의 웹/CLI 입력을 추가했다. defaults hook 확인·정확한 source/storage·고정 POST만 허용하고 다른 VM·삭제·prune·외부 알림 옵션을 거부한다. plan version v13, 실제 role/ACL 적용 없음.
- 신규 0039/action/recovery 등록과 백업 목록/검토/실행 API 3개, `/instances/:vmid/backups`와 VM 상세 진입, CLI `vm backup list/plan/execute`를 작성했다. 공통 UI 결과 확인에 Operation ID 일치와 이 새 흐름의 type/target 확인을 추가했다. 아직 전체 UI/검증 완료로 표시하지 않는다.
- core·migration 집중 43개, managed scope 31개, frontend lint 통과. 초기 생성한 migration downgrade 조건의 문법 오류를 집중 테스트로 발견해 수정했고 재검증 통과했다. route registry와 API/CLI 계약 검사는 새 경로를 추가한 뒤 재실행 중이다. 0039는 운영 DB/격리 PostgreSQL에 아직 적용하지 않았다.
- 다음: API/CLI 검증 결과 보완, 격리 PostgreSQL 동시 admission·전체 검사, 브라우저 목록/검토/실행/결과 확인과 사용 문서, 이어 BAK-02 격리 복원. 실제 backup/restore와 설치/배포는 계속 승인 대기다. Goal active, commit/push 없음.

### M5 BAK-01 화면·PostgreSQL 검증 재개 지점 (2026-09-19 05:39 KST)

- 0039는 이 작업 전용 tmpfs PostgreSQL에만 적용했다. 백업 동일/다른 request key·늦은 재요청·compute/delete 경쟁을 포함한 integration 64개 통과했다. source/storage GET product adapter도 env 연결 `yoonmanserver`/VM100/`nas-server`의 빈 백업 목록과 가용 공간을 확인했다. 실제 백업 생성은 없다.
- 브라우저 fixture에서 빈 목록→원본/공간/IO 검토→동의 전 차단→명시적 생성→canonical Operation 대조→archive 시점/크기와 원본 보존 결과→복원 미실행 구분을 확인했다. 성공 뒤 이전 빈 목록이 남는 UI 오류를 발견해 canonical 관찰의 새 archive/가용 공간으로 갱신하고 재검증했다. 미확정 제출 뒤에는 이전 목록을 현재 결과처럼 표시하지 않는다.
- API/viewer/operator/registry 3개, client 백업/등록 14개와 후속 canonical mismatch/opt-in 검사, frontend test/lint 통과. 첫 전체 검사에서 recovery runner 허용 목록 테스트에 신규 handler 누락을 발견해 목록을 갱신했다. 제품 handler 누락이 아니며 최종 local/container를 재실행 중이다. 실패 snapshot container는 중지하고 수정 snapshot으로 시작했다. 추가 task 실패·다른 payload 재사용 검사는 별도로 실행 중이다.
- architecture/development에 지원 범위·최소 권한·고정 요청·목록/원본 metadata의 한계·0039·복구·웹/CLI 사용법을 기록했다. BAK-01 구현 검증 완료 여부는 최종 검사 결과 뒤 갱신한다. BAK-02와 M6은 미구현, 전체 실환경 변경은 승인 대기이며 Goal active다.

### M5 BAK-02 별도 VM 복원 계약 (2026-09-19 05:44 KST)

- 첫 복원은 같은 node의 선택 NFS backup에 있는 QEMU VMA 계열 archive를 선택하고, 기존 원본 VMID와 다른 미사용 VMID·NFS images storage로 복원한다. 현재 원본 VM은 존재하고 정지 상태여야 하며 원본·archive를 그대로 보존한다. 원본 덮어쓰기·PBS/live restore·다른 node/cluster·자동 삭제는 제외한다. archive config는 PVE extractconfig GET으로 읽되 원문/시크릿을 응답·Operation·로그에 저장하지 않고 허용 장치/옵션·fingerprint만 사용한다.
- 네트워크 충돌은 복원 POST 자체에서 단일 net0를 선택 Linux bridge + 새 로컬 MAC + link_down=1로 덮어써 차단한다. onboot=0/start=0/live-restore=0/force=0/unique=1과 exact 이름/Operation description을 고정한다. scsi0 + ide2 cloud-init, virtio net0 하나, 외부 장치·hook/args/custom snippet·추가 NIC 없는 archive만 지원한다. 부팅 전부터 NIC 링크가 끊어져 있어 원본의 고정 IP·게스트 hostname/SSH key가 복제돼도 실제 네트워크에 연결하지 않는다. 외부 설정 변경은 중지해야 하며 NIC 재연결·게스트 identity/IP 변경은 별도 명시적 운영 단계다.
- `restore` opt-in, 새 `restore_vmids`를 다른 기존/생성/clone/image 범위와 분리한다. backup_storages subset은 backup 또는 restore 기능에 사용한다. 원본 VM.Backup/Audit, 선택 backup/target storage AllocateSpace/Audit, 선택 target VM Allocate/Audit/Config.Disk(실제 volume 조회)·PowerMgmt·GuestAgent.Audit, 선택 bridge SDN.Use를 계획한다. 기존 토큰은 자동 확대하지 않고 갱신 검토/재시작 경로를 사용한다. 임의 disk/network 변경·shell·guest-exec 권한은 추가하지 않는다.
- 공통 TaskChangeService와 두 VMID 정렬 잠금을 `vm_restore`에도 적용한다. source/target exact binding을 Operation/recovery/lock에 동일하게 기록하고 transaction·lease·중복 처리·이력 보존 계약을 유지한다. 신규 0040은 action check만 추가한다. PVE restore 단일 POST 뒤 exact qmrestore task + 원본 config/volume metadata·선택 archive metadata 보존 + 신규 target 이름/설명·정지/onboot=0/net0 link_down·소유 volume 실제 크기·주요 hardware 설정을 검증한다. archive의 root mapping hint와 config가 모순되면 실행하지 않는다. 실패/응답 유실은 잠금을 유지하고 GET-only 재관찰하며 자동 재restore/삭제/후속 start를 하지 않는다.
- 복원 완료는 부팅 확인과 분리한다. 기존 Start/Shutdown 흐름을 명시적으로 재사용하고 복원 검사 보고서에 정확한 복원 Operation·현재 target identity·전원·guest-agent 관찰·NIC 격리·원본/백업 보존을 각각 표시한다. 실행 중 QEMU만으로 OS/서비스/외부 접속 성공을 주장하지 않는다. guest agent가 없으면 해당 항목은 미확인이다. 정리도 기존 현재 VM 재검토·명시적 삭제를 사용한다.
- 검증: archive parser·secret 비보존·대상/권한/bridge/공간·설정변경·archive 바꿔치기·잠금/동시/중복·잘못된 task·응답유실·부분 disk·네트워크 isolation·GET-only recovery·웹/CLI 검사 동선·격리 PostgreSQL/local/container. 실제 restore/boot/cleanup와 새 권한/운영 migration 적용은 exact target 승인 대기다. [공식 VZDump API](https://raw.githubusercontent.com/proxmox/pve-manager/master/PVE/API2/VZDump.pm), [QEMU restore API](https://raw.githubusercontent.com/proxmox/qemu-server/master/src/PVE/API2/Qemu.pm), [backup config 조립](https://raw.githubusercontent.com/proxmox/qemu-server/master/src/PVE/VZDump/QemuServer.pm)을 근거로 하며 로컬 실제 PVE 9.0.11 archive protocol 검증은 남아 있다.

### M5 BAK-01 구현 검증 완료 재개 지점 (2026-09-19 05:46 KST)

- 최종 local/container: client 160, backend 1310 passed/64 skipped, frontend test/lint/build·runtime image 통과. 추가한 task 실패·payload 충돌 2개를 포함한 backup core 36개도 별도 통과했다. 격리 PostgreSQL 64개 통과, diff check 통과. 앞선 recovery 허용 목록 테스트 누락과 UI 이전 목록 잔존은 수정·재검증했다.
- BAK-01 웹·CLI 목록/검토/명시적 생성/실제 archive·원본 보존 결과의 구현 검증을 완료했다. PRD/architecture/roadmap에서 실제 PVE 백업 미검증과 분리했다. env adapter 목록 조회는 read-only protocol 확인이며 설치된 관리형 서버의 실사용 검증이 아니다.
- 다음은 위 BAK-02 계약의 archive config parser·격리 복원 request policy·관리형 최소 권한과 두 VMID lock/recovery 구현이다. M5 전체·M6과 실환경 검증은 여전히 미완료, Goal active다.

### M5 BAK-02 archive·격리 요청 기반 재개 지점 (2026-09-19 05:50 KST)

- `backups/archive.py`에 허용 QEMU config parser·root mapping 대조·원문/secret 비보존 manifest·복원 시 ID/volume 경로 변화 외 hardware 비교를 작성했다. 첫 복원은 SeaBIOS, VLAN/trunk/추가 옵션 없는 virtio net0 한 개로 제한한다. unknown config/section·duplicate key·host path·backup 제외 disk·누락/불일치 root mapping을 차단한다. 별도 검사 전 복원 가능성을 추정하지 않는다.
- `vm_restore/domain.py`에 strict 요청/명시적 확인·새 target task binding·원본과 다른 local MAC 도출을 작성했고 `backups/contracts.py`에 net0 link_down=1/onboot=0/force=0/start=0/live-restore=0/unique=1의 고정 복원 policy를 추가했다. MAC의 전역 유일성을 보장하는 대신 link_down으로 네트워크 트래픽을 막는다. archive 무결성은 raw disk hash를 읽은 것이 아니며 metadata/config 변경 감지와 실제 restore/boot 검증을 구분한다.
- 최소 권한을 위해 destination은 `restore_storages`를 별도 storages subset으로 선택한다. 단순 조회 source storage까지 AllocateSpace를 넓히지 않는다. source backup storage의 AllocateSpace는 PVE archive 읽기에도 필요한 권한이다.
- 집중 검사에서 operation_digest가 mapping만 받는 계약을 확인해 raw config를 mapping에 넣어 fingerprint하도록 수정했다. parser/secret·허용 장치·NIC 격리·잘못된 task·scope 테스트 21개 통과했다. 아직 restore service/API·관리형 role·lock/action·웹/CLI·실환경 검증은 없다. 다음은 관리형 scope/role/정확한 GET/POST와 two-VM admission/recovery, 그 다음 adapter/service를 연결한다.

### M5 BAK-02 서버·복구 기반 재개 지점 (2026-09-19 06:00 KST)

- 관리형 restore opt-in·분리된 restore_vmids/restore_storages·최소 role/ACL 계획(v14)과 exact archive extract GET·고정 격리 restore POST를 구현했다. 관리형/parser 집중 54개 통과. 실제 역할/ACL·PVE 변경은 없다.
- restore adapter/service는 미사용 VMID의 PVE nextid 확인, 권한·NFS 공간·활성 bridge/대기 변경 확인, archive config·파일 metadata와 원본을 재대조한 뒤 단일 qmrestore를 실행한다. 성공에는 정확한 target task·원본/백업 보존·새 identity·정지/onboot off/NIC link_down·소유 disk의 실제 크기/형식·hardware 대조를 요구한다. raw config/게스트 secret은 저장하지 않는다.
- 두 VM 정렬 잠금·GET-only recovery를 restore에도 적용하고 신규 0040/action을 추가했다. source lock 손상 테스트에서 clone 전용 조건이 남은 recovery repository 검사를 발견해 공통 lock 개수 계약으로 수정했다. source 손상·부분 실패·응답 유실·다른 target/UPID·파일/설정 변경·동일 요청 재실행 방지와 기존 clone 회귀를 포함해 core/schema/recovery 92개 통과. 0040은 SQLite test에만 적용했으며 격리 PostgreSQL/운영 DB에는 아직 미적용이다.
- 최초 집중 검사 명령의 cwd/PYTHONPATH를 문서 기준으로 바로잡아 root에서 재실행했다. 생성 중 발견한 0040 downgrade SQL 조건 오류도 수정 후 실제 migration 보존 검사에 통과했다.
- 현재 API·조회 전용 복원 검사 보고서를 연결 중이다. 웹/CLI·등록 입력·실제 화면·전체/local/container/격리 PostgreSQL 검증은 남아 있다. 아직 BAK-02 완료로 표시하지 않는다. 실제 restore/boot/cleanup·운영 DB·설치/배포·commit/push 없음.

### M5 BAK-02 구현 검증 완료 재개 지점 (2026-09-19 06:12 KST)

- 웹 백업 행→격리 복원 조건→새 이름/원본·새 VMID 확인→명시적 실행→새 target canonical Operation 대조→검사 보고서와 VM 상세의 별도 시작/종료 동선을 연결했다. CLI `vm restore plan/execute/report`도 동일하게 원본/새 대상과 전체 payload를 확인하며 서버/profile에 묶인 0600 검토 파일을 사용한다. 기존 연결 갱신의 웹/CLI restore 입력과 최소 권한 계획을 연결했다. TUI 기본 질문과 대시보드는 유지했다.
- 브라우저 fixture에서 격리 동의 전 차단, 공간·MAC/bridge 검토, 성공과 부팅 미실행 구분, 조회 보고서의 정지→실행 중/agent 응답→archive 부분 조회 불가를 확인했다. 보고서 layout을 screenshot으로 직접 확인했다. 실제 PVE 복원/부팅은 없었다. 보고서는 현재 읽기이며 자동 부팅·NIC 연결·정리·DB 보고서 저장을 하지 않는다.
- 0040은 작업 전용 tmpfs PostgreSQL에만 적용했다. clone/restore 정방향·역방향 두 VM 동시 admission과 혼합 경쟁을 포함한 PostgreSQL 68개 통과. local/container는 client 172, backend 1376 passed/68 skipped, frontend test/lint/build·runtime image 통과했다. 뒤에 추가한 frontend restore URL/payload/GET 계약도 별도 검사 통과했다. route registry count/정렬 누락은 수정 후 전체 검사에 통과했다. diff check 통과.
- PRD·architecture·development·roadmap에 첫 지원·권한/0040·실패 복구·사용/격리 부팅/명시적 정리 절차를 갱신했다. BAK-01~02는 구현 검증 완료이며 실제 관리형 설치·PVE backup/restore/archive protocol/부팅/정리는 미검증이다. PVE metadata/config 대조와 disk 전체 내용 무결성을 구분했다. 관리형 정리 전 future restore ID를 기존 VM/delete 범위로 옮기는 재등록이 필요하다.
- 다음은 M6 OPS-01~03의 확정 범위·의존성과 현재 구현을 대조해 정지 VM 이동부터 구현한다. 운영 DB·PVE mutation·설치/배포·commit/push는 없음. M6·실환경 검증이 남아 Goal active다.

### M6 OPS-01 정지 VM 이동 구현 계약 (2026-09-19 06:17 KST)

- 첫 이동은 동일 cluster의 서로 다른 online node, 같은 PVE version·CPU model, 동일 ID의 활성 shared NFS images storage, 동일 이름의 활성 Linux bridge, 정지/onboot=0·비HA 일반 VM이다. scsi0 + ide2 cloud-init, VLAN/trunk 없는 단일 virtio net0만 지원한다. 디스크 복사·storage remap·local disk·snapshot·pending/lock·외부 장치/스크립트·HA·live migration·자동 부팅은 제외한다. disk bytes·설정·게스트 identity는 유지하고 node 위치만 바꾼다. CPU model/version 일치는 부팅/서비스 성공 보장이 아니며 이동 후 부팅은 별도 명시적 단계다.
- 공식 QEMU migrate GET/POST와 env GET-only로 VM100의 정지/ha.managed=0, 대상 node2/3 allowed, local disk/resource 없음, source/node2의 동일 9.0.11 build·Ryzen 7 5825U·nas-server shared NFS를 확인했다. 이 관찰은 테스트 자원 예약이나 VM100 이동 승인이 아니다. 기록 `/tmp/gjallar-migrate-readonly-observation.json`은 0600이며 mutation 없음.
- 검토는 VM.Audit/Migrate/Config.Disk(실제 volume 조회), 양쪽 node Sys.Audit·storage Datastore.Audit·bridge SDN.Use를 확인한다. 새 관리형 migrate opt-in은 기존 선택 VMID와 최소 두 선택 node, storage/bridge 범위 안에서만 허용한다. storage 할당·Sys.Modify·root·raw SSH executor를 도입하지 않는다. PVE API 내부의 이동 transport/cluster 정책을 따르며 Gjallar가 호스트 접속 설정을 바꾸지 않는다.
- PVE migrate precondition의 allowed target·running=false·local/mapped resource 없음과 실제 공유 volume/bridge·node 호환성을 확인하고 검토 digest/최초 dispatch 직전 재검증한다. POST는 target·online=0·with-local-disks=0·force=0만 고정한다. migration_type/network·storage mapping·bandwidth·HA/강제 옵션을 받지 않는다. PVE API의 quorum/실제 VM migration lock을 존중하며 외부 동시 변경의 완전 차단을 주장하지 않는다.
- canonical target은 동일 VMID와 원본 node(UPID task 조회 node)이며 details.destination에 목적 node를 기록한다. cluster+VMID 단일 잠금·기존 TaskChangeService/idempotency/lease를 유지한다. 신규 0041은 vm_migrate action check만 추가한다. 성공은 exact source-node qmigrate VMID task OK, cluster index의 단일 VM이 목적 node에 있음, 목적 config·소유 volume/크기·정지/onboot/guest identity·NIC 설정 보존과 source 위치 소실을 함께 확인한다. 실패·응답 유실·위치 불명은 잠금을 유지하고 GET-only 재관찰하며 자동 재이동/역이동/부팅/삭제하지 않는다.
- 웹·CLI 검토/실행/현재 위치 결과·Operation 복구와 managed 갱신을 함께 연결한다. 테스트는 범위/최소권한·다른 node/VMID·HA/localdisk/bridge 불일치·상태/설정 drift·중복/경합·실패/응답유실·task/위치/volume 불일치·GET-only 복구·UI·격리 PostgreSQL/local/container다. 실제 이동·운영 0041 적용은 정확한 대상/영향 승인 대기다. 이후 OPS-02 준비 보고서와 OPS-03 호스트 설정의 별도 계약을 이어간다.

### M6 OPS-01 서버·권한 기반 재개 지점 (2026-09-19 17:43 KST)

- `vm_migrate/domain.py`·adapter·TaskChangeService를 구현했다. 같은 PVE version/CPU model·shared NFS·동일 활성 bridge, 비HA 정지/onboot=0·단일 disk/NIC와 PVE precondition을 검토한다. 목적 node에서 같은 volume 크기/형식을 실행 전에 확인하고, 이후 정확한 단일 cluster 위치·설정/volume 보존·정지를 대조한다.
- 관리형 migrate opt-in·VM.Migrate/Config.Disk·선택 bridge SDN.Use와 v15 계획을 추가했다. storage 할당·host 수정·전원 권한은 자동 추가하지 않는다. 선택한 두 node/기존 VMID의 exact GET/고정 offline POST만 허용한다. 기존 연결 갱신 경로는 유지한다.
- 신규 0041과 vm_migrate_observation GET-only 복구를 작성했다. core/schema/기존 managed 검사 82개, 추가 migrate 권한·scope 포함 집중 검사 73개 통과. 잘못된 위치/UPID·부분 변경·응답 유실·HA/localdisk/대기변경·node 호환성 실패·재실행 금지를 포함한다. 0041은 SQLite test 외 DB에 아직 적용하지 않았다.
- 남은 일은 OPS-01 API·웹/CLI/권한 입력·사용 문서, 격리 PostgreSQL·전체 검증과 화면 확인이다. OPS-02 준비 보고서·OPS-03 host 설정은 아직 미구현이다. 사용자 상태 질문에 M2~M5 구현 검증 완료와 실환경 검증 대기를 구분해 안내했다. 실제 이동/설치·운영 DB·PVE mutation·commit/push 없음, Goal active.


### M6 OPS-01 구현 검증 완료 재개 지점 (2026-09-19 17:58 KST)

- operator API 검토/이동, VM 상세→별도 노드 이동 화면, CLI `vm migrate show/plan/execute`, 기존 연결 갱신의 migrate 선택을 연결했다. canonical source node/같은 VMID/전체 요청과 목적 실제 위치를 분리하며 성공을 부팅·접속 검증으로 표시하지 않는다. TUI 기본 질문과 대시보드 구성을 유지했다.
- 브라우저 fixture에서 동일 node 차단·잘못된 목적 조회 거절·동의 전 차단·검토→단일 실행→목적 위치/정지·별도 부팅 안내를 확인했고 화면 layout을 직접 봤다. 작은 cloud-init disk가 0.00 GiB로 보이던 표기를 MiB로 보완해 4.00 MiB를 확인했다. 실제 PVE 이동은 아니다.
- API/core/registry 41개, client/등록 22개 통과. client test 대역이 GET과 POST migrate를 혼동한 것을 수정한 뒤 재검증했다. 0041은 기존 작업 전용 tmpfs PostgreSQL에만 적용했으며 이동 중복/늦은 replay·compute/backup/delete 경쟁을 포함한 PostgreSQL 전체 74개 통과했다.
- local/container 공통 검증은 client 185, backend 1418 passed/74 skipped, frontend test/lint/build·runtime image 통과했다. 마지막 용량 표시 보완 뒤 frontend test/lint/build도 별도 통과했다. 기존 build의 큰 chunk 경고는 남아 있고 실패는 아니다. 실제 운영 DB·PVE mutation·설치/배포·commit/push 없음.
- architecture·development에 제한 범위/최소 권한/0041/GET-only 복구·웹/CLI 사용법을 기록하고 PRD/로드맵에 OPS-01 구현 검증 완료와 실환경 검증 대기를 구분했다. 다음은 OPS-02의 노드 영향·대상별 준비 보고서와 OPS-03의 기존 directory storage/VM용 bridge 설정이다. Goal은 active이며 M6 전체와 실환경 검증은 완료되지 않았다.

### M6 OPS-02 노드 유지보수 준비 보고서 계약 (2026-09-19 18:00 KST)

- 기존 workload inventory의 한 관찰에서 선택 node의 VM/template·disk/storage·bridge와 관찰 시각/누락을 읽는다. 현재 연결 권한으로 보이는 QEMU 범위만 다루며 숨겨진 VM·LXC·HA/cluster service·다른 호스트 의존성이 없다고 추정하지 않는다. 빈 목록도 노드 전원 종료 허가가 아니다. 자동 evacuate·정상 종료·백업·migration·host 변경은 없다.
- operator 조회 보고서에 목적 node와 NFS backup storage를 선택하면 기존 OPS-01 검토와 BAK-01 목록의 공개 application 경계를 재사용해 대상별 이동 가능 여부와 최근 archive metadata를 읽는다. 필수 입력이 없으면 ‘미확인/선택 필요’, 미지원 template·실행 중 VM·권한 부족·부분 실패는 각각 표시하고 정상으로 바꾸지 않는다. 기존 write 권한을 자동 추가하지 않는다.
- backup 기준은 운영자가 선택한 최근 시간(기본 24시간, 1~720시간) 안의 양수 크기 archive 존재다. 시점/크기 관찰만 통과하며 복원 가능성·내용 최신성·검사 성공을 보장하지 않는다. 이동 가능·최근 backup metadata가 모두 확인된 VM은 ‘수동 이동 준비 확인’, 원본 node에 남아 있는 사실과 실제 이동 미수행을 함께 표시한다. 부팅·접속·호스트 종료 안전성은 별도 확인한다.
- 한 조회의 추가 PVE 검사는 기본 10개/최대 20개 VM로 제한하고 나머지를 명시적 미검사로 남긴다. 전체 영향 목록도 최대 200개와 잘림/총 관찰 개수를 반환한다. template·중복 ID·관찰 누락·오래된/미래 시각은 준비 완료로 승격하지 않는다. snapshot이 없으면 unavailable을 반환한다. 개별 예상 조회 오류는 해당 검사에만 남기고 다른 대상 결과는 보존하며 임의 broad catch로 프로그래밍 오류를 숨기지 않는다.
- 웹 Insights의 노드 유지보수와 CLI `maintenance node`에서 같은 보고서를 조회하고 VM 상세/백업/명시적 이동으로 이어간다. DB schema·보존 상태·scheduler를 추가하지 않는다. 검증은 missing/stale/partial/권한·빈/중복/잘림·template/running·부분 실패·미래/오래된 backup·준비 결과 구분·GET-only·화면/CLI/API 계약이다.

### M6 OPS-02 구현·화면 검증 재개 지점 (2026-09-19 18:08 KST)

- `maintenance/`의 inventory/public backup·migration 검토 조합과 operator GET API, 웹 Insights 노드 유지보수, CLI `maintenance node`를 연결했다. 실제 이동 실행·Operation 기록·DB schema·자동 종료는 추가하지 않았다. 부족한 선택 권한은 해당 검사에 표시한다.
- 5분 이내 online node와 storage/network/vm_config/vm_detail 관찰을 요구하되 정지 VM optional guest_agent 누락은 차단하지 않는다. scope 밖 자원·LXC·cluster service를 관찰했다고 주장하지 않고 빈 목록도 종료 안전으로 해석하지 않는다. 최근 backup metadata와 수동 이동 준비, 실제 실행 완료를 구분한다.
- backend/core/API/registry 34개와 추가 부분 실패/누락 회귀 2개, CLI 14개, frontend test/lint 통과했다. router import 위치 오류를 집중 검사로 발견해 수정했다. 브라우저 fixture에서 준비 확인 1개·실행 중/backup 권한 실패 1개·빈 범위를 확인했고 상단 보고서와 VM별 카드 layout을 직접 검토했다.
- local 전체 검증: client 199, backend 1452 passed/74 skipped, frontend test/lint/build 통과. 기준 container는 현재 session 71066, `/tmp/gjallar-maintenance-container.log`에서 진행 중이며 아직 완료로 표시하지 않는다. 새 DB 변경이 없어 앞선 PostgreSQL 74개 결과와 분리한다. architecture/development/PRD 사용·범위 문서 갱신, diff check 통과.
- 다음은 container 결과 확인 후 OPS-02 상태 갱신, 이어 OPS-03의 directory storage·VM용 Linux bridge 변경/반영·권한·잠금/복구 계약이다. 실제 PVE mutation·설치/배포·운영 DB·commit/push 없음. Goal active.


### M6 OPS-03 사전 조사 메모 (2026-09-19 18:10 KST)

- [공식 storage config API](https://raw.githubusercontent.com/proxmox/pve-storage/master/src/PVE/API2/Storage/Config.pm)를 확인했다. 등록·수정에는 `/storage`의 Datastore.Allocate가 필요하고 수정은 config digest 검사를 지원한다. 선택 storage에 한정한 product policy와 PVE token 자체의 더 넓은 권한을 구분해 등록 검토에 표시해야 한다. 아직 역할/ACL/DB/schema·host mutation 구현은 하지 않았다.
- [공식 DirPlugin](https://raw.githubusercontent.com/proxmox/pve-storage/master/src/PVE/Storage/DirPlugin.pm)의 path는 고정이고 create-base-path/create-subdirs 기본값은 활성이다. 기존 directory 등록 계약에는 이 기본 파일 생성 영향을 명시적으로 차단하고 실제 존재/활성 검증을 연결해야 한다. raw SSH로 directory를 만들거나 수정하지 않는다.
- [공식 Network API](https://raw.githubusercontent.com/proxmox/pve-manager/master/PVE/API2/Network.pm)의 bridge 생성·수정은 pending config를 만들며 별도 reload가 호스트 전체 ifreload를 수행한다. node Sys.Modify가 필요하고 digest 매개변수는 없다. 단순 bridge 설정 저장을 실제 반영 성공으로 처리할 수 없으며 타인의 pending 변경·관리망·물리 NIC 영향을 검토하고 stage/dispatch/task/관찰 checkpoint와 GET-only 복구를 설계해야 한다. 실제 PVE 9.0.11 변경 protocol은 미검증이다.
- 기존 durable lock/recovery는 VM target binding을 전제로 한다. VMID를 가짜 host ID로 재사용하지 않고 host/storage target의 명시적 잠금과 fencing 계약을 먼저 정할 예정이다. 이미 적용한 migration은 수정하지 않는다. 이 메모는 설계 완료나 live 실행 승인이 아니다.


### M6 OPS-02 구현 검증 완료 재개 지점 (2026-09-19 18:10 KST)

- 기준 container session 71066은 exit 0으로 종료했다. client 199, backend 1452 passed/74 skipped, frontend test/lint/build와 runtime image build가 모두 통과했다. 마지막 카드 문구를 ‘현재’ 대신 ‘관찰 당시 위치’로 명확히 한 뒤 frontend test/lint/build를 별도 재검증했다. 새 DB 변경은 없으며 OPS-01의 격리 PostgreSQL 74개 검증과 구분한다.
- OPS-01~02 구현 검증 완료 / 실환경 검증 대기로 로드맵을 갱신했다. PRD에 남아 있던 첫 범위 ‘초안’과 read/power만 지원한다는 설명을 현재 사용자 승인·구현 상태에 맞췄다. 이전 역사 기록은 보존했다. diff check 통과.
- 다음 실행은 위 OPS-03 조사에 따라 기존 directory storage 등록/수정, VM용 bridge 생성/수정·VLAN-aware와 실제 반영 확인을 위한 host target lock/fencing·단계별 복구 계약부터 작성한다. 그 후 서버/관리형 권한/웹·CLI/격리 검증을 함께 진행한다. M1 설치·M2~M6 live 검증은 정확한 target 승인 대기로 유지한다.
- browser tab 2는 유지보수 fixture이며 `/tmp/gjallar-ui-fixture-migrate-0919.jsx`에 이동 fixture를 보존했다. UI 임시 파일 `.gjallar-review.html/.jsx`는 전체 화면 검증 종료 후 정리한다. Goal active, 커밋·푸시·운영 DB 적용·PVE mutation·설치/배포 없음.

### M6 OPS-03 호스트 변경 조정 기반 계약 (2026-09-19 18:14 KST)

- VMID를 재사용하지 않는 `proxmox_configuration` scope의 cluster 단위 durable lock을 추가한다. canonical target은 storage(`proxmox_storage`, `storage:<id>`) 또는 bridge(`proxmox_network`, `node:<node>/bridge:<iface>`)이며 실제 target과 작업 종류를 Operation·recovery·lock evidence에 동일하게 묶는다. 첫 host operation type은 `host_storage`·`host_network`다.
- 기존 연결 전환·VM admission이 사용하는 transaction advisory lock을 공통 admission gate로 재사용한다. 호스트 변경은 같은 cluster의 열린 VM/host lock이 없어야 진입한다. VM 변경도 열린 host configuration lock이 있으면 진입하지 않는다. 서로 다른 VM의 기존 동시 실행은 유지하고 host 변경 중에만 신규 VM mutation을 보류한다. 외부 PVE 작업까지 막는다고 주장하지 않는다.
- host lock·Operation·recovery lease를 같은 transaction에 준비한다. 매 host checkpoint에서 종류/cluster/target/lock ID/owner/scope/VMID null·두 이력 binding을 대조하고 손상 시 dispatch·success·release를 거부한다. binding 오류 기록을 위한 non-transition paused observation만 허용한다. stale·reconciliation lock은 자동 해제하지 않는다.
- 신규 0042는 기존 `operation_locks`에 두 host action·새 scope와 host 전용 open unique index를 추가한다. 기존 VM partial unique index·이력·vmid 값은 보존한다. host scope와 VMID null/action 조합을 check constraint로 묶는다. host 이력이 남으면 downgrade는 거부한다. SQLite schema/회귀와 실제 격리 PostgreSQL 양방향 VM/host·host/host race, 멱등·rollback·lease/target 손상 검사를 수행한다. 운영 DB에는 적용하지 않는다.
- 관리형 admission은 host feature/node/선택 storage 또는 bridge 범위를 별도로 검사하고 기존 revision pin·전환 drain·암호화 키 확인을 유지한다. 선택하지 않은 기존 연결에는 host 권한을 부여하지 않는다. PVE role/정확한 HTTP 요청 policy와 실제 stage/반영/GET-only recovery handler는 기능별 계약·검사와 함께 이어서 연결한다. 현재 기반만으로 host 기능 완료를 선언하지 않는다.

### M6 OPS-03 호스트 조정 기반 검증 재개 지점 (2026-09-19 18:27 KST)

- `operations/host_config/`의 canonical storage/bridge target·cluster lock·원자 admission과 기존 VM admission의 host lock 차단을 추가했다. 기존 연결 transaction gate를 공유하며 동일 host 요청은 하나의 Operation/lease만 만든다. recovery checkpoint는 두 이력·실제 lock의 binding과 recovery 종류/실행 모드를 확인하고 binding patch 변경도 거부한다. 오류 관찰만 기록할 때는 잠금을 보존한다.
- 새 0042는 VM 이력/index를 보존하고 host scope/action/VMID null 및 open unique index를 추가했다. SQLite schema/회귀 66개, 관리형 연결의 암묵 권한 확장 금지·재시작·admission closed 및 host 공개 lock/drain 검사 포함 집중 82개가 통과했다. 실제 격리 PostgreSQL host/VM·host/host·동일 요청 경쟁 3개도 통과했다. 0042는 기존 임시 PostgreSQL DB에만 적용했다.
- PostgreSQL 전체 77개 중 76개 통과 후 이전 schema 검사에 새 host index/constraint 기대값이 빠진 실패 1개를 수정했다. 해당 schema 묶음 3개 재검증 통과, 기존 DRS hard-zero 거부와 Jobs/Artifacts·VM 이력 보존을 유지했다. PVE 호출 없이 테스트 전용 schema만 생성/정리했다.
- `pnpm run verify`는 exit 0, client 199·backend 1515 passed/77 skipped·frontend test/lint/build 통과다. container는 session 85770, `/tmp/gjallar-host-coordination-container.log`에서 진행 중이다. architecture와 roadmap은 내부 조정 기반/기능 구현 중으로 구분했다. OPS-03 공개 기능·실환경 검증은 아직 완료하지 않았다.
- 다음은 container 결과 확인 후 directory storage의 정확한 생성/수정·GET-only 결과 확인, Linux bridge stage/reload·GET-only 복구, 최소 권한·기존 연결 갱신·웹/CLI 구현이다. host recovery 종류는 기반에만 등록돼 있고 runner handler·공개 생성 경로는 아직 없다. 실제 PVE mutation·운영 DB·설치/배포·commit/push 없음. Goal active.
- 추가 source 확인: [공식 Storage Plugin](https://raw.githubusercontent.com/proxmox/pve-storage/master/src/PVE/Storage/Plugin.pm)은 `create-base-path=0`/`create-subdirs=0`에서 디렉터리 생성을 건너뛰고 기존 base directory 여부를 확인한다. 하위 content directory의 존재까지 보장하지 않으므로 지원 contract에 따로 반영해야 한다. [Config API](https://raw.githubusercontent.com/proxmox/pve-storage/master/src/PVE/API2/Storage/Config.pm)의 생성 시 활성 검사는 API를 받은 local node에 한정되므로 선택 target node의 실제 활성 여부를 별도로 조회해야 한다. 이 조사만으로 실제 PVE 9.0.11 검증을 완료하지 않는다.

### M6 OPS-03 조정 기반 전체 검증 재개 지점 (2026-09-19 18:29 KST)

- container session 85770 exit 0: client 검증 stage(변경 없음, cache 재사용), backend 1515 passed/77 skipped, frontend test/lint/build stage와 runtime image build 통과. local 전체 검증 exit 0과 별도 PostgreSQL 76개 통과 + 실패 schema 묶음 수정 후 3개 재검증 결과를 함께 보존한다. production 실행·설치는 하지 않았다.
- 최종 diff 검사 통과. 내부 host 기반만 추가한 상태이며 기능별 adapter·관리형 기능/범위/ACL 계약·공개 API·GET-only recovery handler·웹/CLI 구현이 다음 재개 지점이다. 기존 관리형 연결의 암묵적 권한 확대는 차단한다. architecture의 OPS-03 기반 절과 roadmap 구현 중 상태를 갱신했다.
- 다음 구현 전 directory storage의 제한된 수정 필드·기존 디렉터리/하위 content directory 확인 방식·응답 유실 결과 관찰 계약과 bridge pending/reload의 외부 변경 검출·실제 활성 확인 계약을 이 work에 추가한다. 현재 공통 recovery runner에는 host handler가 없으므로 먼저 공개 dispatch만 노출하지 않는다. 실제 PVE mutation·운영 DB 적용·설치/배포는 정확한 대상 승인 전 실행하지 않는다. Goal active.

### M6 OPS-03 directory storage 실행 계약 (2026-09-19 18:33 KST)

- 첫 storage 기능은 기존 절대 directory 경로를 선택 node의 비공유 `dir` storage로 등록하고, 기존 `dir`의 content 종류·사용 여부를 수정한다. 기존 path·nodes·shared와 다른 설정은 유지한다. 삭제·경로 이동·포맷·mount·SSH는 제공하지 않는다. storage 설정은 cluster 공용이므로 수정의 기존 nodes 범위(없으면 모든 node)와 선택 node에서만 수행한 활성 검증을 구분해 표시한다. 등록은 enabled 상태만 지원한다.
- 생성/수정 모두 `create-base-path=0`, `create-subdirs=0`을 명시한다. 기존 storage의 자동 directory 생성 옵션도 검토한 변경에 포함한다. 기존 파일·volume을 삭제하거나 디렉터리를 만들지 않는다. base directory 존재/활성은 설정 저장 후 선택 node에서 확인한다. 하위 content directory 존재·새 VM/backup 작성 성공은 이 API로 증명할 수 없으므로 별도 사용 검증으로 표시한다. 비활성화는 설정의 disable 확인이며 host unmount 완료로 표현하지 않는다.
- 공개 흐름은 admin의 변경 검토→기존 설정/영향 노드/변경 후 content·사용 여부→`node/storage/create|update` 재입력과 cluster 영향 동의→최종 실행이다. 웹/CLI는 같은 payload·검토 digest·idempotency key를 사용한다. 검토는 명시적 global storage 할당 권한을 확인하고 선택 target 존재/부재·dir 종류·선택 node 범위·online 상태와 config digest를 확인한다. 대상은 공개 host canonical identity를 사용한다.
- 수정 PUT에는 PVE의 config digest를 전달한다. 등록에는 PVE digest 인자가 없으므로 신규 ID 부재를 직전 재조회하고 PVE 자체 ID 충돌 거부를 사용한다. host admission 후 같은 검토를 반복하고 dispatch evidence를 먼저 남긴 뒤 한 번만 요청한다. 응답 불명/관찰 오류/설정 불일치는 잠금을 유지한다. GET-only recovery는 정확한 target·lease를 재검사하고 추가 POST/PUT/DELETE를 하지 않는다. 응답 확인이 없으면 원하는 상태가 보여도 자동 완료로 승격하지 않는다.
- 최소 추가 token 권한은 `/storage`의 Datastore.Allocate(공식 API의 등록/수정 요구), 선택 host storage의 Datastore.Audit와 기존 선택 node Sys.Audit다. PVE token 자체는 cluster storage 설정 권한이 넓고 Gjallar 요청 policy가 별도 host storage ID를 제한한다는 점을 등록 계획·웹/CLI에서 명시한다. 기존 연결은 host 기능 opt-in과 새 검증·전환·전체 process 재시작 전 사용할 수 없다. 운영 권한/DB 적용과 실제 PVE 실행은 이 계약만으로 승인하지 않는다.
- 자동 검증은 absent/create·update·no-op·노드/type/path/digest 변경·원래 옵션 보존·동시 admission·중단/응답 유실/lease 손상·GET-only recovery·관리형 exact method/path/body·역할/기존 연결 갱신·API admin/CLI 검토파일/웹 표시를 포함한다. 저장만 성공한 경우와 실제 활성 확인 결과를 구분한다.


### M6 OPS-03 directory storage 구현 검증 완료 재개 지점 (2026-09-19 18:58 KST)

- `operations/host_storage/`의 검토·단일 설정 요청·실제 활성/설정 보존 확인과 host GET-only recovery handler를 연결했다. admin API·관리형 v16 opt-in/host_storages scope·최소 ACL·기존 연결 갱신·웹 설정/CLI plan-execute를 함께 구현했다. 대시보드와 TUI 기본 흐름은 보존했다.
- 웹 fixture에서 확인 문구/cluster 동의 전 차단·최종 실행·활성 확인과 하위 디렉터리/실제 작성 미검증 표시·전체 node 수정 영향·잘못된 canonical target 거부/자동 재전송 금지를 확인하고 화면을 직접 봤다. 실제 PVE 실행이 아니다.
- core/API/관리형 등록 집중 147개, client 초기 22개, 마지막 core/handler/API 38개 통과. 전체 allowlist의 새 recovery handler 기대 누락을 수정했다. 최종 `pnpm run verify` session 80591 exit 0과 `pnpm run verify:container` session 88561 exit 0: 각각 client 213·backend 1545 passed/77 skipped·frontend test/lint/build, container runtime image build 통과. 로그 `/tmp/gjallar-host-storage-verify-final.log`, `/tmp/gjallar-host-storage-container.log`. 기존 frontend 큰 chunk 경고는 남아 있다. 새 migration은 없으며 0042의 이전 격리 PostgreSQL 검사와 구분한다.
- 공식 PVE source에서 node storage 상태 GET도 내부적으로 다른 enabled storage를 활성화할 수 있음을 확인해 review 경고와 architecture/development에 반영했다. target 자동 directory 생성 옵션이 해제되기 전에는 활성 조회하지 않는다. 실제 적용 승인은 이 상태 갱신 영향까지 포함해야 한다. 실제 PVE mutation·운영 DB·설치/배포·commit/push 없음.
- PRD·roadmap은 storage 구현 검증 완료/bridge 구현 중/실환경 검증 대기로 구분했다. development의 DB head 표기를 현행 0042로 바로잡고 storage 웹/CLI 사용·최소 권한·실패 복구·검증 한계를 추가했다. 다음은 VM용 Linux bridge 생성/수정·VLAN-aware의 stage/reload/실제 관찰 계약과 구현이다. M6 전체와 M1~M6 실환경 검증이 남아 Goal active다.

### M6 OPS-03 Linux bridge 실행 계약 (2026-09-19 19:04 KST)

- VM용 Linux bridge `vmbrN`을 생성하고 기존 bridge의 autostart·VLAN-aware·허용 VLAN 목록을 수정한다. 신규 bridge는 물리 port 없는 내부 bridge이며 기존 bridge의 port·MTU·설명과 나머지 설정은 보존한다. host IPv4/IPv6 주소·gateway/DHCP/auto 설정이 있는 대상, OVS/SDN 장치·임의 options/hook·별도 inet6 stanza는 첫 지원에서 거부한다. 관리망 주소·물리 NIC 재배치·삭제·SSH는 제공하지 않는다. VM 통신/VLAN 경로와 커널 VLAN table 검증은 별도이며 자동 성공으로 표시하지 않는다.
- PVE GET network metadata는 staged 설정과 실제 active/exists를 섞어 반환한다. 최초 pending diff가 없어야 검토하고 전체 local interface의 설정 fingerprint(상태·동적 priority 제외)를 보존한다. node Sys.Audit/Sys.Modify와 `/sdn/zones/localnetwork` SDN.Audit가 필요하다. 후자는 다른 bridge 변경 누락을 막기 위한 전체 local bridge 읽기다. opt-in host_network/별도 host_bridges 범위와 요청 policy가 변경 대상을 제한하며 token의 node Sys.Modify가 bridge만의 권한은 아니라는 경고를 함께 제공한다. 기존 연결은 갱신·검증·전환·재시작한다.
- host admission 뒤 동일 검토를 재확인하고 stage dispatch evidence→한 번의 POST/PUT→stage ack→staged 전체 설정/제한된 diff 대조→reload dispatch evidence→한 번의 PUT reload→정확한 node/srvreload/networking UPID 저장→task/설정/active 관찰을 수행한다. update에는 PVE digest 인자가 없으므로 외부 동시 관리를 중지해야 한다. Gjallar의 cluster host lock은 PVE 외부 변경을 막지 못한다.
- stage 이후 대상의 요구 설정·기존 옵션 보존과 다른 interface fingerprint가 모두 같아야 reload할 수 있다. raw unified diff는 메모리에서 허용된 bridge 지시문 변화만 검사하고 DB·로그·응답에 원문/주소를 남기지 않는다. 다른 pending·설정 변경, 응답 유실, process 중단은 잠금을 유지하고 자동 다음 단계·재전송·revert/삭제를 하지 않는다. stage만 남은 작업도 GET-only 복구는 조회/보고만 한다.
- reload는 선택 bridge만이 아니라 node 전체 `ifreload -a`와 PVE SDN 설정 생성에 영향을 줄 수 있다. `regenerate-frr=0`을 고정해 FRR 재생성을 요청하지 않되 다른 네트워크의 무영향을 주장하지 않는다. 검토/명시적 동의/live 승인에 노드 접속 단절 가능성과 node 전체 적용 범위를 포함한다. 성공은 exact task OK, pending 없음, 대상 설정/다른 설정 보존, autostart=true일 때 실제 active/exists 확인이다. autostart=false는 부팅 설정만 바꾸며 즉시 down 완료로 표시하지 않는다.
- 테스트는 생성/수정·VLAN 검증·관리망/port 변경 차단·전체 구성 drift/foreign diff·stage/reload 각 응답 유실·사이 중단·wrong UPID·task 실패/active 미확인·GET-only 복구·exact managed policy/권한 갱신·admin API·웹/CLI canonical 결과·전체/local/container를 포함한다. 0042를 재사용하며 새 DB schema 변경은 없다. 실제 node stage/reload·운영 권한/DB·설치/배포는 별도 승인 전 실행하지 않는다.

### M6 OPS-03 bridge 서버·권한 검증 재개 지점 (2026-09-19 19:14 KST)

- `operations/host_network/`에 bridge 검토 규칙·VLAN 정규화·전체 다른 interface fingerprint·raw diff의 허용 지시문/구간 검사를 추가했다. admin review/configure API, stage→검증→reload→정확한 task/실제 active 확인, 각 단계 durable checkpoint와 GET-only recovery를 연결했다. stage와 reload 사이 중단 시 다음 mutation을 자동 수행하지 않는다.
- 관리형 v17 `host_network`·별도 `host_bridges`·선택 node Sys.Modify/전체 localnetwork SDN.Audit를 추가했다. 전체 구성 조회는 명시적 내부 요청 옵션으로 분리해 기존 VM NIC 선택/일반 inventory scope가 확장되지 않게 했다. 발급과 env import 계획 모두 권한 범위 경고를 포함한다. 기존 연결 갱신·revision pin·재시작 검사는 기존 경로를 재사용한다.
- domain 33개, core와 domain 57개, API/admin·registry(81개 route)·기존 recovery/관리형 등록을 포함한 집중 검사 195개 통과. 로그 `/tmp/gjallar-host-network-domain.log`, `/tmp/gjallar-host-network-core.log`, `/tmp/gjallar-host-network-backend.log`. precheck/foreign pending/다른 interface drift·stage/reload 각 응답 유실·중단/lease 유실·wrong UPID/task·새 bridge 보존 옵션 변경·GET-only 복구를 검사했다.
- 아직 bridge 웹·CLI·권한 입력 UI와 전체/local/container·실제 화면 검증을 마치지 않았다. 공식 최신 Network/INotify source의 protocol을 기준으로 구현했고 PVE 9.0.11의 실제 stage/reload는 미검증이다. 운영 DB·PVE mutation·설치/배포·commit/push 없음. 다음은 웹/CLI 연결과 전체 검증이며 Goal active다.


### M6 OPS-01~03 구현 검증 완료 재개 지점 (2026-09-19 19:25 KST)

- bridge의 서버·admin API·관리형 v17 권한/연결 갱신에 웹 `/settings/host-network`와 CLI `host network plan/execute`를 연결했다. VLAN 입력 정규화, 대상 재입력·node 전체 reload 동의·최종 실행, canonical Operation의 종류/target/전체 요청 검사를 제공한다. `HostNetworkPage.jsx`, `host_network_workflow.py`, `host_network/`가 각 UI/application/외부 연동 책임을 나눈다. 기존 대시보드와 TUI 기본 등록 질문은 유지했다.
- 브라우저 격리 fixture에서 VLAN 4095 차단→20-30 10 정규화→동의 누락 차단→검토/최종 실행→task/설정/활성 확인과 VM 통신 미검증 표시를 확인했다. update에서는 기존 eno2 보존·자동 시작 해제와 단계 부분 완료를 성공으로 표시하지 않는 결과/Operation 링크를 직접 확인하고 screenshot으로 읽었다. 제품 경고의 내부 digest/명령 표현은 실제 사용자 영향 설명으로 정리했다. fixture는 실제 PVE 쓰기가 아니다.
- `pnpm run verify` session 39030 exit 0: client 226·backend 1607 passed/77 skipped·frontend test/lint/build 통과. 추가 CLI wizard의 opt-in/TUI 보존 검사를 포함한 client 집중 25개도 통과했다. `pnpm run verify:container` session 42898 exit 0: client 227·backend 1607 passed/77 skipped·frontend test/lint/build·runtime image build 통과. 이후 경고 문구/port 표기를 보완해 domain 33개와 frontend test/lint/build(session 36839)를 다시 확인했다. 최종 diff check 통과. 로그 `/tmp/gjallar-host-network-verify.log`, `/tmp/gjallar-host-network-container.log`, `/tmp/gjallar-host-network-client.log`, `/tmp/gjallar-host-network-domain-final.log`, `/tmp/gjallar-host-network-ui-final.log`.
- 새 DB migration 없이 0042 host coordination을 재사용했다. 기존 격리 PostgreSQL host/VM 경쟁·정합성 검증은 이전 기록이며 이번 기능 검증의 skipped 77개를 새 실행 성공으로 세지 않는다. Node 26 로컬 지원 버전 경고는 기준 Node 24 container 검사와 구분한다. frontend 큰 chunk 경고는 남았고 기능 실패는 아니다.
- PRD·architecture·development에 bridge의 제한된 지원, 최소 권한과 넓은 token authority, pending 저장/노드 전체 반영·복구·웹/CLI 사용법을 갱신했다. roadmap M6는 OPS-01~03 구현 검증 완료 / 실환경 검증 대기다. PVE 실제 stage/reload·관리형 설치·권한/DB 변경·commit/push 없음.
- 다음은 M1~M6 요구사항별 실사용 검증표와 최신 코드/환경을 대조하고, 실제 설치 및 테스트의 정확한 node·storage·bridge·VMID·IP/port·자원 영향·복구/정리 대상을 구체화하는 일이다. env token을 읽기 관찰에 사용할 수 있지만 실제 변경은 AGENTS.md/Goal의 exact-target 승인 전 수행하지 않는다. 기존 VMID 40000~40010의 자원을 보존하고 이번에 만든 자원만 정리한다. 실환경 검증과 설치/중단·재시작/이력 보존이 남아 Goal은 active다.
- browser tab 2는 bridge 부분 완료 fixture이며 `/tmp/gjallar-ui-fixture-host-storage-0919.jsx`에 이전 storage fixture를 보존했다. 임시 `.gjallar-review.html/.jsx`와 작업용 PostgreSQL은 다음 통합/실사용 검증 준비에 재사용할 수 있으며 최종 검증 종료 시 소유한 자원만 정리한다. 미확정 외부 mutation은 없다.

### M1~M6 완료 조건 대조와 재개 지점 (2026-09-19 19:36 KST)

- 직전 사용자 응답은 재개 안내였으며 구현 진척으로 세지 않는다. 이번에는 실제 checkout·diff·현재 문서와 구현을 다시 대조했다. 기존 대규모 미커밋 변경을 보존했고 커밋·푸시하지 않았다. 아래 표는 완료 선언이 아니라 미충족 조건을 추적하는 검증표다. 전체 실환경 완료 근거는 아직 없다.

| 요구사항 | 현재 구현·자동 검증 근거 | 완료에 필요한 별도 실사용 증거 |
|---|---|---|
| M1 설치·첫 관리자·로그인 | `client/bootstrap.py`, `installation/`, bootstrap tests·실제 PG 초기화/race 검사 | 지원 OS/Docker의 실제 bootstrap, 웹·CLI 로그인, 권한 거부·연결 실패 안내 |
| M1 재시작·같은 경로 재실행·보존 | 새 독립 프로세스 PG 검사: 관리자/비밀번호 hash·연결 revision·원본 키 복호화·Operation/event chain 보존, 전환 전 process의 재시작 요구 | 실제 Compose stop/start·bootstrap 재실행·volume/secret/계정/이력 보존, 기본 keyring 또는 명시적 memory 사용 확인 |
| M1 관리형 등록·최소 권한·갱신 | `setup_integration/` v17·웹 등록·CLI 등록·scope/request allowlist·revision pin/drain·PG CAS/race | TLS 검증된 연결 등록, 선택 권한 계획/검증/전환/재시작, 웹·CLI 같은 자원 조회. 현재 env의 insecure TLS는 import 불가 |
| M2 기존 생성·목록·시작·정상 종료 | 기존 Create/VM actions 및 관리형 create/power scope, Operation/lock/recovery 회귀 | 관리형 template 생성·조회·시작·정상 종료, 동일 canonical Operation과 실제 전원 확인 |
| VM-01 CPU·메모리 | `vm_compute/`, 웹 VM 상세·CLI compute, 정지/digest/멱등/부분 반영·권한 검증 | 테스트 VM에서 웹과 CLI 각각 cores/memory 변경 후 PVE config·power 대조 |
| VM-02 디스크 | `vm_disk/`, 웹·CLI disk, NFS scsi0 확장·정확한 task/volume bytes 검사 | 가상 용량 증가 및 축소 거부, 게스트 filesystem 미확장 안내 |
| VM-03 NIC | `vm_network/`, 웹·CLI network, bridge/VLAN·MAC/모델 보존·pending/drift 거부 | 정지 VM net0 변경, 설정과 별도 guest 통신 검사 결과 구분 |
| VM-04 full clone | `vm_clone/`, 웹·CLI clone, 원본/신규 두 lock·task/독립 volume/identity 검사 | 새 VMID·정지 상태·원본 보존·독립 disk 및 guest identity 충돌 안내 |
| VM-05 삭제 | `vm_delete/`, 웹·CLI delete, 대상/삭제 volume 검토·명시 동의·단일 dispatch | 이번에 만든 정지 VM만 삭제 후 VM/승인 volume 부재·보존 자원 확인 |
| VM-06 콘솔 | `console/`, VM 상세 noVNC·CLI 웹 진입, 인증/권한/종료 회귀 | 실제 console 영상/입력·접속 종료·권한 거부/만료 확인 |
| TPL-01 전환 | `vm_template/`, 웹·CLI template, 상태/구성·준비 동의 검증 | 준비된 테스트 VM template 전환과 기존 disk/설정 보존 |
| TPL-02 제작·실패 자원 정리 | `cloud_images/`, image build/cleanup Operation, 웹·CLI·고정 공식 이미지 무결성 | AlmaLinux 9.8 x86_64 20260810 다운로드/업로드/import/template 결과 및 소유 증거에 따른 잔여 자원 정리 |
| TPL-03 테스트 배포·검사·정리 | 기존 Create + `template_test.py`, 웹·CLI 항목별 결과/접속 기록 | 부팅/cloud-init/guest agent/IP/실제 접속 각각 확인, 이번 테스트 VM 명시 삭제 |
| OBS-01~02 현재·추이 | `monitoring/`, 웹 metrics·CLI metrics, 기간/누락 회귀 및 env PVE GET 관찰 | 관리형 설치에서 노드·VM·storage 동일 지표/시점·PVE 이력/누락 표시 |
| OBS-03 상태·알림 이력 | 웹 alerts·CLI alerts, 발생/해제·중복·작업 실패 이력/격리 DB 검사 | 실제 조회·작업 상태에 따른 발생/해제·VM/Operation 진입, 단절을 정상으로 표시하지 않음 |
| BAK-01 백업 | `vm_backup/`, 웹·CLI backup, 목록/정확한 task/archive 검사 | nas-server의 신규 백업 완료·정확한 archive 목록 확인, 원본 보존 |
| BAK-02 별도 복원 | `vm_restore/`, 웹 복원/검사·CLI restore, 신규 VMID·NIC 격리·GET-only 복구 | 새 VMID 복원·원본/archive 보존·격리 부팅/guest 검사·정리 |
| OPS-01 이동 | `vm_migrate/`, 웹·CLI migrate, shared NFS·node/CPU/bridge 호환 및 원본 위치 검사 | 승인 node 간 정지 VM 이동 후 실제 위치·정지·disk/설정 보존 |
| OPS-02 유지보수 준비 | `maintenance/`, 웹·CLI 보고서, 영향/차단·backup/이동 필요 구분 | 실제 node의 영향 VM·관찰 시점·준비 미완료 항목을 PVE와 대조 |
| OPS-03 storage | `host_storage/`, 웹·CLI plan/execute, host lock·설정 보존·자동 directory 생성 차단 | 승인한 기존 directory 등록/수정·node 활성, 실제 content 작성은 별도 검사. 기존 storage 변경/활성 영향 승인 필요 |
| OPS-03 bridge | `host_network/`, 웹·CLI plan/execute, stage/diff/reload/task·GET-only 복구 | 신규 내부 bridge 생성/변경·node 전체 반영 영향·active/설정 보존, VM 통신/VLAN은 별도 확인 |
| UI·문서·기존 기능 보존 | 기능별 직접 fixture 화면 확인, 대시보드 보존·기존 TUI 기본 경로 회귀, 각 기능 runbook | 실제 설치 앱 전체 탐색/권한/VM 상세에서 업무 연결, 검토용 임시 파일 최종 정리 |

- M6 bridge의 `exists` 판정 결함을 발견했다. 실제 PVE 9.0.11의 세 node에 있는 활성 Linux bridge 모두 `exists`를 생략했다. [공식 Network API](https://raw.githubusercontent.com/proxmox/pve-manager/3bf5476b8a4699e2/PVE/API2/Network.pm)의 exists는 physical 존재 표시이며 [공식 parser](https://raw.githubusercontent.com/proxmox/pve-common/master/src/PVE/Network/Interfaces.pm)도 physical 장치에만 이를 설정한다. bridge 테스트 fixture의 가짜 exists=1을 제거하자 9 failed/51 passed로 문제를 재현했다. exact iface/type·active를 확인하도록 수정해 core/domain/API/managed 64개가 통과했다. pending·다른 설정 보존·task/lease 검사는 유지한다. 앞선 active/exists 둘 다 요구한 기록을 이 수정으로 대체한다.
- 실제 PVE commit `3bf5476b8a4699e2` Network.pm을 읽어 `regenerate-frr=0`, node Sys.Modify, ifupdown2 검사·node 전체 ifreload/SDN 생성 protocol이 있음을 확인했다. 공개 source 파일을 읽었을 뿐 host stage/reload를 실행하지 않았다. live ifupdown2 설치/동작은 여전히 미검증이다.
- 19:32 KST GET-only 관찰: PVE 9.0.11, online node yoonmanserver/2/3, VMID 40000~40010 비어 있음, 세 node network pending 없음·vmbr40 부재, nas-server NFS shared/content 지원. storage는 `/storage` 설정만 읽었으며 활성화를 유발할 수 있는 node storage 상태 GET은 호출하지 않았다. 결과 `/tmp/gjallar-readiness-inventory.json`은 0600, token/주소/원문 host 설정 미포함. 이 관찰은 자원 예약·mutation 승인이 아니다.
- 새 `test_fresh_process_preserves_account_connection_key_and_operation_history`는 두 독립 Python process와 전용 PostgreSQL schema를 사용한다. 최초 관리자는 한 번만 생성하고 두 번째 process는 init-schema/setup-admin 재실행에도 기존 ID/hash/audit·active registration revision·Operation/event checksum을 보존하며 원본 0600 key로 synthetic token을 복호화한다. 전환한 첫 process는 `SETUP_RESTART_REQUIRED`를 유지한다. 실제 token 발급·설치/서비스 재시작으로 표현하지 않는다. 집중 3개와 최신 통합 PG 전체 78개 통과, session 47905의 terminal 확인은 이어서 수행한다.
- local 전체 `pnpm run verify` session 47077 exit 0: client 227, backend 1610 passed/77 skipped, frontend test/lint/build 통과. 이 수치는 새 PG process test 추가 전 collection이며 새 검사는 별도 PG 결과다. 기준 container session 39412 진행 중(`/tmp/gjallar-integration-review-container.log`). 새로운 설치·운영 DB·PVE mutation 없음. 다음은 container terminal 확인, 정확한 M1 설치 승인안과 관리형 연결 TLS 준비, 실제 앱 전체 흐름 검증이다.

### 첫 M1 설치 승인안 — 아직 미실행

- 대상: 현재 macOS 26.6.2 arm64, Docker Linux/arm64 28.4.0, Compose 2.39.2. 로컬 설치 경로 `/private/tmp/gjallar-m1-acceptance-0919`(19:35 관찰 시 없음), 웹 `127.0.0.1:18000`(관찰 시 listener 없음). 실행 직전 다시 검사한다. 임시 acceptance 환경이며 운영용 장기 설치 경로가 아니다.
- 사용할 이미지: 이번 checkout의 `pnpm run verify:container`가 만드는 `gjallar:local`을 실제 image ID로 고정하고 PostgreSQL `postgres:17-bookworm`도 bootstrap이 ID로 고정한다. 완료된 build의 ID를 실행 기록에 추가한다. 기존 `gjallar-compute-pg-test-0919` container/DB/volume은 건드리지 않는다.
- 새 전용 Compose project·UUID label named volume과 0600 secrets를 만든다. 새 DB에만 head 0042/설치 marker/첫 테스트 관리자를 준비한다. 테스트 비밀번호는 임의 생성해 전용 0600 파일에 보관하고 argv·대화·로그에 출력하지 않는다. 기존 계정/설정·실제 PVE credential은 복사하거나 변경하지 않는다. OS keyring 변경 없이 명시적 memory client 세션으로 검증한다.
- 승인 요청 범위: 위 설치, 웹/CLI login·잘못된 인증 거부·PVE unconfigured 안내, 같은 경로 bootstrap 재실행·service stop/start와 DB/계정/설정/이력 보존 확인. 설치 검증만으로 M1 관리형 live 연결 또는 M2~M6 완료라고 표시하지 않는다. PVE token 발급/ACL·VM·storage/network 변경은 별도 승인이다.
- 복구·보존: 실패 시 정확한 단계와 소유한 project/volume/manifest를 기록하고 같은 경로 재개한다. volume·key를 삭제/재생성하지 않는다. 검사 종료 시 자체 service만 stop하고 volume/secret/이력은 남긴다. 최종 삭제는 별도 정리 범위 승인 후 수행한다. 기존/운영 DB migration, 외부 공개, 원격 설치, commit/push는 포함하지 않는다.
- 관리형 live 연결의 차단점: 현재 env는 TLS insecure이며 bootstrap Compose에는 PVE env 자동 주입 경로가 없다. 관리형 등록은 TLS 검증을 요구한다. 정확한 endpoint trust/CA와 제품 등록 경로를 확인해야 하며 인증 검증을 끄거나 직접 DB credential 주입으로 우회하지 않는다. 실제 token 발급을 선택하면 사용자 PVE login 입력과 정확한 최소 ACL 승인도 필요하다.

### 통합 검증 완료·설치 승인 대기 재개 지점 (2026-09-19 19:40 KST)

- 기준 container session 39412 exit 0. client stage는 변경 없는 227개 검사 cache 재사용, backend 1610 passed/78 skipped, frontend test/lint/build와 runtime image build 통과다. 추가한 PostgreSQL process 검사는 여기서는 skip하며 실제 PG 전체 session 47905 exit 0의 78 passed로 별도 증명했다. 문서 계약 10개·최종 diff 검사도 통과했다.
- 승인 검토용 설치 이미지 `gjallar:local`: `sha256:1e039a4e04aabccf4773b5777e6921a20b51b17143237908ae5acaebe9a2a374`, linux/arm64. 기존 로컬/PG/container log는 위 경로에 보존한다. frontend 큰 chunk·Alembic path_separator 경고는 기존 상태이며 기능 검사 실패는 아니다.
- 사용자가 지연을 지적했다. 기능별 반복 전체 검증이 시간을 늘렸으며 실사용 승인 대상을 더 일찍 구체화했어야 함을 설명했다. 이후 결함이나 변경 근거 없이 같은 전체 검사를 반복하지 않고, 위 정확한 첫 M1 설치안의 승인과 실제 사용 검증을 우선한다.
- 설치·PVE mutation·운영 DB·commit/push는 여전히 미실행이다. 위 local 설치안 승인 요청을 전달하며, 승인 전 설치 명령을 실행하지 않는다. M1~M6 실제 사용 완료를 주장하지 않고 Goal active로 유지한다. 다음은 승인 시 동일 image/path/port로 bootstrap→인증→재실행/stop/start 보존 검사다. PVE TLS/관리형 등록은 별도 준비·승인 경계를 유지한다.

### 공통 탐색 직접 확인 재개 지점 (2026-09-19 19:44 KST)

- 직전 goal turn은 bridge 버그 수정·독립 process/PG 검증과 설치 승인안 구체화로 진척했다. 현재 설치 승인 질문은 미응답이며 경과 시간이나 Goal 자동 재개를 승인으로 해석하지 않는다.
- 기존 개별 bridge fixture를 `/tmp/gjallar-ui-fixture-host-network-0919.jsx`에 보존한 뒤 임시 `.gjallar-review.jsx`를 실제 `App`·공통 shell·route를 사용하는 읽기 전용 navigation fixture로 바꿨다. 모든 fetch를 synthetic 응답/명시적 오류로 제한하고 non-GET은 거부하므로 실제 backend·PVE로 전달하지 않는다. 실제 관리자 계정이나 VM은 만들지 않았다.
- 브라우저에서 VM 40000 상세 요약/작업과 정지 VM console 차단, 상세→백업의 node1/nas-server 전달→같은 상세 복귀, 상세→이동의 VMID/node 전달, Settings→호스트 bridge의 공통 탐색/선택 표시를 직접 확인하고 화면을 읽었다. 새 차단 문제는 발견하지 않았다. 대시보드·제품 코드 변경과 전체 회귀 재실행은 없다. 이 결과는 설치된 제품의 인증·실행 검증을 대체하지 않는다.
- 기존 tab 2는 이미 사라져 있었으므로 재사용하지 않았고, 현재 tab 3은 host bridge 설정 화면이며 handoff로 보존했다. 임시 fixture는 후속 실제 설치 화면 검증 전환/최종 종료 때 정리한다.
- 남은 선행 조건은 위 M1 local 설치안의 명시 승인이다. 승인되면 검증된 image/path/port로 설치·로그인·재실행·stop/start 보존 검사를 수행한다. 관리형 PVE TLS·등록/권한과 실제 VM/host 검증은 별도 범위를 정해야 한다. 커밋·푸시·설치·외부 mutation 없이 Goal active다.

### 템플릿 탐색 수정·실사용 승인 차단 재개 지점 (2026-09-19 19:46 KST)

- 템플릿 제작 이외의 cleanup/tests 하위 route에서 공통 메뉴가 먼저 나오는 `/instances` prefix를 선택해 Inventory를 강조하는 결함을 확인했다. 새 동작 검사에서 실제 Inventory/기대 템플릿 제작 불일치로 실패를 재현했고, 브라우저의 실제 App cleanup 화면에서도 잘못된 강조를 확인했다.
- `navigationModel.js`의 section 선택은 exact route/alias 우선 규칙을 보존하고 그다음 가장 긴 경로 prefix를 선택한다. `/instances/templates-other`는 템플릿 메뉴로 오인하지 않으며 기존 VM 상세·Create·Operations/Settings 경로 검사를 유지했다. 새 메뉴·화면 디자인·API를 도입하지 않았다. `appNavigation.test.mjs`에 build/cleanup/tests/경로 경계 회귀를 추가했다.
- frontend test/lint/build session 70822 exit 0, 직접 화면에서 템플릿 제작만 강조됨을 확인했다. 기준 Node 24 frontend test/lint/build를 포함한 runtime image build session 92767 exit 0(`/tmp/gjallar-nav-prefix-image.log`). backend/client는 변경 없어 전체 재검사를 반복하지 않았다. diff check 통과.
- 갱신된 설치 후보 `gjallar:local` build image ID는 `sha256:40274863f06b0670cfc6b86a6c65743570a2d2f8c1957cdd6809275012007de7`이다. 위 19:40 이미지에 이 탐색 수정만 더한 버전이며 이전 image ID 기록은 과거 증거로 보존한다. 설치 승인의 path/port/새 DB/계정/보존 범위는 같다. 실행 전 tag의 image ID와 경로/port를 다시 확인한다.
- 현재 tab 3은 읽기 전용 fixture의 템플릿 정리 화면이다. `.gjallar-review.jsx`의 원래 navigation fixture는 `/tmp/gjallar-ui-fixture-navigation-0919.jsx`에 보존했다. 실제 삭제·PVE·DB 요청은 없으며 임시 fixture는 제품 build 입력이 아니다.
- 동일한 첫 M1 설치 승인 미응답이 19:40 승인안 전달, 19:44 탐색 점검, 이번 19:46 점검의 세 연속 goal turn에서 유지됐다. 그동안 독립적으로 확인 가능한 bridge/재시작/웹 탐색 결함·검증을 처리했다. 이제 남은 완료 증거는 실제 설치/관리형 연결/승인된 PVE 대상 사용에 의존한다. 새로운 결함 근거 없이 검사를 반복하거나 승인 대기를 피하기 위한 작업을 추가하지 않는다.
- 완료 감사: M1 실제 설치·로그인·service 보존, 관리형 연결의 TLS/권한 갱신, M2~M6 실제 변경/콘솔/배포·접속·백업·복구·이동·호스트 반영은 미충족이다. 구현/자동 검증으로 대체하거나 Goal 완료 처리할 수 없다. 재개에 필요한 첫 입력은 이미 전달한 `/private/tmp/gjallar-m1-acceptance-0919`, `127.0.0.1:18000` local 설치안 승인이다. 운영 DB·PVE 변경·commit/push는 미실행이다.
- Goal 상태 도구가 `blocked` 전환을 확인했다. 완료가 아니라 위 명시 승인에 대한 대기 상태다. 승인과 재개 후 기존 checkpoint/image/자원 상태를 확인해 이어가며, 현재 검토 탭은 handoff로 보존했다.

### M1 로컬 설치 승인·착수 (2026-09-19 20:08 KST)

- 사용자가 앞선 설치안에 “ㅇㅇ 시작하고”로 승인했다. 승인된 대상은 이 Mac의 `/private/tmp/gjallar-m1-acceptance-0919`, loopback `127.0.0.1:18000`, 새 전용 DB/테스트 관리자, 로그인·재실행·stop/start와 보존 확인이다. 검사 후 자체 service를 stop하고 데이터/secret을 보존한다. 실제 PVE token/ACL·VM·host 변경은 포함하지 않는다. 기존 blocked 승인 사유가 해소돼 이 범위 작업을 재개한다.
- 실행 직전 `gjallar:local` ID `sha256:40274863f06b0670cfc6b86a6c65743570a2d2f8c1957cdd6809275012007de7` linux/arm64를 확인했다. 기존 실행 중인 컨테이너는 작업용 `gjallar-compute-pg-test-0919` 하나이며 변경하지 않는다. CLI bootstrap의 비밀 입력 callback만 자동화하고 실제 product 설치/Compose/maintenance 경로를 사용한다. 임의 테스트 비밀번호는 전용 secrets 파일에 0600으로 기록하며 원문을 출력하지 않는다.
- UI는 개별 기능 흐름과 탐색 오류를 다듬고 직접 확인한 상태다. 전체 화면의 시각적 일관성·정보량·반응형 마무리 검토는 남았음을 사용자에게 설명했다. 기존 대시보드는 유지한다.

### M1 실제 설치·서비스 보존 검증 재개 지점 (2026-09-19 20:20 KST)

- 승인된 전용 Mac 설치를 실제 CLI bootstrap/Compose/maintenance로 실행했다. 최초 시도는 `DOCKER_FAILED`로 storage_ready에서 중단됐으며 원인은 확정하지 못했다. 초기화나 volume 삭제 없이 동일 경로 재개가 성공했다. 따라서 중단 없는 최초 설치 성공이나 원인 수정으로 표현하지 않는다.
- 설치 UUID/project는 `1d5dcc27-5a0a-4301-adf9-76591a09ce21` / `gjallar-1d5dcc27-5a0a-4301-adf9-76591a09ce21`, 전용 named volume은 project에 `-pgdata`를 붙인 이름이다. 새 DB head 0042와 테스트 관리자만 준비했다. 운영 DB와 기존 test container는 변경하지 않았다.
- 실제 health·정적 login 응답, 미인증 401·잘못된 비밀번호 401, memory 세션의 CLI login/status와 PVE unconfigured(exit 6)를 확인했다. 실제 service stop/start 및 동일 경로 bootstrap 재실행 후 계정/hash·설정·Operation/event checksum·원래 secrets·CLI 세션이 보존됐다. 임시 검증 도구가 unconfigured를 처음 exit 0으로 기대한 오류는 exit 6으로 바로잡았으며 제품 결함으로 처리하지 않았다.
- 보존 검사 이력은 `.invalid` endpoint로 로컬 등록 draft를 만든 뒤 즉시 취소한 Operation `proxmox-registration-67620f55-8cf5-454b-8d32-5ddbe7298461`이다. PVE 로그인·token/ACL 요청은 하지 않았다. 근거는 `/tmp/gjallar-m1-install-resume.log`, `/tmp/gjallar-m1-runtime-acceptance.log`, 설치 경로의 0600 `acceptance-result.json`이다. 테스트 credential 원문은 출력하지 않는다.
- 설치된 브라우저 login에서 잘못된 비밀번호가 일반 세션 오류인 “로그인이 필요합니다.”로 표시되는 UX 결함을 발견했다. `LOGIN_FAILED` 401에 계정명/비밀번호 안내를 사용하고 일반 401·403 메시지는 보존한다. LoginPage 오류에 alert 의미를 추가했다. 회귀 테스트의 실패를 먼저 확인한 뒤 frontend test/lint/build 통과, 기준 Node 24 runtime image build 진행 중이다.
- 다음은 실제 브라우저 성공 로그인·연결 미설정 화면, 이 수정의 동일 schema 테스트 설치 반영과 화면 확인이다. 승인된 설치 검증의 결함 수정 범위로 자체 설치에만 적용하고 bootstrap upgrade의 readiness/원래 설정 backup 경로를 사용한다. DB migration·외부 배포는 하지 않는다. 마지막에 자체 service만 stop하고 volume/key/이력을 보존한다. 전체 UI 마무리와 관리형 PVE 실환경 검증은 여전히 미완료다.

### 설치 이미지 전환 결함과 수정 범위 (2026-09-19 20:25 KST)

- actual browser에서 첫 관리자 로그인·reload 세션 유지·로그아웃과 관리형 설정 화면을 확인했다. 미설정 첫 화면이 env 변수만 안내해 등록 경로를 놓치는 결함을 확인했다. 관리자에게 기존 `/settings/proxmox` 링크를 제공하고 다른 역할은 관리자 요청 안내, env 진단은 관리자용 접힌 보조 정보로 유지한다. 정상 대시보드 디자인은 변경하지 않는다.
- 수정 이미지를 같은 `gjallar:local` tag로 build한 뒤 이전 manifest image ID `402748...`가 local image inspect에서 사라졌다. 기존 container는 실행 중이지만 one-off maintenance는 `sha256`를 registry에서 pull하려다 거부됐다. 이번 upgrade 오류의 직접 원인은 확인했으나 최초 설치 오류와 같다고 단정하지 않는다.
- 수정 범위: 검증한 app/PostgreSQL image에 digest로 결정되는 `gjallar-pinned:sha256-…` local 보존 tag를 붙인다. manifest는 그대로 image ID를 사용하고 기존 tag/volume을 삭제하지 않는다. 실행 중 upgrade는 그 설치의 기존 gjallar process 컨테이너에서 read-only `check-ready`를 수행한다. 정지 설치는 기존 one-off 검사, candidate도 별도 one-off schema/identity 검사를 유지하며 불일치 시 stop하지 않는다. DB migration·초기화·권한 변경은 없다.
- 근거: image 보존 tag 및 원래 image가 사라진 실행 중 설치의 upgrade 회귀 두 개를 먼저 실패시켰다. 이어 client regression과 실제 전용 설치에서 candidate 검증·전환·DB/key 보존을 확인한다. 이전 이미지 자체가 사라진 이번 설치의 old image rollback은 보장하지 않으며 backup manifest는 역사적 기록으로 보존한다. 이후 보존 tag는 자동 정리하지 않는다.

### M1 승인된 로컬 사용 검증 완료·다음 재개 지점 (2026-09-19 20:29 KST)

- 실제 테스트 설치를 최종 image `sha256:ba6481c60509f72cc8fc1c98533201ab3aac9b595f93ef5abac5f3701a50b916`로 동일 schema 전환했다. 기존 컨테이너 readiness·candidate readiness·서비스 전환을 모두 통과했고 계정/설정/Operation/event checksum 및 secrets의 전후 digest가 일치한다. `before-upgrade-*`에 원래 manifest/Compose를 보존했다. DB migration이나 초기화를 다시 실행하지 않았다.
- 기준 runtime build session 21310 exit 0에는 Node 24 frontend test/lint/build가 포함된다. client 전체 로컬 session 77539와 Python 3.13 container session 93613 각각 229 passed다. 새 코드의 client 회귀 두 개는 수정 전 실패했다. 이번에는 backend product 변경이 없어서 직전 backend 1610·실제 PG 78개 검사를 불필요하게 반복하지 않았다. 이전 9fdb3d image는 login 문구만 반영한 중간 후보이며 실제 최종 설치 image와 구분한다.
- 실제 Chromium에서 올바른 관리자 로그인, 잘못된 비밀번호 메시지, reload 후 cookie session 유지, logout, 미설정 첫 화면→관리형 연결 설정 링크를 확인했다. 비밀번호는 0600 파일에서 브라우저 입력으로만 전달했으며 로그·대화·screenshot에 원문을 남기지 않았다. `/tmp/gjallar-m1-browser-fixed.log` exit 0. 첫 화면·등록 화면 screenshot을 설치 경로에 보존하고 직접 읽었다. 처음 로그인 확인은 기존 이미지에서, 수정 안내·링크는 최종 이미지에서 각각 검증했다.
- 최종 이미지로 실제 service stop/start도 통과했다. 이후 승인된 약속대로 **자체 Gjallar와 PostgreSQL 서비스만 stopped**로 남겼다. volume 존재·원래 secret digest·port 18000 닫힘을 확인했다. `acceptance-result.json`의 final_state는 stopped다. 기존 `gjallar-compute-pg-test-0919`와 다른 프로젝트는 변경하지 않았다. `/tmp/gjallar-m1-finish-acceptance.log` 및 `/tmp/gjallar-m1-login-fix-upgrade.log` exit 0.
- 정확한 남은 제한: 최초 bootstrap 시도의 Docker 오류 원인은 미확정이다. 이후 같은 경로 재개 및 보존 검사는 통과했다. 초기 이미지 402748은 tag 이동 뒤 local image index가 없어졌으므로 해당 old image로 돌아갈 수 있다고 주장하지 않는다. 최종 app/PostgreSQL image는 digest 기반 보존 tag가 있다. keyring·Linux 설치·관리형 TLS/등록/권한 갱신·M2~M6 실제 PVE 변경/콘솔/guest 접속 검증은 미완료다.
- UI는 기능별 흐름·메뉴 연결과 이번 login/초기 등록 안내를 수정한 상태다. 전체 UI 마무리는 완료로 표시하지 않는다. 다음 독립 작업은 긴 연결 권한 입력의 정보량과 기능 화면 간 일관성·반응형 점검이다. 대시보드 전체 디자인과 기존 TUI는 보존한다. 실환경 VM-01은 TLS trust와 정확한 PVE 변경 승인 후 시작하며 env insecure 우회는 하지 않는다.
- 로드맵·개발 안내·아키텍처에 설치 증거, 이미지 보존 및 첫 연결 안내를 반영했다. Goal 완료 조건을 충족하지 않아 완료 처리하지 않았다. 도구 조회상 Goal 상태는 이전 blocked로 남아 있으며 이번 승인 범위 작업 수행과 구분한다. 커밋·푸시·운영 DB·실제 PVE mutation은 미실행이다.
- 최종 문서 계약 `backend/tests/contracts/test_legacy_backend_cleanup.py` 10 passed, `git diff --check` 통과. 첫 문서 검사 호출의 venv 경로 오타는 저장소 `package.json`의 실제 `backend/venv/bin/python`으로 바로잡아 실행했다. 실행하지 않은 검사를 성공으로 집계하지 않았다.

### 사용자 지정 VM 7001 읽기 확인·변경 전 재개 지점 (2026-09-19 21:20 KST)

- 사용자가 PVE 주소 `192.168.2.11`과 참고/테스트 후보 VM `7001`을 지정했다. 기존 env token으로 cluster resource·exact config/status·guest network 인터페이스만 GET했다. token·password·원문 설정은 출력하지 않았다. `/tmp/gjallar-7001-readiness.json`은 0600이다. 변경·정지·삭제·guest-exec는 수행하지 않았다.
- 관찰: `yoonmanserver3`의 일반 QEMU VM 7001이 running이며 1 socket × 4 cores, memory 8192 MiB, scsi0 `nas-server` 50G, agent 활성이다. net0 `vmbr0`이고 cloud-init 설정과 guest agent 모두 `192.168.2.31/24`, config gateway `192.168.2.1`을 확인했다. DNS override는 config에 없어 실제 guest DNS는 아직 확인되지 않았다. 이 주소는 기존 VM 점유이므로 새 VM에 재사용하지 않는다.
- 시스템 CA로 PVE HTTPS 검증은 실패했다. 이후 관찰은 기존 승인된 env read-only/TLS 정책으로만 수행했다. 관리형 연결에서는 별도 CA/인증서 trust 확인이 필요하며 insecure 우회로 등록하지 않는다.
- VM-01의 정확한 제안 범위: 관리형 연결 준비 후 7001을 정상 종료하고 stopped를 확인한다. 웹으로 4 cores/8192 MiB에서 2 cores/4096 MiB로 변경한 후 PVE 실제 config/status와 canonical Operation을 확인한다. CLI로 원래 4 cores/8192 MiB로 복원하고 재확인한 다음 원래 running 상태로 시작한다. 디스크·NIC·삭제·템플릿 전환·guest 설정은 이 승인안에서 제외한다. 기존 VM이라 정지에 따른 서비스 중단을 명시 승인받기 전 실행하지 않는다.
- 종료 실패는 강제 stop으로 대체하지 않는다. 결과 불명 시 같은 mutation을 재전송하지 않고 관찰·사용자 보고로 전환한다. 복원 결과가 확인되지 않으면 원래 사양으로 복구됐다고 주장하거나 자동 부팅하지 않는다. 40000~40010 신규 테스트 자원 범위와 이번 기존 VM 7001의 제한된 CPU/메모리 검증은 구분한다.
- 다음 입력은 위 일시 중단/사양 변경/복원/재시작 범위 승인이다. 동시에 관리형 PVE trust 경로를 준비한다. Goal 완료·commit/push·실제 PVE mutation은 없다.

### VM 7001 삭제 허용·인증서 선행 조건 (2026-09-19 21:24 KST)

- 사용자가 직전 정상 종료→웹 2 cores/4096 MiB→CLI 원래 4 cores/8192 MiB 복원→재시작 승인안에 동의했고, 7001은 삭제해도 된다고 명시했다. 7001의 해당 테스트와 삭제 허용을 기록한다. 이 승인은 다른 기존 VM의 삭제나 host network/storage 변경, 기존 PVE token/ACL 변경으로 확대하지 않는다. 삭제는 인증서/관리형 연결 준비와 필요한 검증 후 별도 실행 결과를 남기며 지금 수행하지 않았다.
- 공개 TLS certificate만 읽어 진단했다. 현재 시스템 trust 실패 이유는 `unable to get local issuer certificate`다. 인증서 issuer는 PVE Cluster Manager CA이고 SAN에는 사용자 지정 IP `192.168.2.11`이 포함된다. 따라서 접속 IP 미포함이 아니라 발급 CA trust 준비가 우선이다. 공개 leaf를 읽은 사실만으로 trust를 승인하거나 시스템 trust store에 추가하지 않았다.
- 저장소와 현재 acceptance 설치에서 `.pem/.crt/.cer` CA 후보를 찾지 못했다. 필요한 추가 입력은 사용자가 신뢰하는 PVE cluster 공개 CA 인증서의 로컬 파일 위치/파일이다. private key나 Proxmox 비밀번호를 대화에 요청하지 않는다. 이후 해당 CA로 TLS 실제 검증 및 관리형 env import의 서버 credential 준비 조건을 확인한다. 현재 stopped인 acceptance 설치에는 원래 env token이 자동 전달되지 않는 점을 유지하며 임의 DB credential 주입으로 우회하지 않는다.
- VM 네트워크 대역/gateway는 7001에서 확보했다. DNS/새 IP 점유는 후속 생성·접속 검증 전에 확인하며 CPU/메모리 테스트를 위한 추가 사용자 입력으로 반복 요청하지 않는다. 기존 운영 IP 192.168.2.31은 재사용하지 않는다. 실제 PVE mutation·commit/push는 아직 없다.

### 사용자 CA 확인·제품 TLS 호환 결함 (2026-09-19 21:40 KST)

- 사용자가 신뢰하는 공개 CA 파일 `/Users/yoon/Downloads/pve-root-ca.pem`을 제공했다. private key 미포함·BasicConstraints CA=true·PVE Cluster Manager issuer를 확인했다. CA SHA256 `32d8b87fdd0e69b261d00ddca13e1e3895f93888b4c1e5b4c918fe28de4a81d0`, 유효기간 2025-07-18~2035-07-16이다. Downloads 원본·Mac system trust·PVE 인증서를 변경하지 않았다.
- requests의 verify에 이 파일을 지정한 엄격한 CA/hostname 검증으로 PVE version GET 200(9.0.11), exact VM 7001 status GET 200(running)을 확인했다. 기존의 verify=False 관찰과 구분한다. 이 성공을 제품 managed transport 또는 등록 성공으로 확대하지 않는다.
- 제품 ProxmoxSetupTransport는 동일 CA로 PROXMOX_TLS_FAILED를 반환했다. 실제 Python SSL handshake 진단은 code 92 `CA cert does not include key usage extension`, verify_flags=557088이다. Python 3.13 create_default_context의 VERIFY_X509_STRICT 기본 활성화와 PVE 기본 CA의 형식 차이가 원인이다. 공식 근거: https://docs.python.org/3/library/ssl.html#create_default_context . requests 성공만으로 이 제품 실패를 숨기지 않았다.
- 현재 추가 VM/주소/비밀번호 입력을 요청할 사안은 없고, 다음은 이 호환 문제의 처리다. 기본 strict 검증을 전역 해제하거나 실패 시 자동 CERT_NONE/insecure fallback하는 변경은 하지 않았다. 명시적으로 신뢰한 private CA의 호환 범위와 chain·hostname·기간·잘못된 CA 거부를 검증하는 재현 테스트 및 위험/복구 계획을 먼저 구체화한다. 실제 등록·VM mutation·PVE 인증서 재발급은 아직 실행하지 않았다.
- 같은 CA로 `/access/permissions`를 GET한 결과 `/vms/7001`의 Audit/GuestAgent.Audit/PowerMgmt/Config.CPU/Config.Memory와 `/nodes/yoonmanserver3`의 Sys.Audit이 모두 확인됐다(각 HTTP 200, missing=[]). 이것은 현재 token의 첫 compute 검증 권한 확인이며 전체 M2~M6 권한이나 최소 권한 token 발급/갱신 검증의 완료는 아니다.

### 기존 token 우선 검증·신규 등록 후순위 확정 (2026-09-19 21:55 KST)

- 사용자가 기존 token으로 먼저 작업하고, 모든 작업을 마친 뒤 최초 접속/새 token 발급 테스트를 하도록 순서를 명시했다. 첫 검증을 위해 PVE 아이디·비밀번호·OTP를 다시 요청하지 않는다. 기존 env token 사용과 Gjallar의 관리형 등록 완료는 다른 상태이므로 아직 등록됐다고 표현하지 않는다.
- 재개 순서: (1) 사용자 CA의 제품 TLS 호환 문제를 재현/수정하고 hostname·chain·기간·잘못된 CA 거부를 검증한다. (2) 승인된 전용 local 설치에 기존 token을 제품 import 경로로 연결해 검증한다. 원본 `.env` insecure 설정을 그대로 가져오거나 DB에 credential을 직접 넣지 않는다. (3) 승인된 7001 CPU/메모리 웹 변경·CLI 원복과 실제 상태, 시작/종료를 검증한다. (4) 나머지 승인 가능한 M2~M6 기능과 UI 마무리를 진행한다. (5) 마지막에 사용자 PVE 로그인/OTP·전용 token 발급·최초 등록/권한 갱신 경로를 별도로 검증한다.
- 7001 테스트 및 삭제 허용, CA 경로, 기존 env token 사용 지시는 유효하다. 새 host storage/bridge 설정 등 아직 정확한 영향 범위가 승인되지 않은 작업은 묶어서 구체화한다. 기존/운영 DB, 다른 기존 VM 삭제, 임의 권한 변경, commit/push에는 확대 적용하지 않는다.
- 신규 등록 검증은 순서만 미룬 것이며 Goal 완료 조건에서 제거하지 않았다. 사용자의 “기조는 같다”는 설명을 두 경로의 실환경 검증이 동등하다는 증거로 해석하지 않는다. roadmap의 다음 실행 순서도 갱신했다. diff check 통과.
- Goal 도구 조회는 여전히 기존 blocked 상태다. 현재 도구에는 active로 바꾸는 resume action이 없으므로 사용자가 Goal 재개 조작을 하면 이 재개 지점부터 이어간다. 완료 또는 새 blocked 전환을 호출하지 않았으며, 기존의 승인 미응답을 현재 차단 사유로 반복하지 않는다.

### TLS 호환 수정 계획·재개 착수 (2026-09-19 22:00 KST)

- Goal 재개 입력을 수신했다. 직전에는 사용자 CA와 실제 token 권한 확인으로 선행 조건을 구체화했으며, 이번에는 이미 승인된 7001 검증을 위해 제품 TLS 결함을 수정한다. 과거 승인 대기를 새 blocker로 취급하지 않는다.
- 보안 범위: 사용자가 명시한 단일 self-issued CA이고 critical BasicConstraints CA=true이면서 KeyUsage 확장이 없는 기존 PVE root 형식에만 Python 3.13의 RFC 형식 strict flag를 조정한다. 이 결정은 요청 전에 공개 trust anchor 형식으로 고정하며 TLS 실패 후 fallback/retry하지 않는다. system CA·현대 CA·복수 CA bundle에는 기존 strict 정책을 유지한다. CERT_REQUIRED, hostname, chain signature, 유효기간, TLS protocol/cipher, endpoint/DNS pin과 credential 전송 전 handshake는 보존한다. 원본 CA/PVE/system trust와 schema는 변경하지 않는다.
- 검증: synthetic root/leaf와 실제 OpenSSL MemoryBIO handshake로 성공을 먼저 재현하며, 잘못된 CA/hostname·만료/미래 leaf·만료 root·잘못된 EKU를 계속 거부하는지 확인한다. 현대 CA와 복수 CA bundle의 strict 유지, 기존 transport의 실패 시 credential 미전송 검사를 포함한다. 실제 PVE에는 수정 transport로 GET-only token/scope 확인을 먼저 한다.
- rollback은 이 호환 helper/호출을 이전 strict context로 되돌리는 코드/이미지 전환이며 인증서나 DB에 되돌릴 mutation은 없다. strict 형식 검사를 제한적으로 완화한다는 사실을 개발 안내·아키텍처에 명시하고 모든 자체 CA에 검증을 끄는 옵션으로 확장하지 않는다. 다음은 테스트 실패 확인→최소 수정→관련 회귀/기준 container→기존 token의 제품 import 준비다.

### TLS 수정·실제 GET 검증 재개 지점 (2026-09-19 22:07 KST)

- `setup_integration/tls.py`에 계획한 단일 명시 CA의 구형 root 형식 판별과 TLS context 생성을 분리하고 기존 HTTP/upload transport 모두 이 context를 사용한다. 관리형 request allowlist, DB, endpoint, proxy/redirect/retry, secret 입력 계약은 변경하지 않았다.
- 첫 신규 test 실행은 resolver fixture가 `type` keyword를 받지 못하는 테스트 도구 오류였다. 이를 수정한 뒤 이전 default-context 정책을 test process에 주입해 같은 성공 검사를 재실행했다. 현대 CA는 통과하고 구형 CA만 실제 `CA cert does not include key usage extension`로 실패했다(`/tmp/gjallar-tls-baseline.log`: 1 failed/1 passed). 이 실패를 제품 결함 재현 근거로 사용한다.
- 수정 후 setup_integration 전체 132 passed. synthetic CA/leaf의 실제 OpenSSL MemoryBIO handshake로 구형/현대 CA 성공과 wrong CA·hostname·expired/future leaf·expired root·client-only EKU의 정확한 verify code를 확인했다. system CA/modern CA/non-CA/복수 bundle strict flag 보존과 기존 실패 시 credential 미전송 검사도 통과했다. backend 기준 container session 60501 진행 중(`/tmp/gjallar-tls-container.log`).
- 수정된 실제 제품 transport로 사용자 CA를 지정한 PVE GET이 성공했다: version 9.0.11, 7001 compute/power/read 권한 missing=[]이며 context CERT_REQUIRED/hostname check=true. PVE 또는 인증서 mutation은 없다. requests-only 성공이 아니라 수정 제품 transport의 실제 결과다.
- 다음 실행 범위는 기존 승인된 local 설치에서 같은 schema 이미지 전환과 env token import다. bootstrap의 정상 compose/manifest는 변경하지 않는다. 첫 import에 필요한 token은 해당 설치의 원래 DB/key를 사용하는 일회성 local 등록 서버에만 0600 임시 env 파일로 전달하고 제품 로그인·등록 API를 사용한다. 기존 PVE token/ACL은 변경하지 않으며 root.env와 운영 DB는 건드리지 않는다. 전환 뒤 임시 서버/파일을 정리하고 원래 관리형 서비스를 재시작해 원래 key로 active revision을 사용하는지 확인한다. 임시 서버도 loopback 18000만 사용하며 다른 서비스와 동시에 띄우지 않는다.

### 관리형 import 완료·7001 실행 직전 (2026-09-19 22:10 KST)

- 기준 backend container session 60501 exit 0: 1619 passed/78 skipped. runtime image session 97053 exit 0이며 실제 설치 image는 `sha256:fe20329d409c786d3d1a30f030deb7f3da174b46785da2d1945f82878fab8288`이다. 동일 schema upgrade session 75486 exit 0, DB/원래 secret 지문 보존을 확인했다.
- 기존 token을 실제 사용자 로그인/등록 API로 가져와 활성화했다. attempt `67c18e1b-a0bb-4443-84a8-9b00df6ebcdc`, Operation `proxmox-registration-67c18e1b-a0bb-4443-84a8-9b00df6ebcdc`, active revision `1888e121-7e1f-4b1d-b94e-d6118e817ddf`, version 8. 선택 범위는 node yoonmanserver3·VM 7001, features read/power/compute, storage/bridge 선택 없음이다. PVE token/ACL에는 쓰지 않았다.
- 임시 등록 서버를 종료하고 `--rm` 컨테이너 부재를 확인한 뒤 생성한 0600 평문 env 사본만 삭제했다. 원래 bootstrap 서비스를 다시 시작했고 실제 CLI connection status는 live/fresh/inventory_available=true다. 이 서버에는 env token 자동 주입이 없으므로 원래 key로 저장된 관리형 credential을 사용한다. 신규 PVE 로그인·토큰 발급 테스트는 후순위로 유지한다.
- 실제 브라우저 VM 7001 상세에 running/4 CPU/8 GB, node·IP·50 GB disk가 표시됨을 screenshot으로 직접 확인했다. CPU·메모리 변경 준비는 running 상태에서 disabled다. 웹/API fixture가 아닌 설치된 앱이며 `/tmp/gjallar-7001-web-inspect.log` exit 0이다.
- 다음 실제 mutation은 이미 승인받은 7001 정상 종료 하나다. 기존 4 cores/8192 MiB·running 및 CPU/memory/digest 외 config의 hash를 기록한 뒤 CLI request ID `acceptance-7001-shutdown-0919`로 한 번 실행한다. stopped 직접 확인 후 웹 2 cores/4096 MiB, CLI 원복, 원래 running 재시작을 순서대로 확인한다. 각 단계가 미확정이면 다음 쓰기를 진행하지 않고 같은 Operation을 관찰한다. 디스크/NIC/다른 VM은 변경하지 않는다.

### 7001 정상 종료 확인·CLI 결과 계약 결함 (2026-09-19 22:15 KST)

- 승인된 7001 CLI shutdown을 request ID `acceptance-7001-shutdown-0919`로 한 번 제출했다. CLI는 MUTATION_UNCONFIRMED(exit 8)를 반환했으므로 mutation을 재전송하지 않았다. Operation GET에서 `vm-shutdown-yoonmanserver3-7001-5680e3bf819d7960` succeeded/coordination_incomplete=false를 확인하고 별도 PVE GET에서 stopped·4 cores/8192 MiB 및 나머지 config hash 보존을 확인했다. 실제 VM은 현재 정지 상태이며 다음 설정 변경은 아직 하지 않았다.
- 직접 원인: 기존 native start/shutdown 응답은 canonical Operation과 같은 ID를 `job_id`로 제공하지만 CLI 공통 mutation 함수는 `data.operation.operation_id`만 요구했다. 기존 CLI mock이 실제 power 응답과 달라 자동 검사에서 놓쳤다. 실제 계약의 job_id 응답으로 fixture를 고쳐 실패를 먼저 재현한다.
- 수정 범위는 CLI 결과 조회다. power 경로만 명시적으로 job_id를 canonical 조회 locator로 사용하고 Operation GET의 ID/type/node/VMID/idempotency key와 coordination 완료를 대조한다. 새 기능의 embedded Operation 및 요청 본문 일치 검사는 유지한다. upstream mutation·retry·lock/lease·DB/API 응답 계약은 변경하지 않는다. 이후 web compute와 CLI 원복, 실제 start 성공 결과로 확인하며 이미 완료된 shutdown을 검증 때문에 반복하지 않는다.

### 웹 compute 실제 변경·CLI 원복 준비 (2026-09-19 22:18 KST)

- power CLI fixture를 실제 job_id 응답으로 바꾼 뒤 start/shutdown 성공 검사 2개가 실패했다. power만 명시적 job_id locator와 canonical type/node/VMID/idempotency 검증을 추가했다. 다른 mutation의 embedded Operation 및 requested payload 비교는 보존한다. 잘못된 ID/type/node/VMID/request가 성공으로 표시되지 않는 검사 포함 local/container client 전체 234 passed.
- 실제 웹에서 7001의 정지 상태와 4 cores/8192 MiB를 읽고 2 cores/4096 MiB 검토 화면을 직접 확인한 뒤 실행 버튼을 한 번 눌렀다. 웹 요청 ID `41925bb5-74f3-4578-9898-5ba6aed5ed18`, Operation `vm-compute-7880f84fc37808e849b02333bebf6b218b088efc0fab3efd3e96e91909d8c0b4`, HTTP 200 및 canonical 성공 표시를 확인했다. 별도 PVE GET에서 2/4096/stopped와 나머지 config hash 동일함을 확인했다.
- 웹 검토/결과 screenshot은 설치 경로 `web-7001-compute-review.png`, `web-7001-compute-result.png`이며 직접 읽었다. browser script는 입력 대기용 stdin이 남아 있어 결과 확인 후 EOF로 정상 종료했다(session 1962 exit 0). 새 mutation 재전송은 없다.
- 실제 CLI로 현재 2/4096/stopped를 다시 읽고 원래 4/8192로 복원할 0600 `7001-restore-review.json`을 작성·검토했다. request ID `acceptance-7001-compute-restore-0919`로 실행 중이며 다음은 terminal/Operation/PVE config 확인 후 원래 running 재시작이다. 원복 확인 전에는 시작을 보내지 않는다.

### VM-01 실환경 검증 완료·다음 재개 지점 (2026-09-19 22:20 KST)

- 실제 CLI 원복은 exit 0, Operation `vm-compute-7043fe8b05f46af19df31015e6ffd7b61888b0ba11d769a73fffd7bd0eb653ff` succeeded/coordination_incomplete=false다. canonical observed_after는 4 cores/8192 MiB/stopped이며 별도 PVE GET도 일치했다.
- 이후 승인된 CLI start request ID `acceptance-7001-start-0919`, Operation `vm-start-yoonmanserver3-7001-9c8fcc5b3e19fce4` succeeded/coordination_incomplete=false·exit 0을 확인했다. 실제 PVE의 최종 상태는 **running·4 cores·8192 MiB**다. CPU/memory/digest를 제외한 원래 config SHA256 `08e192ee9c0d281e503e13f56b0e7aee3ffdb28b667666b51217d6ecff76a802`가 전 단계에서 동일했다. 디스크·NIC·다른 설정을 변경하지 않았고 7001을 삭제하지 않았다.
- 웹 변경 HTTP/canonical 성공과 실제 PVE, CLI 원복/시작의 canonical 성공과 실제 PVE를 각각 대조했다. 첫 shutdown은 실제 성공했으나 수정 전 CLI 표시가 미확정이었음을 보존한다. 결과 조회 수정 후 start의 실제 CLI 성공으로 새 경로를 확인했고 종료를 불필요하게 반복하지 않았다. UI 최종 상세 읽기는 별도 screenshot으로 보존한다.
- 검증 묶음: setup 132 passed, backend 기준 container 1619 passed/78 skipped, client local/container 234 passed, runtime build(기준 frontend test/lint/build 포함) 통과, 문서 계약 10 passed, diff check 통과. schema/transaction 구현은 이번 턴에서 변경하지 않아 이전 실제 PG 78개 검사를 재실행했다고 주장하지 않는다. 최신 설치 image는 fe20329…이며 정상 bootstrap 서비스가 running, 임시 import container/평문 env 사본은 제거됐다. 새 검증 세션이 진행 중인 동안 이 loopback 설치를 사용하고 전체 실환경 검사 종료 시 자체 서비스만 stop한다.
- 로드맵·PRD는 VM-01/기존 전원과 token import의 실제 검증만 갱신했다. Goal 전체는 미완료다. M2 나머지 VM 기능, M3~M6 실제 검증, UI 전체 마무리와 마지막 신규 로그인/발급/권한 갱신 검증은 남아 있다.
- 다음은 기존 token의 나머지 기능 권한·대상 준비를 읽기 전용으로 대조하고 관리형 연결의 추가 범위를 검토한다. 7001 삭제 허용과 신규 테스트 VMID 40000~40010 범위를 보존한다. 디스크 확장·NIC·복제·백업/복구·호스트 설정의 아직 명시되지 않은 정확한 영향/정리 범위는 작업 문서에 구체화해 묶어서 승인받는다. 그동안 실제 모니터링 GET/표시와 독립적인 UI 정리는 계속할 수 있다. PVE 인증서/기존 token/ACL·운영 DB·commit/push는 변경하지 않았다.
- 최종 실제 웹 상세(`web-7001-finished.png`)도 직접 확인했다. running/4 CPU·8 GB가 복구됐고 실행 중 CPU 변경 버튼은 다시 disabled다. `web-7001-before.png`는 최초 관찰로 보존했다. 후속 성능·guest 애플리케이션 준비 완료를 이 결과로 대신 주장하지 않는다.

### M4 실제 조회·등록 이력 조회 결함 재개 지점 (2026-09-19 22:30 KST)

- 직전 사용자 질문 응답은 Goal active 확인만 했으므로 구현 진전으로 집계하지 않는다. 이번에는 기존 관리형 설치의 CLI VM 7001/노드 yoonmanserver3 현재 사용량·1시간 PVE 이력 조회가 exit 0임을 확인했다. VM CPU 이력 60개 중 관찰 53/결측 7이며 정지 구간을 0으로 채우지 않는다.
- 실제 CLI alerts는 PROTOCOL_ERROR로 실패했다. 서버 예외는 등록 Operation의 `proxmox_connection` 대상을 VM locator로 해석한 `get_target_operation_lock`의 ValueError다. 실제 등록 이력을 포함한 공통 Operation 상세에도 같은 결함이 있다. 오류를 알림 화면에서 숨기거나 해당 작업을 누락시키지 않는다.
- 수정 범위는 읽기 전용 lock 조회의 대상 분기다. 연결 등록/폐기는 자체 connection transaction/advisory lock을 사용하므로 `proxmox_connection`에 VM durable lock 조회를 적용하지 않는다. VM/host lock 취득·해제·lease·DB schema·등록 직렬화는 그대로 유지한다. 실제 저장소와 공통 facade를 사용하는 회귀 검사로 등록/폐기 실패 이력 및 상세를 확인하고, 잘못된 VM locator의 거부를 보존한다. 복구는 이 조회 분기의 코드/동일 schema image 원복이다.
- 웹 모니터링 검사는 대기 timeout이 발생해 화면 증거를 수집 중이다. CLI 성공을 웹 성공으로 대신하지 않는다. PVE mutation은 없으며 다음은 실패 회귀 재현→최소 수정→관련 검사→승인된 loopback 설치 동일 schema 갱신과 실제 웹/CLI 재조회다.

### 다음 M2 실환경 검증의 구체적 승인 범위 (2026-09-19 22:33 KST)

- 최신 GET: yoonmanserver3의 7001은 running, scsi0는 nas-server의 50 GiB qcow2, onboot 미지정(기본 0), 단일 net0 vmbr0이다. nas-server는 shared NFS이고 images/backup을 허용한다. 테스트 VMID 40000~40010은 모두 비어 있다. vmbr0·vmbr1·vmbr2는 active이며 VLAN-aware가 아니다. 실제 storage 활성/용량과 pending 상태는 실행 전 제품 plan에서 확인한다. vmbr2는 기존 bridge이며 여기서 host 설정을 바꾸지 않는다.
- 승인 요청할 실행 묶음: 7001 graceful shutdown → 같은 node/nas-server에 40000(`gjallar-acceptance-m2-40000`) full clone → 원본 7001을 원래 running으로 복구. 복제본은 부팅하지 않는다. 7001의 192.168.2.31/24, hostname/host key가 복사되므로 guest identity 중복을 인정하되 정지 상태로만 검사한다.
- 정지 복제본 40000에서 scsi0 50→52 GiB 확장(축소 불가, guest filesystem 확장 없음), net0 vmbr0→vmbr2→vmbr0 변경 및 원래 MAC/model/firewall 등 나머지 설정 보존을 웹·CLI와 실제 config/volume으로 대조한다. 호스트 network reload·VLAN/물리 NIC/관리 주소 수정은 포함하지 않는다. 이미 running으로 복구한 원본 7001은 웹 console 화면 연결만 확인하며 guest 입력을 보내지 않는다.
- 검증 후 이번 실행이 만든 40000만 제품 delete로 삭제하고 VM/소유 volume 부재를 확인한다. 기존 7001 삭제는 허용돼 있으나 이 묶음에서는 보존한다. 최대 추가 가상 용량은 52 GiB + cloud-init이며 qcow2 실제 할당량·NFS 여유 용량을 plan에서 확인한다. NFS 상태 조회는 PVE 내부에서 다른 enabled storage 상태 점검/활성화가 발생할 수 있다.
- 기존 token/ACL을 바꾸지 않고 local 관리형 연결의 선택 범위를 node yoonmanserver3·VM7001/40000·nas-server·vmbr0/vmbr2로 늘려 import/plan/activate하고 원래 DB/key로 재시작한다. 필요한 read/power/compute/disk/network/clone/delete/console 및 clone VMID40000만 선택한다. 실제 token 권한이 없으면 별도 PVE ACL 변경을 하지 않고 해당 검사 미완료로 남긴다. 신규 issue 로그인은 마지막으로 유지한다.
- 복구: 응답 유실 시 같은 Operation GET/PVE 관찰만 하고 재전송하지 않는다. clone 미확정이면 40000의 소유/작업 증거부터 확인하며 임의 삭제하지 않는다. 원본이 정지됐으면 clone task/lock 종료를 확인한 뒤 승인된 원래 running 복구를 우선한다. 복제본 disk는 축소 대신 소유 확인 후 정리하며 NIC 검사는 정지 상태라 guest 통신 변경이 없다. 기존 active revision/key를 보존하여 local scope 전환 실패 시 관찰/기존 연결 복구 경로를 따른다.
- 이 묶음은 아직 승인 대기이며 현재 턴에서는 GET과 local 동일 schema 버그 수정만 했다. 백업/복원·이미지 제작·노드 이동·호스트 설정은 이 승인에 포함하지 않는다.

### M4 관리형 실환경 조회 확인·UI 정리 재개 지점 (2026-09-19 22:37 KST)

- 등록/폐기 Operation 실제 저장소→공통 facade→알림 보고서 회귀 2개가 수정 전 VM locator ValueError로 실패했고, 조회 helper의 `proxmox_connection` 분기 후 통과했다. 잘못된 VM locator는 계속 거부한다. backend 관련 검사 143 passed, 기준 container session 22194 exit 0: **1622 passed/78 skipped**, 문서 계약 10 passed, diff check 통과. 이번 수정은 읽기 분기이며 schema·transaction·취득/해제 알고리즘을 변경하지 않았다. 실제 PostgreSQL 전체 검사를 이번에 재실행했다고 주장하지 않는다.
- runtime build session 55830 exit 0. 승인된 같은 설치/DB/key의 bootstrap upgrade session 6167 exit 0이며 기존 DB·모든 secret 지문 보존을 확인했다. 현재 정상 서비스는 running, image는 `sha256:bcbe7de7dfd4df9c0e4b31d824e5022220425fda179bb485fd0cca27b1883dce` (`gjallar:acceptance-alerts-0919`)다. 이전 image/key/volume과 이력을 보존했다.
- 실제 CLI alerts exit 0, 등록을 포함한 6개 Operation 조회, unavailable=[]·실패 구간 0개다. 실제 active 등록 Operation `proxmox-registration-67c18e1b-a0bb-4443-84a8-9b00df6ebcdc`의 CLI 상세도 exit 0이다. 실제 실패/해제 표본이 없으므로 양성 알림 실환경 검증을 완료로 표시하지 않는다. 테스트의 실패 이력으로 제품 DB를 채우지 않았다.
- 실제 웹 검사 session 60798 exit 0: VM/node 현재·1시간 추이, 지표 전환, VM 모바일 390px, 알림 화면을 확인했다. VM CPU 차트는 2개 segment로 실제 정지 결측을 끊었고 node는 1개, 모바일 page overflow=false다. 앞선 timeout/Error는 검사 locator가 label 안의 option 텍스트 및 logo img를 구분하지 못한 문제였으며 검사 코드를 고쳤다. 제품 오류와 섞지 않는다.
- 직접 PVE RRD GET의 같은 timestamp와 CLI 표본을 대조했다. 시간 경과로 남은 VM CPU 46개/결측 7개, node CPU 53개가 일치했다. 단위 변환과 결측 보존을 실제 원천과 확인했으며 source/기간 밖 값까지 완료 주장하지 않는다. `monitoring-direct-comparison.json`, `monitoring-web-result.json`, `web-metrics-vm-desktop.png`, `web-metrics-vm-mobile.png`, `web-metrics-node-desktop.png`, `web-alerts-desktop.png`를 전용 설치 경로에 보존했다. 모바일/노드/알림 screenshot을 직접 읽었다. architecture·roadmap의 M4 실제 범위도 갱신했다.
- UI 다음 작업은 직접 본 사용량 화면의 미관찰 IO 카드 반복을 명확한 미관찰 안내로 모으고 모바일 차트 축 숫자 가독성을 높이는 것이다. 데이터·결측/임계 의미와 dashboard 전체 구성을 유지한다. 이어 VM 상세의 전체 작업 패널 정보량을 실제 화면 기준으로 정리한다. 이번 묶음에서 UI 자체를 이미 바꿨다고 표시하지 않는다.
- 다음 M2 묶음의 구체적 대상/영향/복구는 위 절에 기록하고 사용자에게 async 승인 질문을 보냈다. 아직 답변이 없다. 7001 현재 config/VM pending의 정적 clone 조건은 통과했고 cloud-init도 nas-server다. 정지 상태를 가정한 domain 검사일 뿐 실제 shutdown/clone plan 완료가 아니며 새로운 PVE mutation은 하지 않았다. 7001은 running·원래 사양이고 테스트 VM은 만들지 않았다. 승인 회신 전에는 storage 활성 조회·선택 범위 갱신·추가 VM mutation을 진행하지 않는다.
- 현재 진행 중 검증 process는 없다. Goal은 active/미완료이며 M2 승인 대기와 독립적인 UI 작업을 이어간다. M3~M6 나머지 live 검사, storage/긴 기간/실제 초과·해제 모니터링, 마지막 신규 로그인/발급 검증을 남긴다. commit/push·PVE token/ACL·호스트 설정·운영 DB 변경은 없다.

### 웹 정보량·모바일 차트 정리 착수 (2026-09-19 22:38 KST)

- 직전 Goal 턴은 실제 관리형 조회 결함 수정·원천 대조·문서 갱신을 완료한 progress다. 이번에는 최신 `MetricsPage`/VM 상세와 직접 읽은 실제 screenshot을 기준으로 기존 dashboard를 유지하며 두 화면만 정리한다.
- `MetricsPage`의 유효 현재 값은 카드에 남기고 null/미관찰 지표는 이름을 빠짐없이 한 안내에 모았다. 0은 유효 값으로 계속 표시한다. 차트는 mobile 160px/desktop 224px 높이를 확보하고 축 범위를 SVG 밖의 읽을 수 있는 텍스트로 이동했다. segment·시각 선택·결측·임계 규칙·원천 조회는 그대로다.
- 실제 7001 상세는 변경 폼이 모두 펼쳐져 최근 Operation이 아래로 밀렸다. `VmResourcePanels`는 콘솔을 즉시 보이게 유지하고 사양/디스크/NIC, 복제/템플릿, 영구 삭제를 native details로 묶는다. 자식 component는 접어도 unmount하지 않아 입력·요청/결과·단일 dispatch 상태가 유지된다. 삭제는 접힌 제목에도 비가역성을 표시하고 각 실행 전 영향·확인·동의는 기존 폼에서 유지한다. 설정 진단은 마지막 details로 옮겼다.
- 동일 schema runtime image build session 66565 진행 중이며 기준 Node 24 frontend test/lint/build를 수행한다. 다음은 승인된 loopback 설치의 같은 DB/key image 갱신, 실제 GET 화면 desktop/mobile 확인, 별도 browser fixture에서 펼침/접힘 입력 보존과 변경 요청 없음 검증이다. 실제 VM 정지나 API mutation을 UI 검증에 사용하지 않는다. 다음 M2 변경 승인 질문은 여전히 대기다.

### VM 상세·사용량 UI 검증 완료와 재개 지점 (2026-09-19 22:41 KST)

- 변경 파일은 `MetricsPage.jsx`, `VmResourcePanels.jsx`, `VmDetail.jsx`다. 기존 backend/API·단일 dispatch·console anchor·부모 VM key·폼 hook을 유지했다. API 또는 실제 PVE 상태를 UI 개선 때문에 변경하지 않았다. native details는 사용자 동작으로만 접히며 폼/검토/결과 DOM과 React 상태를 유지한다.
- runtime build session 66565 exit 0: Node 24의 기존 frontend 전체 test·lint·build 통과. 관련 코드와 diff check를 확인했다. 동일 설치 upgrade session 24382 exit 0, DB/원래 secret 지문 보존. 현재 running image `sha256:f45e4a5c82791c90bd499e84a8c89eae54caae350949d711939aa75a789ba5e1` (`gjallar:acceptance-ui-0919`). 이전 image/키/volume 보존. backend/client 변경이 없어 직전 통과 검사를 반복했다고 주장하지 않는다. 문서 계약 10 passed.
- 실제 모니터링 UI 검사 session 61901 exit 0: node/VM 유효 값 카드 3개, 미관찰 IO 항목 안내, VM 결측 segment 2/node 1, 모바일 차트 높이 ≥160px·overflow=false, 지표 변경·알림 조회를 확인했다. 실제 VM 상세 검사 session 45667 exit 0: 기본 접힘, Enter 키 펼침/접힘, running CPU 변경 disabled, mobile overflow=false를 확인했다.
- 별도 동일 browser의 GET response fixture만 정지 VM으로 바꿔 복제 입력 VMID/name/storage를 작성하고 접었다 펴도 값이 보존되는지 확인했다. 실제 7001은 정지하지 않았다. 로그인 이후 모든 non-GET API 요청 차단 guard를 두었고 mutation 요청 자체가 0개였다. 실제 변경 결과/미확정 상태를 새로 발생시켜 UI 검증했다고 주장하지 않는다. 화면 검사 evidence는 `vm-ui-result.json`, `monitoring-ui-result.json`이며 실제/fixture screenshot 이름을 구분했다.
- `web-ui-metrics-vm-mobile.png`, `web-7001-ui-after-desktop.png`, `web-7001-ui-after-mobile.png`를 직접 확인했다. 동일 1440px 폭의 VM 상세 전체 높이는 이전 2830→1983px로 줄었고 작업 이력이 더 위에 나타난다. 필요 작업·삭제 영향과 기존 접근 경로는 남아 있다. 모바일 chart 축 숫자는 이제 SVG 축소 영향을 받지 않는다.
- development에 새 펼침 경로/입력 보존을 반영하고 roadmap의 UI 완료 범위를 이 두 화면으로 한정했다. architecture 첫 요약에 남아 있던 “설치·관리형 조회 미검증/마이그레이션 미구현”을 실제 관련 절·코드·work의 증거에 맞춰 고쳤다. 미검증 범위를 제거하지 않았다. 신규 PVE 로그인/발급은 마지막이며 완료가 아니다.
- 다음은 나머지 웹 흐름, 특히 Proxmox 연결 설정과 템플릿·백업/복원·노드 유지보수의 중복/정보량·모바일 표시를 실제 또는 명시적 격리 화면에서 확인하고 정리하는 것이다. M2 실제 변경 묶음의 승인 회신이 오면 위 exact scope와 fresh plan부터 진행한다. 아직 회신이 없어 새로운 PVE mutation·scope 전환은 수행하지 않았다. 진행 중 command/session은 없고 loopback 서비스만 running이다. Goal active/미완료, commit/push 없음.

### Proxmox 연결 화면 정보 구성 변경 계획·진행 (2026-09-19 22:44 KST)

- 직전 Goal 턴은 VM/모니터링 UI 구현·실제 화면 검증을 완료한 progress다. 현재 관리형 설치 `/settings/proxmox`의 screenshot을 새로 읽었다. 이미 등록된 상태에서도 신규 입력/모든 선택 권한이 펼쳐져 있으며 “호스트 storage” 안에 network, “VM 백업” 안에 이동·복원이 포함돼 제목도 불명확했다.
- 이번 변경은 `ProxmoxSetupPage.jsx`의 표시 구성이다. 등록 이력 로딩 중 새 폼을 먼저 보여주지 않고, 이력이 있으면 기존 등록 선택과 새 등록 준비 진입을 먼저 제공한다. 이력이 없는 첫 등록은 기존처럼 폼을 연다. 새 폼은 기본 연결·대상 입력 뒤 기능별 details로 묶고 접힌 제목에도 선택 checkbox 개수를 표시한다. 모든 input/name/FormData/등록 intent·idempotency·action 및 최종 권한/영향 검토는 유지한다. 접기 자체는 등록·권한 부여가 아니다.
- 인증·권한 구현 변경은 없다. 설명은 전용 발급의 30일과 기존 token import의 권한 불변을 구분하도록 정정했다. 기능 그룹을 접어도 checkbox/값을 유지하므로 최종 제출에서 숨겨진 권한이 누락되거나 추가되지 않는지 실제 browser의 intercepted prepare payload로 대조할 예정이다. 실제 준비 POST/PVE 로그인/발급/활성화는 하지 않는다.
- runtime build session 36568에서 Node 24 test/lint/build 진행 중. 다음은 동일 schema·원래 key/DB의 승인된 로컬 설치 image 전환 후 실제 기존 이력 화면 확인과, POST를 전달하지 않는 격리 browser fixture의 빈 이력/입력 보존/정확한 요청 계약 검사다. 기존 M2 변경 승인 질문은 대기 중이며 변경 범위를 임의 확대하지 않는다.

### Proxmox 연결 UI 검증 완료·재개 지점 (2026-09-19 22:47 KST)

- `ProxmoxSetupPage.jsx`의 새 진입/권한 그룹 표시를 구현했다. 조회 기본 권한은 유지하며 VM 일상 관리, 호스트 storage·bridge, 공식 이미지 제작, 템플릿 기반 생성, 백업·복원·이동, 제작 소유 자원 정리로 묶었다. 접힌 summary는 선택 개수를 표시한다. 기존 prepare/authenticate/act/권한 계획 본문·최종 실행·폐기 확인은 변경하지 않았다.
- runtime build session 36568 exit 0: Node 24 frontend test/lint/build 통과. 승인된 동일 schema 설치 upgrade session 60794 exit 0이며 DB/secret 지문을 보존했다. 현재 running image `sha256:2a39d31fbffbafec28aface53fb1a3ce19196ad7c8dd21964cbb803829e077af` (`gjallar:acceptance-setup-ui-0919`), 기존 active revision/token/key/volume/이력은 유지한다.
- 실제 browser 검사 session 38316 exit 0: 등록 이력이 있을 때 신규 폼 미노출, 기존 active import 등록 GET, 새 등록 입력, 최초 선택 checkbox 0개, 390px mobile overflow=false 확인. 실제 기존 화면과 신규 입력 desktop/mobile screenshot을 저장했고 기존/모바일 이미지를 직접 읽었다.
- 빈 이력 GET과 prepare 응답만 browser 안에서 가로챈 별도 fixture로 첫 등록 폼 자동 노출, 접힌 일상관리 3개/복원 1개 선택 표시, VMID와 storage 값 보존을 확인했다. 전달 직전 payload는 features `[read,power,compute,clone,restore]` 및 기존 VM 7001/clone 40000/restore 40006와 해당 node/storage/bridge만 포함했다. 다른 선택 기능의 권한이 추가되지 않았다. 준비 POST 1개는 전부 browser 안에서 처리했고 서버/PVE로 전달한 mutation은 0개다. 이를 신규 로그인·발급·실제 연결 갱신 완료로 표시하지 않는다.
- evidence: 전용 설치 경로 `setup-ui-result.json`, `web-setup-ui-existing-desktop.png`, `web-setup-ui-new-desktop.png`, `web-setup-ui-new-mobile.png`. development에 새 진입/권한 선택 사용법을 반영하고 roadmap UI 범위를 갱신했다. backend/client/auth 구현은 변하지 않아 관련 전체 검사를 반복하지 않는다. diff check 통과.
- 다음 M2 승인 대기 계획의 **연결 scope 보정**: contracts의 clone 대상은 기존 VM 범위와 겹칠 수 없다. 따라서 1차는 vmids=[7001], clone_vmids=[40000]으로 복제하고, 완료 후 2차는 vmids=[7001,40000], clone 기능/clone_vmids 제거 후 disk/network/delete 검사로 전환한다. 동일 token/허용 target/node/nas-server/vmbr0·vmbr2 안에서 local 선택 범위만 단계별로 갱신하며 PVE ACL을 바꾸지 않는다. 앞선 범위 문장의 40000을 양쪽에 동시에 넣는 해석은 사용하지 않는다. 아직 실제 전환/clone/새 VM 변경은 시작하지 않았다.
- Goal active/미완료. 현재 진행 중 command는 없으며 loopback 설치만 running이다. 승인 질문 회신이 없으므로 독립적인 템플릿/백업·복원/유지보수 웹 흐름을 다음으로 확인한다. 마지막 신규 로그인·발급 검증은 사용자와 별도로 남긴다. commit/push, 실제 PVE mutation·권한·호스트·운영 DB 변경은 없다.

### 템플릿 결과 오인 재현·수정 범위 (2026-09-19 22:51 KST)

- 직전 턴은 연결 UI 구현/검증 progress다. 이번에는 현재 백업/복원/유지보수/템플릿 코드를 대조하고 초기 화면을 캡처했다. 제작 결과 화면이 응답 Operation ID와 canonical GET의 ID를 비교하지 않는 것을 발견했다.
- 실제 설치 frontend를 사용하는 browser fixture session 2632 exit 0에서 요청 ID `fixture-build-request`와 다른 `different-operation`의 succeeded 응답을 제공했는데 “실제 템플릿과 base volume을 확인했습니다”가 표시되는 결함을 재현했다. 원래 node/VMID/type는 같아 기존 느슨한 검사를 통과했다. POST 1개는 browser 내에서 가로채고 서버/PVE mutation은 0개다. `web-image-result-before.png`를 직접 읽었다.
- 수정은 frontend 결과 조회 대조만이다. 제작은 기존 `assertChangeResult`로 Operation ID/type/canonical VM target/node/전체 실제 제출 payload를 확인한다. VM compute/disk/network/clone/delete/template/image_cleanup의 공통 hook 호출에도 누락된 operationType을 연결한다. clone은 원본이 아닌 새 VMID가 canonical target이므로 기존 hook의 operationVmidFromPlan으로 지정한다. backend/DB/권한/lease/retry/dispatch는 바꾸지 않는다.
- 성공 메시지와 다음 작업 링크는 정확히 일치하는 canonical 성공·조정 완료에서만 제공한다. 불일치는 기존 미확정/작업 확인 경로를 유지하고 재전송하지 않는다. 회귀는 공통 helper의 유형/노드/VMID/전체 요청 불일치, 실제 브라우저 negative/positive fixture, 표준 frontend test/lint/build로 확인한다. 실제 제작·정리는 기존 승인 대기와 별개이며 이 검사로 완료 표시하지 않는다.

### 템플릿·VM 결과 검증 보강 완료와 재개 지점 (2026-09-19 22:54 KST)

- `ImageBuildPage`는 실제 최종 제출 payload를 한 변수로 유지하고 기존 `assertChangeResult`에 넘긴다. helper는 canonical target뿐 아니라 details의 VMID 일치도 확인한다. compute/disk/network/clone/delete/template/image_cleanup hook 호출에 실제 backend operationType을 연결했다. disk는 `vm_disk_resize`이고 clone canonical target은 `new_vmid`다. backend task/config application의 실제 계약을 읽고 대조했다.
- `changeResult.test.mjs`에서 기존 ID/type/node/target/request 검증과 추가 기능별 요청 key·검토 digest·확인 문구·동의값/상세 VMID 불일치 거부를 확인했다. 기준 runtime build session 25060 exit 0: Node 24 frontend test/lint/build 통과. 이전 실제 7001 CLI 원복 canonical JSON과 저장된 검토 payload를 새 helper에 입력했을 때 succeeded로 통과했다. 새 실제 mutation으로 정상 흐름을 반복하지 않았다.
- 승인된 같은 schema 설치 upgrade session 78331 exit 0, 기존 DB·secret 지문 보존. 현재 running image `sha256:b8687e08128e2d51a321bfbd1f8d9a1c6eb47712e41c5bcbd4888e55a25dedec` (`gjallar:acceptance-result-ui-0919`). 관리형 active revision/키·token/volume/이력은 유지한다.
- 수정 뒤 browser negative session 2839 exit 0: 다른 Operation ID의 succeeded를 오류/결과 미확정으로 남기고 완료 문구·후속 생성/정리 링크를 제공하지 않았다. `web-image-result-after.png`를 직접 읽었다. positive fixture도 정확한 ID·대상·전체 제출 payload일 때 정상 완료 표시를 확인했다(`web-image-result-positive.png`). 각 POST는 browser 안에서만 응답했고 서버/PVE mutation 0개다. 실제 제작·정리·중단 복구 검증과 구분한다.
- 백업·복원·노드 유지보수·이미지 정리 초기 화면도 현재 설치에서 캡처했다. 백업/유지보수 기본 화면을 직접 읽었으며 불필요한 전체 재설계를 하지 않았다. 아직 실제 backup storage 조회·복원·report의 전체 입력/결과 UI를 이번 턴에서 완료했다고 주장하지 않는다. 현재 architecture에 공통 결과 확인 계약을 반영했다.
- 다음은 격리 browser fixture에서 백업 목록→복원 검토→결과/검사 링크, 노드 유지보수의 상태별 다음 행동·모바일 표시를 확인하고 필요한 결함을 고치는 것이다. 별도 승인 대기 M2 묶음이 허용되면 기존 정확한 단계별 scope와 fresh plan으로 전환한다. 승인 회신 없음/새 PVE mutation 없음. command/session은 모두 종료됐고 전용 설치만 running이다. Goal active/미완료, commit/push 없음.

### 백업·복원·유지보수 화면 연결 검증 (2026-09-19 22:59 KST)

- 직전 턴은 템플릿·VM 결과 대조 수정/검증 progress다. 이번에는 현재 RestoreReport/Maintenance/Migrate 계약과 입력을 대조하고 installed frontend의 browser fixture로 백업 목록→archive 포함 복원 링크→새 VMID/이름/격리 동의→최종 검토→정확한 canonical 성공→검사 보고서/새 VM 상세 링크를 확인했다.
- session 50877 exit 0: 복원 대상 40006, 원본 40000, archive가 모든 단계에 유지되고 NIC 격리와 부팅 미실행 안내가 표시됐다. 모바일 백업 목록/복원 report/유지보수 report overflow=false. 실제 복원은 하지 않았고 POST 1개는 browser 안에서만 응답했다. 모든 별도 non-GET 요청은 차단하며 서버/PVE 전달 mutation 0개다.
- 유지보수 보고서에서 node1→node2를 선택했지만 “정지 VM 이동 검토”를 열면 목적 노드가 빈 값이었다. link가 source만 전달하고 MigrateForm도 destination을 초기화하지 않는 두 지점을 확인했다. frontend 두 파일에 선택적 destination_node query를 연결한다. 기존 route와 원본-only 링크는 유지하며 입력 초깃값만 제공한다. 이동 조건 GET 재검토·대상/영향 확인·실행 버튼·서버 검증은 그대로이고 자동 조회/실행은 추가하지 않는다.
- 다음은 기준 Node 24 test/lint/build와 같은 schema local 설치 업데이트, 동일 browser fixture의 목적 node2 전달 확인 및 새 화면에서 mutation이 자동 발생하지 않는지 확인이다. M2 실제 변경 승인 대기는 계속하며 원본 7001/운영 자원에는 손대지 않는다.

### 백업·복원·유지보수 연결 검증 완료와 재개 지점 (2026-09-19 23:03 KST)

- `MaintenancePage.jsx`에서 보고서의 목적 노드를 선택적 query로 전달하고 `MigratePage.jsx`에서 입력 초깃값으로 받는다. 기존 원본-only 링크와 매번 새 조건 검토·대상 확인·동의·명시적 실행을 유지한다. API/권한/DB/실행 계약은 변경하지 않았다.
- runtime build session 10666 exit 0: 기준 Node 24 frontend test/lint/build 통과. 동일 schema local upgrade session 15538 exit 0, DB/secret 지문 보존. 현재 running image `sha256:376e39e89e96f2c8a5e505bf2f25ff5815c740c30344b215bb36fb4e4b58fe89` (`gjallar:acceptance-handoff-ui-0919`). 기존 관리형 연결/volume/key와 이전 image를 보존했다.
- browser fixture session 45530 exit 0: 백업 archive 전달→복원 검토→정확한 canonical 결과→검사 report/새 VM 링크가 유지됐고, 유지보수 보고서의 node2가 이동 화면에 전달됐다. mobile overflow=false, 복원 POST 1개는 browser 내부에서만 처리했으며 서버/PVE mutation 0개다. 링크 진입 시 이동 실행 요청도 발생하지 않았다. `web-restore-report-mobile-after.png`, `web-maintenance-report-mobile-after.png`를 직접 읽었다. 실제 복원/이동 완료와 구분한다.
- development에 목적 노드 전달과 재검토 사용법, roadmap에 이 fixture UI 검증 범위를 반영했다. 문서 계약 10 passed. backend/client는 이번 묶음에서 바꾸지 않아 전체 검사를 반복했다고 주장하지 않는다.
- Goal 상태를 다시 확인했으며 active다. 사용자가 정한 기존 등록 연결 우선·신규 PVE 로그인/발급은 마지막 순서를 유지한다. 진행 중 command는 없고 승인된 loopback 설치만 running이다. 별도 M2 실제 변경 묶음의 승인 회신은 여전히 없으므로 새로운 scope 전환/PVE mutation은 하지 않았다.
- 다음 재개 지점은 남은 템플릿 정리·호스트 설정 검토 화면을 격리 fixture로 확인하는 것이다. 승인 회신 시에는 위 단계별 scope와 fresh plan부터 M2 full clone/디스크/NIC/console/삭제 검증을 진행한다. M3~M6 live 검증과 마지막 신규 로그인/발급은 미완료다. commit/push 없음.

### 호스트 설정 결과 표시·템플릿 정리 화면 검사 착수 (2026-09-19 23:07 KST)

- 직전 턴은 유지보수 목적 노드 전달 수정·브라우저/기준 빌드 검증을 완료한 progress다. 현재 host 두 화면과 결과 helper, VM 공통 hook, CLI mutation 및 backend canonical Operation facade를 대조했다.
- host UI는 canonical status만 succeeded이면 완료 문구를 표시한다. 공통 facade의 coordination_incomplete는 recovery 미완료 또는 본 작업 소유 lock 잔존을 나타낸다. CLI/VM UI는 이를 완료에서 제외하므로 호스트 UI도 같은 기준으로 보강한다. 실제 storage/network 설정·조정 알고리즘·권한·DB는 변경하지 않는다.
- 브라우저 fixture는 host 검토 POST/실행 POST와 canonical 결과를 모두 가로채고 나머지 non-GET을 차단한다. succeeded + coordination_incomplete 응답의 잘못된 완료 표시를 먼저 재현하고 정상 완료/미완료 모두 검사한다. 템플릿 정리는 검토/확인/결과→다른 소유 자원 별도 검토의 입력 전달도 함께 확인한다. 실제 PVE 호스트 변경/삭제는 하지 않는다.

### 호스트 결과 표시 수정·템플릿 정리 UI 확인 완료와 재개 지점 (2026-09-19 23:09 KST)

- browser before session 87232 exit 0: storage/bridge 두 화면 모두 canonical succeeded + coordination_incomplete=true에서 완료 문구를 표시하는 문제를 재현했다. 원본 screenshot을 직접 읽었다. 새 helper 회귀도 수정 전 실패를 확인했다.
- `features/hostConfiguration/result.js`는 기존 exact ID/type/target/전체 요청 대조 뒤 상태와 양쪽 coordination_incomplete를 함께 판정하는 verified 값을 제공한다. `HostStoragePage`/`HostNetworkPage` 완료 표시가 이 값을 사용하며 storage 미완료 안내는 기존 Operation의 잠금·복구 확인으로 연결한다. backend/API/권한/잠금 알고리즘·실제 설정은 바꾸지 않았다.
- `hostConfigurationResult.test.mjs`는 정상 결과·대상/요청 불일치와 5개 상태 × 두 수준의 조정 여부를 두 기능에 대조한다. local helper 통과, runtime build session 87918 exit 0에서 기준 Node 24 전체 frontend test/lint/build 통과. 문서 계약 10 passed, diff check 통과. backend/client 전체 검사를 이번에 재실행했다고 주장하지 않는다.
- 승인된 같은 설치 upgrade session 66034 exit 0: DB·secret 지문 보존. 현재 running image `sha256:93450c4f3c4ce0716af46495436a02a8ef4e529a836e01fa22662391757980ac` (`gjallar:acceptance-host-ui-0919`). 이전 image/원래 volume/key/관리형 revision은 유지한다.
- browser after session 29888 exit 0: 두 기능의 조정 미완료는 확인 필요, 정상 완료는 완료로 표시한다. VLAN 20-30 10 11-19 입력은 최종 요청에서 10-30으로 정규화된다. 템플릿 정리의 제작 Operation/VMID 전달→삭제·보존 검토→명시적 확인→canonical 결과→업로드 원본 별도 검토 연결을 확인했다. 모바일 page overflow=false. host 실행 각각 2개·cleanup 1개와 host 검토 POST는 모두 브라우저 내부 fixture이며 서버/PVE로 전달한 mutation은 0개다. 실제 storage/bridge 변경·템플릿 삭제가 아니다.
- `host-cleanup-ui-before.json`, `host-cleanup-ui-after.json` 및 `web-host-*-{before,after}-*.png`, `web-cleanup-*.png`를 전용 설치 경로에 보존했다. 수정 후 storage 미완료/bridge 정상 완료 화면도 직접 읽었다. architecture에 완료 판정 계약을 반영했다.
- 진행 중 command/session은 없고 loopback 검증 설치만 running이다. Goal active/미완료. 다음은 템플릿 테스트 배포·검사/접속 기록의 웹 흐름과 M4 긴 기간 PVE 읽기 검증을 현재 구현·권한 범위 안에서 확인한다. 새 실제 PVE 변경 묶음의 승인 회신은 아직 없으므로 M2 단계별 scope 갱신/clone 등은 실행하지 않았다. 신규 로그인/발급은 사용자 지시대로 마지막에 남긴다. commit/push 없음.

### 장기 이력 원천 대조·배포 검사 증거 확인 착수 (2026-09-19 23:13 KST)

- 직전 턴은 host 완료 표시 수정/검증 progress다. 이번에는 관리형 CLI로 VM7001/노드 yoonmanserver3의 day/week/month/year 이력 8개를 GET-only 조회했다. 모두 exit 0이며 각각 1440/336/121/1140개 point, 60/1800/21600/21600초 해상도를 반환했다. 기간 이름만으로 실제 관찰 기간·보존량을 확대하지 않는다.
- 제품 transport와 제공된 CA를 사용한 직접 PVE RRD GET으로 같은 timestamp의 CPU·메모리·network, VM disk rate 전체 값을 대조했다. 조회 시각 차이로 day 공통 timestamp는 1439개이고 다른 기간은 전부 일치한다. 결측도 그대로 null이며 year의 오래된 빈 구간을 0으로 바꾸지 않는다. 전용 설치 경로 `cli-metrics-{vm,node}-{day,week,month,year}.json`, `monitoring-long-direct-comparison.json`에 증거를 보존했다. storage 상태 조회/실제 변경은 하지 않았다.
- `TemplateTestPage`는 최초 report의 operation_id를 대조하지 않고 증거 저장 후 GET이 아직 미기록 상태여도 성공 문구를 표시한다. CLI도 최종 재조회한 증거를 대조하지 않는다. 기존 backend의 exact Create/Job/artifact 결합 계약을 읽고, frontend/CLI에서 조회 작업·target과 저장 응답의 access 상태/시각/artifact가 재조회 보고서에 실제 연결됐는지 확인하도록 보강한다. 기록 실패 시 새 요청을 자동 제출하지 않는다. 서버 증거 저장·인증·DB 계약은 변경하지 않는다.

### 장기 이력 실제 조회·접속 증거 대조 완료와 재개 지점 (2026-09-19 23:21 KST)

- 실제 관리형 CLI의 node/VM day/week/month/year 8개 조회와 원천 GET 대조를 완료했다. day 공통 timestamp 1439개, week336/month121/year1140개에서 모든 지원 지표 값·단위·결측이 일치했다. VM day 결측 metric 값42개, month459/year7592개, node month255/year5350개를 null 그대로 확인했다. 이는 실제 보존된 표본의 검증이며 기간 전체 보존이나 storage 검증은 아니다.
- 실제 웹 long-history session 69570 exit 0: VM year와 node month 조회·지표 전환, VM year 390px mobile overflow=false를 확인했다. `web-long-metrics-vm-year-mobile.png`를 직접 읽어 오래된 미관찰 구간이 0으로 연결되지 않고 실제 관찰 범위·21600초 해상도·유효/누락 수를 표시하는지 확인했다. 이 실행은 로그인 후 non-GET 차단을 유지했으며 별도 VM/PVE 변경이 없다.
- template browser before session 99743 exit 0: 다른 생성 작업 report를 표시했고, 접속 기록 후 재조회가 not_run 상태인데도 기록 완료 문구가 표시됐다. `web-template-test-before-stale.png`를 직접 읽었다.
- `features/workloads/templateTestResult.js`와 `TemplateTestPage.jsx`, CLI `template_test_workflow.py`는 역사적 report의 정확한 생성 작업/대상을 확인하고, 새 증거의 access 상태·시각·artifact ID/checksum이 재조회 report에 연결됐을 때만 기록 확인을 표시한다. 같은 요청 ID를 재사용하면 backend가 반환한 원래 증거를 유지·대조하고 기존 기록임을 표시한다. 새 시각/상태로 기존 기록을 덮어쓰지 않는다. 서버/DB/인증/멱등 저장 구현은 변경하지 않았다.
- 최종 local client session 77755: **257 passed**. 기준 client container session 58496: **257 passed**. runtime build session 8730 exit 0에서 기준 Node24 전체 frontend test/lint/build 통과. 새로운 helper는 불일치·오래된 상태·다른 artifact·각 접속 결과·idempotent replay를 확인한다. 문서 계약10 passed, diff check통과. backend 전체는 이번에 변경하지 않아 이전1622/78 skipped를 다시 실행한 결과로 주장하지 않는다.
- 처음 검증한 중간 image 설치 뒤 idempotent replay 보존 회귀를 추가해 최종 image로 한 번 더 갱신했다. 최종 upgrade session6790 exit0, DB/원래 secret 지문 보존. 현재 running image `sha256:9c38356f0fac2a989fe5c8409db4dc0c8f41bd051213e9ca2e9440f3578e7047` (`gjallar:acceptance-template-test-ui-0919`). 이전 image/volume/key/관리형 revision은 유지한다.
- 최종 browser session75355 exit0: wrong report는 form 없이 오류, stale report는 기록 미확정, positive는 기록 확인, replay는 원래 failed/시각과 기존 기록 안내를 표시했다. 기록 POST3개는 browser fixture로만 처리했고 실제 제품 DB/PVE 전달 mutation0개다. 모바일 overflowfalse, 수정 후 stale/replay screenshot을 직접 읽었다. 실제 VM 배포·SSH 접속 기록으로 제품 DB를 채운 검사가 아니다.
- architecture/development에 증거 대조·기존 기록 재사용을 반영하고 roadmap M4에서 확인한 장기 이력 범위를 갱신했다. 전용 설치 경로에 `monitoring-long-ui-result.json`, `monitoring-long-direct-comparison.json`, `template-test-ui-{before,after}.json`과 화면 증거를 보존했다.
- 진행 중 command/session 없음, loopback 설치 running. Goal active/미완료. 다음은 최신 요구사항별 검증표와 현재 UI 진입/생성 검토 흐름을 대조해 남은 독립 검증을 마무리한다. M2 실제 clone/디스크/NIC/console/삭제 묶음은 위 구체적 승인 질문의 회신 대기이며 실행하지 않았다. M3~M6 나머지 실환경 변경·storage/실제 초과·해제 사례 및 마지막 신규 로그인/발급도 미완료다. commit/push 없음.

### 생성 검토 화면·현재 유지보수 조회 확인 (2026-09-19 23:28 KST)

- 직전 턴은 장기 이력 실제 원천 대조와 접속 증거 대조 수정/검증 progress다. 이번에는 현재 로드맵·19:36 검증표를 읽고 이후 실제 검증 근거와 대조한다.
- 설치 frontend의 격리 browser에서 템플릿40000 전달, 다른 템플릿39999로 자동 대체하지 않음, 3CPU/접속 사용자/SSH 공개키/IP 입력과 이전 단계 이동 보존, boot_and_verify 기본값, 최종 검토의 미확정 IP 직접 확보 확인, 검토 승인 후에도 별도 실제 생성 동의 필요를 확인했다. 검토/승인 POST는 browser 안에서만 처리하며 실제 draft/Operation/PVE 생성은 없다.
- 앞선 browser timeout2건은 제품 오류가 아니라 검사의 승인 문구(`승인되었습니다.`)와 원본 부재 시 설명을 포함하는 접근성 이름을 잘못 지정한 문제였다. 해당 locator를 수정해 전체 검사를 마무리한다. 실제 화면을 직접 읽었고 mobile 생성 요약12개가 모두 한 열로 표시되는 정보량을 확인했다.
- `CreateInstanceWizard`의 요약 타일만 mobile2열/desktop3열로 정리하며 IP·SSH fingerprint는 좁은 화면에서2칸을 사용한다. min-width0과 기존 긴 값 줄바꿈을 유지한다. 입력/검토/승인/최종동의/생성 계약과 dashboard는 바꾸지 않는다. 새 테스트를 추가하는 대신 기존 기준 frontend 검사와 수정 전후 실제 browser 화면·높이/overflow를 확인한다.
- 기존 관리형 CLI `maintenance node yoonmanserver3` 실제 GET exit0. 선택 범위의7001(running,4cores8192MiB,nas-server/vmbr0)만 관찰되며 status=incomplete, node_shutdown_safe=false, read_only=true다. 목적node/backupstorage를 지정하지 않아 두 추가 검사는not_checked로 남긴다. 비선택 VM·storage·bridge까지 관찰한 전체 노드 안전성 검사로 확대하지 않는다.

### 생성 검토 UI·선택 노드 보고서 검증 완료와 재개 지점 (2026-09-19 23:32 KST)

- 생성 browser before session76199 exit0, after session85329 exit0. 지정 원본40000/다른 원본39999·부팅 정책·수정 사양·단계 이동 입력 보존·원본 부재 차단·IP 직접 확보 확인·검토 승인과 최종 생성 동의를 분리해 확인했다. 수정 전후 각각 draft/preflight/plan/approve4개 요청은 브라우저 fixture로만 응답했으며 생성 요청0개/제품 DB·PVE 전달 mutation0개다.
- `CreateInstanceWizard` 변경은 요약 grid·긴 값 span·min-width뿐이다. 모바일390px 동일 fixture 전체 높이2993→2721px,320px에서도 page overflowfalse다. 수정 후320px screenshot을 직접 읽었고 IP·SSH fingerprint가 넓은 줄에 남는지 확인했다. 실제 생성 검토/실행 성공으로 확대하지 않는다.
- runtime build session12943 exit0: 기준 Node24 frontend 전체 test/lint/build 통과. 같은 설치 upgrade29417 exit0: DB·원래 secret 지문 보존. 현재 running image `sha256:24d659f21ddd8acfb2547bdc3f7f6f096f040546b83ee1cf7d6ea059d3543b55` (`gjallar:acceptance-create-review-ui-0919`). backend/client는 이 묶음에서 변경하지 않았다. 문서 계약10 passed, diff check통과.
- 실제 maintenance CLI의 선택 VM7001 정보를 PVE config/status GET과 대조했다. node/name/running·4cores8192MiB·nas-server/vmbr0가 일치한다. 실제 웹 session5093 exit0에서도 같은 범위·준비 미완료·노드 종료 안전성 미확인, 선택하지 않은 백업/이동 검사not_checked를 확인했다. mobile overflowfalse, non-GET요청0개. 웹 screenshot을 직접 읽었다. 이 조회를 전체 노드의 종료 안전성·이동 준비 완료로 해석하지 않는다.
- 전용 설치 경로의 `create-handoff-ui-{before,after}.json`, `web-create-template-review-{mobile-after,320px}.png`, `maintenance-direct-comparison.json`, `maintenance-live-ui-result.json`, `web-maintenance-live-mobile.png`를 보존했다. roadmap/architecture에 실제로 검증한 범위만 반영했다.
- 현재 장기 이력8개 모두 임계 초과 구간0개다. 관찰하지 않은 발생/해제를 완료로 표시하지 않으며 검증을 위해 운영 VM에 임의 부하를 주지 않았다. 실제 storage 관찰과 추가 준비 검사도 선택 범위 갱신/승인에 의존한다.

### 현재 완료 조건 재대조 (2026-09-19 23:32 KST)

19:36 표의 **당시 미검증 상태**는 보존한다. 아래는 이후 코드/기록/설치/원천/화면 증거를 반영한 현재 판단이며 전체 완료 선언이 아니다.

| 요구사항 | 현재 확보한 근거 | 남은 완료 증거·재개 조건 |
|---|---|---|
| M1 설치·로그인·재시작 보존 | 승인된 Mac arm64 loopback bootstrap 재개, 실제 웹/CLI 로그인, stop/start·재실행·동일 schema upgrade의 DB/key/계정/이력 보존 | 최초 Docker 오류 원인은 미확정으로 보존. 마지막 신규 PVE 로그인·발급 경로는 사용자와 검증 |
| M1 관리형 연결·최소 권한·갱신 | 제공 CA TLS 검증·기존 token import/activate/restart, 실제 선택7001의 read/power/compute, 각 추가 feature/scope/권한 자동 회귀 | 신규 기능에 필요한 기존 연결 선택 범위 갱신과 실제 권한 검증. 현재 M2 묶음의 단계별 scope 승인 회신 대기 |
| M2 목록·시작·종료·VM-01 | 실제7001 정상 종료→웹2cores4096MiB→CLI4cores8192MiB원복→시작, canonical/PVE/설정 보존 대조 | 첫 지원 조합에서 확인 완료. 기존 템플릿 생성 실환경은 아래 TPL-03과 함께 남음 |
| M2 VM-02~05 | 구현/자동/PG·웹/CLI/결과 대조 및 fixture UI 검사 | 7001 full clone→40000 정지본 disk50→52GiB·NIC변경/원복→소유40000삭제·원본 보존. 위22:33/22:47 exact scope 승인 필요 |
| M2 VM-06 | 인증된 noVNC·만료/종료/권한·CLI진입 자동 검사 및 VM 상세 연결 | 실제7001 console화면/종료. 앞선 승인 질문의 입력 없는 연결 확인 범위 대기 |
| M3 TPL-01 | 전환 operation·정지/설정/volume/준비 동의·웹/CLI 자동 검사 | 준비된 정지 테스트 VM의 실제 전환·원본disk보존 |
| M3 TPL-02 | 고정 공식 이미지 무결성 다운로드, 제작/정리 실행·복구 계약·웹/CLI·fixture 결과 대조 | 승인된 VMID/storage의 실제 upload/import/template/소유 자원 정리 |
| M3 TPL-03·기존 VM생성 | 지정 템플릿→생성 입력/검토/승인/최종동의 fixture, 검사 보고서·접속 증거의 exact binding/replay, client257/기준frontend검사 | 실제 별도VM생성/부팅/cloud-init/guest-agent/IP/직접SSH 결과와 명시적 삭제. 대상·네트워크/SSH접속 조건 및 영향 승인 필요 |
| M4 OBS-01~02 | 관리형 node/VM current·hour 및 CLI day/week/month/year, PVE모든지원지표/결측대조, 실제웹장기/모바일 | 선택 storage 상태·이력. scope갱신과 storage관찰 영향 승인 필요 |
| M4 OBS-03 | 실제 등록 이력 포함alerts, 정상/결측 화면; 발생/해제/중복/복구 자동·fixture검사 | 실제 초과/해제 및 실패/복구 표본은 현재없음. 실제 검증 중 자연 표본 또는 별도 승인한 테스트 조건 사용 |
| M5 BAK-01~02 | 백업/격리복원 실행·잠금/복구/PG·웹/CLI, backup→restore→report fixture | 실제 backup/archive→별도VMID격리복원/부팅/결과/정리·원본보존. M2 승인에 포함되지 않음 |
| M6 OPS-01 | 정지shared NFS이동 실행/복구·웹/CLI·목적node인계 검사 | 실제 승인node 간 이동·양쪽위치/정지/config보존·별도부팅 |
| M6 OPS-02 | 실제 선택node/7001 보고서 웹·CLI·PVE대조, 미선택 추가검사/숨은범위/노드안전성미확인 | 선택범위 갱신 후 실제 backup/migration 준비항목 대조 |
| M6 OPS-03 | directory/bridge 웹·CLI·권한/host조정/PG·정상/미완료결과 fixture | 기존directory정확한경로·storageID/내부bridge·노드전체reload영향 및 복구계획의 별도승인 후 실제검증 |
| UI·기존기능·문서·최종게이트 | dashboard/TUI보존, 주요신규화면 실제설치+격리fixture/모바일, 최신client257·frontend기준검사·문서계약10·diff검사 | 실제실행 뒤 전체업무결과확인, 필요한최종통합회귀, 검증용임시진입파일·소유service정리 |

- 현재 code/test command는 모두 종료됐고 loopback 검증 설치만 running이다. 미확정 외부 mutation은 없다. Goal은 active/미완료이며 이번 턴은 구현·실환경 읽기/문서 상태를 진전시킨 progress다.
- 다음 필수 진전은 위M2승인 묶음이다. 답변이 오면 fresh GET/권한plan→clone대상분리scope1→복제/원본원복→기존VM범위scope2→disk/NIC/삭제를 실행한다. 그전에 새 scope를 활성화하거나 실제 자원을 바꾸지 않는다. 추가 독립 결함이 발견되지 않는 한 동일 검사·화면을 이유 없이 반복하지 않는다. 기존 승인 질문에 답이 없다는 점은 전체 완료로 바꾸지 않는다. commit/push 없음.

### 승인 대기 차단 판정과 재개 조건 (2026-09-19 23:33 KST)

- 직전 턴은 생성 UI 개선·실제 유지보수 조회·검증표 갱신을 완료한 progress다. 이번에는 현재 Goal/status·23:32 검증표·AGENTS 위험 경계를 다시 확인했다. 반복 검사를 새 구현 진전으로 세지 않는다.
- 같은 M2 live target/side effect 승인 부재가 최소 직전3개 연속 Goal 턴(호스트 UI/23:09, 장기 이력·증거 대조/23:21, 생성 UI·유지보수/23:32)에 모두 기록돼 있다. 그동안 독립적인 구현/검증을 끝냈으며, 현재 확인된 남은 필수 증거는 새 선택 범위와 실제 PVE 변경 또는 마지막 사용자 로그인/발급에 의존한다. 새 승인 회신은 없다. 실행 중 검증 handle이나 미확정 mutation을 기다리는 상황도 아니다.
- AGENTS의 `live Proxmox mutation·smoke: 정확한 target과 side effect를 별도 승인받는다.`에 따라, VMID40000~40010 사용/정리 허용과 기존7001 사용 허용을 새 구체적 변경 전체의 승인으로 확대하지 않는다. 22:33/22:47에 마련한 exact scope/영향/복구/단계별 연결 전환 계획을 그대로 재개 조건으로 유지한다. 이미 승인된 기존token 사용·동일schema로컬설치·7001 CPU/전원 검증은 다시 승인 요청하지 않는다.
- 차단 조건은3개 이상의 연속 Goal턴에 재확인됐고 독립적인 남은 수정이 확인되지 않아 Goal을 blocked로 전환한다. 이는 완료나 사용자 요청 pause가 아니다. 전체 M1~M6 목표와 미완료 표를 유지한다. 승인 없이 새VM/scope/ACL/운영DB/호스트를 바꾸거나 코드 변경·같은 테스트 반복으로 대기 시간을 채우지 않는다.
- 재개할 첫 묶음: PVE192.168.2.11/node yoonmanserver3에서7001정상종료→nas-server에40000 fullclone→7001재시작. 복제본40000은부팅하지 않고 disk50→52GiB·net0 vmbr0→vmbr2→vmbr0검사, 소유확인 후이번40000만삭제.7001console는화면연결/종료만확인. 기존token/ACL불변의 localmanaged선택범위2단계갱신과 storage조회활성영향은동일승인에포함한다. 실패시원본running복구를우선하고 미확정재전송/임의정리를하지않는다. 세부조건은22:33/22:47절을따른다.
- 검증용 loopback서비스/전용DB·key·이력·image·증거는 후속실환경검증을 위해 보존하며 전체검증종료시 소유service만stop한다. commit/push없음.

### M2 실제 변경 승인 수신·재개 지점 (2026-09-20 00:18 KST)

- 사용자가 남은 작업 안내의 첫 M2 묶음에 “ㅇㅇ 진행해”로 승인했다. 22:33/22:47의 정확한 대상·영향·2단계 선택 범위 전환·복구 계획으로 재개한다. 이후 M3~M6 호스트/백업/템플릿 변경 전체로 확대하지 않는다.
- 새 PVE GET에서 7001 running/4cores8192MiB/50GiB/nas-server/vmbr0, 테스트 VMID40000~40010 부재와 기존 bridge를 재확인했다. local18000·원래 DB/키 설치는 healthy다. 원본 config/volume을 먼저 보존하고 1차 import/activate/restart 후 clone 준비를 검증한다. 승인된 40000은 절대 부팅하지 않는다.
- Goal의 저장 상태는 아직 blocked이며 API는 resume 상태 변경을 지원하지 않는다. 사용자 재개 지시에 따라 실제 작업을 이어가고 완료로 표시하지 않는다. commit/push 없음.

### M2 복제 실행 중 재개 지점 (2026-09-20 00:23 KST)

- 기존 token/ACL 불변의 1차 import/activate/restart 완료: 등록 `85d1cde4-7a30-4632-8a5d-d3916d32acb3`, read/power/compute/clone/console, 원본7001/새40000/nas-server/vmbr0·vmbr2. 임시 token env 복사와 import container를 제거하고 정상 관리형 서버로 재시작했다.
- 7001 정상 종료와 CLI clone plan 완료. clone POST는 단1회 실행했다. Operation `vm-clone-b9329a5b95f541895f82e0f8dff9dca177627eb19368cfc20c4c3b740f93b18f`는 running/task이며 원본·복제본 lock과 heartbeat가 유효하다. CLI15초 대기는 MUTATION_UNCONFIRMED로 끝났으나 서버 task 관찰은 계속된다. 재전송하지 않았다.
- 다음은 기존 Operation/PVE task GET으로 완료·lock해제를 확인한 뒤 원본7001 start다. 그전 서버 재시작/2차scope전환/원본start/복제본삭제를 하지 않는다. 원본 config는 전용 비공개 파일로 보존했다.

### M2 full clone 완료·원본 재시작 (2026-09-20 00:29 KST)

- 위 clone Operation이 succeeded/completed, coordination_incomplete=false, target_lock=null, recovery completed임을 CLI canonical GET으로 확인했다. 실제 PVE task 진행률을 관찰하며 기다렸고 clone POST는 재전송하지 않았다.
- 직접 PVE GET에서 40000 정지·Operation 소유 marker·별도50GiB volume·새MAC/SMBIOS UUID와 원본 전체 config(digest 제외) 보존을 확인했다. 복사된 IP는 원본과 같지만 복제본은 한 번도 부팅하지 않았다. 증거 `m2-direct-clone.json`, `m2-clone-original-config.json`.
- CLI로 원본7001 start 완료(exit0). 이후 2차 scope를 import/activate/restart했다: 등록 `2727dd09-5afd-4f7d-acdb-52b0c78932ea`, 기존VM7001/40000, clone기능/미래VM범위제거, read/power/compute/disk/network/delete/console. PVE ACL·token은 변경하지 않았다. 임시 token env와 import container 제거 완료.
- 다음은 웹40000의 디스크50→52GiB와NIC vmbr0→vmbr2, CLI NIC원복·소유복제본삭제 및7001입력없는콘솔 확인이다. 현재 backend/client 구현 변경은 없고 실제 실행/관찰만 진행한다.

### 디스크·NIC 실검증 완료 / 콘솔·삭제 결함 수정 범위 (2026-09-20 00:37 KST)

- 웹 scsi0 50→52GiB 완료(`vm-disk-6894a778f8481e9860b100a0d19f12ad90cadc589d09a013900bdc35aa2d7e71`), CLI disk show와 직접 volume55834574848bytes 대조. 웹 net0 vmbr0→vmbr2(`vm-network-234cbb7ebaad82f51b826bea52b955e9efc89b003ede8d26b88fa50a26435a99`) 후 CLI vmbr0원복(`vm-network-6cbed5fb7ef09b0f9f1d6f85728b2165774d13e2649ee9cdf600b5ab2a5b2b30`) 완료. 원본 전체config/4cores8192/running, 복제본정지·MAC·기타config 보존 확인. 웹 screenshot을 직접 읽었다. 첫 NIC browser 실패는 implicit label 선택자 문제로 요청0개였고 수정 후 성공했다.
- 실제 console은 CONSOLE_PROXY_INVALID. 원문 ticket/password 저장·출력 없이 응답 형태만 검사하여 PVE의 port가 4자리 decimal string임을 확인했다. 기존 parser는 int만 받아 거부한다. 5900~5999의 canonical ASCII 문자열만 정수로 normalize하고 bool/공백/float/범위외 등은 계속 거부하는 호환 수정과 회귀를 먼저 수행한다.
- 삭제 POST는 단1회 실행했으나 Operation `vm-delete-549295020e83cf33504fe00a3c9faf0394f6024880cb61211f3a254e5504731d`가 needs_reconciliation / VM_DELETE_DISPATCH_UNKNOWN / UPID없음 / paused로 남았다. 직접GET에서40000은 여전히 정지 상태로 존재한다. 기존 전송은 DELETE의 purge=0·destroy-unreferenced-disks=0을 body로 보낸다. PVE HTTP server는 POST/PUT 외 body를 거부하므로 managed/legacy 전송에서 DELETE 선택값을 query로 전달하는 최소 호환 수정을 회귀 검증한다. [PVE HTTP server 처리 근거](https://lists.proxmox.com/pipermail/pve-devel/2023-February/055950.html).
- 승인된 정확한 target/권한/purge값·단일dispatch·lock·recovery계약은 바꾸지 않는다. 기존 미확정 삭제는 자동 재요청하거나 DB/잠금을 강제 수정하지 않는다. 이전 요청의 확정 증거와 안전한 처리 경로를 별도로 확인한다. 수정 이미지는 기존 승인된 동일schema 로컬설치에만 적용한다. 원본7001은 running이고 테스트40000은 아직 남아 있다.

### PVE 응답·전송 호환 수정 검증과 재개 지점 (2026-09-20 00:44 KST)

- `console/domain.py`의 제한된 decimal port 정규화, `setup_integration/transport.py`와 legacy `proxmox/client.py`의 DELETE query 전송을 수정했다. 기존 선택 범위 검증 뒤 정확히 같은 purge=0/destroy-unreferenced-disks=0 값을 전달한다. task/lock/recovery 또는 자동 재시도는 변경하지 않았다.
- 회귀는 수정 전6 failed/11passed로 재현한 뒤 관련143passed. 기준 backend-test container session40572는 **1644passed/78skipped**, 문서계약10passed, diff검사통과. client/frontend는 변경하지 않았다. runtime image build98769는 기존 frontend 검증 cache를 재사용했으며 이번에 frontend 검사를 새로 실행했다고 주장하지 않는다.
- 같은schema 로컬upgrade45688 완료: `sha256:a2470236b4a2e47233f7a85583b521e6f08feafdceac52a85baf2b97542428ca` (`gjallar:acceptance-pve-compat-0920`). DB·원래secret지문·미확정작업을 보존했다. 현재 콘솔실환경 재검증을 이어간다.
- storage hour CLI와 직접PVE 동일timestamp118개지표값 일치. 현재nas-server 약80.8%로 실제 warning구간이 있으며 관찰시작전부터 높아 onset_confirmed=false다. 실제web/mobile의 현재warning과 최신결측에 따른 이력관찰불명을 확인했고 결측을해제로표시하지 않는다. 삭제needs_reconciliation 알림1개도 실제웹/CLI에서 확인했다. 두mobile screenshot을 직접 읽었다. 실제초과의 시작·해제/실패후복구완료까지 검증했다고 주장하지 않는다.

### 콘솔 실검증 완료·삭제 수동 복구 제안 (2026-09-20 00:50 KST)

- 문자열port 수정 후 실제 RFB handshake·canvas·명시적 종료 성공. 화면은 “Guest has not initialized the display (yet).”이며 게스트 OS 로그인 화면 성공이나 키보드 입력을 주장하지 않는다. screenshot을 직접 읽었다. 진단용 WebSocket subclass가 noVNC의 raw-channel prototype 검사와 충돌한 검사실패는 wrapper 제거로 해결했으며 제품 수정으로 세지 않는다.
- 실제 브라우저 disconnect 뒤 gateway가 중복close를 보내는 별도 오류를 회귀로 재현하고 client_state도 확인하도록 수정했다. local41passed, 기준container 관련41passed. 처음 container 단독명령의 PYTHONPATH 누락은 고친 뒤 통과했다. 전체1644/78검사는 이 마지막guard 전 결과로 구분한다.
- 최종 runtime67177·동일schema upgrade80975 완료, image `sha256:ccc6e761db1f06059ece412d927ded801486cd8b286fb2669f603ca15ac39b46` (`gjallar:acceptance-console-close-0920`), DB/key보존. 최종 실제browser78772 성공 및 해당서버로그 중복close/exception없음. 콘솔 연결 종료 완료. app/DB는 후속검증을 위해 계속 실행한다.
- 삭제 Operation은 아직 version3/checksum `sha256:da174ee838b1cd42fe6c4e9dc53f039eb1e6b8e12d3ba739337ab0fca1847f07`, needs_reconciliation/paused, UPID없음이다. 수정 코드는 미래DELETE의 전송형식을 고쳤지만 기존미확정결과/잠금을 자동변경하지 않는다. 테스트40000은52GiB·vmbr0·정지로 남고 원본7001은4cores8192MiB·원래50GiB·running이다.
- **별도 승인 요청할 제한된 수동 복구**: 전용local18000의 DB `gjallar`만0600 pg_dump백업 → 정확한 기존삭제Operation을 취소(cancelled)하는 감사event추가·기존event/실패코드보존 → 동일transaction으로 그Operation의40000잠금만해제 → 수정된정상CLI로40000의새삭제검토/단1회실행 → canonicaltask성공·VMID/소유2volume부재·7001보존확인. 실패한옛요청을 성공으로덮어쓰지 않는다. productionDB·다른VM·PVE권한·호스트설정은 제외한다.
- 실행 준비 script `/tmp/gjallar-m2-delete-repair.py`는 기본read-only이며 `--apply-approved-cancellation` 때만 기존fenced recovery repository의claim/commit으로 local취소event와정확한잠금해제를 수행한다. raw SQL삭제/이력삭제/전역lock해제/PVE mutation을 포함하지 않는다. 설치UUID·Operation종류/상태/버전/checksum·paused·현재잠금owner·7001상태·40000소유marker/원래삭제manifest동일·PVE active task없음을 사전검사했다. 현재read-only실행통과. 실제취소나새DELETE는 **아직실행하지 않았다**.
- 승인 후에도 전후조건을 새로 검사한다. mismatch/active task가 있으면중단한다. local취소commit실패는transactionrollback, 취소완료뒤새삭제실패는새Operation관찰로남기고반복하지않는다. 백업은사고대응근거이며 외부삭제후옛DB복원을자동실행하지않는다. 이는 최초삭제시정의하지않았던local수동잠금해제이므로 AGENTS의DB정합성·recovery위험경계에따라 별도로승인받는다.
- roadmap/architecture/development에 이번 실제검증과삭제미완료, 호환수정을 반영했다. M3~M6 추가실환경변경은별도범위검토가남는다. Goal완료아님, commit/push없음.

### 수동 복구 승인·UI 전면 개선 범위 확정 (2026-09-20)

- 사용자가 “ㅇㅇ 그냥 다 해도돼 진행해”로 직전 구체적 수동복구/정리안을 승인했다. 전용DB백업 후 기존삭제취소 감사event·정확한40000잠금해제, 새CLI검토/삭제/원본보존 확인을 진행한다. 재승인하지 않는다.
- 같은 메시지에서 UI 전면 개선과 상단 탭 네비게이션 정리를 명시했다. 이전 dashboard 전체 디자인 고정 제약은 이번 UI 개편에 대해 대체된다. 기존 기능·자원/작업 의미·권한·실행동의·canonical URL·TUI는 보존한다. 현재 제품/코드를 디자인 기준으로 실제화면을 살펴 탐색 구조와 페이지 위계, 작업 진입·상태·모바일 표현을 일관되게 정리한다. 새 product/backend권한 또는 PVE호스트 변경 허용으로 해석하지 않는다.

### 삭제 정리 완료·UI 구현 재개 지점 (2026-09-20 01:05 KST)

- 승인한 전용DB0600백업의 restore list 검증 후 기존 fenced recovery 경로로 정확한 미확정 삭제만 cancelled 처리했다. 옛 실패·event를 보존하고 해당40000잠금만 해제했다. 새 CLI review는 정지40000·52GiB scsi0와4MiB cloudinit 두 소유volume만 포함함을 확인했다.
- 새 삭제 `vm-delete-9e62c2483298c7ec6e793b6319d5aeb45e8caecc2433f996807e9fe3e6b7c23c` 단1회 실행이 succeeded/completed, lock=null, recovery completed다. 직접PVE GET에서 VMID·소유volume 부재, 원본7001 전체config(digest제외)·running 보존 확인. `m2-direct-deleted.json`, 새 CLI 결과/검토를 전용설치에 보존했다. 이전 미확정 요청을 성공으로 덮어쓰지 않았다.
- IAB 실제 대시보드 화면을 확인했다. 과대한 헤더·영문/한글 혼합·모바일 아이콘 전용 메뉴·8개 하위탭을 개편한다. 상단5개 업무영역, 모니터링/설정의 그룹별 왼쪽 메뉴(모바일 select), VM작업 분류, 공통표면/입력/키보드초점, 대시보드·주요목록·로그인을 일관되게 구현하고 화면에서 재검증한다. canonicalURL·권한·동의·결과계약은 보존한다. UI만 변경하며 새 PVE mutation은 없다.

### 웹 탐색 개편 구현·검증 중 재개 지점 (2026-09-20 01:15 KST)

- 상단5개 한국어 메뉴·브랜드/연결상태 헤더, exact-active 및 고정 메뉴 위치, 그룹별 모니터링/설정 메뉴(데스크톱 rail·모바일 select), 대시보드 카드/위계, 주요 workflow 공통표면·입력·focus·reduced-motion, VM 개별설정 disclosure와 작업진입, 로그인/페이지제목/favicon을 개편했다. 정상 목록의 관찰근거는 접고 불완전 context·stale근거는 펼친다. 기존변경·canonicalURL·권한·동의·폼/결과계약·TUI는 보존한다.
- IAB에서 수정 전/후 화면을 직접 확인했다. 실제 nodemetrics 조회, 모바일 select→alerts 이동,320/390px 메뉴이름·선택위치·page overflow없음,7001상세CPU설정 펼침/실행중변경차단·삭제분리,설정/host bridge320px를 확인했다. 이 UI 점검은 PVE 변경을 실행하지 않았다.
- frontend전체회귀 통과. 첫 lint의 사용하지 않는 nav용변수 제거, 레이블/메뉴노출 변경에 맞춘 UI계약 테스트 갱신 후 Node24 container frontend test/lint/build 통과. 최초 전체verify는1644passed/78skipped와 문서 anchor1개실패였고 PRD 제목 변경의 roadmap anchor를 수정한 문서계약10passed. 현재 공통verify·verify:container 재실행 중이며 완료 결과를 이어 기록한다.
- 첫 runtime UI upgrade는 중지 직후 port검사에서 PORT_IN_USE로 멈췄다. listener부재 확인 뒤 기존 service start의 upgrade journal 재개로 새 image실행을 복구했다. 반복upgrade는이미같은이미지여서unchanged였으므로 검증script의running전용assert가실패했다. DB삭제/새설치/키재발급은없다. 최종이미지는 이후 목록근거 접기를 포함한 전체검증 산출물로 한 번 더 적용하고 전후DB/secret지문을파일로기록해확인한다.
- PRD/로드맵의 dashboard고정제약을 최신승인으로대체하고 architecture에 탐색계약을갱신했다. 최종 전체검증·현재코드image적용·배포화면검사·임시UI서버정리·문서최종대조가 다음순서다. M3~M6 미검증 실제변경을 이번UI검사로완료처리하지 않는다. commit/push없음.

### 다음 M3 live 묶음의 구체적 승인안 (2026-09-20 01:18 KST)

- 다음 독립 검증은 TPL-02 공식 이미지 제작/정리다. 새 GET에서 VMID40000~40010 모두미사용, nas-server가NFS/shared이며import·images·backup content를이미제공함을확인했다. 호스트storage content변경은불필요하다. 증거 `m3-environment-read-0920.json`.
- 대상: 기존PVE192.168.2.11/node yoonmanserver3, 새VMID40001/name gjallar-acceptance-image-40001, staging와disk모두nas-server,bridgevmbr0. 고정catalog의AlmaLinux9.8이미지589299712bytes를Gjallar의임시파일로다운로드하고기존SHA256/헤더검사→고유Operation전용import파일업로드→2cores/2048MiB/10GiB일반VM작성→정지template전환/실제volume확인. 복제/생성계열의최초조건에따라업로드파일·VMID부재/권한/스토리지여유공간을재조회한다. 게스트부팅·고정IP할당·7001전원/설정변경·호스트설정변경은포함하지않는다.
- 기존token/ACL불변의관리형import/activate/restart경로로image_build+image_vmids40001·선택nas-server/vmbr0를활성화한다. 제작성공후40001을기존vmids로옮기고image_cleanup과동일storage를선택해권한검토한다. 정상웹/CLI를통해같은buildOperation이소유한template/volume와staging파일을각각검토·정리하고원천부재를확인한뒤선택범위를7001중심으로되돌린다. 로컬설치만재시작하며운영PVE권한은바꾸지않는다.
- 정상task/volume/marker와원본 7001 보존을대조한다. 미확정이면재전송/강제잠금해제/임의파일삭제를하지않고Operation·UPID·잔여자원을기록한다. 제작실패의PVE자체정리와소유불명잔여물은독립수동복구범위로분리한다. 검증완료전정상부팅/배포·TPL-01·백업/복원/이동완료를주장하지않는다.
- 이exact scope는직전40000수동복구/삭제승인에포함되지않았으므로AGENTS live mutation 경계에따라별도승인을받는다. UI최종검증/문서갱신은승인답변과독립적으로계속한다.

### 전체 검증 완료·작업 필터 누락 보완 (2026-09-20 01:22 KST)

- `pnpm run verify` exit0: client257passed, backend1645passed/78skipped, frontend전체test/lint/build통과. `pnpm run verify:container` exit0: backend1645passed/78skipped, 기준Node24 frontend전체통과(client stage는변경없는cache). backend최종gateway guard도전체회귀에포함했다. 남은Vite593kB주chunk크기경고는실패가아니며이번UI변경을이유로의존성/빌드분할전환을추가하지않았다.
- 실제작업목록을확인해종류필터가옛4개작업에고정된누락을발견했다. `entities/operation/model.js`의label정의를공통목록으로공개하고목록필터가같은18개지원종류(연결등록포함)를사용하도록변경했다. 모든지원종류의회귀를추가했고frontend전체통과. IAB에서VM삭제필터가40000의새succeeded/옛cancelled두작업만반환함을확인했다. 최종수정후frontend기준container test/lint/build를재실행중이다. backend/client변경은없어전체재검사는반복하지않는다.
- IAB에서키보드skiplink의main-content실제초점,템플릿제작·기존VM생성·작업목록의1280px화면/선택위치,모바일호스트bridge320px를추가확인했다. 템플릿부재시생성다음단계차단은유지된다. 읽기/탐색외실제변경은실행하지않았다.

### UI 최종 반영·재개 지점 (2026-09-20 01:25 KST)

- 최종 image `sha256:f892ff7d1c93a9797d86c8dab1ac1f7cda38cb9e59208db13f3dd7b6907e49a5` (`gjallar:acceptance-ui-final-0920`)를 동일 schema 전용 loopback18000에 적용했다. 업그레이드 전후 계정·감사·Operation checksum·등록·연결·설치·revision의 count/digest 및 기존 secret 파일 지문이 모두 일치한다. `ui-final-upgrade-before.json`/`ui-final-upgrade-verified.json`에 근거를 보존했다. 이 최종 적용은 exit0이며 앞선 포트 충돌은 남아 있지 않다.
- 마지막18종류 필터 반영 후 기준Node24 frontend전체test/lint/build를 다시 통과했다. IAB 실제18000에서 새상단/대시보드,기존계정logout→login,연결확인중5개탭유지·연결완료를확인했다. 최종1280px대시보드 screenshot은 `ui-final-dashboard-1280.png`다. 임시dev5175의소유PID5517만종료했다. 검증용18000·DB는사용자화면확인과후속검증을위해보존한다.
- 현재소유테스트VM40000/volume은없고7001은원래설정으로실행중이다. 미확정PVE요청없음. 문서PRD/goal-prompt/roadmap/architecture와이work의UI방향·검증범위를대조했고commit/push없음.
- 다음작업은위01:18 M3제작/정리exact scope의사용자회신을확인하고fresh GET→관리형scope갱신→정상제작/검증/정리다. 승인질문은발송했으며아직회신없음. 임의M3~M6변경이나최초PVE로그인/발급은하지않았다. Goal전체는미완료이며M2추가실검증·UI반영결과를M3~M6완료로확대하지않는다.

### 기능별 상단 탐색 재구성·재개 지점 (2026-09-20)

- 사용자 지적에 따라 이전 다섯 탭의 이름·배치 변경을 넘어 기능 위치를 재구성했다. 상단은 전체 현황 / VM 관리 / 템플릿 / 모니터링 / 인프라 / 작업 이력이다. 템플릿 제작·정리를 VM 메뉴에서 분리하고, 유지보수를 모니터링에서 인프라 연결·스토리지·브리지 설정과 함께 배치했다. 계정·사용자 관리는 우측 계정 메뉴로 옮겼다. 백업·복원·이동 등 VM 대상 작업은 기존 VM 상세에서 이어간다.
- canonical URL과 AdminGuard를 유지한다. 상단도 exact/alias 우선·최장 prefix 선택기를 사용해 템플릿에서 VM 탭이, 유지보수에서 모니터링 탭이 중복 활성화되지 않게 했다. 계정 메뉴는 관리자 항목 필터와 Escape/외부 클릭/경로 변경 닫기를 제공한다.
- frontend 전체 테스트와 lint 통과. 초기 auth 표시 계약 테스트는 사용자 정보가 AccountMenu로 이동한 구조에 맞춰 갱신했다. 현재 Node24 runtime 이미지 빌드 중이며 이후 기존 loopback18000에 동일 schema 적용·DB/secret 보존 대조·실제 데스크톱/모바일 탐색 확인을 진행한다. 노드 scope는 이번 UI 변경으로 확장하지 않았고 M3 live 승인 대기는 별도로 유지한다.

### 기능별 탐색 반영·검증 완료 / 재개 지점 (2026-09-20)

- 최신 Node24 container frontend 전체 test/lint/build, 로컬 frontend test/lint, 문서계약10passed와 diff 검사를 통과했다. 앞선 전체 verify/verify:container는 위01:22 기록이며 이번 frontend 변경으로 backend/client 전체를 반복하지 않았다. 기존 Vite chunk 크기 경고는 남는다.
- `gjallar:acceptance-functional-nav-0920`, image `sha256:8d0a3624e959999e54d1728d9dcc3f2f253645bce34ce7a2e36f86e13b37b777`를 기존18000에 적용했다. 중지 직후 PORT_IN_USE가 재현됐고 listener 부재·기존 연결 TIME_WAIT를 확인했다. 포트 해제 후 정상 service start의 upgrade journal 재개가 성공했다. 교체 전 저장한 DB count/digest와 기존 secret 지문이 모두 일치한다. 근거는 `functional-nav-upgrade-before.json`/`functional-nav-upgrade-verified.json`이다. 포트 검사를 우회하거나 bootstrap 코드를 변경하지 않았다. 설치 안정화에서 TIME_WAIT 오인 처리의 재현·개선이 남는다.
- 실제 IAB18000에서 템플릿 독립 메뉴, VM 목록/생성 메뉴, 유지보수가 분리된 모니터링, 인프라의 유지보수→브리지/스토리지 이동, 정확히 하나의 상위 선택, 계정 이동·Escape·메뉴 밖 링크 클릭 닫기를 확인했다. 320px에서 여섯 이름·인프라 select·계정 진입과 수평 overflow 없음, 데스크톱 화면을 직접 확인했다. screenshot `functional-navigation-1280.png`를 보존했다. 재시작 중 오류 페이지에 남은 검증 tab 대신 같은 IAB 새 tab에서 검사했다. span의 press 검사 실패는 실제 키보드 Escape로 재검증했다.
- PRD·architecture·roadmap을 여섯 기능 영역으로 갱신했다. 새 PVE 변경·노드 범위 확대·DB migration·commit/push는 없다. Goal은 미완료다. 다음은 별도로 요청한 M3 exact scope 회신 확인 후 제작/정리 실검증이며, UI 탐색 검증을 미검증 M3~M6 완료로 확대하지 않는다.

### 정보 밀도 중심 UI 전면 개선 착수 / 재개 지점 (2026-09-20)

- 사용자 요청은 Grafana처럼 현재 상태·추이·문제를 한 화면에서 파악하는 것이다. 실제 현황 화면에서 큰 2열 요약 카드와 중복 인프라 목록 때문에 노드 표가 첫 화면 밖으로 밀리는 것을 확인했다. 이번에는 작은 요약 행, 실제 PVE CPU/메모리/네트워크 차트, 최근 실행 작업, 촘촘한 노드 표로 재구성하고 공통 shell·폼·목록의 간격과 위계를 함께 정리한다.
- 여섯 기능 탭과 기존 canonical route·권한·동의·실행 결과를 보존한다. 기존 읽기 API와 차트 결측 처리만 재사용하며 새 수집기·자동 PVE 변경·DB 변경은 없다. 퍼센트는 고정 축으로 읽고, 현재 값과 이력의 마지막 값·관찰 시각·미관찰을 구분한다. 요약 화면의 노드 범위는 기존 관리형 선택 범위다.
- 완료 조건은 실제 로컬 서버에서 정보 밀도와 모바일 가독성·탐색·차트 조작 확인, frontend 전체 test/lint/Node24 build 및 관련 데이터 표시 회귀 통과, 최신 문서와 재개 지점 갱신이다. M3~M6 live 완료와 구분한다.

### 밀도 개선 구현·실제 화면 점검 / 재개 지점 (2026-09-20)

- 어두운 소형 헤더, 넓은 공통 작업 영역, 작은 요약 지표, 4개 노드 추이 패널과 최근4개 Operation, 촘촘한 노드 표를 구현했다. 템플릿/백업/복원/호스트 설정 등의 공통 workflow와 VM 목록/상세·작업 목록의 제목·간격·폼 높이를 줄였으며 모바일 입력은44px를 유지한다. 모니터링은 처음부터 노드 지표를 읽고 CPU/메모리/네트워크(지원 VM은 디스크 포함)를 함께 보여준다. 시각별 slider·표와 임계 이력은 별도로 접근한다.
- 실제 PVE의 노드/VM7001 지표, 네트워크 평균과 마지막 이력 표시, 현재0값 유지, 키보드 slider Home, 대상 변경 시 이전 차트 제거,320/390px 수평 overflow 없음과 템플릿 폼을 확인했다. 관리형 범위 밖 노드의 통계나 샘플 데이터를 만들지 않았다. 노드 현황과 차트는 각각 표시한 조회 시점의 값이다.
- 늦은 응답·대상/기간 불일치·조회 오류·선택 해제 회귀, 현재0/미관찰/오래된 이력/이력 불가 렌더링, CPU 고정축·메모리 용량축·스토리지 최대 사용률 회귀를 추가했다. frontend 전체test/lint와 첫Node24 runtime build통과. 이후 모바일 필터2열/차트밀도·축 보완이 있어 최종Node24 build를 다시 실행하고 검증된 로컬18000에 반영한다. 전후 DB/secret 보존·마지막 화면 확인이 다음이다.

### 모니터링 중심 UI 반영 완료 / 재개 지점 (2026-09-20)

- 최종 `gjallar:acceptance-dense-ui-final-0920`, image `sha256:d18ce34b0ecc01a4e6829821e5b6289fb5f2f35eb98a4181cd3583784fc8fe6d`를 기존 loopback18000에 반영했다. 정상 upgrade exit0이며 이번에는 포트 대기/재개가 필요하지 않았다. 전후 DB count/digest와 기존 secret 지문 일치, 근거 `dense-ui-final-upgrade-before.json`/`dense-ui-final-upgrade-verified.json` 보존.
- 최종 VM 열 너비 수정 후 frontend 전체 test와 Node24 container test/lint/build 통과. 문서계약10passed, git diff --check 통과. Vite 주 chunk 약601kB 경고는 남으며 backend/client 변경은 없어 앞선 전체verify 결과와 구분한다.
- 배포된18000에서4개 실제추이·최근4개작업·노드표를 검증했다.1280x900에서 노드표 하단888px로 첫 화면에 들어온다. VM 목록의 Running과 Memory 잘림을 열 너비 조정 후 확인했다.320px 현황은 document scrollWidth320이며 상단 여섯 탭·작은 지표·차트가 반응형으로 배치된다. 최종 screenshot `dense-ui-final-dashboard-1280.png`와 개발 검토본을 보존했고 브라우저 viewport 임시값을 해제했다.
- PRD·architecture·roadmap과 현재 work에 정보 밀도 방향·조회 계약·결과를 갱신했다. 임시 dev5175만 종료하고 사용자 검토용18000·DB는 계속 둔다. 새 PVE 변경, 운영 DB 변경, commit/push는 없다. 전체 Goal은 미완료이며 M3 exact scope 승인 회신 확인과 남은 실환경 검증이 재개 지점이다.

### 전체 클러스터 노드 지원·통합 검증 착수 / 재개 지점 (2026-09-20)

- 사용자가 현재 연결된 클러스터 전체 노드 지원과 전체 테스트를 요청했다. fresh PVE GET `/nodes`에서 `yoonmanserver`, `yoonmanserver2`, `yoonmanserver3` 세 노드가 online이며 Gjallar에는 관리형 등록의 명시적 선택 때문에 `yoonmanserver3`만 노출됨을 재확인했다.
- 기존 토큰·CA와 import-plan → import-env → activate → 서버 재시작 경로로 해당 세 노드를 선택한다. 기존 VMID·스토리지·브리지·기능 범위는 보존한다. 새 노드 추가가 자동으로 모든 VM의 변경·삭제 권한을 선택하는 의미는 아니다. PVE 토큰/ACL·VM·호스트 설정은 이 묶음에서 변경하지 않는다.
- 로컬 전용 설치의 DB 백업과 기존 계정·설치·schema·Operation/secret 보존 근거를 남긴다. 연결 갱신 실패 시 기존 활성 revision을 유지하고 중간 등록 상태를 기록하며, 성공 후에는 모든 서버를 재시작한다. 임시 import 서버와 환경변수 복사본은 제거하고 기존 서비스로 복귀한다. 임의 SQL 수정·강제 activation·키 재발급은 하지 않는다.
- 완료 조건: PVE 원천과 Gjallar/API/CLI/UI의 세 노드 일치, 각 노드의 현황·선택된 스토리지/브리지·RRD 이력 조회, 범위 밖 대상 차단 유지, 전체 로컬/기준 container 검증과 문서 갱신. 실패는 원인별로 수정·재검증하며 M3~M6의 미실행 mutation 검증과 구분한다.

### 전체 노드 연결 갱신·실제 API/CLI 검증 / 재개 지점 (2026-09-20)

- 첫 import 검증은 이전 M2 정리에서 삭제한40000이 기존 `vmids`에 남아 있어 `PROXMOX_SCOPE_UNAVAILABLE`로 차단됐다. 등록 `6ec7d7a7-aa57-4d93-82e4-98de4cd92bfb`는 활성화되지 않았고 정상 cancel API로 종료했다. 기존 선택을 무조건 복제하지 않고 현재 존재하는7001만 남긴 새 계획을 검토했다.
- 등록 `d457509b-207b-44bb-872c-5fedd03f9cf2`가 verified→active를 완료했다. 노드는 세 대 모두, VM7001, nas-server, vmbr0/vmbr2와 기존 read/power/compute/disk/network/delete/console 기능을 유지한다. 기존 전용서비스로 재시작했고 임시 import 컨테이너·plaintext 복사본 제거를 확인했다. PVE 토큰/ACL·VM/호스트 변경은 없다.
- PVE 원천/API/CLI의 전체 노드·상태·CPU/메모리 용량·선택된 node별storage/bridge가 일치했다. 세 노드×hour/day/week/month/year 15개 RRD 조회가 모두 current/history available이며 완료된 공통 시각의 CPU 값이 직접PVE와 일치했다. 노드별nas-server와VM7001지표·작업알림·카탈로그·insights도 조회했다. 범위 밖 node/VM/storage403, 미로그인401을 확인했다.
- 유지보수는 node1/2의 `no_visible_targets`, node3의 `incomplete`를 확인했다. 이는 선택한 VM 범위의 관찰이며 실제클러스터에 VM이 없다는 뜻이 아니다. 모든 보고서의 `coverage=visible_qemu_only`, `node_shutdown_safe=false`를 확인했다. 전체VM조회/변경범위를 자동으로 확대하지 않았다.
- `cluster-scope-before.sql`과 before/verification JSON을 전용설치0600으로 보존했다. 원본7001의전체config(digest제외)·running, 테스트40000~40010부재,계정/감사·설치/schema·secret지문이 유지됐다. 새등록2건을제외한기존모든Operation checksum도일치한다. 첫실검증script는MiB반올림 대신내림을가정해실패했고제품의기존round계약에맞춰수정한뒤통과했다. 제품수치결함은아니다.
- 공통 `pnpm run verify` exit0: client257passed, backend1645passed/78skipped, frontend test/lint/build통과. 기준container전체검증과실제UI전체노드선택/모바일검증을마무리한다. 근거 `cluster-read-verification-0920.json`; 미실행M3~M6 mutation완료와구분한다.

### 전체 노드 통합 검증 완료 / 재개 지점 (2026-09-20)

- `pnpm run verify:container`도 exit0이며 backend1645passed/78skipped, client·frontend test/lint/build 단계를 통과했다. 기존 Vite 약601kB chunk 경고와 Alembic deprecation 경고는 남는다. 이번 노드 지원은 기존 다중 노드 구현의 관리형 선택 범위를 갱신한 것이며 제품 코드를 불필요하게 바꾸거나 재배포하지 않았다.
- 건너뛴78개도 별도 임시 PostgreSQL 17에서 실행했다. 첫 빈 DB 실행은 기본 schema가 필요한5개에서 missing table로 실패했고, 새 전용 DB에0042까지 migration 후78passed/skip0으로 재검증했다. 이는 테스트 준비 오류이며 제품 버그로 처리하지 않았다. 초기화 순서를development에 명시했다. 두 임시 tmpfs DB·컨테이너·secret은 정리했고 기존 설치DB/다른 테스트컨테이너는 보존했다.
- IAB 실제18000에서 3/3 online·세 노드 표, 노드별 추이 선택과 서로 다른 실제 메모리 값, 상세 모니터링으로 선택 노드 전달, 대상 변경 시 이전 차트 제거와 명시적 조회, node2 유지보수의 선택 범위 안내를 확인했다.320px에서 세 노드 선택과 document scrollWidth320,1280px 현황을 확인했고 임시 viewport를 해제했다. `cluster-three-nodes-dashboard-0920.png`를 보존했다.
- development의 다중 노드 갱신/삭제된 VMID 처리/선택 범위 해석/PG 검사 절차와 roadmap M1·M4·M6 검증 상태를 갱신했다. 문서계약10passed와diff검사를 수행했다. 커밋·푸시 없음.
- 전체 노드 조회·선택과 이번 자동/실제 읽기 검증은 완료다. 전체VM·storage·bridge를 무조건 선택한 상태가 아니며 VM7001/nas-server/vmbr0·vmbr2 범위를 유지한다. M3 제작·배포, M5 백업·복원, M6 이동·호스트변경의 실제 mutation 및 마지막 신규PVE로그인/발급 검증은 아직 남아 있다. 다음 재개 시 위 M3의40001 exact scope 회신과 최신 연결을 확인하며, 이 결과만으로 Goal을 완료 처리하지 않는다.

### 클러스터 전체 현황·노드 상세 분리 착수 / 재개 지점 (2026-09-20)

- 최신 사용자 요청은 운영 현황에서 모든 연결 노드를 함께 보여주고 개별 상세를 별도 탭으로 분리하며 여백을 유용한 정보로 채우는 것이다. 기존 screenshot·화면·컴포넌트를 기준으로 전체 현황의 하위 탐색을 `클러스터 전체 / 노드 상세`로 구성한다. 요약 행·노드 비교표·전체 추이·주의 항목·최근 작업을 밀도 있게 배치한다.
- 기존 읽기 API의 노드별 보고서를 합성한다. CPU는 현재 관찰한 노드 CPU 용량으로 가중 평균, 메모리/네트워크는 모든 노드의 같은 시각 관찰값만 합산하며 결측/실패를0으로 대체하지 않는다. 네트워크 합계는 노드 간 내부 트래픽도 포함한다. 공유 storage 용량은 중복 합산하지 않는다. VM·자원 선택 범위와 권한은 유지한다.
- `/`와 기존 모니터링 URL을 보존하고 호환 가능한 `/nodes` 상세 진입을 추가한다. 완료 조건은 집계·결측·대상 변경 회귀, frontend test/lint/Node24 build, 실제3노드 화면·모바일·탭 이동 확인과 문서 갱신이다. 검증한 동일schema UI이미지를 기존 로컬18000에 반영하고 DB/secret 보존을 대조한다. 새 PVE mutation·DB migration·commit/push는 없다.

### 클러스터 집계·상세 탭 구현과 화면 검증 / 재개 지점 (2026-09-20)

- `/`의6개 요약 지표 행(노드·가중CPU·전체메모리·선택VM·최대storage·Red진단), 위쪽 전체노드 비교표, 모든노드의4개 추이, 운영확인사항·최근작업으로 재배치했다. `/nodes`는 기존MetricsPage의node 전용 모드로 자원 구성·5개기간·시각별값·임계 이력을 제공한다. 노드 링크로 대상이 전달되고 기존 `/insights/metrics`의VM/storage선택은 유지한다. 사용처가 없어진 이전단일노드 DashboardTrends는 ClusterTrends로 대체했다.
- `clusterMetrics`의 가중집계·같은시각정렬·결측/null/0·잘못된대상/기간·해상도차이·최대4동시요청·취소를 회귀로 검증했다. inventory 전체조회실패·offline·CPU관찰누락도 합계로 오인하지 않는다. 초기회귀실패는새shell/한글표현에따른source-contract갱신과ESM import확장자로 해결했고frontend전체test/lint가 통과했다.
- 실제3노드48logical CPU/메모리179.2GiB 중약93.8GiB 사용, 전체추이3/3관찰을 확인했다. 비교표node2→상세와node3변경/조회, 상세자원 구성·320px overflow없음을확인했다. 전체화면320px에서표헤더가세로로눌리는문제를확인해table최소폭+내부가로스크롤로수정했다. 이마지막수정후frontend재검증과Node24최종이미지빌드/반영을마무리한다. 공통verify·기준container검증도진행중이다.

### 클러스터 전체 현황 반영 완료 / 재개 지점 (2026-09-20)

- 공통 `pnpm run verify`와 기준 `pnpm run verify:container` exit0: client257passed, backend1645passed/78skipped, frontend test/lint/build 통과. 최종 모바일 표 수정 뒤 frontend test/lint와 별도 Node24 최종 이미지 test/lint/build도 통과했다. PostgreSQL 전용78개는 앞선 전체 노드 검증에서 모두 통과했으며 이번 frontend 변경으로 재실행하지 않았다. 기존 Vite chunk 크기·Alembic deprecation 경고는 남는다.
- 최종 `gjallar:acceptance-cluster-overview-0920`, image `sha256:0833028ff5e16e2f1e2e8daf14117ab9576c27ce26249e9eaa99b22b7bb255cc`를 정상 upgrade로 기존18000에 반영했다. 전후 DB count/digest와 기존 secret 지문 일치. 근거 `cluster-overview-upgrade-before.json`·`cluster-overview-upgrade-verified.json`은 전용 설치 디렉터리에 보존했다.
- 배포된18000에서 실제3/3노드·48CPU·179.2GiB 전체용량·약93.8GiB 사용과4개 집계 차트를 확인했다. node2 비교표 링크가 해당 상세로 연결되고16logicalCPU·59.7GiB·선택storage/bridge를 보여준다. 개발 화면에서 하루 추이1440관찰값도 확인했다.320px 배포 화면은 document폭320, 표760/컨테이너294로 페이지 overflow 없이 표 내부에서만 가로스크롤한다. 브라우저 오류로그 없음. `cluster-overview-final-0920.png`를 보존했다.
- PRD·architecture·roadmap·development에 전체/상세 탐색과 집계 계약·사용 절차를 반영했다. 임시 dev5175를 종료하고 viewport를 해제했으며 사용자 검토용18000·DB는 유지한다. PVE mutation·DB migration·commit/push 없음.
- 이번 UI 요청은 구현·자동검증·실제 화면 확인 완료다. 전체 Goal의 M3 제작/배포, M5 백업/복원, M6 이동/호스트변경 및 마지막 신규PVE로그인/발급 실검증은 여전히 남는다. 위 M3의40001 exact scope 승인 회신 확인과 최신 연결 확인을 다음 재개 지점으로 유지하며 Goal 완료로 처리하지 않는다.
