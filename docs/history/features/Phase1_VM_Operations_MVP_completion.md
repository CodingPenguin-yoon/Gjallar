# Phase 1 VM Operations MVP 완성도 개선

> Historical note:
> This `docs/history/features` file is historical implementation/planning context, not current product source of truth or current implementation status.
> Current MVP product source of truth is [`../../product/prd/drs-advisor/`](../../product/prd/drs-advisor/README.md); current implemented status is [`../../product/status/current.md`](../../product/status/current.md).
> This create-first material is historical/supporting capability context only. It must not define the next MVP success line or implementation order.

## 한 줄 요약

이번 작업은 Gjallar의 Phase 1 남은 항목을 묶어서, VM 운영자가 실제로 쓰는 흐름을 더 자연스럽게 만들기 위한 개선이다.

```text
VM 생성 준비 → provisioning 요청 → task/log 추적 → node/storage 상태 확인
```

## 왜 필요했는가

Gjallar의 방향은 단순히 “VM 생성 버튼이 있는 화면”이 아니다.

Gjallar는 Proxmox 위에서 운영자가 매일 켜놓고 보는 운영 콘솔이 되어야 한다.

운영 콘솔에서 중요한 질문은 다음과 같다.

1. 지금 어떤 VM을 만들려고 하는가?
2. 어떤 node/template/storage/network/IP 설정으로 만들 것인가?
3. 생성 요청을 보낸 뒤 어디서 진행 상태를 볼 수 있는가?
4. 실패하면 어떤 단계에서 실패했는가?
5. VM을 올릴 node나 storage 쪽에 위험 신호는 없는가?

이전 상태에서는 inventory/detail/lifecycle safety는 좋아졌지만, VM 생성 이후의 작업 추적과 monitoring 쪽 연결감이 아직 약했다.

그래서 이번 작업에서는 Phase 1 남은 항목을 아래 세 축으로 정리했다.

```text
1. Provisioning UX
2. Task/Log UX
3. Node/Storage Monitoring UX
```

---

## 1. VM 생성 flow UX를 provisioning 기준으로 정리

### 기존 문제

기존 UI에는 아직 `Launch`, `Deploy`, `Infrastructure Control Plane` 같은 오래된 표현이 남아 있었다.

Gjallar는 GitLab/staging/app deploy 도구가 아니므로, 사용자가 보는 표현도 다음 방향으로 맞춰야 한다.

```text
Deploy app X
Launch infra X
Provision VM O
VM Operations Console O
```

### 변경 내용

#### 1. 화면 타이틀 정리

기존:

```text
Infrastructure Control Plane
```

변경:

```text
Gjallar VM Operations Console
```

#### 2. 생성 버튼 정리

기존:

```text
Launch Instance
Launching...
```

변경:

```text
Provision VM
Provisioning...
```

#### 3. `/api/provision` 신규 endpoint 추가

기존에는 VM 생성 요청도 compatibility 이름인 `/api/deploy`를 사용했다.

이번 작업에서 신규 endpoint를 추가했다.

```text
POST /api/provision
```

그리고 프론트엔드 신규 호출은 `/api/provision`을 사용하도록 바꿨다.

단, 기존 호환성을 위해 아래 endpoint는 유지한다.

```text
POST /api/deploy
```

즉 현재 구조는 다음과 같다.

```text
신규 UI/문서: /api/provision
기존 호환:   /api/deploy
```

#### 4. Provisioning Review 추가

VM 생성 마지막 단계에 review panel을 추가했다.

사용자는 `Provision VM` 버튼을 누르기 전에 다음을 한눈에 확인할 수 있다.

```text
Target
- VM 이름
- node
- template

Resources
- CPU
- memory
- storage

Network
- DHCP/static
- bridge
- requested IP

Bootstrap
- Ansible packages 개수
- Ansible roles 개수
```

### 구현 파일

```text
frontend/src/utils/provisioningSummary.js
frontend/tests/provisioningSummary.test.mjs
frontend/src/components/CreateInstanceWizard.jsx
frontend/src/App.jsx
frontend/src/services/api.js
backend/app/domains/deploy/router.py
backend/tests/test_provision_route.py
```

