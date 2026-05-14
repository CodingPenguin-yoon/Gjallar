# VM lifecycle action 안전장치

> Historical note:
> This `docs/archive/features` file is historical implementation/planning context, not current product source of truth or current implementation status.
> Current MVP product source of truth is [`../../product/drs-advisor/`](../../product/drs-advisor/README.md); current implemented status is [`../../current/README.md`](../../current/README.md).
> Existing-VM lifecycle action material here is historical context. DRS Advisor execution must follow `../../product/drs-advisor/` final pre-check, approval, Proxmox task tracking, and reconciliation rules.

## 요약

Gjallar의 VM lifecycle action 안전장치는 운영자가 VM 목록이나 VM 상세 영역에서 `start`, `shutdown`, `stop`, `reboot`, `terminate` 같은 조작을 실행할 때 **대상 VM과 조작 위험도를 다시 확인**하게 만드는 기능이다.

이 기능의 목적은 단순히 버튼 클릭 전에 팝업 하나를 띄우는 것이 아니다. Gjallar가 앞으로 Proxmox 운영 콘솔이 되려면, VM 조작이 다음 조건을 만족해야 한다.

```text
1. 어떤 VM에 실행되는지 명확해야 한다.
2. 이 조작이 얼마나 위험한지 알 수 있어야 한다.
3. 되돌릴 수 없는 조작은 실수로 실행되면 안 된다.
4. 취소/실행 결과가 운영 로그에 남아야 한다.
```

## 왜 필요했나

### 1. Gjallar의 방향이 “VM 생성 UI”가 아니라 “운영 콘솔”이기 때문

현재 Gjallar의 제품 방향은 다음이다.

```text
Proxmox VM Operations & Monitoring Console
```

운영 콘솔은 단순히 VM을 보여주는 화면이 아니라, 운영자가 실제 인프라에 영향을 주는 조작을 수행하는 곳이다.

특히 VM lifecycle action은 다음처럼 실제 서비스 영향이 크다.

| Action | 영향 |
|---|---|
| start | VM을 켜고 리소스를 사용하기 시작함 |
| shutdown | guest OS 종료 요청, 서비스 중단 발생 |
| stop | 강제 전원 차단에 가까워 데이터 손상 가능성 있음 |
| reboot | 서비스 재시작/중단 발생 |
| terminate | VM 종료 후 삭제, Gjallar UI 기준 되돌릴 수 없음 |

그래서 Gjallar가 “매일 켜놓고 쓰는 운영 콘솔”이 되려면 lifecycle action에 실수 방지 장치가 필요하다.

### 2. Proxmox API는 강력하지만, UI 레벨의 운영 맥락은 직접 만들어야 함

Proxmox 자체는 VM 조작 API를 제공한다. 하지만 API는 다음을 대신 판단해주지 않는다.

- 이 VM이 정말 사용자가 의도한 VM인지
- 지금 클릭한 action이 안전한지
- 운영자에게 어떤 위험 문구를 보여줘야 하는지
- 삭제 같은 조작에 추가 확인이 필요한지
- 사용자가 취소했을 때 운영 로그에 어떻게 남길지

Gjallar의 역할은 Proxmox 위에 이런 운영 맥락을 얹는 것이다.

### 3. VM 목록과 detail drawer에 action이 같이 들어갔기 때문

직전 작업에서 VM detail drawer가 추가됐다. 이제 사용자는 VM 목록 row뿐 아니라 detail 영역에서도 lifecycle action을 실행할 수 있다.

즉 action 진입점이 늘어났기 때문에, action 실행 전에 공통 확인 정책을 두는 것이 필요했다.

## 구현 목표

이번 작업의 구현 목표는 다음이었다.

```text
위험도별 lifecycle action 정책을 한 곳에 모으고,
InstanceList와 VM detail drawer에서 같은 정책을 사용하게 한다.
```

세부 목표:

1. action별 위험도 정의
2. action별 확인 메시지 생성
3. terminate는 VM 이름을 직접 입력해야 진행되도록 처리
4. 사용자가 취소하면 실제 API 호출을 하지 않음
5. 취소 사실을 UI log에 남김
6. 정책 로직은 테스트 가능한 utility로 분리

