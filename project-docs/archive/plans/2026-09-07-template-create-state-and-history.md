# 템플릿 기반 Create의 상태 판단과 이력 저장 분리

- 상태: `IMPLEMENTED`
- 작성일: `2026-09-07`
- 구현 승인: 사용자, `2026-09-07`, “진행해보자” — 1단계 한정
- 상위 기준: [프로젝트 명세](../../specifications/project-specification.md), [ADR-008](../../decisions/adr-008-template-based-create-and-persistence-simplification.md), [ADR-009](../../decisions/adr-009-proxmox-state-authority-and-create-history.md)

> 승인된 1단계만 구현 완료했다. 2·3단계는 미승인 후속 설계이며 이 완료 상태가 구현 권한을 부여하지 않는다.

## 목표와 범위

Proxmox의 실제 정보로 템플릿 기반 VM 생성을 검토하고 실행한다. 입력·검토·작업 이력은 보존할 수 있지만 DB의 과거 VM 상태가 현재 실행 조건의 기준이 되지 않게 한다. 최종 목표는 필수 DB 프로필 없이 템플릿에서 시작하는 입력 흐름이다.

첫 구현 범위는 **검토 계산과 기록 책임의 분리**로 제한한다. 기존 API·artifact·승인 checksum·기록 시점을 유지하며 계산 결과를 application의 명시적 persistence 단계로 전달한다. 이 단계에서 DB write 수 감소나 프로필 독립을 완료했다고 표현하지 않는다.

후속 단계는 직전 조회·충돌 판정, 템플릿 중심 입력, 이력 저장 시점 정리다. 아래 미결정 계약을 확정하고 Plan의 구현 승인 범위를 갱신한 뒤 진행한다.

비범위: ISO·빈 VM 생성, OS 설치, DB 제거·교체, 인증 변경, migration·기존 데이터 삭제, request/Jobs table 폐기, 파일 guard 제거, complete `live` gate 완화, production 배포·live VM 작업.

## 현재 근거와 목표

| 현재 코드 | 전환 방향 |
|---|---|
| `vm_create/drafts.py`, `preflight.py`가 DB 프로필을 조회 | 먼저 정책 조회를 계산 입력과 분리하고, 후속 단계에서 선택적 프리셋과 명시적 정책으로 구분 |
| `vm_create/application.py`의 draft·preflight 단계가 Jobs 기록 | 기록 책임은 application에 유지. 계산 자체가 기록을 요구하지 않도록 경계 명확화 |
| `vm_create/planner.py`가 plan 계산 중 5종 artifact 저장 | 계산 결과와 저장용 payload를 만들고 별도 persistence 단계에서 기존 artifact 계약으로 저장 |
| approve·preview·execute가 `build_preview_plan` 재호출 | 계산과 저장 호출을 명시적으로 구분. 승인된 evidence를 재계산 부수 효과로 바꾸지 않도록 검증 |
| request·workload·Jobs와 Operation 병행, 성공 projection이 recovery 완료와 결합 | 첫 단계 그대로 유지. 과거 상태 guard와 idempotency·동시 작업 guard는 후속 조사에서 구분 |

코드 위치는 `backend/app/` 기준이다. 현재 구조의 상세는 [DB](../../database/current-schema-and-ownership.md)와 [흐름](../../flows/verified-operation-lifecycle.md)을 따른다. 이 Plan은 기존 구현이 모든 직전 조회 조건을 이미 충족하거나 위반한다고 단정하지 않는다.

## 대안과 추천

- **경계 분리부터 진행(추천)**: API·승인·복구 계약을 유지하며 계산을 독립적으로 검증한다. 초기 DB write 수와 필수 프로필은 남는다.
- 검토 기록을 즉시 제거: 저장 호출은 줄지만 Jobs·artifact·승인 consumer 계약이 한 번에 달라지고 입력 이력을 보존하려는 목적도 놓친다.
- 입력 UI·프로필·schema·recovery를 일괄 재작성: 목표로 바로 갈 수 있으나 변경 원인과 실패 복구 범위가 커진다.

## 단계와 인수 조건

### 1. 계산과 persistence 경계 분리 — 첫 승인 대상

- draft·preflight·plan의 DB 접근과 결과 소비자를 정리하고, DB 프로필에서 얻은 정책은 계산 진입 전에 명시적으로 전달한다. 기존 운영자 설정값을 유지한다.
- 계획의 내용·checksum 계산과 artifact 저장을 나눈다. 저장 후 생성되는 artifact metadata는 application이 응답으로 조합한다. 기존 ID·checksum 의미·응답 필드는 유지한다.
- application에서 기존 기록 순서를 명시적으로 실행한다. Jobs·Operation·승인·runner·recovery의 저장 계약은 그대로 둔다.
- 인수 조건: 동일 입력·정책·관찰값은 같은 계획 내용을 만들며 계산 구간에서 DB/Jobs/artifact write가 발생하지 않는다. 기존 검토·승인·실행 응답과 실패 의미가 유지된다.
- 검증: 계산 테스트, DB 프로필 수정값 보존, draft/preflight/plan 계약, exact approval·drift, artifact 저장 실패 시 mutation 부재, 기존 Create recovery 회귀 테스트.

### 2. Proxmox 직전 조회와 충돌 판정 — 상세 계약 확정 후

