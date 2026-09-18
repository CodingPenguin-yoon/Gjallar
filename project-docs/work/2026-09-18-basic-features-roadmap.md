# 기본 기능 실사용 중심 로드맵 재구성

- 상태: `IMPLEMENTED` — 문서 방향 수정. 기능 구현이나 실환경 검증 완료를 뜻하지 않는다.
- 사용자 확정: 기본 기능을 빠르게 완성해 사용, 웹 + CLI 우선, TUI 개선 후속.

## 결정과 범위

서버/API를 먼저 나열하던 로드맵을 M1~M6의 사용자 업무로 재구성했다. 기능마다 서버·필요한 웹/CLI·검증을 연결하며 M2부터 사용을 시작하고 나머지를 추가한다. 기존 기능 ID와 구현 근거, 과거 work의 의미를 보존한다. PRD의 우선순위 문단도 같은 방향으로 갱신한다. 코드·아키텍처·실제 인프라는 변경하지 않는다.

상세 지원 조합과 범위 축소는 초안이다. 특히 OPS-03 후속 이동, 첫 환경, CPU/NIC/clone/backup/migration 지원 조건은 실행 전 확정해야 한다. 첫 M2 Goal에는 관리형 권한 경로와 웹·CLI를 포함한다. Goal 실행이나 live mutation을 시작하지 않는다.

## 검증과 남은 일

문서 간 방향·상대 링크·기존 기록 연결과 diff를 확인한다. 검증 결과: `git diff --check` 통과, `backend/tests/contracts/test_legacy_backend_cleanup.py` 10개 통과(문서 구조·상대 링크·레거시 제거 계약). 전체 제품 테스트와 live 검증은 문서 정리 범위에서 실행하지 않는다.

남은 일은 로드맵 초안의 제품 경계 확정과 첫 실행 work 작성이다.

## 후속 문서 정합성 점검

사용자의 두 문서 재검토 요청에 따라 PRD와 개발 안내를 현재 로드맵·코드·기존 검증 기록과 대조했다. PRD에 이후 합의된 대시보드 유지·나머지 웹 흐름 정리와 첫 버전 경계를 추가했고, 로드맵에 해당 UI 방향과 착수 순서를 연결했다. 개발 안내의 등록 기능 미구현·PostgreSQL 검증 전 설명은 현재 코드와 과거 통합 검사 결과에 맞게 수정했다. 사용자 연결 성공, 전체 환경 지원, 운영 복구 검증을 구분했다. 실행 명령·권한·DB 계약이나 제품 코드는 변경하지 않았다.

후속 수정 후 문서 계약 검사 10개와 `git diff --check`를 다시 통과했다. 문서 변경만 수행했으므로 전체 `verify`·container build·live 검증은 재실행하지 않았다.

## 커밋 전 통합 검증

사용자의 전체 작업 커밋·푸시 요청에 따라 CLI·TUI와 문서 변경을 포함한 현재 checkout을 검증했다.

- `pnpm run verify`: 통과. client 80 passed, backend 808 passed / 28 skipped, frontend tests·lint·build 성공. 로컬은 Python 3.14 / Node 26.8.1이며 Node 지원 버전 경고와 기존 dependency deprecation 경고가 있다.
- `pnpm run verify:container`: 통과. Python 3.13 backend 808 passed / 28 skipped. client-test와 Node 24 frontend 검사·production build는 유효한 Docker cache를 재사용했다. 서비스 기동·배포는 하지 않았다.
- `git diff --check`와 staged diff 검사: 통과. PostgreSQL 전용 28개 검사는 테스트 환경 미설정으로 skip됐고 live Proxmox 검증은 수행하지 않았다.
- 초기 sandbox 실행은 pnpm registry 접근과 Docker socket 제약이 있어 중단 또는 실패했으며, 승인된 실행 환경에서 위 검증을 완료했다. 검증 실패를 숨기는 설정 변경은 하지 않았다.