### 구현 방식

UI component 안에 조건문을 계속 늘리지 않고, review 계산 로직을 utility로 분리했다.

```text
buildProvisioningSummary(config)
```

이 함수는 다음 값을 계산한다.

```text
ready 여부
missing required fields
target node/template/storage
resources
network mode/IP/gateway
bootstrap enabled/packages/roles
```

이렇게 분리한 이유는 다음과 같다.

1. UI가 복잡해져도 summary 계산 로직을 테스트할 수 있다.
2. 나중에 provisioning 전 확인 정책을 강화할 때 같은 함수를 재사용할 수 있다.
3. component가 “화면 표시”에 집중할 수 있다.

---

## 2. Task/Log UX 정리

### 기존 문제

VM 생성 요청 이후에는 Task Board로 이동하지만, 운영자가 바로 알고 싶은 정보가 부족했다.

운영자는 보통 다음을 먼저 본다.

```text
지금 진행 중인 작업이 몇 개인가?
실패한 작업이 있는가?
성공/완료된 작업은 몇 개인가?
이 task가 어느 VM/node에 대한 것인가?
```

### 변경 내용

#### 1. Task Board summary cards 추가

Task Board 상단에 요약 카드를 추가했다.

```text
Total
Live
Done
Failed
Archived
```

이제 task 목록을 모두 읽기 전에 전체 상태를 볼 수 있다.

#### 2. task target 표시 개선

task 표시 이름을 다음 metadata 기준으로 더 명확히 만든다.

우선순위:

```text
vm_name
server_name
task id 기반 fallback
```

node 표시 우선순위:

```text
vm_node
server_id
node
```

표시 예:

```text
web-01 @ pve-01
```

#### 3. Task detail에 Provisioning Target 섹션 추가

Task detail panel에서 raw metadata만 보여주지 않고, 운영자가 보는 항목을 별도로 정리했다.

```text
Requested Name
Node
VMID
VM Name
Template
Storage
Networks
Requested IP
Packages
Roles
```

raw metadata는 그대로 보존하지만, 먼저 읽어야 할 정보는 “Provisioning Target”으로 분리했다.

### 구현 파일

```text
frontend/src/utils/taskBoardSummary.js
frontend/tests/taskBoardSummary.test.mjs
frontend/src/components/TaskBoard.jsx
```

### 구현 방식

Task Board 계산 로직을 utility로 분리했다.

```text
buildTaskBoardSummary(tasks)
describeTaskTarget(task)
pickProvisioningMetadata(metadata)
```

이렇게 한 이유는 다음과 같다.

1. task status 기준이 여러 component에 흩어지는 것을 줄인다.
2. task metadata 표시 규칙을 테스트할 수 있다.
3. 향후 lifecycle action task, backup task, risk scan task가 추가되어도 같은 패턴으로 확장할 수 있다.

---

## 3. Node/Storage monitoring 개선

### 기존 문제

Monitoring 화면은 node별 CPU/memory/storage 사용률을 보여주지만, 운영자가 먼저 봐야 하는 “위험 신호 요약”이 약했다.

운영자는 모든 node card를 하나씩 읽기 전에 아래를 먼저 알고 싶다.

```text
온라인 node가 몇 개인가?
critical signal이 있는가?
warning signal이 있는가?
storage가 위험한 곳이 있는가?
```

### 변경 내용

#### 1. Monitoring summary cards 추가

Monitoring 화면 상단에 cluster 상태 요약을 추가했다.

```text
Nodes Online
Critical Signals
Warnings
Refresh interval
```

#### 2. Node/Storage signal list 추가

CPU/memory/storage 사용률과 node status를 기반으로 warning/critical signal을 만든다.

기준:

```text
>= 90%: critical
>= 70%: warning
그 외: healthy
```

node가 online이 아니면 critical signal로 본다.

표시 예:

```text
pve-01/local 91.0%
pve-02 is offline
pve-02 CPU 95.0%
```

### 구현 파일

```text
frontend/src/utils/monitoringSignals.js
frontend/tests/monitoringSignals.test.mjs
frontend/src/components/MonitoringDashboard.jsx
```

### 구현 방식

monitoring signal 계산을 utility로 분리했다.

