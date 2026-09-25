# Gjallar 작업 지침

이 저장소는 Proxmox의 실제 상태와 실행 권위를 존중하면서, 갈랴르의 웹에서 템플릿 준비·VM 관리·모니터링·복구를 끝내는 운영 도구를 지향한다. 현재 구현과 미구현 목표는 PRD·아키텍처·로드맵에서 구분한다.

## 기본 원칙

- 응답과 공동 문서 본문은 한국어로 작성한다. 코드 식별자, API, 명령, 파일명과 환경 변수는 실제 표기를 유지한다.
- 확인하지 않은 구조, 명령, 버전과 동작을 추측하지 않는다.
- 사용자의 기존 변경을 보존하고 요청 범위에 필요한 최소 변경만 만든다.
- 관련 없는 리팩터링, 포맷 변경, 이름 변경과 정리를 섞지 않는다.
- 시크릿, 토큰, 비밀번호, 개인정보를 코드·로그·문서에 남기지 않는다.

## 작업 전 확인

1. `project-docs/development.md`에서 환경·검증·운영 조건과 이 문서의 위험 경계를 확인한다.
2. 관련된 PRD·아키텍처·로드맵·작업 기록만 읽는다. API·DB·실행 복구의 핵심 계약은 아키텍처에서 확인한다.
3. 관련 진입점, 인접 코드, 공개 계약, 테스트와 설정을 조사한다.
4. 현재 동작, 목표 동작, 범위, 비범위와 검증 가능한 완료 조건을 구분한다.

모든 문서를 일괄해서 읽지 않는다. 제품 의도와 현재 동작을 판단할 때는 다음 순서를 따른다.

1. 사용자가 가장 최근에 명시하거나 승인한 방향
2. 현재 `APPROVED` PRD (`project-docs/prd.md`)
3. 현재 아키텍처의 유효한 설계 결정과 계약
4. `work/`의 현재 `APPROVED` 구현 계획
5. 코드와 테스트가 보여주는 실제 동작

`SUPERSEDED`·`REJECTED` ADR과 종료된 `IMPLEMENTED`·`SUPERSEDED`·`CANCELLED`·`ROLLED_BACK` Plan은 역사적 맥락이며 새로운 변경의 구현 권한이 아니다. 현재 존재하는 호환 경로나 제거 대상도 별도 승인 없이 장기 유지·확장 대상으로 해석하지 않는다.

## 위험과 승인

다음 변경은 고위험으로 보고 구체적인 범위·검증·복구 방안을 작업 문서에 먼저 정한다.

- live Proxmox mutation·smoke: 정확한 target과 side effect를 별도 승인받는다.
- DB schema·migration·데이터 이동·소유권·transaction·정합성 변경
- 인증·권한·session·개인정보·시크릿 처리 변경
- `/api/v1` 또는 canonical frontend route의 비호환 변경
- 도메인 경계·의존 방향·주요 배포 구조 전환
- idempotency·target lock·lease·retry·recovery·reconciliation 변경
- raw shell/SSH executor·worker·queue·scheduler·cache·신규 외부 시스템 도입
- DRS 제거 migration production 적용·historical Jobs/Artifacts 보존 변경·제거된 계약 복원
- telemetry collector·TSDB·alert delivery·신규 monitoring dependency 도입

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

변경 영역과 위험에 비례해 실제 명령을 실행한다. 세부 명령과 실행 조건은 [개발·운영 안내](project-docs/development.md)를 단일 기준으로 따른다.

- diff 검사: `git diff --check`
- 공통 로컬 검증: `pnpm run verify`
- 기준 container 검증: `pnpm run verify:container`

버그 수정은 가능하면 실패를 재현하는 테스트를 먼저 추가하거나 식별한다. 실행하지 못한 검사는 성공으로 표현하지 않고 이유와 남은 위험을 보고한다.

## 문서와 완료

공동 source of truth는 `project-docs/`다. 프로젝트 목적, 기술 스택, 아키텍처, 도메인, 공개 API·DB 계약 또는 주요 성공·실패 흐름이 실제로 바뀐 경우에만 관련 현재 상태 문서를 갱신한다. 단순 변경 이력은 Git이 담당하며, 의미 있는 기능·문제 해결은 `project-docs/work/`에 결정 이유·결과·검증·남은 일을 기록한다. 작업 완료 시 로드맵과 관련 현재 문서도 갱신한다.

문서 역할은 [문서 안내](project-docs/README.md)를 따른다. API·DB·도메인·실행 흐름과 중요한 결정은 아키텍처에 통합한다. 큰 작업은 `project-docs/work/`의 한 문서에서 계획·진행·결과를 이어 기록하고 별도 Plan·완료 요약을 중복 생성하지 않는다. 과거 원본 묶음은 보존하며 현재 규칙으로 해석하지 않는다.

완료 전에는 요구사항 충족, 최종 diff, 테스트·Lint·빌드 결과, 문서 영향과 남은 위험을 확인한다. 최종 응답에는 변경 결과, 주요 파일의 역할, 실행한 검증, 문서 변경과 잔여 위험을 간결하게 포함한다.
