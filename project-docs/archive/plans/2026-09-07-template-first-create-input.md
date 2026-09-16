# 템플릿 중심 생성 입력과 선택적 DB 프리셋

- 상태: `IMPLEMENTED`
- 날짜: `2026-09-07`
- 승인자: 사용자
- 승인 근거: 필수 DB 프로필 제거·템플릿 중심 입력 후속에 “좋아 진행하자”로 진행 승인
- 기준: [ADR-009](../../decisions/adr-009-proxmox-state-authority-and-create-history.md)

## 범위·선택

기본 UI는 Proxmox 템플릿 → 사양·대상·네트워크·접속 정보 → 검토·승인 흐름이다. additive `creation_mode=template` 요청은 DB 프로필을 조회하지 않는다. 템플릿의 node/VMID를 명시하고 현재 inventory에서 찾는다. 기본 사양은 템플릿에서 얻으며 cloud-init 사용자명은 사용자가 입력한다.

기존 profile 요청은 호환성을 위해 유지한다. mode 생략은 기존 profile 동작이다. 프리셋을 선택하면 DB에서 운영자 수정값과 해당 프리셋의 제한을 적용한다. 프로필 제한은 과거에도 선택한 프로필별 정책이며 새 직접 입력 경로의 전역 제한으로 복제하지 않는다. 프리셋 API 오류·빈 목록은 직접 입력을 차단하지 않으며 실패한 API를 로컬 가짜 프리셋으로 대체하지 않는다.

직접 입력의 안전 조건은 CPU·메모리·디스크 양의 정수, 관찰된 대상 노드 CPU·총 메모리 이내, template disk 이상·storage 여유 공간 이내, cloud-init/guest-agent 준비·SSH key 필수·비밀번호 로그인 금지, 명시한 template/node/bridge와 기존 static IP 검증이다. 템플릿 family를 Ubuntu로 고정하지 않는다. 작업 직전 fresh 재검증과 exact approval·idempotency·lock·recovery는 유지한다.

## 데이터·계약

직접 입력의 저장된 `profile_id`는 빈 문자열이며 DB 프로필 FK가 아니다. 승인·이력에는 선택 template와 입력 hardware/access/network를 기존 형태로 보존한다. `profile_hardware_limits={}`로 프로필을 선택하지 않았음을 표현한다. mode와 profile 동시 선택은 거부한다. mode를 바꾼 재실행은 기존 plan/approval identity 검증을 통과해야 한다.

schema 이관·데이터 삭제, VMID 재사용 소유권 변경, Jobs/artifact 폐기, 인증·권한·live gate 변경은 비범위다. UI의 고정 호스트/개인 사용자 기본값과 직접 경로의 프로필 필수 gate를 제거한다. 다른 화면의 레거시 정리는 하지 않는다.

## 단계와 완료 조건

1. 직접 template draft와 profile 없는 preflight를 구현하고 application의 각 계산·fresh 검증에서 DB profile 접근을 분기한다. DB 프로필 조회를 실패시키거나 빈 DB여도 직접 검토·승인이 가능하고, profile 경로의 수정값 보존 테스트가 통과해야 한다.
2. UI 기본값·템플릿 첫 배치·선택적 프리셋·payload를 연결한다. profile API 실패가 직접 검토를 막지 않고 템플릿 변경 시 사양이 적절히 반영되며 기존 승인 화면·실행 상태가 유지돼야 한다.
3. template 삭제/조건 변화·입력 범위·모드 혼합·승인 binding·DB 감사 기록을 검증한다. backend 전체, frontend tests/lint/build, UI read-only 확인, 문서 링크·diff 검사와 독립 quality-review를 수행한다.

## 되돌리기·중단

schema 변경 없이 해당 코드/UI만 되돌릴 수 있다. 새 직접 입력으로 저장한 이력은 삭제하지 않는다. 과거 버전은 새 요청 mode를 해석하지 못하므로 롤백 시 진행 중 직접 입력 작업을 먼저 확인하고 기존 recovery 지원 여부를 검증한다. 실제 VM 생성은 실행하지 않는다.

이 승인은 템플릿 직접 입력과 선택적 프리셋, 해당 범위의 불필요 코드 제거를 의미하며 DB 삭제·이력 소유권 이관·실환경 mutation 또는 배포를 의미하지 않는다.

## 구현 결과와 검증

- 템플릿 직접 입력은 DB profile 조회 없이 draft·preflight·plan·승인·작업 직전 검증을 수행한다. 선택적 프리셋은 기존 DB 설정을 보존한다. 빈 `profile_id`를 허용하며 schema는 변경하지 않았다.
- UI의 로컬 복제 프로필 3개, 고정 노드·개인 사용자 기본값과 프로필 필수 gate를 제거했다. 프리셋 조회 실패에도 직접 입력이 가능하다.
- backend 전체: **624 passed, 6 skipped**. 직접 입력 테스트 16개에 프로필 조회 금지, 사양·모드 검증, 모의 runner의 생성 완료·DB 이력·중복 실행 방지를 포함한다. frontend 17개 테스트 스크립트, ESLint와 production build가 통과했다.
- 별도 quality-review에서 확정 결함은 없었다. 격리된 브라우저 fixture에서 프리셋 API 실패 시 입력 가능 여부와 템플릿 변경 시 CPU·메모리·디스크 반영을 확인했고 임시 fixture는 삭제했다.
- 문서 계약·링크 검사 10개와 `git diff --check`가 통과했다. 로컬은 Python 3.14.6·Node 26.8.1로 기준 runtime과 다르며, `pnpm run verify`가 출력 없이 멈춰 각 검사를 직접 실행했다. Docker 접근 제한으로 container 기준 검증은 수행하지 못했다. PostgreSQL 통합·실제 Proxmox 생성·프로세스 재시작 복구는 이번 검증에 포함하지 않았다.
- 로컬 backend를 변경 코드로 재시작했으며 background recovery는 disabled로 유지했다. 실제 연결의 partial 관찰에서는 기존 complete-live gate로 생성을 차단한다.

완료된 VMID의 기존 소유권 guard와 Jobs/artifact·파일 guard는 아직 consumer가 있어 유지한다. 이력 소유권 이관이나 삭제는 후속 범위다.