```text
buildMonitoringSummary(nodes)
getResourceTone(percent)
toNumber(value)
```

이렇게 한 이유는 다음과 같다.

1. threshold 정책을 component에서 분리한다.
2. 운영 리스크 대시보드 Phase 2에서 같은 signal 로직을 확장할 수 있다.
3. node/storage risk 표시 기준을 테스트로 고정할 수 있다.

---

## 4. API compatibility 정리

### 변경 전

```text
frontend → POST /api/deploy
```

### 변경 후

```text
frontend → POST /api/provision
```

호환 endpoint:

```text
POST /api/deploy
```

### 왜 `/api/deploy`를 바로 삭제하지 않았나

기존 코드나 외부 호출이 아직 `/api/deploy`를 사용할 수 있기 때문이다.

그래서 이번 단계에서는 다음 전략을 선택했다.

```text
신규 경로 추가
프론트는 신규 경로로 이동
기존 경로는 compatibility alias로 유지
```

이 방식은 기능을 깨지 않으면서 제품 용어를 정리하는 점진 migration이다.

---

## 5. 테스트와 검증

이번 작업은 테스트를 먼저 추가하고, 실패를 확인한 뒤 구현했다.

새로 추가한 frontend tests:

```text
frontend/tests/provisioningSummary.test.mjs
frontend/tests/taskBoardSummary.test.mjs
frontend/tests/monitoringSignals.test.mjs
```

새로 추가한 backend test:

```text
backend/tests/test_provision_route.py
```

최종 검증:

```text
node frontend/tests/inventorySummary.test.mjs
node frontend/tests/lifecycleSafety.test.mjs
node frontend/tests/provisioningSummary.test.mjs
node frontend/tests/taskBoardSummary.test.mjs
node frontend/tests/monitoringSignals.test.mjs
cd frontend && npm run lint
cd frontend && npm run build
cd backend && PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"
python3 -m compileall backend/app backend/tests
git diff --check
```

결과:

```text
전부 통과
backend unittest: 4 tests 통과
frontend build/lint 통과
backend app title: Gjallar VM Operations API
```

Redis 미연결 경고는 기존과 동일하게 출력될 수 있지만, app import와 tests는 통과한다.

---

## 6. 이번 작업 후 Phase 1 상태

Phase 1의 기존 완료 항목:

```text
[x] Proxmox inventory 화면 정보 구조 정리
[x] VM detail drawer/page 1차 구현
[x] VM lifecycle action 안전장치 강화
```

이번 작업 완료 항목:

```text
[x] VM 생성 flow UX를 provisioning 기준으로 더 정리
[x] task/log UX 정리
[x] node/storage monitoring 개선
```

즉 Phase 1 VM Operations Console MVP의 주요 항목은 1차 완료 상태다.

---

## 7. 남은 한계와 다음 개선 후보

이번 작업은 “MVP 완성도 개선”이며, 아직 다음 고도화가 남아 있다.

### UI smoke test

아직 실제 브라우저에서 dev server를 띄워 클릭 흐름을 직접 확인하지는 않았다.

다음에 하면 좋은 검증:

```text
1. dev server/backend 실행
2. Create VM 화면에서 review panel 확인
3. Provision VM 클릭 후 Task Board 이동 확인
4. Task detail의 Provisioning Target 확인
5. Monitoring summary/signal 확인
```

### Backend server-side safety

현재 lifecycle safety는 frontend 중심이다.

향후 destructive action은 backend에서도 confirmation token을 요구하는 방식이 좋다.

### Task/log와 lifecycle action 연결

현재 Task Board는 provisioning task 중심이다.

향후 lifecycle action도 backend task로 남기면 다음이 가능해진다.

```text
누가 어떤 VM에 reboot/stop/terminate를 요청했는가?
언제 성공/실패했는가?
관련 Proxmox UPID는 무엇인가?
```

### Phase 2 risk dashboard

이번 monitoring signal은 Phase 2 risk dashboard의 기반이다.

다음 후보:

```text
backup 누락 VM
오래된 snapshot
qemu guest agent 없음/미응답
storage usage 위험
owner/environment/tag 누락
장기 stopped VM
```
