# Gjallar Frontend

React·Vite 기반 운영 UI입니다. `/api/v1`의 cookie session을 사용하며 backend의 권한·관찰 상태·실행 가능 여부를 표시합니다.

- [전체 문서](../project-docs/README.md)
- [현재 구조·화면·API 계약](../project-docs/architecture.md)
- [설치·실행·테스트](../project-docs/development.md)
- [작업 기준](../AGENTS.md)

`src/app`은 route·navigation, `pages`는 화면 조합, `features`는 기능 흐름, `entities`·`shared`는 공통 model·API·UI를 담당합니다. `components`·`utils`에는 일부 기존 구현이 남아 있습니다. 화면 계약은 `tests/`와 실제 route에서 확인하고 목록을 별도로 복제하지 않습니다.
