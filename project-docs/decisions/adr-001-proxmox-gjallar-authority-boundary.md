# ADR-001: Proxmox와 Gjallar의 권한 경계 및 실행 모드

- 상태: `ACCEPTED`
- 날짜: `2026-07-20`
- 결정자: `사용자`
- 대체하는 ADR: `없음 — 이전 ADR-001은 미승인 초안이므로 문서 초기화에서 폐기`
- 대체된 ADR: `없음`

## 배경

Gjallar는 Proxmox GUI를 day-2 운영의 기본 진입점에서 대체하려 한다. 그러나 Proxmox 자체 actual state와 task execution을 복제하면 정합성·복구 위험이 커지고, arbitrary shell을 제공하면 control plane의 권한·감사 경계가 무너진다. 동시에 Proxmox GUI로 해결하기 어려운 작업을 `qm`으로 수행할 수 있는 안전한 운영 경험이 제품 차별점이 된다.

## 결정 기준

- actual state와 실행 결과의 단일 권위
- API와 manual 작업의 중복 mutation 방지
- 승인, 검증, evidence, reconciliation 가능성
- operator usability와 Proxmox GUI 의존 축소
- secret·권한·arbitrary command 위험 억제
- 현재 API/token 구조에서 점진 구현 가능성

## 검토한 선택지

### 1순위: Proxmox actual-state authority + Gjallar verified operation authority

- 구조: Proxmox가 actual state와 low-level task를 소유하고, Gjallar가 operation intent, policy, approval, verification, evidence를 소유한다.
- 실행 모드: `managed_api`, `guided_manual`, `observe_only`.
- guided manual: allowlist 기반 `qm`/PVE UI instruction bundle을 발급하고 operator가 외부에서 실행한 뒤 Gjallar가 API로 after-state를 검증한다.
- 장점: 이중 source of truth를 만들지 않으면서 API로 안 되는 작업까지 같은 안전 lifecycle에 포함한다.
- 단점: 일부 작업은 완전 자동화가 아니며 manual handoff와 verification UX가 필요하다.
- 전환 위험: 기존 기능별 성공/실패 의미를 공통 operation taxonomy로 바꿔야 한다.

### 대안 1: Proxmox GUI/API wrapper

- 구조: 기존 PVE 기능을 최대한 그대로 재노출한다.
- 적합한 경우: 단순한 통합 UI가 목표일 때.
- 장점: 빠른 기능 확장.
- 단점: 제품 차별점과 evidence ownership이 약하고 GUI parity 경쟁이 된다.
- 추천안보다 낮은 이유: 운영 간소화와 검증 가능한 manual workflow 요구를 해결하지 못한다.

### 대안 2: Embedded raw shell 또는 backend SSH executor

- 구조: Gjallar 안에서 임의 `qm` command를 직접 실행한다.
- 적합한 경우: 폐쇄된 개인 도구이고 권한·감사 위험을 별도로 수용할 때.
- 장점: 최대 자유도.
- 단점: command injection, secret, privilege escalation, 결과 검증, 복구 책임이 지나치게 크다.
- 추천안보다 낮은 이유: control plane 안전 경계와 정면으로 충돌한다.

## 결정

- 선택: `Proxmox actual-state authority + Gjallar verified operation authority`.
- 실행 모드:
  - `managed_api`: Gjallar가 API dispatch, task poll, post-check를 관리한다.
  - `guided_manual`: Gjallar는 allowlisted instruction을 발급하고 외부 실행 후 API로 검증한다.
  - `observe_only`: insight만 제공하며 dispatch authority가 없다.
- API failure 후 manual mode로 silent fallback하지 않는다.
- arbitrary shell/SSH executor와 raw embedded terminal은 초기 제품 범위에서 제외한다.
- Proxmox UI는 initial setup과 break-glass 경로로 남긴다.

## 결정 이유

이 구조는 Proxmox가 잘하는 low-level execution을 재구현하지 않으면서 Gjallar가 반드시 소유해야 할 운영 의도와 검증 증거를 제품 핵심으로 만든다. manual 작업도 자유로운 shell이 아니라 검토·승인·재검증 가능한 operation으로 제한해 안전성과 차별점을 함께 확보한다.

## 결과와 영향

- 영향 도메인: Workloads, Operations, Policy/Approval, Evidence/Audit, Insights, Setup/Integration.
- 공개 계약: 신규 operation resource를 additive하게 도입하고 기존 `/api/v1`은 compatibility facade로 유지한다.
- 데이터: operation, attempt, external task reference, plan/approval digest, verification, evidence가 필요하다.
- 정합성: dispatch ambiguity를 `needs_reconciliation`, manual verification 대기를 `awaiting_verification`으로 표현한다.
- 보안: command template allowlist, parameter validation, expiry, redaction, server-side actor가 필요하다.
- UI: mode, freshness, side-effect uncertainty와 recovery action을 명시해야 한다.

## 감수한 단점

- API와 manual 모두에 공통 operation UX를 설계해야 한다.
- 모든 `qm` 사용 사례를 즉시 지원하지 못하고 action별 allowlist를 점진 추가한다.
- Proxmox API로 after-state를 검증할 수 없는 작업은 성공 자동 판정이 제한된다.

## 검증 방법

- 동일 operation type에서 managed/manual mode가 같은 plan·policy·evidence contract를 사용한다.
- API timeout 또는 crash window가 second mutation 대신 reconciliation으로 이어진다.
- arbitrary command와 secret-bearing parameter가 boundary test에서 거부된다.
- terminal task와 direct after-state 없이는 `succeeded`가 되지 않는다.
- operator가 Proxmox GUI를 열지 않고 supported day-2 flow를 끝낼 수 있다.

## 재검토 조건

- Proxmox가 필요한 작업을 모두 안정적인 API로 제공해 manual mode의 가치가 사라질 때
- guided manual의 검증 불가능 작업 비중이 운영상 허용 수준을 넘을 때
- multi-tenant, regulated environment에서 stronger approval/audit isolation이 필요할 때
- 별도 privileged executor를 운영할 명확한 보안·복구 요구와 승인이 생길 때
