# Spring Boot Preset

Project Profile에서 `spring-boot`를 선택한 프로젝트에만 적용한다. 이 preset은 특정 언어, build 도구, 데이터 접근 기술, 데이터베이스를 미리 확정하지 않는다.

## 설계 시 결정할 항목

`$project-bootstrap`은 프로젝트 요구사항을 근거로 다음을 사용자와 결정한다.

- Java 또는 Kotlin과 공식 지원 버전
- Gradle Wrapper 또는 Maven Wrapper
- Spring Boot와 주요 Spring 모듈
- JDBC, JPA, MyBatis, jOOQ 등 데이터 접근 방식
- migration 도구와 데이터베이스
- 동기·비동기 처리 방식
- 모듈 및 패키지 구조
- 테스트 도구와 로컬 실행 방식

선택지는 프로젝트 적합도 순으로 최대 세 개까지 제시한다. 공식 지원 정보와 호환성을 확인하고 선택 이유, 감수한 단점, 확인일을 Project Profile에 기록한다.

## 재현 가능한 환경

- 프로젝트가 승인한 JDK 버전을 Toolchain 또는 동등한 방식으로 명시한다.
- 시스템 전역 build 도구보다 프로젝트 Wrapper를 우선한다.
- 의존성 버전과 lock 또는 dependency verification 정책은 프로젝트 선택을 따른다.
- Codex가 실행할 명령은 Project Profile에 기록한다.
- 로컬 JDK와 wrapper 설정이 없으면 임의의 전역 버전으로 우회하지 않는다.

## 코드 구조

프로젝트 복잡도에 맞게 단순한 구조부터 시작한다.

- Controller는 HTTP 입력 검증, 인증 문맥 전달, 응답 변환을 담당한다.
- Application Service 또는 Use Case는 업무 흐름, 권한, 트랜잭션을 조정한다.
- 핵심 비즈니스 규칙은 Spring, HTTP, persistence entity에 불필요하게 결합하지 않는다.
- Repository, Mapper, Gateway는 데이터 접근과 외부 연동을 담당한다.
- 다른 도메인의 repository 구현이나 persistence entity를 직접 참조하지 않는다.

단순 CRUD에 모든 계층과 interface를 기계적으로 만들지 않는다. 규칙, 외부 효과, 변경 이유가 분리될 때만 물리적인 계층을 추가한다.

## 데이터 접근

JPA, MyBatis, JDBC, jOOQ 등은 다음 기준으로 비교한다.

- 도메인 상태와 관계의 복잡도
- 복잡한 조회와 SQL 제어 필요성
- 트랜잭션 및 성능 요구사항
- 팀 경험과 디버깅 가능성
- 테스트와 migration 전략

공통 원칙:

- persistence entity나 mapper model을 외부 API 계약으로 그대로 노출하지 않는다.
- SQL과 매핑 계층에 비즈니스 정책을 숨기지 않는다.
- 사용자 입력은 안전한 parameter binding을 사용한다.
- transaction annotation이나 경계는 업무 원자성과 일치하는 계층에 둔다.
- 적용된 migration 파일을 덮어쓰지 않는다.

## 오류와 계약

- Spring 예외를 도메인·애플리케이션 계약과 구분한다.
- Controller advice 또는 프로젝트가 선택한 방식으로 오류 응답을 일관되게 변환한다.
- broad exception handler가 원인을 숨기거나 정상 응답으로 바꾸지 않게 한다.
- React 등 외부 소비자가 의존하는 API 변경은 호환성과 migration 경로를 검토한다.

## 테스트와 검증

- 핵심 규칙은 Spring context 없이 검증 가능한 단위 테스트를 우선한다.
- HTTP 계약은 프로젝트가 선택한 web test 방식으로 검증한다.
- persistence는 실제 mapping, query, transaction이 중요하면 통합 테스트를 사용한다.
- 외부 연동은 adapter 계약과 실패 변환을 테스트한다.
- `test`, `check`, `build` 같은 실제 wrapper 명령은 Project Profile에서 확정한다.

## 피할 패턴

- Controller에서 직접 SQL과 핵심 상태 전이를 처리
- 하나의 Service가 여러 도메인의 모든 기능을 소유
- 모든 클래스에 interface와 구현체를 기계적으로 생성
- persistence entity를 도메인·API 모델로 함께 사용
- 편의를 위한 거대한 `common`, `utils`, `BaseService`
- 테스트를 통과시키기 위한 transaction·validation·타입 규칙 우회