- inventory cache 사용 지점, backend mutation gate, runner의 clone·config·resize·start 전제 조건을 조사한다.
- 첫 mutation 직전 새 조회와 이후 단계별 필요한 재검증 지점을 명시한다. 승인 영향이 있는 변경과 단순 과거 관찰값 차이를 구분한다.
- DB guard별로 승인/replay/진행 중 작업/과거 관찰 비교 역할을 분류한다. 이전 요청 기록 때문에 같은 VMID의 신규 요청을 차단하는 규칙도 이때 별도 확정한다. 오래된 lock을 실제 VM 상태만 보고 해제하지 않는다.
- 검증: 검토 후 템플릿 삭제·VMID 선점·자원 변경·조회 실패, DB 과거 상태 불일치, 직전 조회 이후 API 충돌, 실행 후 상태 불일치. 동일 요청 replay와 실행 중인 작업 보호를 함께 확인한다.

### 3. 템플릿 중심 입력과 이력 정책 — 상세 계약 확정 후

- DB 등록 없이 Proxmox 템플릿을 선택하고 사양을 입력한다. 프로필의 기본값과 허용 노드·사양 제한 등 정책을 분리한다.
- 제안: 검토 요청 단위로 민감정보를 제거한 입력·검토 결과·관찰 출처/시각을 보존한다. 매 키 입력 저장은 추가하지 않는다.
- 저장된 검토는 과거 기록으로 표시하며 현재 인프라 조회의 fallback이나 자동 상태 복원의 근거로 쓰지 않는다.
- 확정할 것: 이력 식별자·수정/재검토 관계, 보존 기간, 검토 기록 실패 시 응답, 승인과 해당 검토의 immutable binding, 프리셋/정책 저장 위치와 기존 설정 이관.
- 검증: 프리셋 없이 생성 검토, 운영자 정책 보존, 시크릿 비저장, 과거 이력과 현재 상태 표시 구분, 승인 후 입력 변경 차단.

## 계약·위험과 검증 실행

영향 영역은 Create application/planner, profile policy 입력, Jobs/artifacts, approval digest와 frontend review consumer다. 첫 단계에서는 `/api/v1/vm-create/*`, DB schema, 권한, target lock·lease·checkpoint·GET-only recovery 계약을 변경하지 않는다.

구현 시 관련 `backend/tests/vm_create/`, `backend/tests/contracts/test_api_v1_vm_create*.py`, `backend/tests/operations/test_vm_create*.py`, `backend/tests/db/test_create_vm_profiles.py`와 frontend Create 계약 테스트를 실행한다. 실제 변경에 맞는 전체 검증은 [프로필](../../project-profile.md)의 `pnpm run verify` 및 `pnpm run verify:container`를 기준으로 하며 미실행 검사는 이유를 기록한다. 문서 단계는 문서 계약 테스트와 `git diff --check`로 검증한다.

## 중단·되돌리기

첫 단계는 schema와 데이터 이관 없이 진행한다. 응답 ID·checksum 변경, 승인 evidence 덮어쓰기, 새로운 외부 mutation 경로, 복구 transaction 변경이 필요해지면 중단하고 범위를 다시 정한다. 실패 시 이 작업에서 분리한 코드만 되돌리며 기존 사용자 변경과 저장된 이력은 보존한다. 불명확한 외부 효과가 있으면 기존 GET-only recovery와 lock 보존 원칙을 따른다.

후속 단계의 데이터 이관·retention과 roll-forward는 계약 확정 시 별도로 작성한다. 구현 후 독립 `quality-review`, 실제 검증과 문서 반영을 마친 뒤 상태를 변경한다.

## 승인 문장

이 승인은 **1단계의 검토 계산과 persistence 경계를 분리하면서 기존 API·기록 시점·승인·복구 계약을 보존하는 구현**을 의미하며, **2·3단계의 계약 변경, DB 이관·삭제, lock 제거, live mutation 또는 배포**를 의미하지 않는다.

사용자는 “진행해보자”로 위 1단계 구현을 승인했다. 2·3단계는 상세 계약 확정 후 별도 승인한다.

## 1단계 구현·검증 결과

- `drafts.build_default_vm_draft`, `preflight.run_preflight`는 application에서 조회한 프로필 정책을 입력으로 받는다. 필수 프로필과 운영자 수정값은 유지한다.
- `planner.calculate_vm_create_plan`이 저장 없이 계획 내용을 계산하고 `plan_persistence.persist_vm_create_plan`이 기존 artifact와 승인 metadata를 저장·조합한다. application의 기존 기록 시점과 실행·복구 계약은 유지했다.
- DB 접속 없이 반복 계산, 다른 draft의 preflight 거부, artifact 순서·반복 ID/checksum, 5종 artifact 각각의 저장 실패 시 mutation factory/runner 미호출을 검증했다.
- 관련 회귀 테스트 166개 통과. 백엔드 전체 594개 통과·PostgreSQL 전용 6개 skip 이후 실패 주입 5개 추가를 포함한 경계 테스트 8개 통과. 프론트엔드 17개 테스트·ESLint·Vite build 통과. 문서 계약 테스트 10개와 `git diff --check` 통과.
- `pnpm run verify`와 `pnpm run verify:container`는 출력 없이 대기하여 중단했고, 로컬 검증의 동일 Python/Node 명령을 직접 실행했다. Docker API socket 접근 거부로 container 검증은 미실행이다. 로컬 Python 3.14.6·Node 26.8.1은 기준 Python 3.13·Node 24와 다르다. 전체 backend의 deprecation warning 462개는 별도 변경하지 않았다.
- 독립 `quality-review`에서 런타임 결함은 발견되지 않았다. 저장 실패 테스트 공백을 보완하고 재검토에서 종료했다. live Proxmox mutation·production DB 작업·배포는 수행하지 않았다.
- 후속: 직전 상태 조회·충돌 판정과 템플릿 중심 입력·이력 정책은 2·3단계 상세 계약을 확정하고 새 구현 범위로 승인받는다.
