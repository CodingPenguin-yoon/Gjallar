# Create replay의 완료 결과 이관

- 상태: `IMPLEMENTED`
- 날짜: `2026-09-07`
- 승인자: 사용자
- 승인 근거: 다음 레거시 정리 단계 진행에 “ㄱㄱ”로 승인
- 기준: [ADR-010](../../decisions/adr-010-create-result-history.md)

## 목표·범위

Create 완료 replay가 변경 가능한 node:VMID linkage 대신 이미 저장된 succeeded Operation의 결과를 반환하도록 한다. 기존 요청·Jobs·승인·멱등성은 유지한다. 새로운 테이블 없이 소비자 하나를 이관한다. 성공 결과가 유효하면 current linkage 부재/다른 owner에도 과거 결과를 반환하고 VM mutation은 호출하지 않는다. 성공 Operation의 결과 누락/손상은 기존 409 reconciliation-required로 닫는다.

현재 결과를 request observed_after와 입력으로 재조합하는 fallback과 replay의 중복 linkage 조회를 제거한다. 과거 호환 요청은 succeeded Operation이 없을 때만 exact job/node/VMID linkage를 사용한다. 자료가 부족하면 차단한다.

## 단계·검증

1. 성공 Operation 결과의 identity 검증을 domain 함수로 분리하고 replay 호출자를 이관한다.
2. 정상 replay, 현재 linkage 삭제/owner 교체, 결과 손상·다른 target·다른 operation type, legacy 호환과 중복 mutation 방지 테스트를 실행한다.
3. backend 전체·frontend tests/lint/build·문서/diff 검사와 독립 quality-review를 수행하고 현재 문서를 갱신한다.

## 복구·영향·비범위

schema·transaction 변경은 없다. 코드 rollback이 가능하나 현재 linkage 없는 replay는 이전 코드에서 다시 차단될 수 있다. 기존 결과를 수정·삭제하지 않는다. 잘못된 owner 결과 반환 또는 추가 mutation이 발견되면 중단한다. 외부 effect와 DB의 원자성을 새로 가정하지 않으며 기존 checkpoint/lease를 보존한다.

이 승인은 replay의 완료 결과 이관을 의미하며 VMID 재사용 허용, evidence/readiness 전체 이관, schema·데이터 삭제, 파일 잠금 제거·live mutation·배포를 의미하지 않는다. 다음 소비자 변경은 복구와 외부 재생성 식별 근거를 검증한 뒤 구체화한다.

## 구현 결과

성공 Operation의 workload snapshot을 검증하는 domain 함수를 추가하고 replay 소비자를 이관했다. 현재 row와 입력으로 결과를 재조합하던 fallback, replay 단계의 중복 current linkage 조회를 제거했다. 성공 Operation의 누락·손상은 legacy fallback으로 숨기지 않는다. 현재 linkage 삭제·다른 owner에서도 당시 결과를 반환하며 다른 owner row를 수정하지 않는다.

검증: backend 전체 **651 passed, 6 skipped**, frontend 17개 테스트 스크립트·ESLint·Vite build 통과, 문서 계약 10개·diff 검사 통과. 독립 quality-review에서 확정 결함 없음. 모의 runner로 mutation 재실행 없음·손상된 history의 409를 확인했다.

로컬 Python 3.14/Node 26에서 검증했다. container 기준·PostgreSQL 통합·실제 VM 생성은 이번 검증에 포함하지 않았다. schema·데이터 migration은 없으며 local backend에 변경을 반영하고 background recovery disabled를 유지한다. evidence summary·readiness owner·성공 projector·VMID guard·파일 lock은 후속이다.
