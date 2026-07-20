# FastAPI Preset

Project Profile에서 `fastapi`를 선택한 프로젝트에만 적용한다. 이 preset은 Python 버전, 패키지 관리자, ORM, DB, sync/async 방식을 미리 확정하지 않는다.

## 설계 시 결정할 항목

`$project-bootstrap`은 다음을 프로젝트 적합도 순으로 제안한다.

- 공식 지원되는 Python 버전
- `uv`, 표준 `venv`와 pip, Poetry 등 환경·의존성 관리 방식
- FastAPI 및 validation library 버전
- sync 또는 async 실행 모델
- SQLAlchemy ORM/Core, SQLModel, 직접 SQL 등 데이터 접근 방식
- migration 도구와 데이터베이스
- 패키지 및 도메인 구조
- 테스트, Lint, 포맷, 타입 검사 도구

선택 이유, 감수한 단점, 공식 정보 확인일을 Project Profile에 기록한다.

## 재현 가능한 환경

- 프로젝트 로컬 `.venv` 또는 승인된 격리 환경을 사용한다.
- 의존성 선언과 lock 파일을 Git에 포함하고 `.venv`는 제외한다.
- Codex는 프로젝트가 선택한 실행 명령을 사용한다. 예를 들어 `uv run`을 선택한 프로젝트에 임의로 다른 설치 방식을 섞지 않는다.
- Python과 주요 도구 버전을 Project Profile에 기록한다.

## 코드 구조

- Router는 HTTP 검증, 인증 문맥, request·response 변환을 담당한다.
- Application Service 또는 Use Case는 업무 흐름과 transaction을 조정한다.
- 핵심 규칙은 FastAPI, Pydantic, DB session에 불필요하게 결합하지 않는다.
- Repository와 external adapter는 DB·네트워크 구현과 매핑을 담당한다.
- dependency injection은 의존성 경계를 명확하게 하는 범위에서 사용한다.

단순 endpoint에 과도한 Command, Port, Adapter 계층을 만들지 않는다. 테스트와 변경 이유가 분리될 때만 추상화를 추가한다.

## Sync와 Async

sync/async는 유행이 아니라 실제 I/O, 드라이버, 동시성, 운영 복잡도를 기준으로 선택한다.

- async endpoint에서 blocking I/O를 직접 실행하지 않는다.
- sync와 async DB session을 무계획하게 혼합하지 않는다.
- background task가 중요한 업무 처리의 내구성을 보장한다고 가정하지 않는다.
- 재시도, 멱등성, 취소, timeout이 필요한 흐름은 명시적으로 설계한다.

## 모델과 데이터 접근

- HTTP validation model, application input, domain value, persistence model의 역할을 구분한다.
- 단순한 프로젝트에서는 의미 없는 변환 계층을 만들지 않는다.
- ORM 모델을 공개 API 계약으로 그대로 사용하지 않는다.
- DB session과 transaction 수명을 유스케이스 원자성과 맞춘다.
- 사용자 입력을 SQL 문자열에 직접 삽입하지 않는다.
- 적용된 migration 파일을 덮어쓰지 않는다.

## 오류와 보안

- 외부·DB 오류를 내부 의미가 있는 오류로 변환하고 원인을 보존한다.
- catch-all 후 성공 응답이나 빈 결과를 반환하지 않는다.
- request validation만으로 권한 검증이 끝났다고 가정하지 않는다.
- 로그와 validation error에 시크릿·개인정보가 노출되지 않게 한다.

## 테스트와 검증

- 핵심 규칙은 빠른 단위 테스트로 검증한다.
- API status, schema, auth는 HTTP 수준 테스트로 검증한다.
- DB query와 transaction은 필요한 경우 실제 DB 또는 승인된 통합 환경으로 검증한다.
- async 흐름은 timeout, cancellation, retry 조건을 테스트한다.
- `pytest`, formatter, Lint, 타입 검사, build 관련 실제 명령은 Project Profile에서 확정한다.

## 피할 패턴

- Router에서 DB transaction과 비즈니스 규칙 전체 처리
- 모든 의존성을 전역 singleton이나 숨은 module state로 관리
- sync/async 혼합을 임시 thread 우회로 숨김
- Pydantic model 하나를 모든 계층에서 재사용
- broad `except Exception` 후 오류 무시
- 타입 오류를 광범위한 `Any`와 ignore로 숨김
