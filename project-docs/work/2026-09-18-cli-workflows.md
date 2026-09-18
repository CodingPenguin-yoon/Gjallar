# CLI 운영 흐름 완성

- 상태: `IMPLEMENTED` (코드·격리 검증; 실환경 업무 검증은 남음) — 사용자가 CLI 우선 설치·접속, 기존 VM 작업, 출력·오류 안내 구현을 승인했다.
- 기존 전체 화면 TUI 변경은 유지하되 추가 시각 작업은 중단한다.

## 범위와 완료 조건

1. 기본 도움말, 로그인할 서버 선택·계정 입력, 사람이 읽는 터미널 출력과 명시적 `--json`, 오류 후 다음 행동을 제공한다. 기존 파이프 JSON 사용은 유지한다.
2. 서버의 기존 VM 상세·시작·정상 종료·템플릿 생성 API와 Operation 조회를 연결한다. 생성은 계획 파일 → 검토·명시적 실행이며 서버의 checksum·권한·preflight·target lock을 재사용한다.
3. VM 변경은 정확한 node/VMID·요청 identity·사용자 확인을 요구한다. timeout/오류 뒤 자동 mutation 재전송 없이 동일 작업 조회를 안내한다. 서버 API/DB/인증·session 저장·recovery 계약은 변경하지 않는다.
4. 모의 transport 및 실제 backend 계약 테스트, CLI 프로세스·PTY 검사, 공통 검증을 실행한다. 실제 서버 health/사용자 로그인 후 조회는 별도로 기록한다.

## 위험·복구 경계

- live VM 변경·Proxmox 토큰 발급/ACL 변경은 이번 코드 구현 승인에 포함하지 않는다. 대상·영향을 별도로 승인받아야 한다.
- 생성 검토 파일은 사용자가 지정한 신규 로컬 파일에 0600으로 저장하며 기존 파일을 덮어쓰지 않는다. 서버 origin/profile에 결합하고 실행 요청에는 서버 계획 ID/checksum과 동일 payload를 사용한다.
- 계획도 서버 Jobs/Artifacts/Operation 기록을 만든다. 로컬 dry-run으로 표현하지 않는다. 계획 실패 뒤 기록을 임의 삭제하지 않는다.
- 변경 요청의 idempotency identity는 사용자가 명시한다. 결과 불명은 실패/성공으로 단정하지 않고 nonzero와 작업 조회 안내를 반환한다.
- rollback은 CLI 코드/패키지만 복원한다. 서버에 이미 기록·실행된 계획과 VM 변경을 되돌리거나 삭제하지 않는다.

## 결과

로컬 `127.0.0.1:8000/health`의 HTTP 200/healthy 확인. 저장된 `local-8000` 연결은 선택된 session이 없으며 사용자에게 로컬 비표시 로그인 실행을 요청했다.


### 구현 결과

- `cli.py`: 기본 도움말·공통 옵션·단일 연결 로그인·bootstrap/login 분리·memory shell. 기존 TUI는 `tui` 명령으로 유지했다.
- `workflows.py`: VM 상세·전원·생성 계획/실행·Operation 조회. POST는 재시도하지 않으며 후속 GET의 terminal 상태·coordination으로 완료를 판정한다. 사용자 확인·yellow 동의·서버/profile 결합·계획 checksum을 유지한다.
- `output.py`: TTY 표·요약, 파이프/명시적 JSON, 제어문자 escape·한글 안내. JSON 출력에 입력 prompt를 섞지 않는다.
- Application의 명시적 연결 선택과 authenticated request를 재사용했다. 서버 production 코드·DB migration·실행/복구 규칙은 변경하지 않았다.

### 검증

- 로컬 client 최종 80개 통과. 잘못된 대상/권한·yellow 미동의·red 차단·기존 검토 파일 보호·서버/profile 불일치·응답 유실 단일 전송·Operation 미완료·memory shell session·비밀번호 비노출을 포함한다.
- 실제 FastAPI+격리 SQLite 계약 검사에서 template 생성 계획→승인→실행→Operation 조회를 검증했다. Proxmox mutation runner만 모의 처리하며 실제 인프라 생성 검증은 아니다.
- `pnpm run verify`: client 79개, backend 808개 통과·PostgreSQL 전용 28개 skip, frontend test/lint/build 통과. 로컬 Python 3.14.6·Node 26.8.1로 기준 버전 차이는 컨테이너 검증과 구분한다.
- `pnpm run test:client:container`: Python 3.13에서 최종 80개 통과.
- 설치된 CLI 프로세스에서 도움말·JSON·오류 종료 코드·생성 예제 검사 통과. 실제 PTY에서 memory shell 로그인→조회→종료와 비밀번호/쿠키 비노출을 확인했다(모의 API).
- 문서 계약 10개와 `git diff --check` 통과. PRD 현재 제공 범위·아키텍처·로드맵·개발 안내를 갱신했다.

- `pnpm run verify:container` 통과: Python 3.13 client 79개, backend 808개 통과·28개 skip, Node 24 frontend stage와 runtime image build 성공(변경 없는 frontend/runtime 단계는 Docker cache 재사용). 기존 서버 재시작·배포는 하지 않았다.
- 후속 결과 GET에서 session이 만료돼도 원래 mutation 결과를 미확정으로 유지하도록 보완했다. 최종 client 80개와 실제 FastAPI 계약 2개를 재검증했고 최종 wheel을 재설치했다.
- 실제 설치의 `gjallar service status --human`: 앱·PostgreSQL 모두 running/healthy, installation_state ready. health 및 서비스 조회만 했으며 로그인/Proxmox 조회 증거와 구분한다.

### 남은 검증

사용자의 로컬 로그인 완료 확인이 아직 없어 실제 계정 로그인·Proxmox 자원 조회·VM mutation은 미검증이다. 로컬 서버 health 확인과 격리 계약 검사를 실환경 업무 완료로 표시하지 않는다. 관리형 read/power profile의 Create 제한도 유지한다.
