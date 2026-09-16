# ADR-008: 템플릿 기반 VM 생성과 저장 의존성 단순화 방향

> 후속 적용: [ADR-011](adr-011-create-legacy-retirement.md)이 current-workload write·파일 guard 병행과 readiness owner 이관 범위를 대체한다. 아래는 결정 당시 기록이다.

> 저장 정책 구체화(2026-09-14): [ADR-012](adr-012-create-preset-and-history-retention.md)가 선택적 DB 프리셋 유지와 현재 저장 단위의 입력·검토·승인·작업 기록에 자동 만료·삭제를 도입하지 않는 정책을 확정한다.


- 상태: `ACCEPTED`
- 날짜: `2026-09-07`
- 결정자: `사용자`
- 상위 제품 기준: [프로젝트 명세](../specifications/project-specification.md), [ADR-007](adr-007-observe-first-operations-intelligence.md)
- 관계: ADR-007의 Create VM 범위를 구체화한다. ADR-002의 점진 전환, ADR-003의 현재 연결 gate와 ADR-004의 durable coordination 원칙은 유지한다.
- 적용 상태: 제품 범위와 후속 설계 방향 채택. 생성 로직·DB·API 변경은 미착수이며 상세 구현 Plan은 별도로 작성한다.

> 후속 구체화(2026-09-07): [ADR-009](adr-009-proxmox-state-authority-and-create-history.md)에 따라 DB write 수보다 현재 상태의 권위와 이력 저장 책임을 구분한다. 입력·검토 이력은 보존할 수 있으며 상세 [구현 계획](../archive/plans/2026-09-07-template-create-state-and-history.md)의 승인된 1단계는 `IMPLEMENTED`이며 나머지는 후속 설계다. 아래는 최초 합의 당시의 기록이다.

## 배경

현재 Create VM은 Proxmox 템플릿 복제 후 디스크·config를 설정하고, 선택한 power policy에 따라 부팅과 결과를 검증한다. 입력에는 DB의 생성 프로필이 필수다. 초안·사전 검사부터 Jobs를 기록하며, 계획을 만들 때 preflight report·VM manifest·planned Git diff·plan·review summary artifact를 저장한다. 승인·미리보기·실행도 계획을 다시 계산하고 같은 artifact를 갱신한다.

실행 시 공통 Operation/event/recovery/lock과 기존 `vm_create_requests`, `vm_instances`, Jobs/Artifacts를 함께 유지한다. Create의 검증된 성공은 호환 projection, recovery 완료와 durable lock 해제까지 같은 fenced transaction으로 닫는다. 이 구조는 기존 consumer와 재시작 안전성을 보존하지만 여러 상태 사본의 정합성과 호환 계층을 실행 완료 조건에 결합한다.

사용자는 이 DB 의존성을 조사한 뒤 템플릿 기반에 집중할지 ISO로 처음부터 만드는 기능까지 확대할지 검토했다. 현재 단계는 템플릿 기반 생성에 집중하고, 템플릿 선택·사양 입력을 중심으로 생성 흐름과 저장 구조를 정리하는 방향에 동의했다.

## 검토한 선택지

| 선택지 | 장점 | 비용·책임 | 결정 |
|---|---|---|---|
| 템플릿 기반 생성에 집중 | 준비된 OS를 반복 배포하고 action별 성공 기준을 한정할 수 있다. 기존 clone·설정·검증 코드를 재사용한다. | 사용할 템플릿을 Proxmox에서 준비해야 한다. | 현재 단계 채택 |
| 빈 VM 생성과 ISO 연결 | 템플릿이 없는 OS와 특수 설치를 시작할 수 있다. | 가상 하드웨어·ISO·부팅 설정, Proxmox 콘솔로의 설치 handoff와 새로운 성공 의미가 필요하다. | 현재 단계 제외 |
| OS 설치 완료까지 자동화 | 설치부터 준비까지 일괄 처리할 수 있다. | OS별 installer·실패/재개·완료 검증과 추가 권한을 소유한다. | 현재 단계 제외 |

## 채택한 방향

### 제품 범위

- Proxmox가 OS 설치, 특수 하드웨어 구성과 템플릿 제작을 담당한다.
- Gjallar는 Proxmox 템플릿의 사용 적합성을 확인하고, 사용자가 입력한 사양·네트워크·접속 설정으로 복제·설정·검증한다.
- 템플릿과 생성 프로필을 구분한다. 템플릿은 Proxmox의 OS·disk 기반이고, 프로필은 CPU·메모리 등의 기본값·제약을 담는 Gjallar 설정이다.
- 목표 입력 흐름은 `템플릿 선택 → 사양·네트워크·접속 정보 → 검토·승인 → 생성·검증`이다. 프로필은 사용자 입력을 돕는 선택적 프리셋으로 축소하는 방향을 검토한다.
- 현재 범위에 ISO 업로드·선택 기반 신규 VM, OS 설치 자동화, 내장 설치 콘솔, 템플릿 제작·변환 action을 추가하지 않는다.

