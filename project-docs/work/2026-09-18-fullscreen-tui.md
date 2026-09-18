# 전체 화면 TUI

- 상태: `IMPLEMENTED` — 사용자 요청: k9s처럼 전체 터미널에서 선택하는 UI
- 범위: 기존 client application 위 전체 화면 탐색·목록·상세·검색·입력·연결 선택. CLI JSON 계약과 서버 권한·session·설치·등록 계약은 유지한다.
- 비범위: 신규 VM mutation, 실제 설치/Proxmox 변경, 인증·저장 구조 변경.

## 계획과 완료 조건

1. macOS/Linux Python 표준 curses로 전체 화면·방향키·단축키·한글 출력을 구현한다. 작은 화면·크기 변경·종료 시 터미널 복원을 확인한다.
2. 기존 로그인·조회·설치·Proxmox 등록을 화면 내 입력/결과와 연결한다. 저장된 연결을 선택하며 비밀번호를 출력하지 않고 기존 명시적 실행 확인을 유지한다.
3. 격리 테스트와 PTY 실행으로 키 조작·오류·검색·비밀번호 비노출·종료를 검증하고 패키지를 재설치한다. 실제 서버 로그인/Proxmox 검증과 구분한다.

## 결과

- `terminal.py`: 전체 화면·탐색 패널·검색·상세·스크롤·마스킹 입력·연결 선택·작은 화면 안내·터미널 복원. 한글은 읽을 수 있게 출력하고 제어문자는 escape한다.
- `tui.py`: 기존 Application/설치/등록 함수를 호출하는 controller. 실패한 로그인 뒤 저장된 연결을 다시 선택할 수 있고 오류 창의 Esc는 메뉴로 돌아간다.
- `cli.py`는 새 TUI 진입점을 사용하고 설치 계정 안내를 보완했다. bootstrap의 낡은 Proxmox 등록 미지원 문구도 현재 흐름에 맞췄다.
- `pnpm run verify` 통과: 당시 client 55개, backend 807개 통과·28개 skip, frontend test/lint/build 성공. 후속 client 수정 뒤 전체 client 56개 재검증 통과.
- 실제 PTY에서 alternate screen 진입·작은 화면/크기 복구·모의 API 로그인·비밀번호 비노출·logout 없는 종료·원래 terminal 복원을 확인했다. 기존 client mock API를 쓴 검증이며 실제 서버/PVE 로그인이 아니다.
- 현재 로컬 Python 3.14.6/Node 26.8.1에서 실행했다. 기준 Python 3.13/Node 24 container 검증과 실제 macOS Keychain 저장·Linux terminal·Proxmox 등록은 이번에 실행하지 않았다.
- 문서 계약 검사 10개와 `git diff --check`도 통과했다.
- CLI wheel을 저장소 client 가상환경에 재설치했다. 사용자 기존 설치·서버·연결 파일은 수정하지 않는다.
- 조회는 명시적 `r` 새로고침이며 동기식 서버 작업 도중 키 입력을 처리하지 않는다. 자동 polling·새 VM mutation은 범위 밖이다.

## 표현 보완

사용자의 Codex CLI 스타일 요청에 맞춰 고정 검정/청록 배경과 반전 선택 영역을 제거했다. 터미널 기본 전경·배경을 따르고, 선택은 `❯`와 굵기로 구분한다. 흐린 글자 속성 없이 여백·짧은 제목으로 정리했으며 입력란은 질문 바로 아래에 표시한다. 시작 메뉴에는 항목 간 여백을 추가했다. 변경 후 client 56개와 diff 검사를 통과했다.