## 구현 파일

### Frontend utility

```text
frontend/src/utils/lifecycleSafety.js
```

역할:

- action별 위험도 정책 정의
- VM 표시 이름 생성
- confirmation message 생성
- typed confirmation 필요 여부 판단

주요 함수:

```text
getInstanceDisplayName(instance)
getLifecycleActionPolicy(action)
requiresTypedConfirmation(action)
buildLifecycleConfirmation({ instance, action })
```

### Frontend test

```text
frontend/tests/lifecycleSafety.test.mjs
```

역할:

- action 정책이 의도대로 나오는지 검증
- terminate만 typed confirmation을 요구하는지 검증
- 확인 메시지에 VM 이름/node/vmid/status/risk 설명이 포함되는지 검증

### UI integration

```text
frontend/src/components/InstanceList.jsx
```

변경 내용:

- lifecycle action 실행 전 `confirmLifecycleAction(instance, action)` 호출
- 일반 action은 `window.confirm()` 사용
- terminate는 `window.prompt()`로 VM 이름을 직접 입력해야 진행
- 사용자가 취소하면 API 호출 없이 log에 취소 메시지 남김
- VM 목록과 detail drawer action 모두 같은 handler를 사용하므로 동일 정책 적용

## action별 정책

### start

```text
severity: low
confirmation: 일반 confirm
```

의미:

- VM을 켠다.
- 상대적으로 안전하지만 리소스 사용과 서비스 시작이 발생할 수 있다.

확인 메시지 핵심:

```text
Power on the VM. This is usually safe but may start services or consume node resources.
```

### shutdown

```text
severity: medium
confirmation: 일반 confirm
```

의미:

- guest OS에 정상 종료 요청을 보낸다.
- VM 안의 서비스가 내려간다.

확인 메시지 핵심:

```text
Ask the guest OS to shut down gracefully. Services inside the VM will become unavailable.
```

### reboot

```text
severity: medium
confirmation: 일반 confirm
```

의미:

- VM을 재시작한다.
- 서비스 중단이 발생한다.

확인 메시지 핵심:

```text
Restart the VM. Running services will be interrupted until the VM is back online.
```

### stop

```text
severity: high
confirmation: 일반 confirm
```

의미:

- 강제 전원 차단에 가까운 조작이다.
- 정상 shutdown보다 위험하다.
- 쓰기 중인 데이터나 서비스 상태에 문제가 생길 수 있다.

확인 메시지 핵심:

```text
Force power off the VM. This can interrupt writes and may cause application or filesystem issues.
```

### terminate

```text
severity: critical
confirmation: typed confirmation
```

의미:

- VM을 종료하고 필요하면 강제 stop 후 삭제한다.
- Gjallar UI 기준 되돌릴 수 없는 조작이다.

확인 방식:

```text
VM 이름을 정확히 입력해야 진행된다.
```

예시:

```text
Type exactly "web-01" to continue.
```

이유:

- terminate는 실수 비용이 가장 크다.
- 일반 confirm은 습관적으로 누르기 쉽다.
- VM 이름을 직접 입력하게 하면 사용자가 대상 VM을 한 번 더 인지하게 된다.

## 확인 메시지에 포함되는 정보

모든 confirmation에는 다음 정보가 들어간다.

```text
Target: VM 이름
Location: node/vmid
Current status: 현재 상태
Risk: action별 위험 설명
```

예시:

```text
Stop VM web-01?

Force power off the VM. This can interrupt writes and may cause application or filesystem issues.

Target: web-01
Location: pve-a/101
Current status: running
Confirm only if this is the intended VM.
```

terminate 예시:

```text
Terminate VM web-01?

Shutdown, force stop if needed, and permanently delete the VM. This action cannot be undone from Gjallar.

Target: web-01
Location: pve-a/101
Current status: running
Type exactly "web-01" to continue.
```

## 동작 흐름

### 일반 lifecycle action

대상:

```text
start / shutdown / stop / reboot
```

흐름:

```text
사용자 버튼 클릭
  ↓
buildLifecycleConfirmation()으로 action별 메시지 생성
  ↓
window.confirm() 표시
  ↓
사용자가 취소하면 API 호출하지 않음
  ↓
사용자가 확인하면 performInstanceAction() 호출
  ↓
결과 log 출력 후 inventory refresh
```

### terminate action

대상:

```text
terminate
```

흐름:

```text
사용자 Terminate 버튼 클릭
  ↓
buildLifecycleConfirmation()으로 critical 메시지 생성
  ↓
window.prompt() 표시
  ↓
VM 이름을 정확히 입력하지 않으면 API 호출하지 않음
  ↓
정확히 입력하면 terminateInstance() 호출
  ↓
결과 log 출력 후 inventory refresh
```

## 기존 방식과 달라진 점

### 기존

- terminate만 2번 confirm이 있었다.
- start/shutdown/stop/reboot는 버튼 클릭 후 바로 API 호출로 이어졌다.
- action별 위험도/설명 문구가 공통 정책으로 정리되어 있지 않았다.
- VM 목록 action과 detail action이 늘어날 경우 정책이 흩어질 위험이 있었다.

### 변경 후

- 모든 lifecycle action 전에 확인 단계가 생겼다.
- 위험도 정책이 `lifecycleSafety.js`로 분리됐다.
- terminate는 confirm 2번이 아니라 VM 이름 typed confirmation으로 강화됐다.
- 사용자가 취소하면 API 호출 없이 log에 남긴다.
- VM 목록과 detail drawer가 같은 action handler를 사용한다.

## 테스트

추가한 frontend 테스트:

```bash
node frontend/tests/lifecycleSafety.test.mjs
```

검증 내용:

- VM 표시 이름 fallback 동작
- action별 severity
- terminate만 typed confirmation 요구
- stop 확인 메시지에 force power off 위험 설명 포함
- 확인 메시지에 node/vmid 포함
- terminate 확인 메시지에 permanently delete 설명 포함

전체 검증:

```bash
node frontend/tests/inventorySummary.test.mjs
node frontend/tests/lifecycleSafety.test.mjs
cd frontend && npm run lint
cd frontend && npm run build
cd backend && PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
cd backend && .venv/bin/python -c 'from app.main import app; print(app.title)'
python3 -m compileall backend/app backend/tests
git diff --check
```

결과:

```text
통과
```

## 이번 구현에서 의도적으로 하지 않은 것

### 1. 별도 modal 컴포넌트는 아직 만들지 않음

현재는 browser 기본 `confirm/prompt`를 사용한다.

이유:

- MVP 단계에서는 기능 정책과 안전 흐름을 먼저 고정하는 것이 중요하다.
- custom modal은 디자인 작업량이 크다.
- 이후 task/log UX 정리 또는 design system 정리 때 modal로 교체할 수 있다.

향후 개선:

```text
window.confirm/prompt → Gjallar 공통 ConfirmDialog 컴포넌트
```

### 2. RBAC/권한 정책은 아직 넣지 않음

현재는 frontend confirmation 중심이다.

향후 운영 환경에서는 backend 권한도 필요하다.

예:

```text
viewer: action 불가
operator: start/shutdown/reboot 가능
admin: stop/terminate 가능
```

### 3. maintenance window 검사는 아직 넣지 않음

현재는 사용자가 직접 확인한다.

향후에는 다음 정책을 붙일 수 있다.

```text
업무시간 중 reboot/stop/terminate 경고 강화
production tag VM은 추가 승인 필요
owner 없는 VM은 terminate 제한
```

## 향후 확장 방향

이 기능은 Phase 2의 governance/risk dashboard와 연결될 수 있다.

예:

- backup 없는 VM terminate 시 강한 경고
- production tag VM reboot 시 추가 승인
- guest agent 없는 VM shutdown 시 stop fallback 가능성 안내
- 오래된 snapshot 있는 VM delete 전 snapshot 확인
- task log에 action requester/target/risk level 기록

즉 이번 작업은 단순 confirm 추가가 아니라, Gjallar의 `Govern → Act` 축으로 확장하기 위한 기본 안전 레이어다.

## 관련 commit

```text
7e4724c Add VM inventory detail drawer
```

이번 lifecycle safety 작업은 다음 commit으로 별도 기록한다.
