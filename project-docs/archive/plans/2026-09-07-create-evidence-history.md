# Create evidence 조회의 역사 결과 이관

- 상태: `IMPLEMENTED`
- 날짜: `2026-09-07`
- 승인자: 사용자
- 승인 근거: replay 이후 evidence/readiness 소비자 정리 진행 요청 “정리시작”
- 기준: [ADR-010](../../decisions/adr-010-create-result-history.md)

## 목표와 범위

evidence summary의 succeeded Operation 결과는 현재 `vm_instances`와 분리한다. 검증된 생성 당시 workload는 기존 domain history 규칙을 재사용하고 observed_after는 같은 작업의 request/artifact에서 읽는다. 현재 VM row가 변경/삭제/다른 owner여도 과거 결과를 유지한다. 역사 결과가 손상되면 현재 row로 복원하지 않고 미기록으로 표시한다.

succeeded Operation 없는 legacy 조회만 기존 workload evidence를 읽는다. 선택한 자료의 출처를 `vm_instance_source`로 추가하며 기존 응답 필드는 유지한다. legacy에서 같은 job의 row가 여러 개이거나 요청 target과 다르면 임의 첫 row를 선택하지 않는다. 정상 자료는 기존대로 표시하고 손상된 linkage는 미기록으로 표시한다.

## 조사와 후속 경계

readiness는 사용자가 제출한 로컬 evidence이며 실제 VM 조회를 수행하지 않는다. 현재 node/VMID와 create_job_id로 연결한다. 단순 최신 Operation 검색으로 owner를 바꾸면 외부 재생성 여부를 증명할 수 없으므로 이번 단계에서 바꾸지 않는다. recovery는 기존 fingerprint와 exact lock/lease를 검증하고 현재 projector의 foreign owner 거부를 유지한다. VMID 재사용 제한·잠금 제거를 이 작업과 함께 수행하지 않는다.

## 단계·검증

1. 현대 성공/legacy 조회 경계를 분리하고 중복 row의 임의 선택을 제거한다.
2. 현재 row 삭제·내용 변경·다른 owner, 현대 결과 손상, legacy 정상·중복·잘못된 target, 기존 redaction/API 계약을 테스트한다.
3. backend 전체, frontend tests/lint/build, 문서·diff 검사와 독립 quality-review를 수행한다.

## 선택·복구

현재 row를 계속 우선하면 이력이 변경될 수 있다. 새 history table은 기존 Operation 결과와 중복되므로 추가하지 않는다. 코드 rollback 가능하고 DB schema/기존 데이터는 바꾸지 않는다. 잘못된 작업 결과 노출 또는 raw secret 노출이 있으면 진행을 중단한다. 출처 필드 추가 외 API 필드 삭제는 없다.

이 승인은 evidence 조회의 역사 결과 이관과 legacy 선택 안전성 보완을 의미하며 readiness 입력 계약 변경·VMID 재사용·실환경 작업·schema/데이터 삭제·파일 guard 제거를 의미하지 않는다.

## 구현·검증 결과

- succeeded Operation의 검증된 역사 결과를 evidence helper/CLI에 적용했다. 현재 workload 우선 조회를 제거하고 legacy 중복 row의 임의 선택을 제거했다. 현재 row 변경·삭제·owner 교체에도 현대 성공 evidence는 유지한다.
- 손상된 역사 결과는 미기록으로 표시하며 request 부재 시 같은 job artifact의 observed_after를 사용한다. 새 source 필드를 추가하고 기존 응답·redaction은 보존했다. HTTP endpoint와 UI 변경은 없다.
- backend 전체 **655 passed, 6 skipped**, frontend 17개 스크립트·ESLint·Vite build 통과, 문서 계약·diff 검사 통과. 독립 quality-review에서 확정 결함 없음. 리뷰 후 제안된 request 부재 artifact fallback 회귀 테스트도 추가하여 전체 검증을 재실행했다.
- Python 3.14/Node 26 로컬 검증이다. container 기준·PostgreSQL 통합·실환경 mutation은 실행하지 않았다. DB migration·기존 데이터 삭제·agent 설정 변경은 없다.

readiness는 로컬 제출 evidence의 귀속이며 현재 linkage가 실제 외부 재생성을 증명하지 않는다. 정확한 생성 identity 입력/검증 계약을 정하기 전 최신 Operation을 추정 연결하지 않는다. recovery의 기존 fingerprint/lock/lease 검증은 유지하고 VMID 재사용·projector·파일 guard 제거는 후속으로 남긴다.