### 생성 흐름과 저장 책임

- 기존 Proxmox clone·설정·결과 검증을 재사용하면서 입력·검토 계산과 DB 저장의 책임을 분리한다.
- 검토·승인·실행에서 반복 생성되는 artifact와 이전 GitOps 모델의 산출물은 소비자와 승인 digest 의미를 확인하고 축소한다.
- 공통 Operations를 실행 의도·승인·단계·task reference·검증 결과의 기준으로 삼는다. 기존 요청·Jobs·VM 연결 정보에 중복된 실행 판단과 저장을 단계적으로 줄인다.
- VM 연결 정보는 생성 출처 등 필요한 local metadata를 보존하며 Proxmox actual state의 별도 권위가 되지 않는다.
- 중복 요청 방지, 같은 target의 충돌 방지, 외부 호출 전후 durable checkpoint, 검증 evidence와 재시작 후 GET-only 관찰은 유지한다.
- target lock과 recovery lease는 다른 역할이므로 단순 중복으로 합치지 않는다. DB·파일 잠금 공존은 전환 부채로 관리한다.

## 현재 구현과 후속 결정의 경계

| 항목 | 현재 코드 | 후속 설계에서 정할 것 |
|---|---|---|
| 프로필 | DB 프로필이 필수이며 운영자가 수정한 값을 사용한다. | 선택적 프리셋의 입력·정책 역할, DB 또는 versioned configuration, 기존 수정값 보존 |
| 검토 | 초안·사전 검사부터 DB write, 계획 artifact 반복 upsert | 저장할 시점과 최소 evidence, 순수 계산 경계, exact approval binding |
| 실행 기록 | Operation과 request/Jobs/workload/artifact 병행 | producer/consumer 전환, replay 기준, 공개 응답 호환과 historical retention |
| 잠금 | PostgreSQL durable lock + compatibility file guard | 전체 mutation 경로의 durable lock 사용 확인, 열린 guard 처리와 제거 순서 |
| 생성 적격성 | frontend/backend mutation 모두 complete `live` 필요 | action에 필요한 target/source만으로 판단할지 별도 검토. 이번 결정으로 gate를 완화하지 않는다. |
| 복구 | GET-only 관찰과 local projection 복구. mutation을 재호출하지 않는다. | canonical evidence와 호환 projection의 완료 조건을 분리할 구체적 정합성 계약 |

DB 성능 병목을 측정한 결정은 아니다. 확인한 문제는 계산·검토와 persistence의 결합, 반복 기록과 호환 구조의 복잡성이다. 인증·session도 PostgreSQL에 의존하므로 Create를 단순화해도 앱 전체가 DB 없이 동작하는 것은 아니다.

## 구현과 검증 원칙

후속 Plan은 실제 consumer, API 호환, schema·데이터 보존, transaction, idempotency·lock·recovery, 실패 후 복구·되돌리기를 구체화한다. table 삭제, 신규 migration, 단순 lock 해제, approval/evidence 생략을 문서 정리의 부수 효과로 수행하지 않는다.

검증에는 exact-plan 승인·drift, 동일 요청 replay, 동일 VMID 충돌, 외부 호출 전후 crash, DB 기록 실패, stale recovery worker와 결과 검증을 포함한다. 신규 검토 흐름은 기존 문서의 성공/실패 의미를 유지하거나 변경하는 지점을 명시한다.

## 합의 기록과 재검토 조건

- 사용자 대화에서 DB 의존성 조사와 템플릿/ISO 생성 선택지를 비교한 뒤, 템플릿 중심 추천에 대해 `일단 오케이`라고 수락하고 현재 수정 방향을 포함한 문서 체계화를 요청했다.
- 이 합의는 현재 제품 범위와 다음 설계 방향을 기록하는 근거다. DB 이관·schema 변경·실제 생성 로직 재작성·live mutation의 구체적 실행 승인은 후속 Plan과 target 범위로 관리한다.
- 템플릿으로 처리할 수 없는 설치를 Gjallar 안에서 반복해야 하거나, 고정 프리셋을 넘어 프로필 관리 기능이 필요해지면 제품 범위와 저장 방식을 재검토한다.

구현 현황은 [아키텍처](../architecture/overview.md), [DB](../database/current-schema-and-ownership.md), [작업 흐름](../flows/verified-operation-lifecycle.md)을 따르고 후속 작업 상태는 [계획 인덱스](../plans/README.md)에서 확인한다.
