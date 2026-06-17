# Gjallar External Boundaries PRD

> Current MVP product source of truth is `docs/product/drs-advisor/`. If this document conflicts with that folder, `docs/product/drs-advisor/` wins.
> Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.
> This create-first material is historical/supporting capability context only. It must not define the next MVP success line or implementation order.

## 0. 목적

이 문서는 Gjallar가 외부 시스템과 어떻게 연결될 수 있는지의 최소 경계를 정의한다.
목적은 Gjallar가 외부 앱 배포 도구의 부속품으로 변하는 것을 막는 것이다.

## 1. 원칙

> Gjallar가 먼저 VM/Proxmox 계층을 안정적으로 소유한다. 외부 연계는 그 다음이다.

외부 시스템은 Gjallar의 consumer일 수 있지만, Gjallar의 제품 정체성을 결정하지 않는다.

## 2. Gjallar의 절대 소유 영역

- Proxmox credential 사용
- Proxmox API 호출
- VM 생성/전원/상태/readiness
- node/storage/network/profile/template inventory
- preflight/risk/smoke 결과
- VM runtime target 등록 여부

외부 시스템은 Proxmox를 직접 만지지 않는다.

## 3. Gjallar의 비소유 영역

- 앱 repo 분석
- 앱 Docker image build
- 앱 deploy/restart/log/health
- 앱 DB migration
- 앱 rollback
- 프로젝트별 배포 이력

이 영역은 Gjallar PRD에서 설계하지 않는다.

## 4. Runtime Target 개념

Runtime Target은 “외부 앱 운영 도구가 나중에 사용할 수 있도록 Gjallar가 후보로 표시한 VM”이다.

이 create-first material에서는 VM 생성이 우선이었다.
현재 DRS Advisor MVP에서 Runtime Target은 **active 실행 대상 확정**이 아니라 **candidate/readiness 표시** context로만 남으며, 다음 구현 순서를 정하지 않는다.

candidate 조건:

- VM이 Gjallar에서 생성 또는 등록됨
- static IP 또는 안정적 접근 주소가 있음
- 사용자가 runtime target 등록을 명시적으로 선택함

candidate_ready 조건:

- static IP 또는 안정적 접근 주소가 있음
- guest-agent/SSH/bootstrap/smoke 통과
- risk가 red가 아님

Runtime Target은 자동 생성하지 않는다.
Create VM wizard에서 사용자가 체크한 경우에만 후보가 된다.
MVP에서는 `active` 자동 전환을 하지 않는다. `active` 정책은 2차에서 별도 확정한다.

## 5. 외부 read-only API

MVP 후반부 또는 Phase 6에 아래 read-only API를 제공한다.

- runtime target 목록
- 특정 VM readiness/risk
- 특정 VM의 최근 smoke 결과
- blocked reason

외부 API는 destructive action을 열지 않는다.
전원 제어, 삭제, 스냅샷, 리소스 변경은 Gjallar UI/API의 안전 정책을 따른다.

## 6. 현재 PRD에서 제외하는 것

- 외부 앱 배포 UI
- 외부 project registry
- 앱 로그/헬스 화면
- 앱 rollback 화면
- 외부 도구 전용 승인 큐

필요하면 나중에 별도 PRD에서 다룬다.

## 7. Heimdall 위치

Heimdall은 가능한 외부 consumer 중 하나다.
Gjallar PRD에서는 Heimdall을 중심으로 설계하지 않고, “readiness/risk를 읽는 외부 시스템”으로만 취급한다.

과거 create-first MVP 경계는 아래처럼 정의했다. 현재 DRS Advisor 방향과 충돌하면 `docs/product/drs-advisor/`가 우선한다.

```text
Gjallar:
- VM candidate/readiness/risk를 read-only API로 제공
- Proxmox actual state를 읽고 운영 판단/정책/감사/작업 state를 저장
- Heimdall registry에 직접 write 하지 않음

Heimdall:
- deploy target registry를 소유
- 배포 전 Gjallar readiness/risk를 조회할 수 있음
- Proxmox를 직접 만지지 않음

Hermes/user:
- Gjallar candidate를 보고 Heimdall target으로 승격할지 결정
```

즉 MVP는 느슨한 연결이다.
자동 등록, 공용 runtime-target manifest, active target 승격 정책은 2차에서 별도 재검토한다.
