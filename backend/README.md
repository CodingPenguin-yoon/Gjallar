# Gjallar Backend

FastAPI 기반 API·관찰·작업 실행과 PostgreSQL 저장 계층입니다.

- [전체 문서](../project-docs/README.md)
- [현재 구조·코드 위치·API/DB·복구 계약](../project-docs/architecture.md)
- [설치·실행·테스트·장애 대응](../project-docs/development.md)
- [작업·live 실행 승인 기준](../AGENTS.md)

세부 route는 `app/api/v1/`, DB 모델과 migration은 `app/db/`·`alembic/`, 검증은 `tests/`에서 확인합니다. 실제 구현 설명은 아키텍처에 한 번만 관리합니다.
