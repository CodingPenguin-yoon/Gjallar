# Gjallar 작업 지침

이 저장소는 Proxmox의 실제 상태와 실행 권위를 존중하면서 상태·변화·위험과 운영 증거를 먼저 관찰하고 설명하며, 필요한 경우에만 제한된 검증 작업을 제공하는 Observe-first Operations Intelligence with Verified Actions이다.

## 기본 원칙

- 응답과 공동 문서 본문은 한국어로 작성한다. 코드 식별자, API, 명령, 파일명과 환경 변수는 실제 표기를 유지한다.
- 확인하지 않은 구조, 명령, 버전과 동작을 추측하지 않는다.
- 사용자의 기존 변경을 보존하고 요청 범위에 필요한 최소 변경만 만든다.
- 관련 없는 리팩터링, 포맷 변경, 이름 변경과 정리를 섞지 않는다.
- 시크릿, 토큰, 비밀번호, 개인정보를 코드·로그·문서에 남기지 않는다.

## 작업 전 확인

1. `project-docs/project-profile.md`에서 현재 환경, 저장소 지도, 검증 명령과 위험 영역을 확인한다.
2. 작업에 직접 관련된 Specification, Architecture, ADR, Plan, API, DB, Flow 문서만 읽는다.
3. 관련 진입점, 인접 코드, 공개 계약, 테스트와 설정을 조사한다.
4. 현재 동작, 목표 동작, 범위, 비범위와 검증 가능한 완료 조건을 구분한다.

모든 문서를 일괄해서 읽지 않는다. 제품 의도와 현재 동작을 판단할 때는 다음 순서를 따른다.

1. 사용자가 가장 최근에 명시하거나 승인한 방향
2. 현재 `APPROVED` Specification
3. 대체 관계상 최신 `ACCEPTED` ADR
4. 현재 `APPROVED` Plan
5. 코드와 테스트가 보여주는 실제 동작

`SUPERSEDED`·`REJECTED` ADR과 `CANCELLED`·`ROLLED_BACK` Plan은 역사적 맥락일 뿐 현재 구현 권한이 아니다. 현재 존재하는 호환 경로나 제거 대상도 별도 승인 없이 장기 유지·확장 대상으로 해석하지 않는다.

## 위험과 승인

데이터·보안·공개 계약·외부 상태, 아키텍처·운영 의존성, 비동기·복구처럼 실패 영향이나 되돌리기 비용이 큰 변경은 고위험으로 본다. Gjallar의 구체적인 trigger와 live 작업 승인 경계는 [`project-docs/project-profile.md`](project-docs/project-profile.md)를 단일 기준으로 따른다.

고위험 작업은 구현 전에 `$task-planning`으로 공유 Plan을 작성하고 사용자의 범위 승인을 받는다. 아키텍처 전환은 사용자가 명시적으로 요청하거나 승인한 경우에만 `$architecture-evolution`을 사용한다. 고위험 구현은 완료 전에 `$quality-review`로 구현과 분리된 검토를 수행한다.

승인된 구조 안의 일반 구현, 테스트, 명확한 버그 수정, 호환 가능한 내부 리팩터링과 실제 변경에 따른 문서 갱신은 반복 승인 없이 진행한다.

파괴적 데이터 작업과 저장소 외부 수정은 명시적 승인 없이는 수행하지 않는다.

## 구현 규율

- 기존 구현, helper, interface, DTO, 예외와 테스트 패턴을 먼저 찾는다.
- HTTP/UI, application flow, domain rule, DB와 외부 연동의 책임을 불필요하게 섞지 않는다.
- 다른 도메인의 내부 구현이나 persistence model을 편의상 직접 참조하지 않는다.
- broad catch, silent fallback, suppression으로 오류와 계약 위반을 숨기지 않는다.
- 적용된 Alembic migration을 수정하거나 삭제하지 않는다. 새 변경은 새 migration으로 만든다.
- generated file은 생성 원본을 수정한다.
- `git commit`, `git push`, rebase, force push와 hard reset은 사용자가 요청한 경우에만 수행한다.

## 검증

변경 영역과 위험에 비례해 실제 명령을 실행한다. 세부 명령과 실행 조건은 [`project-docs/project-profile.md`](project-docs/project-profile.md)를 단일 기준으로 따른다.

- diff 검사: `git diff --check`
- 공통 로컬 검증: `pnpm run verify`
- 기준 container 검증: `pnpm run verify:container`

버그 수정은 가능하면 실패를 재현하는 테스트를 먼저 추가하거나 식별한다. 실행하지 못한 검사는 성공으로 표현하지 않고 이유와 남은 위험을 보고한다.

## 문서와 완료

공동 source of truth는 `project-docs/`다. 프로젝트 목적, 기술 스택, 아키텍처, 도메인, 공개 API·DB 계약 또는 주요 성공·실패 흐름이 실제로 바뀐 경우에만 관련 현재 상태 문서를 갱신한다. 일반 변경 이력은 Git이 담당하며 작업별 요약 문서를 만들지 않는다.

완료 전에는 요구사항 충족, 최종 diff, 테스트·Lint·빌드 결과, 문서 영향과 남은 위험을 확인한다. 최종 응답에는 변경 결과, 주요 파일의 역할, 실행한 검증, 문서 변경과 잔여 위험을 간결하게 포함한다.
