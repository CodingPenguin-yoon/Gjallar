# M1 설치·연결: 현재 흐름 조사와 첫 구현 범위

- 날짜: `2026-09-16`
- 설계 갱신: `2026-09-17`
- 상태: 제품 방향 `APPROVED`. M1-1·M1-2는 이번 사용자 승인으로 구현했으며 아래 실행 결과에 검증을 기록한다. 실제 설치·서비스 기동은 미실행. M1-3 이후 credential 설계는 `DRAFT`, 전체 M1은 진행 중이다. 초기 진단 우선 제안은 `SUPERSEDED`.
- 기준 커밋: `8feae46` — 요청 시 존재한 문서 통합·로드맵·VM 생성 진행 표시 변경을 보존했다.
- 이번 착수 범위: 설치 → 최초 계정 → Proxmox 연결 → 웹 첫 자원 조회를 코드·테스트와 대조하고 M1 첫 구현 범위와 검증 가능한 완료 기준을 정한다.

## 계획과 경계

1. AGENTS.md·PRD·M1 로드맵·아키텍처·개발 안내와 기존 diff를 확인한다.
2. 설치 진입점, 계정 bootstrap과 로그인, 연결 관찰/API/UI, inventory와 기존 테스트를 조사한다.
3. 현재 제공 기능과 공백을 구분하고 첫 구현의 범위·비범위·완료 기준·검증·복구 방안을 이 문서에 이어 기록한다.
4. 로드맵에는 조사와 구현의 상태를 구분해 반영하고 문서 계약·diff를 검증한다.

이번 변경은 조사·합의 문서에 한정한다. 실제 DB·계정·credential 변경, 서비스 실행, live Proxmox 호출, 설치 방식 전환과 CLI 인증 구현은 하지 않는다. 고위험 구현은 AGENTS.md에 따라 구체적인 범위·검증·복구를 먼저 기록한다. 최초 요청에 따른 커밋 이후 추가 commit·push는 별도 요청 대상이다.

## 후속 대화에서 합의한 방향 (`APPROVED`, 미구현)

사용자는 Proxmox에 먼저 로그인하고 필요한 권한의 토큰을 발급받아 계속 사용하는 연결 경험과, 시작 시 로컬 Gjallar 실행/기존 Gjallar 서버 접속 중 선택하는 방식을 승인했다. 제품 요구사항은 [PRD](../prd.md), 전체 완료 기준은 [M1 로드맵](../roadmap.md)에 반영한다.

| 시작 경로 | 준비와 최초 연결 | 운영 |
|---|---|---|
| 이 컴퓨터에서 실행 | 서비스·DB 준비 → 최초 Gjallar 계정 → Proxmox 로그인 → 기능·대상·권한 확인 → 전용 토큰 발급·권한 설정·저장·조회 검증 | 로컬 Gjallar API를 웹·CLI·TUI가 함께 사용 |
| 기존 Gjallar 서버 연결 | 클라이언트 준비 → Gjallar 주소·Gjallar 계정 로그인 → 해당 서버 자원 조회 | 로컬 DB나 Proxmox 토큰 없이 같은 서버 API 사용 |

기존 서버에 접속하는 행위는 새 Proxmox 연결을 만들거나 기존 연결을 변경하는 행위가 아니다. Proxmox 최초 연결은 Gjallar 관리자에게만 제공할 대상으로 설계한다. 로그인 성공만으로 token 생성·권한 부여가 가능한 것으로 판단하지 않는다.

토큰과 작업 기록은 선택한 Gjallar 서버에서 관리한다. CLI/TUI에 별도 Proxmox 직접 운영 경로를 만들지 않는다. Proxmox 로그인 비밀번호는 연결 과정에서만 사용하고 저장하지 않는다. 기능에 필요한 권한과 실제 부여 가능한 권한을 확인하며 토큰 권한 자동 확대를 하지 않는다. Gjallar 사용자 권한·실제 token 권한·대상 실행 조건을 모두 적용하고 Proxmox의 최종 거부를 존중한다.

선택한 연결을 다음 실행에 사용할 수 있게 저장하고 현재 접속 서버를 표시한다. TUI 종료·로컬 서비스 중지는 구분한다. 로컬 컴퓨터가 꺼지면 Gjallar 관찰도 멈춘다. Proxmox task 접수 후 클라이언트나 서비스가 종료돼도 외부 실행 취소를 가정하지 않으며 기존 미확정 결과·복구 계약을 유지한다.

### 방향 합의 당시 남겨둔 구현 계약

1. 두 시작 경로의 설치·실행·종료·재실행 계약, 지원 OS/CPU, 배포 도구와 PostgreSQL 준비 책임. 원격 연결만 선택한 경우 로컬 서버·DB를 설치하지 않는 완료 조건을 정한다.
2. 최초 관리자 설정과 CLI/TUI의 Gjallar 인증·session 보관·만료·로그아웃·연결 전환. 로컬 전용 노출과 원격 TLS/origin 정책을 구분한다.
3. Proxmox 인증서 확인·로그인/지원 MFA·token 소유 계정·권한 매핑·서버 측 보관과 암호화 키 관리. 로그인 정보를 CLI에서 Proxmox로 직접 전송할지 Gjallar를 경유할지 등의 최초 등록 transport는 아직 확정하지 않았다. 확정된 것은 운영 호출과 장기 token 보관의 서버 집중이다.
4. 발급 성공/응답 유실/저장 실패/재요청을 구분할 identity와 상태, 교체·폐기·연결 해제 절차. 어느 token이 생성됐는지 불명확할 때 자동 재발급·삭제하지 않는다. 생성한 token의 확인·폐기가 불가능하면 잔여 권한과 다음 조치를 알려야 한다.
5. 기존 env token 설정·현재 DB·작업 이력을 보존하는 전환과 복구 방안. 데이터 삭제나 기존 migration 수정으로 단순화하지 않는다.

세부 계획은 이 파일에 이어 작성한다. 실제 기능을 만들기 전에 authentication/secret·DB·배포·외부 token mutation 각각의 변경 범위·검증·복구를 먼저 정한다. 이번 합의는 제품 방향의 승인으로 기록하며 정확한 live target과 side effect 승인을 대체하지 않는다. 새 API·schema·command 이름이나 저장 방식을 임의로 확정하지 않았다.

검증은 두 시작 경로의 신규/기존 설치, 재실행과 종료, 잘못된 Gjallar 로그인/Proxmox 로그인 구분, 발급 권한 부족, token 비노출·서버 보관, 발급/저장 중단과 중복 요청, 실제 권한 변경·폐기, 웹/TUI의 같은 자원·권한 조회를 포함하도록 설계한다. 실패 시 이전 연결·계정·데이터를 보존하고 확인된 신규 자격 증명만 정리할 수 있어야 한다.

## 이전 세션 검증 기록 (`2026-09-16`)

- 기존 변경 커밋 전 `git diff --check` 통과.
- 기존 변경 커밋 전 `pnpm run verify` 통과: backend 762 passed, 23 skipped, 32 subtests passed; frontend 테스트·lint·production build 통과.
- 로컬 Node는 `26.8.1`로 기준 `24`와 달라 engine 경고가 있다. Python venv는 3.13을 사용한다. 이 결과를 기준 container·macOS/Linux 신규 설치 또는 live 검증 완료로 해석하지 않는다.
- 조사 중 `pnpm run verify:container` 통과: Python 3.13 backend 762 passed, 23 skipped; production image build 성공. Node 24 frontend test/lint/build 단계는 Docker cache를 재사용했다. 최초 sandbox의 Docker socket 접근 실패 뒤 권한 확장으로 실행했다. runtime entrypoint나 서비스는 실행하지 않았다.
- 23개 skip은 별도 PostgreSQL 테스트 URL이 필요한 통합 검사다. 실제 DB migration·동시성·재시작 검증 완료로 간주하지 않는다.
- 네트워크와 DB를 사용하지 않는 Python 재현에서 upstream 401/403이 같은 reason임을 확인했다. 환경을 비운 `allowed_origins()`에 port 8000 origin이 없음을 확인했고, stub의 정상 빈 list와 잘못된 object가 모두 `live`·노드 0개가 되는 현재 동작을 확인했다.
- 문서 작성 후 `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/contracts/test_legacy_backend_cleanup.py`: 10 passed. 문서 구조·링크와 레거시 계약 및 `git diff --check` 통과.
- 실제 macOS/Linux 신규 설치, 브라우저 조작, live Proxmox 조회/변경은 미실행이다. 기존 테스트와 위 재현을 제품 설치 완료의 증거로 사용하지 않는다.
- 후속 방향 합의 반영 후 문서 계약 테스트를 다시 실행해 10 passed를 확인했다. diff whitespace 검사 통과. 이번 후속 변경은 문서뿐이므로 전체 verify·container verify는 재실행하지 않았고 위 결과는 앞선 조사 시점의 기록이다.

## 현재 흐름과 코드 근거

경로는 저장소 루트 기준이다. 실제 설치·live 접속의 성공 여부가 아니라 현재 코드와 테스트에서 확인한 동작이다.

| 단계 | 현재 동작과 근거 | M1에서 남은 공백 |
|---|---|---|
| 로컬 설치 | `package.json`, `.env.example`, `development.md`: Python 3.13 venv·Node 24·pnpm 10.34.5·별도 PostgreSQL을 수동 준비하고 migration·seed·create-admin 후 `pnpm run dev` | 의존성/DB 사전 검사, 지원 OS·CPU·버전 행렬, 중간 실패 안내, 재실행 가능한 bootstrap 없음 |
| Container | `Dockerfile`은 Node 24 UI 빌드와 Python 3.13 API를 묶는다. `docker/entrypoint.sh`는 migration → seed → 선택적 admin bootstrap → 서버 순서이며 실패 시 중단 | PostgreSQL 제공·준비 검사 없음. 기존 DB도 매 시작 migration 대상이므로 단순 재시작을 안전한 설치 재시도로 간주할 수 없음 |
| 최초 계정 | `backend/app/auth/users.py`: `create-admin`은 기본 비밀번호 비표시 입력. `bootstrap-admin-from-env`는 환경 변수 두 개가 없으면 no-op, 한쪽만 있으면 실패. 같은 이름의 활성 admin은 비밀번호를 바꾸지 않고 유지하고, 같은 이름의 비활성/비-admin은 거부 | 웹 최초 계정 생성 없음. bootstrap은 전체 DB의 최초 admin 여부를 검사하는 방식이 아니라 **username 기준**이므로 다른 이름으로 재실행하면 추가 admin을 만들 수 있음. 이 동작 변경은 별도 인증·DB 설계 대상 |
| 로그인 | `backend/app/auth/api.py`, `sessions.py`, `frontend/src/app/App.jsx`, `pages/auth/LoginPage.jsx`: `/auth/me` → `/login` → `/auth/login` cookie session → 연결 조회. 계정 관리용 Python CLI는 DB에 직접 접근 | 이것은 제품 CLI 인증·조회가 아님. session 저장·만료·logout·출력/종료 코드 계약이 필요. `/auth/me` 요청 오류도 UI에서 anonymous로 처리되어 DB/API 장애와 로그인 필요를 구분하지 못함 |
| 브라우저 origin | `backend/app/auth/config.py`, `origin.py`: unsafe request의 Origin은 allowlist에 있어야 한다. 기본값은 localhost/127.0.0.1의 frontend port 5173 | Docker의 기본 8000 origin이나 서버 hostname은 자동 허용되지 않는다. 같은 origin 배포라도 `GJALLAR_ALLOWED_ORIGINS`가 없으면 브라우저 login이 `403 FORBIDDEN_ORIGIN`으로 막힐 수 있음. 현재 기본 설치 단계에는 이 설정 안내가 충분하지 않음 |
| 연결 설정 | `backend/app/proxmox/inventory.py`: process env와 `.env`의 URL/token/TLS 설정으로 단일 adapter 구성. 필수 값 부재는 `unconfigured`. `.env` 로드는 최초 한 번이며 기존 env를 덮어쓰지 않음 | 웹 저장 API/폼 없음. 파일 수정 뒤 재조회 버튼만으로 설정이 반영되지 않으며 process 재시작 또는 container 재생성이 필요 |
| 연결 조회 | `backend/app/api/v1/inventory.py` → `workloads/inventory.py` → `setup_integration/proxmox_connection.py`. `/setup/proxmox/connection`은 viewer 이상에게 상태를 반환하는 GET | 전체 inventory 관찰이므로 단순 ping이 아니다. 401/403을 같은 `proxmox_authentication_failed`로 축약. UI에는 원인별 구체적 조치가 부족 |
| 부분 관찰 | `backend/app/proxmox/inventory.py`, `models.py`: storage/network/config/guest-agent 실패 source·target을 availability에 보존하고 partial snapshot 제공 | 일부 source의 예외는 성공 여부만 남겨 TLS/401/403 원인이 소실된다. 최상위 연결 reason만 세분화해도 모든 권한 진단이 완성되는 것은 아님 |
| 재조회 | `frontend/src/app/App.jsx`의 retry는 같은 GET을 호출. query는 `observe()`를 사용하며 snapshot/detail cache 기본 TTL은 10초 | 강제 fresh 조회가 아니며 즉시 새로운 관찰을 보장하지 않음. 이번 첫 구현안에서는 cache 정책을 변경하지 않고 관찰 시점과 안내로 제약을 밝힘 |
| 첫 자원 | `api/v1/router.py`의 viewer guard 아래 `/nodes`, `/vms`, `/templates`, `/storage`, `/networks` 제공. `/`와 `/instances`, `/instances/:vmid`는 연결 boundary 뒤에 있음. `features/workloads/inventory/model.js`는 nodes/VM 관찰과 별도 Insights/Operations 문맥을 조합 | VM 목록과 템플릿 API는 있지만 첫 설치 완료를 확인하는 통합 절차·제품 CLI가 없음. 권한 범위 밖 자원이 없는 것으로 보이는 경우까지 전체 cluster 관찰로 보장할 수 없음 |

유지할 계약: snapshot 부재 시 inventory API는 `503`, 정상적으로 조회한 빈 목록은 성공이다. partial snapshot은 읽기 가능하고 source·관찰 시점·누락을 표시한다. `live`는 mutation 권한 검사 통과가 아니다. fake fixture는 제품 연결 성공으로 쓰지 않는다. 계정/Jobs/Operations 접근은 Proxmox 연결 실패와 분리한다.

추가 관찰: `_list_nodes_payload`·`_list_qemu_payload`는 list가 아닌 payload를 빈 목록으로 변환한다. stub으로 `/nodes`가 object를 반환해도 `live`·노드 0개가 되는 현상을 재현했다. 첫 진단 구현에서 기존 허용 payload와 테스트를 확인한 뒤 명시적 관찰 실패로 처리할 범위를 정한다. 임의 응답을 광범위한 fallback으로 수용하지 않는다.

## 초기 제안: 연결 실패 진단과 첫 조회 안내 (`SUPERSEDED`)

아래는 조사 직후의 제안이다. 후속 합의에 따라 진단 개선만 먼저 하는 순서는 대체됐다. 진단·회귀 요구사항은 새 연결 흐름에 필요한 근거로 남기며, 아래 비범위와 완료 판정은 새 M1 구현 범위를 제한하지 않는다.

**사용자 결과:** 기존 방식으로 서버와 계정을 준비한 사용자가 로그인과 연결에서 막힌 이유를 구분하고, 수정할 설정·재시작 필요 여부를 확인해 기존 자원 조회로 이어간다. 설치 자동화 완료를 의미하지 않는다.

이 범위를 먼저 제안하는 이유는 설치 방식·credential 저장·CLI 인증 결정을 기다리지 않고 기존 API와 화면을 재사용할 수 있기 때문이다. 진단 결과는 이후 bootstrap·CLI에서도 공통 근거가 된다.

### 포함과 변경 지점

1. **최상위 Proxmox 조회 진단:** 기존 connection `state/source/freshness/reason`과 HTTP 계약은 유지하고, 추가 진단 필드로 upstream 401 인증 실패와 403 권한 부족을 구분한다. 예를 들어 `diagnostic_code`를 새 필드로 추가하되 실제 명칭과 DTO는 구현 시 기존 consumer를 확인해 고정한다. TLS·timeout·unreachable·기타 API 거부·형식 오류는 제한된 코드로 표현한다. 알 수 없는 원인을 권한 부족으로 추정하지 않는다.
2. **호환 처리:** 구형 `reason`을 읽는 consumer는 계속 동작하고, 새 UI는 새 필드가 없는 응답에서 기존 안내로 돌아간다. Gjallar의 `AUTH_REQUIRED`·`AUTH_FORBIDDEN`·`FORBIDDEN_ORIGIN`과 Proxmox upstream 진단을 구분한다. API route와 session/role 검증은 변경하지 않는다.
3. **첫 조회 안내:** 기존 `ProxmoxConnectionBoundary`와 로그인 실패 안내에 원인별 다음 행동을 연결한다. 미설정은 필요한 변수 이름과 설정 적용 절차, TLS는 인증서 신뢰/주소 확인, 401은 token 설정 확인, 403은 접근 범위/권한 확인, timeout/접속 불가는 backend에서의 경로·주소 확인을 안내한다. TLS 검증 자동 해제나 admin 권한 일괄 부여를 해결책으로 삼지 않는다.
4. **설치 문서 보완:** `development.md`의 기존 로컬·Docker 절차에 실제 browser origin 설정, 프로세스 env 적용/재시작, `/health`와 로그인·inventory 성공의 차이, 정상 empty와 실패/partial의 확인 방법을 넣는다. 실행 명령은 이 work 문서에 중복 관리하지 않는다.
5. **회귀 검증:** `test_api_v1_inventory.py`, `test_inventory_adapter.py`, `test_api_v1_auth.py`, `frontend/tests/proxmoxConnection.test.mjs`, `authFlow.test.mjs`의 기존 패턴을 확장한다. helper만 검사하지 않고 adapter → query → authenticated HTTP 응답 → 화면 매핑을 확인한다.

### 비범위

자동 설치기·DB provisioning·Compose/systemd 추가·OS/CPU 지원 확정, 최초 계정 정책 변경, credential 저장/수정 API, CLI 인증과 session 저장, 권한 자동 부여, source별 예외 모델의 전면 확장, cache/refresh 정책 변경, 새 관찰 수집기, VM mutation은 제외한다. partial source의 상세 원인은 현재 근거가 없으면 확인 불가로 남기며 M1 후속 범위로 유지한다.

### 완료 기준과 재현 방식

| 입력/상황 | 첫 구현 완료 조건 | 검증 |
|---|---|---|
| 필수 연결 값 누락 | 변수 이름만 안내, `unconfigured`, 자원 조회 503, 샘플 데이터 없음 | 환경 값을 격리한 adapter/API 계약 테스트 |
| Proxmox 401 / 403 | 서로 다른 진단과 다음 행동, 기존 reason/state/HTTP consumer 호환 | requests HTTPError stub을 실제 관찰 경계로 통과시키는 테스트 |
| TLS / timeout / 연결 거부 / 기타 오류 | 정해진 진단으로 분류, 원시 exception·URL·header·body를 출력하지 않음 | 합성 민감 문자열을 넣은 예외로 응답·출력 비노출 확인 |
| 잘못된 inventory payload / 정상 빈 목록 | 형식 오류를 정상 empty로 표현하지 않고, 유효한 빈 list는 성공으로 유지 | nodes/QEMU 응답 형태별 adapter 테스트 |
| Gjallar session 없음/만료, origin 거부 | Proxmox credential 오류로 표시하지 않음. 서버 role/origin 계약 보존 | 인증된 TestClient 흐름과 frontend 오류 매핑 테스트 |
| 정상 / partial / snapshot 없음 | source·observed_at·누락 의미 보존. partial은 기존 읽기 경로를 유지하고 기존 action gate가 완화되지 않음 | 기존 inventory·Create/Start/Shutdown 회귀 검사 |
| 설정 수정 뒤 재조회 | env 재적용·재시작 안내 및 cache TTL 제약을 명시. 새 시각을 관찰하지 않았는데 갱신 완료라 말하지 않음 | UI 매핑 검사 및 mock 응답을 사용한 브라우저 확인 |
| 웹 첫 조회 | 로그인 → 연결 확인 → `/instances`에서 VM 조회, `/instances/:vmid` 상세 이동. VM 없음/관찰 실패도 구분 | API fixture를 사용하는 브라우저 확인. 실제 Proxmox 검증과 분리 |

모든 조건과 문서 계약·`git diff --check`·로컬 verify·기준 container verify가 통과해야 이 구현안을 `IMPLEMENTED`로 바꾼다. 브라우저 검증은 현재 source/regex 테스트만으로 대체하지 않는다. live 검증이 없으면 실제 설치/연결 재현은 미검증으로 남긴다.

### 위험 경계와 복구

- 변경 대상은 관찰 결과의 분류·직렬화·UI 안내다. 인증/인가 판정, secret 수집·저장, DB schema·migration·이력·transaction, mutation gate·lock·recovery를 변경하지 않는다.
- 진단은 allowlist 코드만 전달한다. 비밀값을 포함할 수 있는 upstream 응답을 통째로 저장/출력하는 설계로 확장하지 않는다. secret 처리 정책이나 인증 의미 변경이 필요해지면 이 문서의 범위·검증·복구를 먼저 갱신한다.
- API는 추가 필드 방식으로 구형 consumer 호환을 보존한다. 기존 reason 의미를 직접 교체하거나 route를 바꿀 필요가 생기면 비호환 변경 영향과 전환안을 먼저 기록한다.
- 롤백은 이 구현에서 추가한 분류/표시/테스트 변경만 되돌리는 코드 변경으로 한다. DB downgrade·row 삭제·credential 변경·Proxmox 역변경이 필요 없는 범위다. 사용자 기존 변경과 기준 커밋은 보존한다.
- 실제 DB migration·서비스 배포·live smoke는 여기의 테스트 통과로 승인되지 않는다. live 작업은 exact target과 side effect를 별도 승인받는다.

## 조사 당시 확인한 후속 공백

다음은 조사 당시 확인한 공백이다. 현재 순서와 결정 상태는 위 합의 및 다음 구현 계약을 우선한다. 별도 work 문서를 미리 만들지 않는다.

- macOS 로컬과 Linux 상시 서버의 배포 방식, OS/CPU/버전과 테스트 행렬, DB 준비 책임. 현재 Dockerfile 존재나 한 호스트의 build를 지원 환경 인증으로 쓰지 않는다.
- 새 DB 설치와 기존 DB 업그레이드를 구분하는 bootstrap, 단계별 실패·재실행·설정/데이터 보존. `20260824_0029`의 기존/production DB 승인 경계를 유지한다.
- 계정 bootstrap의 재실행 정책과 credential 보관, CLI의 기존 session API 사용 여부·안전한 저장·만료·logout·구조화 출력·종료 코드. 로컬 계정 관리 CLI를 제품 CLI로 확장해 DB 직결을 우회 경로로 삼지 않는다.
- partial source별 인증/권한/연결 진단과 실제 필요한 Proxmox 권한 검증. 현재 코드를 조사한 것만으로 PVE 버전별 최소 privilege 목록을 확정하지 않는다.
- 지원 환경별 신규 설치·서비스 재시작·중간 실패 재시도와 동일 계정의 웹/CLI 자원 조회를 재현한다. 설치 시작부터 실제 자원 확인까지 시간과 막힌 단계를 측정하고, 실제 관찰 범위·누락을 기록한다.

## 이전 세션 결과 (`2026-09-16`)

요청한 문서와 코드·기존 테스트 대조를 완료하고 후속 대화의 로컬 실행/기존 서버 접속·로그인 후 token 발급 합의를 같은 문서에 이어 기록했다. PRD는 제품 경험, 아키텍처는 미구현 목표 경계, 로드맵은 M1 범위·완료 기준과 다음 설계를 갱신했다. 초기 진단 우선 제안은 대체 상태로 표시했다. 기능 구현·배포는 하지 않았으므로 개발 안내의 현재 실행 명령은 변경하지 않았다.

## 2026-09-17 설계 구체화 (`DRAFT`, 미구현)

### 상태와 이번 조사 범위

시작 시 HEAD는 `8feae46`이었다. `architecture.md`, `prd.md`, `roadmap.md`, `work/README.md`의 미커밋 diff와 이 미추적 작업 문서를 먼저 읽고 보존했다. 이번 추가 변경도 문서에 한정한다. 제품 합의는 위 `APPROVED` 절, 현재 구현은 아키텍처와 아래 코드 근거, 이 절의 API·DB·명령·배포 이름은 **구현 제안**이다. 공식 소스를 읽었다는 사실과 대상 환경에서 검증했다는 사실을 구분한다. 실제 설치·서비스 기동·migration 적용·Proxmox 접속 및 mutation·commit·push는 하지 않는다.

권장안은 **같은 Compose 배포 묶음의 Gjallar 단일 이미지 + PostgreSQL, 별도 Python CLI/TUI, 서버에서 수행하는 Proxmox 로그인과 토큰 등록**이다. 첫 구현은 기존 서버 연결의 작은 수직 단위로 시작하고, 로컬 설치·credential 등록을 차례로 붙인다. 이는 합의된 두 시작 방식의 단계적 구현이며 초기 진단 우선안으로 돌아가는 것이 아니다.

### 1. 현재 코드와 재사용 경계

| 조사 대상 | 확인한 현재 구현 | 재사용과 새로 필요한 경계 |
|---|---|---|
| `Dockerfile`, `docker/entrypoint.sh` | Node 24 UI build + Python 3.13 API 이미지. 시작 시 migration·seed·env admin 실행. DB container와 installer 없음 | 이미지와 build 검증 재사용. 설치/upgrade와 일반 serve를 분리해야 하며 현 entrypoint를 그대로 bootstrap 재시도에 쓰지 않음 |
| `auth/users.py`, `passwords.py`, `db/models.py` | PBKDF2 hash, users/sessions, username 기준 env bootstrap, last enabled admin 보호 | hash·검증·role·관리 API 재사용. 최초 설치 전용 zero-user transaction을 추가해야 함. 기존 `create_user()`는 자체 transaction이므로 외부 transaction으로 감쌌다고 원자적이 되지 않음 |
| `auth/api.py`, `sessions.py`, `config.py`, `origin.py` | login의 `Set-Cookie`와 `expires_at`, SHA-256 session hash 저장, 기본 8시간 절대 만료. `/me`는 비로그인도 200 + `authenticated=false`. Origin 없는 unsafe 요청 허용 | CLI도 cookie API 사용 가능. Bearer/JWT/refresh token 불필요. 현재 `/me`에는 만료 시각이 없으므로 login 응답의 값을 클라이언트가 보관. Origin 검사를 완화할 필요 없음 |
| 계정 변경 | disable·관리자 password reset은 session revoke. 본인의 change-password는 현재 session 유지, 나머지 revoke. role은 매 요청 users에서 읽음 | CLI가 role·만료를 독자적으로 허용 판정하지 않음. 서버 판정이 최종 |
| `proxmox/inventory.py`, `client.py` | env token을 읽는 독립 read adapter / mutation client. inventory cache는 process-local. mutation 오류가 원시 response/error 정보를 담을 수 있음 | inventory DTO·조회·action 검증 재사용. credential provider를 주입하는 seam 필요. 로그인/발급에는 원시 오류가 흐르는 기존 mutation client를 그대로 사용하지 않음 |
| `setup_integration/proxmox_connection.py`, `workloads/inventory.py` | 연결 관찰과 fresh/partial/unavailable gate. 401/403은 현재 같은 reason. complete와 mutation 권한은 다름 | 기존 reason/HTTP 의미 유지, 후속 additive diagnostic/capability 필드. 권한별 대상 제외를 장애/빈 자원으로 오인하지 않도록 selected scope와 missing source 분리 필요 |
| `operations/core/` | intent/idempotency·version/checksum fence·projection/event. operation_type은 문자열이나 상태·consumer 제약 존재 | 공개 application/repository port를 통한 비밀 없는 등록 작업 이력 재사용 가능. 새 operation type의 serializer·UI·read 권한도 검증 필요 |
| `operations/locks/`, `recovery/`, `target_lock.py` | lock은 VMID locator와 네 action allowlist. recovery 역시 네 GET-only kind, 기본 disabled runner | VMID 0 같은 가짜 대상으로 토큰 발급을 끼워 넣지 않음. connection별 등록 attempt/CAS는 setup 소유로 설계. 기존 VM lock·lease·runner에 token mutation retry를 추가하지 않음 |
| `db/session.py`, `jobs/`, Alembic | PostgreSQL transaction, 기존 Jobs/artifact/history 보존, 적용된 `0029`는 roll-forward-only | session_scope와 기존 history reader 재사용. secret을 Jobs/artifact JSON에 저장하지 않음. 기존 revision·cluster_id·operation ownership은 유지 |
| 기존 테스트 | `test_api_v1_auth.py`, `test_auth_bootstrap.py`, route registry, inventory/frontend connection, `test_target_operation_lock.py`, recovery 및 PostgreSQL 통합 검사 | 각 구현 단위에서 관련 회귀를 실행. SQLite 테스트는 PostgreSQL 경쟁/잠금 검증을 대체하지 않음 |

새 `ProxmoxCredentialProvider` 제안은 endpoint·TLS trust·credential revision을 한 snapshot으로 반환한다. read와 mutation의 클래스 분리는 유지하되 credential source는 공유한다. cache key에는 secret 원문 대신 connection/revision/trust revision을 쓰고 전환 시 폐기한다. API assembly에서 port를 주입하며 workloads/operations가 setup의 ORM model을 직접 읽지 않는다.

### 2. 배포·runtime·PostgreSQL 권장안

| 대안 | macOS 로컬 / Linux 상시 서버 | 유지보수 판단 |
|---|---|---|
| 호스트 Python·Node·PostgreSQL + launchd/systemd | OS별 설치·권한·서비스·DB upgrade 절차가 다름 | 현재 개발 실행은 유지하되 제품 설치 기본으로 채택하지 않음 |
| Docker Compose + 기존 앱 이미지 + PostgreSQL | macOS는 Docker Desktop, Linux는 Docker Engine + Compose plugin. 같은 manifest·이미지 사용 | **권장**. 기존 build 자산을 활용하고 runtime·DB 조합을 한곳에서 검증 |
| Podman / Colima / 임베디드 PostgreSQL / 단일 실행 파일 | VM/runtime 차이 또는 플랫폼별 패키징·DB lifecycle 추가 | M1 공식 지원 범위 밖. 대체 runtime이 된다고 시험 없이 선언하지 않음 |

Compose 제공 형태와 OS별 설치 조건은 [Docker Compose 공식 안내](https://docs.docker.com/compose/install/), [macOS](https://docs.docker.com/desktop/setup/install/mac-install/), [Ubuntu](https://docs.docker.com/engine/install/ubuntu/)를 확인했다. Docker 설치·기동·호스트 권한 변경은 installer가 몰래 수행하지 않고 의존성 단계로 안내한다. 원격 연결만 선택하면 Docker 검사·설치·DB 준비를 전혀 하지 않는다.

지원 **검증 목표**는 macOS arm64/x86_64의 출시 시 Docker Desktop 지원 OS, Linux Ubuntu 24.04 LTS amd64/arm64다. Linux 상시 운영을 기준으로 하며 macOS는 로그인 세션·절전·Docker Desktop 종료의 영향을 받는 로컬 운영이다. 다른 배포판·Windows·rootless/대체 runtime은 M1 완료 주장에 포함하지 않는다. 각 OS/CPU의 실제 설치 테스트 전에는 지원 완료로 표시하지 않는다.

새 관리형 DB는 PostgreSQL **17 계열**을 권장한다. 서버·DB 이미지는 release manifest에서 검증된 patch와 digest로 고정하고 `latest`를 쓰지 않는다. 17은 [PostgreSQL 공식 지원 정책](https://www.postgresql.org/support/versioning/)에 있는 유지보수 계열이며, 이 선택은 Gjallar 호환 검증 완료를 뜻하지 않는다. 기존 외부 PostgreSQL은 제자리 보존하고 major upgrade나 관리형 volume으로의 이동을 자동 실행하지 않는다.

배포 계약 제안:

1. `gjallar` 앱 1 process/1 replica와 `postgres` service를 기본으로 한다. 기존 in-process recovery 설정을 보존한다. Redis·queue·별도 worker를 추가하지 않는다. 앱 container에 Docker socket을 mount하지 않는다.
2. 로컬은 `127.0.0.1`의 선택 port만 publish하고 DB는 host에 publish하지 않는다. app 내부 bind와 host 공개 bind를 구분한다. `GJALLAR_ALLOWED_ORIGINS`에는 실제 UI origin을 설정한다. 현재 기본값은 frontend 개발 port만 포함하므로 production port의 브라우저 login 성공을 가정하지 않는다.
3. 상시 서버의 원격 공개는 같은 이미지 앞의 Caddy TLS profile을 기본 제안한다. 기존 검증된 TLS proxy가 있으면 이를 사용한다. canonical HTTPS origin·Secure cookie·신뢰할 proxy 범위를 명시한다. [Caddy 자동 HTTPS](https://caddyserver.com/docs/automatic-https)는 DNS/도달성 조건이 필요하며 private CA는 클라이언트 신뢰 배포가 별도다. 내부 주소에 공인 인증서가 자동 발급된다고 안내하지 않는다.
4. PostgreSQL은 전용 named volume, 별도 bootstrap superuser와 앱 DB role을 사용한다. 앱 role은 자기 DB/schema만 소유하고 cluster superuser/CREATEDB/CREATEROLE 권한을 갖지 않는다. DB 비밀번호는 0600 host secret file → Compose secret mount로 전달한다. 앱에 DB URL `_FILE` 입력을 추가하는 것은 후속 구현이며 현재 지원 기능이 아니다.
5. `pg_isready` health 이후 앱 role의 실제 DB 연결과 expected Alembic revision을 검사한다. [Compose readiness 조건](https://docs.docker.com/compose/how-tos/startup-order/)만으로 schema 준비를 보장하지 않는다. 일반 serve는 revision 불일치에서 중단하며 migration/seed/admin을 실행하지 않는다. 새 installer용 명시적 serve 경로를 먼저 추가하고 기존 entrypoint의 즉시 변경은 피한다.
6. 생성 파일·volume·이미지 digest·schema revision·완료 단계만 설치 manifest에 기록한다. secret은 기록하지 않는다. manifest/volume 충돌, 다른 설치의 DB, 불명확한 기존 데이터는 정지한다. manifest만 믿고 DB가 비었다고 판단하지 않는다.
7. 업그레이드는 backup/복원 가능성 확인 → 앱 drain/정지 → 별도 one-off migration → revision 확인 → 새 앱 기동이다. 기존 DB의 `0029` preflight와 별도 적용 승인 경계는 그대로다. DB major upgrade·자동 `down -v`·uninstall 시 volume 삭제는 제공하지 않는다.

### 3. Bootstrap과 최초 관리자

전체 M1 완료 시 사용자 흐름 제안:

| 단계 | 이 컴퓨터에서 Gjallar 실행 | 기존 Gjallar 서버 연결 |
|---|---|---|
| 선택 | 설치 위치·port·local 노출 확인 | Gjallar HTTPS 주소·연결 별칭 입력 |
| 준비 | Docker/Compose·CPU·disk·port·volume 검사, 고정 release 다운로드·검증, 전용 DB 준비 | 클라이언트만 준비. Gjallar 인증서 검증 |
| DB/계정 | 새 빈 DB 초기화 → 최초 관리자 설정 → 일반 serve | 기존 Gjallar 계정 로그인. 신규 관리자 생성 없음 |
| 로그인 | 이후 동일한 Gjallar API login | 동일한 Gjallar API login |
| Proxmox | 미설정일 때 관리자에게 새 연결 wizard 제공 | 이미 설정된 서버 자원 조회. 관리자라도 접속만으로 재설정하지 않음 |
| 완료 | token 첫 조회의 범위·누락과 현재 서버 표시 | 서버가 제공한 범위·누락과 현재 서버 표시 |

최초 관리자는 **설치 호스트에서 실행하는 일회성 server maintenance command**로 만든다. native bootstrap이 비표시 입력·확인을 받고 container의 전용 `setup-admin` 진입점(제안)에 stdin pipe로 넘긴다. remote client가 DB driver를 갖거나 DB에 직접 접속하지 않는다. 이 예외는 설치 중 서버 초기화만이며 운영 API 우회 경로가 아니다. 공개된 unauthenticated `create first admin` HTTP endpoint와 bootstrap 비밀번호 env는 새 경로에 넣지 않는다. 웹은 생성 후 일반 login으로 들어간다. 상시 Linux 서버도 해당 호스트에서 bootstrap을 실행하고 원격 클라이언트는 이후 로그인만 한다.

- 새 설치로 확인된 DB에 한해 revision 일치와 **users 전체 0건**을 조건으로 한다. enabled admin 0건만으로 계정을 추가하지 않는다. 과거 작업 이력이 있는데 users가 없는 DB도 신규 설치로 추정하지 않는다. 기존 사용자/비활성 관리자만 있는 DB는 별도 계정 복구 절차로 보낸다.
- PostgreSQL에서 users에 대한 동시 insert까지 직렬화하는 transaction lock을 잡고 zero-user 검사·admin insert·비밀 없는 audit를 한 transaction에서 처리한다. 기존 users validation/hash를 재사용하되 transaction을 받는 내부 helper를 분리한다. 기존 관리 API·last-admin 보호의 의미는 유지한다.
- 이름·비밀번호는 argv/env/manifest/log/HTTP URL에 넣지 않는다. 성공 후 pipe와 메모리 참조를 정리한다. 기존 비밀번호 hash 알고리즘을 이번 M1의 편의상 바꾸지 않는다.
- 재실행에서 사용자가 있으면 로그인으로 이동하고 덮어쓰지 않는다. 생성 commit 후 응답 유실도 같은 처리다. 설치 단계 상태는 관리자 비밀번호가 맞는지 검사하는 인증 수단이 아니다.
- app 기동 전 failure는 DB/volume을 보존한다. 최초 관리자 생성만 성공했어도 다음 실행에서 추가 admin을 만들지 않는다. 기존 `bootstrap-admin-from-env`는 legacy 운영 호환으로 남기고 새 installer는 호출하지 않는다.
- TUI의 종료는 client process만 닫는다. service stop은 별도 명령·대상 표시 후 graceful stop이며 VM/Proxmox task를 취소하지 않는다. DB volume·connection·session/작업 기록은 보존한다. 앱 종료 시 새 mutation 진입을 막고 기존 durable checkpoint를 존중한다.

### 4. CLI/TUI와 Gjallar session

**Python 3.13 + Typer CLI + Textual TUI + HTTPX**를 권장한다. Python API 생태계·기존 테스트 패턴을 활용하고 둘이 같은 `GjallarApiClient`/application service를 호출한다. Go/Bubble Tea는 독립 binary에 장점이 있지만 언어·release matrix를 하나 더 관리해야 하고, Node/Ink는 frontend 지식을 활용해도 backend와 다른 client 도구 묶음이 필요하다. 무의존 단일 binary는 M1 목표가 아니므로 Python wheel과 `uv tool install`을 우선한다. [Typer](https://typer.tiangolo.com/), [Textual 테스트](https://textual.textualize.io/guide/testing/), [uv 도구 설치](https://docs.astral.sh/uv/guides/tools/)를 근거로 한 기술 제안이다.

`client/`를 backend와 독립 package로 두고 SQLAlchemy·Alembic·Proxmox SDK를 의존하지 않는다. release wheel/lock/hash와 Python 범위를 고정하고 검증된 artifact에서 설치한다. package index 이름 확보·배포 pipeline은 아직 없다. 문서의 `gjallar connect/login/logout/connection use/status/nodes/vms/templates/tui`는 제안한 CLI surface이며 현재 실행 가능한 명령이 아니다. bootstrap은 후속 optional install 모듈에서 고정 argv의 Docker Compose만 호출하며 임의 shell/SSH를 받지 않는다.

| 항목 | 클라이언트 계약 제안 |
|---|---|
| 연결 정보 | OS별 application config 아래 versioned JSON. 별칭·canonical origin·cookie 이름·CA 참조·마지막 선택만 저장. 비밀번호·cookie·Proxmox secret 없음. 0700 directory/0600 file, atomic replace, 동시 변경 conflict 처리 |
| 서버 identity | 첫 단위는 scheme/host/port로 정규화한 origin을 key로 사용. path prefix 배포는 제외. 연결 이름이 같아도 origin 변경은 새 연결로 취급하고 기존 session을 보내지 않음. 향후 server UUID discovery는 additive API로 검토 |
| TLS/transport | remote는 검증된 HTTPS 필수, local HTTP는 literal loopback만. URL userinfo/query/fragment 거부. redirect 자동 추종 금지. CA 검증·hostname 검증 유지, `--insecure` 없음. [HTTPX SSL 설정](https://www.python-httpx.org/advanced/ssl/) 재사용 |
| login | 기존 `POST /api/v1/auth/login` 사용. `Set-Cookie`에서 지정한 session cookie만 취득, login의 `expires_at`과 저장. 기본 이름 `gjallar_session`, 기존 커스텀 이름은 connection option. 응답 body로 secret을 복사하지 않음 |
| session 보관 | macOS Keychain / Linux Secret Service를 허용 목록으로 사용. key는 origin + profile UUID + account. [keyring 지원 backend](https://keyring.readthedocs.io/en/latest/)를 확인했지만 headless 사용 가능성은 별도 검사. 평문 fallback은 금지 |
| headless | keyring이 없거나 잠겼으면 저장 불가를 설명하고 process-memory session 선택. TUI 한 실행 또는 명령 실행 중 비표시 login 후 조회 가능. 다음 프로세스는 재로그인. 연결 설정만은 저장. 장기 자동화 token/daemon/keyring 설치 강제는 범위 밖 |
| 만료 | 서버 절대 만료가 권위. 기본 8시간을 새 client가 늘리지 않음. 시작·전환 시 `/auth/me` 검사, `authenticated=false` 또는 인증 endpoint의 401이면 해당 session 삭제·재로그인. 403은 권한 오류이며 자동 logout/권한 확대하지 않음. 자동 refresh·비밀번호 보관 없음 |
| logout | 서버 `/auth/logout`의 revoke 확인 후 local secret 삭제. 통신 실패여도 local secret은 지우되 `서버 폐기 확인 안 됨`과 만료/관리자 sessions 화면의 다음 조치를 표시. 성공이라고 보고하지 않음. 연결 설정 삭제와 logout을 별개로 제공 |
| 연결 전환 | 새 연결 검증 성공 후 selected pointer 변경. 이전 HTTP client/cookie jar와 화면 cache 폐기, 늦은 응답은 generation으로 무시. 원래 서버 session은 만료까지 유지 가능하며 사용자가 logout-all로 개별 폐기. 다른 origin에 cookie 재사용 금지 |
| login 실패/저장 실패 | 잘못된 login/timeout은 이전 연결을 유지. login 성공 후 keyring 저장 실패는 새 session logout을 시도하고 결과를 알린 후 memory 사용 또는 종료. login 응답 자체 유실은 유효 session 존재 가능성을 알리고 자동 login 재전송하지 않음 |
| 화면·출력 | TUI 상단에 서버 별칭·주소·Gjallar 계정·role, 연결 상태·관찰 시각을 표시. JSON은 stdout 하나, 안내는 stderr. exit 제안: 0 정상, 2 입력, 3 Gjallar 인증, 4 권한, 5 transport/TLS, 6 연결 미설정/관찰 불가, 7 저장/내부 오류. partial은 데이터와 경고를 함께 주고 0, snapshot 부재는 6 |

CLI는 브라우저 Origin을 위조하지 않고 현재 허용된 non-browser cookie 흐름을 사용한다. 웹의 Origin/CORS/HttpOnly/SameSite 계약은 유지한다. 다중 origin으로 cookie를 보내는 전역 cookie jar나 PVE credential 입력 option은 만들지 않는다. 사용자별 자원 ACL은 현재 Gjallar role 모델에 없는 기능이며, M1의 선택 대상은 서버 connection의 공통 범위다.

웹도 현재 Gjallar origin·계정과 Proxmox 관찰 범위를 구분해 표시한다. 웹에서 다른 Gjallar 서버를 선택하면 해당 origin의 웹으로 이동해 그 서버의 독립 session을 사용한다. 기존 cookie/비밀번호를 URL이나 브라우저 저장소로 전달하지 않는다. 이 웹 표시·이동은 후속 M1 통합 범위이며 첫 CLI/TUI 단위에 frontend 변경을 섞지 않는다.

### 5. Proxmox 공식 근거와 지원 경계

`2026-09-17` 공식 Proxmox GitHub 조직의 소스와 문서를 확인했다. pve.proxmox.com의 API viewer/일부 문서는 이 조사 환경에서 403이어서 공식 source mirror로 계약을 확인했다. 아래 commit은 조사한 upstream snapshot이며 **출시된 PVE 버전 또는 실제 사용자의 설치 버전과 같다고 가정하지 않는다**. M1 목표는 PVE 9.x의 고정된 검증 조합으로 시작하되, 실제 `pve-manager`·`pve-access-control`·`qemu-server` package 버전과 대응 source를 기록한 compatibility fixture가 준비되기 전 지원 버전을 광고하지 않는다. PVE 8.x 지원은 별도 fixture/실환경 검증 후다.

| 근거 | 확인한 계약 |
|---|---|
| [User.pm](https://github.com/proxmox/pve-access-control/blob/5ccd07d9302562b73374d331b63d25b04b86766c/src/PVE/API2/User.pm), `generate_token/read_token/delete_token` | `/access/users/{userid}/token/{tokenid}`의 POST/GET/DELETE. 자기 계정 또는 해당 사용자의 group을 통한 `User.Modify` 검사. POST 결과에 secret `value`가 한 번 반환되며 기존 ID는 거부. 조회는 metadata만 반환 |
| [AccessControl API](https://github.com/proxmox/pve-access-control/blob/5ccd07d9302562b73374d331b63d25b04b86766c/src/PVE/API2/AccessControl.pm) | `/access/ticket` POST, password/otp/tfa-challenge. challenge를 정상 ticket으로 취급하면 안 됨. `/access/permissions` GET은 effective user/token 권한 조회 |
| [ACL.pm](https://github.com/proxmox/pve-access-control/blob/5ccd07d9302562b73374d331b63d25b04b86766c/src/PVE/API2/ACL.pm), [RPCEnvironment.pm](https://github.com/proxmox/pve-access-control/blob/5ccd07d9302562b73374d331b63d25b04b86766c/src/PVE/RPCEnvironment.pm) | `/access/acl` PUT의 `perm-modify` 검사. `Permissions.Modify` 외에 특정 VM/storage/pool의 allocate 권한으로 제한적 위임 가능하나 부여 role·propagate의 부분집합 검사도 있음. `privsep=1` effective 권한은 owner와 token 권한의 교집합 |
| [Role.pm](https://github.com/proxmox/pve-access-control/blob/5ccd07d9302562b73374d331b63d25b04b86766c/src/PVE/API2/Role.pm) | custom role 생성/변경은 `/access`의 `Sys.Modify`. ACL 변경 권한과 별개이며 `PVE` 접두어는 예약 |
| [Qemu.pm](https://github.com/proxmox/qemu-server/blob/7b44050a7a66451954dc53b2d38e5834b01777ab/src/PVE/API2/Qemu.pm), [Agent.pm](https://github.com/proxmox/qemu-server/blob/7b44050a7a66451954dc53b2d38e5834b01777ab/src/PVE/API2/Qemu/Agent.pm) | VM 목록은 VM.Audit로 필터링. clone/config/resize/start/shutdown은 각각 권한·실행 조건을 검사. 조사 snapshot의 guest agent 권한은 `VM.GuestAgent.*`로 분리돼 있음 |
| [Nodes.pm](https://github.com/proxmox/pve-manager/blob/49318c671b82f31e6b273b79447526161739b97a/PVE/API2/Nodes.pm), [Network.pm](https://github.com/proxmox/pve-manager/blob/49318c671b82f31e6b273b79447526161739b97a/PVE/API2/Network.pm), [Tasks.pm](https://github.com/proxmox/pve-manager/blob/49318c671b82f31e6b273b79447526161739b97a/PVE/API2/Tasks.pm), [Storage/Status.pm](https://github.com/proxmox/pve-storage/blob/7c6a03839920d4939a8ae725a2b0ef91c0cbc6c9/src/PVE/API2/Storage/Status.pm) | 목록 응답 자체가 권한으로 필터링되거나 node 통계가 생략됨. 다른 token의 task 조회는 소유자 규칙/노드 Sys.Audit에 주의 |
| [pveum.adoc](https://github.com/proxmox/pve-docs/blob/129210f6f340f2f93d1f5647957d686da243ee06/pveum.adoc), [certificate-management.adoc](https://github.com/proxmox/pve-docs/blob/129210f6f340f2f93d1f5647957d686da243ee06/certificate-management.adoc) | token privilege separation/1회 secret 반환, TOTP·WebAuthn 등 MFA, 기본 cluster CA와 node certificate, 사용자 제공 인증서·ACME 구성 |

소스의 `update_token_info`에는 `regenerate`도 있지만 모든 대상 PVE가 지원한다고 가정하지 않는다. M1 교체는 새 token ID를 발급·검증하고 active pointer를 바꾸는 방식으로 통일한다. console endpoint의 token 제약도 있으므로 이 등록 설계로 M2의 콘솔 인증까지 해결됐다고 보지 않는다.

### 6. 로그인 위치·TLS·MFA·권한 설계

**Proxmox 로그인은 Gjallar 서버에서 처리한다.** 웹/CLI/TUI는 인증된 admin session으로 selected Gjallar에만 username/realm/password/MFA 응답을 보낸다. 서버가 PVE TLS 확인 → ticket 획득 → 기능·대상·권한 계획 → 명시적 확인 → token 발급/ACL → token 조회 검증을 수행한다. 클라이언트가 PVE에 직접 login하거나 token을 받아 다시 서버로 보내는 경로는 만들지 않는다.

TLS/입력 정책:

- Gjallar→PVE는 HTTPS와 CA chain/hostname 검증을 기본으로 한다. self-signed cluster CA는 신뢰할 기존 관리 경로에서 받은 **공개 CA 인증서**를 서버에 등록한다. CA digest·인증서 subject/SAN/기간을 표시하고 승인된 trust revision에 묶는다. 인증되지 않은 접속에서 본 fingerprint만 자동 신뢰하지 않는다. 인증서 오류가 나면 credential 전송 전에 중단한다.
- system CA 또는 connection별 CA bundle을 사용한다. CA private key는 받지 않는다. 신뢰 변경은 admin의 별도 계획 확인과 재검증 대상이며 기존 연결은 새 trust 검증 전 바꾸지 않는다. 새 wizard에 `PROXMOX_TLS_INSECURE=true` 우회 option을 넣지 않는다.
- admin이 지정한 HTTPS host/port와 고정 `/api2/json` 경로만 호출한다. redirect·userinfo·fragment·임의 URL path를 받지 않는다. 사설 PVE 주소는 필요하지만 loopback/link-local/metadata/multicast 목적지는 거부하고 DNS 결과를 연결 동안 고정·검사한다. 등록 전용 client는 환경 proxy를 묵시적으로 신뢰하지 않는다. 실제 endpoint를 arbitrary fetch proxy로 쓸 수 없게 한다.
- password/OTP는 해당 호출 메모리에만 존재한다. PVE ticket·CSRF·challenge는 actor/Gjallar session/attempt에 묶은 최대 5분 process-memory context로만 보관하고 client에 반환하지 않는다. 완료·취소·logout·권한 상실·만료·재시작 때 폐기한다. 메모리 zeroization 보장을 주장하지 않는다. 요청 body·header·upstream exception을 logger/APM/validation error에 싣지 않는다.

MFA 지원 제안은 `pam`/`pve` password login과 **TOTP**를 우선한다. realm OTP는 `otp`, challenge 방식은 같은 `/access/ticket`에 `tfa-challenge`와 protocol에 맞는 두 번째 응답을 `password`로 보내며 두 방식을 섞지 않는다. challenge 도착은 login 성공이 아니다. 정확한 TOTP 응답 encoding은 고정 버전 공식 인증 구현과 fixture로 검증한 codec만 허용한다. 잘못된 OTP는 자동 반복하지 않고 자체 attempt rate limit도 적용한다. WebAuthn/U2F는 PVE RP ID/origin에 묶이므로 다른 Gjallar origin에서 단순 중계 지원한다고 약속하지 않는다. recovery key·Yubico·LDAP/AD·OIDC도 M1 초기 지원 밖으로 명시하며 MFA 해제를 권하지 않는다. 이 지원 범위로 실제 사용자 환경을 수용하는지는 token 등록 구현 전 확인한다.

토큰 소유권과 권한 계획:

1. 기본 owner는 로그인한 PVE 계정이다. 로그인 비밀번호는 버리고 그 계정에 귀속된 **Gjallar 전용 token**만 장기 저장한다. 다른 사용자의 token을 암묵적으로 만들거나 `root@pam`을 기본 입력하지 않는다. 상시 운영의 기존 서비스 계정을 owner로 선택하는 것은 필요한 `User.Modify`/owner 권한을 확인한 명시적 고급 선택이다. M1에서 PVE 사용자·그룹·realm을 자동 생성/확대하지 않는다.
2. `privsep=1`, 유한 만료(권장 90일, owner의 유효기간도 확인), installation/attempt에서 정한 충돌 어려운 token ID를 쓴다. owner 비활성/삭제/권한 변경이 token에 영향을 준다는 점을 안내한다. 운영 token에 User.Modify·Permissions.Modify·Sys.Modify를 편의상 부여하지 않는다.
3. 기능·대상별 path/privilege와 owner effective 권한, 등록 actor의 token 생성/ACL/role 생성 권한을 별도 열로 제시한다. 생성 가능 여부를 시험하기 위해 token을 미리 만들지 않는다. 계획 당시 권한이 충분해도 dispatch의 실제 거부 가능성이 남는다.
4. exact privilege set의 versioned custom role을 사용한다. 기존 role이 같은 이름인데 정의가 다르면 중단하고 덮어쓰지 않는다. 필요한 role이 없고 `/access` Sys.Modify가 없으면 role 준비가 필요한 것으로 차단한다. 넓은 PVEAdmin/Administrator role로 대체하지 않는다. 기존 exact role 재사용은 가능하다.
5. ACL은 승인한 token/path/role/propagate tuple만 추가한다. owner/group ACL은 자동 수정하지 않는다. 원래 owner 권한이 부족하면 기능 또는 범위를 줄이거나 해당 관리자가 별도 조치해야 한다. M1 자동 등록은 보수적으로 해당 path의 Permissions.Modify를 요구할 수 있지만, 이를 Proxmox의 유일한 가능 조건이라고 설명하지 않는다.
6. 발급 이후 **token 자신으로** `/access/permissions`와 실제 조회를 확인한다. API 200/빈 list만으로 모든 대상 권한이나 cluster가 비었다고 판정하지 않는다. `selected_scope`, `visible_scope`, `missing_privileges`, `observed_at`을 구분한다. scope 밖 node/VM을 조회하지 않는 필터와 current gate의 관계는 provider 통합 단위에서 함께 구현해야 한다.

아래 표는 조사 snapshot 기준의 매핑 출발점이다. 제품의 새 mutation 구현 권한이나 모든 PVE 버전에 통용되는 최소 role 목록이 아니다.

| 선택 기능 | 실제 호출·path와 권한 | 설계상 제한 |
|---|---|---|
| 노드/VM/template 기본 조회 | `/nodes`는 인증 사용자 접근, node 통계는 `/nodes/{node}`의 `Sys.Audit`. QEMU 목록/config/status는 `/vms/{vmid}`의 `VM.Audit` | node 이름이 보이는 것과 모든 통계·VM이 보이는 것을 구분. template도 QEMU 조회 |
| storage/network 조회 | storage 목록은 `/storage/{id}`의 `Datastore.Audit` 또는 `Datastore.AllocateSpace`. local bridge 목록은 `/sdn/zones/localnetwork/{bridge}`의 `SDN.Audit` 또는 `SDN.Use` | read profile은 Audit 권한 우선. SDN vnet은 실제 zone/path로 계산. network config 단건의 Sys.Audit와 목록 필터를 혼동하지 않음 |
| guest IP 관찰 | 조사 `Agent.pm`의 network-get-interfaces는 `/vms/{vmid}`의 `VM.GuestAgent.Audit` 또는 `VM.GuestAgent.Unrestricted` | read에는 Audit만 요청. 구버전 privilege 이름을 추측해 넣지 않음. agent 미설치/정지는 권한 문제와 구분 |
| 기존 Start/Shutdown | target `/vms/{vmid}`의 `VM.PowerMgmt`와 상태 관찰 권한 | complete-live·실행 확인·lock·UPID/post-check 유지 |
| 기존 template clone | source `VM.Clone`, 새 VM `VM.Allocate` 또는 지정 pool의 VM.Allocate, 사용하는 storage의 `Datastore.AllocateSpace`, bridge/vnet의 `SDN.Use` | 현재 Gjallar clone payload는 pool을 보내지 않으므로 pool 권한만으로 생성된다고 약속하지 않음. future VM scope가 넓어지는 점을 확인받음 |
| clone 후 config/resize | 입력 field에 따라 `VM.Config.CPU/Memory/Network/Options/Cloudinit/Disk` 등. resize는 VM.Config.Disk이며 storage 조건도 확인 | 현재 payload·template drive를 기준으로 계산. 임의 config 지원은 범위 밖 |
| boot_and_verify | power/read + 조사 snapshot의 guest exec/exec-status는 `VM.GuestAgent.Unrestricted` | guest 내부 실행 능력을 주는 넓은 권한임을 별도 표시. M1 기본 조회 토큰에 자동 포함하지 않음 |
| task/recovery 조회 | task owner 또는 실행 node의 `Sys.Audit` | 새 token이 기존 token의 task를 같은 owner로 읽을 수 있다고 가정하지 않음. 교체 preflight에 과거 미완결 task 조회 포함 |

첫 token wizard의 기본 기능은 자원 조회다. 기존 action 사용을 선택하면 위 추가 권한과 대상별 실행 조건까지 검사한다. 미검증된 PVE/version/feature 조합은 기능을 차단하고 이유를 표시한다. admin role 하나로 실제 token scope·target condition을 우회하지 않는다. 기존 VM 행동 gate를 단순히 partial 허용으로 바꾸지 않는다.

### 7. 서버 저장·키와 API/DB 제안

장기 secret은 setup 소유 PostgreSQL table의 **인증 암호화 ciphertext**로만 저장한다. `cryptography`의 [AESGCM](https://cryptography.io/en/latest/hazmat/primitives/aead/)을 사용해 256-bit master key, 매 암호화의 새 96-bit nonce, AAD로 installation/connection/credential revision을 결합한다. nonce 재사용을 막고 key ID/format version/tag를 검증한다. library를 직접 구현하거나 기존 password hash를 복호화 가능한 token 저장에 쓰지 않는다.

- master key는 설치당 생성한 host 0600 파일, 상위 0700 directory, app에 read-only secret mount. DB dump·이미지·환경 값·설치 manifest·client에는 포함하지 않는다. [Compose secret](https://docs.docker.com/compose/how-tos/use-secrets/)은 파일 전달 수단이며 host에서의 암호화 저장소라고 주장하지 않는다. 호스트 접근 통제/디스크 암호화와 분리 backup은 운영 책임이다.
- ciphertext가 하나라도 있으면 누락된 키를 자동 재생성하지 않는다. key 누락/InvalidTag는 credential 사용을 차단하되 로그인·작업 이력 조회는 유지하고 관리자에게 복구를 안내한다. env credential로 조용히 fallback하지 않는다.
- key rotation은 새 key ID 등록 → 새 write 전환 → 각 row를 새 nonce로 재암호화·검증 → 기존 key로 암호화된 row/backup의 복원 정책 확인이다. 중단 시 두 key를 보존해 재개한다. key 폐기는 DB/token 폐기와 별개이며 backup에 필요한 key를 조기 삭제하지 않는다.
- DB backup과 key backup은 별도 보관·복원 연습이 필요하다. key 완전 유실 시 기존 secret 복구는 불가능하므로 PVE에서 exact token 폐기 후 새 등록이 필요하다. 이력은 지우지 않는다. 이 설계는 DB dump 단독 유출 위험을 줄이지만 서버 root 침해를 막는 것으로 설명하지 않는다.

후속 additive schema 후보(첫 구현 M1-1에는 추가하지 않음):

| setup 소유 저장 단위 | 주요 필드·불변 조건 |
|---|---|
| `proxmox_connections` | connection ID, 기존 cluster_id, endpoint, trust revision, source(`legacy_env`/`managed`), selected features/scope, active credential ID, version, admission 상태. 단일 active connection만 허용 |
| `proxmox_credentials` | revision ID, connection FK, owner/token metadata, expire, ciphertext/nonce/key ID/AAD version, pending/active/retiring/revoked 상태. plaintext getter는 내부 provider에만 |
| `proxmox_registration_attempts` | attempt/Operation ID, actor, idempotency digest, intent digest, plan digest, token ID, expected connection version, phase, dispatch marker, lease generation/expiry, 마지막 sanitized 오류. connection당 unresolved attempt는 하나 |

secret과 상태 snapshot은 동일 setup transaction에서 commit하고, 공개 Operation의 상태/event와 결합할 때 core의 transaction-aware port를 사용한다. ORM 테이블 직접 참조나 별도 commit들을 원자적이라고 부르지 않는다. Operation에는 attempt/revision 참조·권한 계획 digest·상태만 두며 secret/ticket/OTP/원시 upstream body는 싣지 않는다. 기존 `redact_secrets()`는 PVE의 단순 `value` 필드를 가리지 못하므로 redaction 후 저장만으로 안전하다고 보지 않고 **허용 필드만 복사하는 DTO**를 사용한다.

후속 `/api/v1/setup/proxmox/registrations` 제안은 admin 전용이다. create는 endpoint/trust 선택과 idempotency identity, login/mfa는 sensitive payload, plan/confirm은 features/scope·expected version·digest, status는 비밀 없는 phase, observe는 GET-only 재조사, revoke는 별도 exact 대상 확인을 받는다. 성공 envelope/기존 auth·connection GET은 유지하고 새 path를 추가한다. 계획 변경은 재확인하며 stale version·다른 intent의 key 재사용은 409, 권한 부족은 403, upstream/저장 불가는 sanitized 502/503 및 attempt ID로 구분한다. viewer에게 등록 계정·ACL·토큰 metadata를 노출하지 않는다. 관리 API 승인 전에 정확한 DTO/route registry를 다음 구현 단위에서 고정한다.

### 8. 토큰 발급 상태와 중단 복구

PVE mutation과 Gjallar DB는 한 transaction이 아니다. 계획 확인에는 endpoint/CA revision·owner·token ID·features/scope·ACL tuple·expire·현재 connection version을 결합한다. secret을 받기 전에 DB와 key 사용 가능성을 검사하고 **정해진 token ID와 dispatch intent를 durable commit**한다. PVE 호출 동안 DB transaction을 열어 두지 않는다. 단계별 CAS/lease로 writer를 제한하되 lease 만료를 외부 미실행의 증거로 쓰지 않는다. 프로세스 재시작/timeout 뒤 mutation 자동 재호출은 하지 않는다.

권장 phase는 `prepared → authenticated → planned → confirmed → token_dispatching → secret_staged → acl_applying → verifying → active`다. auth material은 메모리만이므로 재시작 후 `authenticated` 기록이 남아도 `reauth_required`로 표시한다. PVE secret 수신 직후 우선 암호화 staging commit을 하고, 승인된 ACL을 적용·검증한 다음 active로 승격한다. 사용자에게 보이는 완료 순서는 합의대로 발급·권한 설정·안전한 저장 확인·첫 조회이며, staging은 저장 실패 시 무권한 token의 잔류를 줄이기 위한 내부 단계다.

| 실패·사건 | 저장/표시할 상태와 판단 | 재개·정리 |
|---|---|---|
| dispatch marker 저장 실패 | `prepared`/저장 불가, 외부 호출 없음 | DB 복구 후 같은 attempt를 읽고 계속. 새 token ID 자동 생성 없음 |
| PVE POST 이후 응답 유실·process crash | `issue_unknown`, token이 생겼을 수 있음 | 재로그인 후 저장된 exact owner/token ID metadata 조회. 조회 오류/권한 부족을 부재로 해석하지 않음. 늦은 요청 가능성이 있으므로 즉시 재POST하지 않음 |
| metadata는 존재하지만 secret 없음 | `orphaned_token`, secret 재조회 불가능 | actor가 exact ID·attempt 근거를 확인하고 폐기에 동의 → DELETE/부재 확인 후 새 attempt/ID. 소유 근거 불일치 또는 기존 collision이면 삭제하지 않고 manual 조치 |
| secret 수신 후 staging commit 실패 | 같은 process에 secret만 남거나 crash 시 orphan 가능 | 동일 ciphertext/revision의 DB commit 결과를 먼저 조회하고 local 저장만 재시도 가능. secret은 파일 spool/log로 빼지 않음. 복구 불가면 orphan 처리, ACL 단계로 진행하지 않음 |
| ACL 일부 적용 후 실패·응답 유실 | `acl_partial`/`acl_unknown`, 완료 tuple과 불확실 tuple 구분 | 재로그인·ACL/effective 권한 관찰 후 명시적 계속 또는 폐기. 기존 owner/group/다른 token ACL을 rollback하지 않음. 자기 token의 승인 tuple만 정리 |
| 검증 실패 | `verification_failed`, active는 원래 credential | TLS/권한/부분 관찰/실제 빈 자원을 구분. 범위 변경 시 새 plan 확인. 같은 secret으로 read 검증을 다시 할 수 있으나 권한 자동 확대 없음 |
| active commit 후 client 응답 유실 | attempt GET에서 `active`와 동일 revision 반환 | 최초 요청 재전송은 같은 상태 replay. token 재발급/secret 재노출 없음 |
| 중복 요청 | 같은 key+같은 intent는 같은 attempt, 다른 intent는 409. 다른 key라도 unresolved connection slot 충돌은 409 | 성공/불명 상태를 보존. expired lease takeover는 observation부터 하며 오래된 writer는 CAS 거부. PVE의 동일 ID 생성 거부도 보조 방어로 사용 |
| 취소·ticket 만료 | 외부 호출 전만 안전한 `cancelled`. 호출 후는 `cleanup_required` | 비밀번호/ticket을 보존해서 자동 복구하지 않고 재로그인. 취소가 token 삭제 성공을 의미하지 않음 |
| revoke timeout/실패 | `revocation_pending`, 잔여 PVE 권한 있음 | fresh login으로 exact metadata/권한 확인. DELETE 응답/없는 token의 확인까지 기록. 401/403/timeout은 폐기 완료가 아님. 확인 불가 시 수동 조치와 exact ID만 표시 |

PVE token/ACL 생성은 VM task UPID 흐름이 아니므로 기존 task polling을 억지로 재사용하지 않는다. mutation callback을 background recovery runner에 등록하지 않으며, 새 setup observer는 read-only 확인만 한다. Proxmox secret이나 password를 재요청해 임의 원본 mutation을 반복하지 않는다. 생성 ID의 comment는 상관관계 보조 정보이며 암호학적 소유 증명이 아니다. collision을 사전 GET으로 확인하고 immutable attempt 기록·발급 시각·ID·owner를 함께 대조한다.

DB 장애 중에는 위 실패 phase조차 저장되지 못할 수 있다. 재시작 후 마지막 durable `token_dispatching`/`acl_applying`을 성공이나 미실행으로 읽지 않고 불명 상태로 재구성한다. token 조회에서 부재를 관찰했어도 이전 요청이 끝났음을 확인하지 못하면 새 발급을 막고 manual reconciliation에 남긴다. 자동으로 안전한 취소나 exactly-once 외부 실행을 보장한다고 표현하지 않는다.

이전 발급 요청의 종료를 서버 측 근거로 확인하고 fresh metadata 조회에서도 exact ID가 없으면 `failed_no_token`으로 닫을 수 있다. 그 후 사용자가 새 등록을 시작하며 새 attempt/ID를 사용한다. 서버 측 근거를 확보할 수 없으면 잠시 기다렸다는 이유만으로 닫지 않고, PVE 관리자가 잔류 token과 요청을 확인하는 수동 절차를 안내한다.

교체·폐기·연결 해제 계약:

- 교체는 기존 active token을 유지한 채 새 revision을 별도 ID로 등록한다. 새 token으로 선택 자원과 미완결 task 관찰 가능성을 확인한 후 pointer를 CAS 변경한다. 이전 token 폐기는 별도 단계이며 실패 시 `retiring/revocation_pending`으로 남긴다. 이전 token 자체를 regenerate하지 않는다.
- 연결 전환 중 신규 VM mutation을 막는 admission gate를 둔다. current action 진입과 active revision 선택을 같은 조정 경계에서 읽어 TOCTOU를 막아야 한다. M1은 혼합 worker/hot swap을 지원하지 않고 drain/재시작으로 전환한다. nonterminal Operation뿐 아니라 open lock·noncompleted recovery가 있으면 일반 교체를 중단한다. 긴급 token 폐기는 가능하나 해당 작업의 관찰 중단·manual recovery를 명시한다.
- 다른 token으로 과거 task 조회가 가능한지 불명확하면 기존 token을 폐기하지 않는다. token이 이미 손상/폐기돼 복구가 막혔으면 exact cluster/task read가 가능한 대체 credential을 검증하는 별도 복구 절차로 간다. 원래 mutation을 재실행하지 않는다.
- 연결 해제는 사용 중단과 PVE token 폐기를 분리한다. 관리형 token은 폐기 확인까지 metadata와 attempt를 보존한다. 외부에서 가져온 env token은 소유권/다른 consumer를 모르므로 기본적으로 폐기하지 않는다. 공유 custom role을 자동 삭제하거나 사용자를 삭제하지 않는다.
- credential 폐기 후 secret ciphertext는 별도 secret 보존 정책에 따라 제거하되 작업/등록 metadata·event는 남긴다. DB backup에 남은 ciphertext가 있다고 token이 계속 유효한 것은 아니며 upstream revoke 확인을 별도로 기록한다.

### 9. 기존 env·DB·이력 전환

1. 첫 CLI/TUI 단위는 backend 설정·schema에 손대지 않고 현재 서버를 그대로 사용한다. `.env` 값을 client로 복사하거나 client에서 읽지 않는다.
2. credential provider 도입 시 default source는 기존 env adapter다. DB에 관리형 연결이 없으면 현재 동작 유지, 생성 중인 pending row는 active 설정을 바꾸지 않는다. migration은 새 table/index를 더하는 새 revision만 만들고 기존 users/sessions/Jobs/Artifacts/Operations/locks/recovery와 `GJALLAR_CLUSTER_ID`를 유지한다.
3. 서버 관리자에게 env 연결의 존재·TLS 정책·전환 영향만 보여준다. 명시적 import는 서버가 env secret을 직접 읽어 암호화 저장하고 **동일 token**으로 fresh read를 검증한다. Proxmox token/ACL을 변경하지 않는다. 기존 insecure TLS 설정은 자동으로 안전해진 것으로 표시하지 않고 신뢰 설정을 먼저 해결한다.
4. import 또는 새 전용 token 등록이 검증된 후 maintenance window에서 신규 mutation 차단 → worker drain → 미완결 lock/recovery 확인 → source/active revision commit → 모든 app 재시작·cache 폐기 → read 검증한다. managed 선택 후 key/DB 오류가 나도 env로 silent fallback하지 않는다. 충돌하는 두 source는 명시한 active source만 사용한다.
5. 전환 성공과 rollback 준비를 확인한 뒤 운영자가 기존 secret env 제거를 수행한다. installer가 원본 `.env`를 덮어쓰지 않는다. 기존 DB volume, job/artifact ID, Operation chain, VMID/cluster coordination identity는 바꾸지 않는다. 서버 clone을 원본과 동시에 운영하지 않는다.
6. rollback은 새 mutation drain 후 확인된 이전 source/revision을 명시적으로 복구하고 같은 cluster·권한·TLS를 재검증한다. 이미 revoke한 token을 되살릴 수 있다고 가정하지 않는다. schema downgrade/row 삭제/`alembic stamp`/새 빈 DB로 바꿔서 장애를 숨기지 않는다. additive schema는 남겨 roll-forward를 우선한다.

### 10. 구현 분할과 첫 단위

| 순서 | 단위와 결과 | 위험·선행 조건 |
|---|---|---|
| **M1-1** | 기존 Gjallar API로 연결 선택·로그인·session 보관·CLI/TUI 기본 조회 | 아래 파일/API/테스트 범위. 새 auth server/DB/PVE mutation 없음 |
| M1-2 | Compose local bootstrap, explicit init/serve, zero-user 관리자, start/status/stop | 배포·인증 transaction 변경. 고정 release/OS/PG 행렬, 별도 disposable 환경 검증 |
| M1-3 | setup credential provider·암호화 저장·env import·등록 attempt/비밀 없는 Operation 기록 | 새 migration·키 backup/복원·CAS/admission 계약. PVE mutation 전에 crash 테스트 |
| M1-4 | 서버 PVE login/TOTP·scope 계획·발급/ACL·검증·교체/폐기와 웹 연결 wizard | 고정 PVE fixture, exact live target/side effect 별도 승인. 기존 action gate 회귀 |
| M1-5 | macOS/Linux 새 설치·기존 서버·기존 DB 전환의 통합 검증 | OS/CPU별 실측, live 조회/등록·복구 evidence. 여기까지 충족해야 전체 M1 완료 |

**M1-1의 목표:** 이미 동작하는 Gjallar 서버에 client만 설치해 로그인하고, 선택을 저장하고, 노드/VM/template과 연결 관찰 상태를 CLI 및 최소 TUI에서 읽는다. 현재 서버에 Proxmox가 미설정이면 같은 사실을 보여주고 설치/연결 완료라고 주장하지 않는다.

변경 파일 제안(신규 경로는 아직 존재하지 않음):

| 파일 | 책임 |
|---|---|
| `client/pyproject.toml`, `client/uv.lock` | 독립 wheel·entry point·Python/dependency/test 고정 |
| `client/src/gjallar_client/api.py`, `errors.py` | HTTPX transport, 기존 envelope/오류와 `/me` 처리, origin 고정·redirect/TLS 정책 |
| `client/src/gjallar_client/connections.py`, `sessions.py` | versioned atomic connection 저장, 허용 keyring/memory, 만료·logout·전환 |
| `client/src/gjallar_client/application.py`, `cli.py`, `tui.py` | 공통 login/조회 use case, Typer command, Textual 서버 표시·선택·조회/종료 |
| `client/tests/test_transport.py`, `test_sessions.py`, `test_connections.py`, `test_cli.py`, `test_tui.py` | 아래 완료 조건, HTTPX mock/임시 파일/fake keyring/Textual pilot 사용 |
| `backend/tests/contracts/test_api_v1_auth.py` | 필요할 경우 기존 cookie client contract를 실제 FastAPI TestClient로 검증하는 회귀 추가. 동작 변경 없음 |
| `package.json`, `Dockerfile`, `.dockerignore` | client 검사 command와 검증 전용 client-test stage를 root verify/container verify에 연결. production image에 CLI/TUI 의존성은 넣지 않음. 실제 CI wiring은 해당 파일 현황을 다시 읽고 최소 변경 |
| `project-docs/development.md`, `architecture.md`, `roadmap.md`, 이 work | 구현 후 실제 설치/검증 명령·제공 범위·결과 반영. 이번에는 운영 명령 변경 없음 |

API/DB 영향: 호출하는 endpoint는 기존 `/api/v1/auth/login`, `/auth/me`, `/auth/logout`, `/setup/proxmox/connection`, `/nodes`, `/vms`, `/templates`뿐이다. 새 backend route·DTO 필수 필드·schema·migration은 없다. login/logout에 의한 기존 session row 생성/revoke는 있으며 `read-only client`를 DB 무변경이라는 뜻으로 쓰지 않는다. backend role·Origin 정책은 유지한다. client 파일·OS keyring은 새로운 저장 경계이므로 위 보관·복구 계약을 먼저 적용한다.

비범위: Docker 자동 설치, local 서비스/DB 생성, 최초 관리자, 새 PVE login/token/ACL, provider 전환, 새 암호화 table, VM mutation, 전체 VM 관리 TUI, SSO/MCP, 장기 자동화 API token, binary 패키징. M1-1의 시작 선택 화면은 두 경로를 유지하되 local bootstrap은 `아직 제공되지 않음`으로 명확히 표시하고 어떤 설치 동작도 하지 않는다. 사용 중인 local 서버 주소로의 연결은 기존 서버 연결과 같은 client 경로다. M1-2에서 그 선택에 실제 bootstrap을 연결한다.

완료 기준과 테스트:

| 시나리오 | 검증 가능한 통과 조건 |
|---|---|
| 원격 연결 | Docker·DB·PVE 환경 변수 없는 환경에서 mock Gjallar login/조회 성공. client dependency에 backend/DB/Proxmox 모듈 없음 |
| 실제 계약 | FastAPI TestClient의 Set-Cookie/login expiry, `/me`의 200 false, viewer 읽기/403 구분. mock JSON만 맞고 실제 서버 contract가 다른 문제 방지 |
| session lifecycle | fake clock으로 expiry, revoke/disable/password reset 응답 처리. keyring 없는 headless는 memory 안내, 평문 secret 파일 없음 |
| 주소/연결 전환 | 같은 host의 다른 port·다른 profile 분리, URL userinfo/redirect/remote HTTP 차단, TLS 오류, 잘못된 CA, 이전 응답 generation 폐기, 전환 실패 시 원래 선택 유지 |
| 저장 중단 | read-only directory·atomic replace 실패·손상 config·keyring lock/failure·동시 업데이트에서 기존 config와 session 보존. 새 session 보관 실패의 logout 성공/불명 구분 |
| logout | 서버 revoke 성공·이미 만료·네트워크 실패를 다르게 출력, 모든 경우 해당 local secret 삭제, 실패에 성공 exit 없음 |
| 관찰 상태 | 정상 empty, partial, unconfigured, snapshot 없는 503, Gjallar 401, 권한 403, protocol mismatch를 fixture로 구분. 정상 빈 목록을 실패로, 실패를 빈 목록으로 바꾸지 않음 |
| 출력/보안 | JSON 단일 stdout·정해진 exit, 합성 secret을 cookie/header/body/exception에 넣고 stdout/stderr/log/config/trace에 비노출. keyring 허용 backend만 사용 |
| TUI | Textual pilot으로 로그인→선택→노드/VM/template 조회→전환→종료 실행. 현재 서버/계정/role·시각 표시. quit에 service stop/logout/token revoke 호출 없음 |
| 회귀/배포물 | client tests + 기존 로컬 verify/container verify + wheel smoke. 지원 후보 OS/CPU에서 keyring과 TUI 실제 동작을 별도로 기록. mock 통과만으로 설치 지원/웹과 live 자원 동등성 완료 선언 안 함 |

M1-1 rollback은 client 사용 중단과 새 session logout/서버 관리자 revoke, 이전 client artifact 복귀다. 생성한 config는 backup 후 version 호환을 검사해 보존하며 자동 삭제하지 않는다. backend/DB/PVE 변경이 없으므로 migration downgrade·토큰 폐기·작업 기록 복구는 필요하지 않다. login 응답 유실/서버 logout 실패의 session은 만료 또는 관리자 sessions 화면으로 정리한다. 기존 미커밋 문서·다른 코드 변경은 되돌리지 않는다.

### 11. 남은 결정과 검증 게이트

일상적인 기술 선택은 위 권장안으로 구체화했으며 이번 설계 기록을 위해 추가 사용자 답변을 요구하지 않는다. 구현 전에는 아래를 구분해서 닫는다.

- **설계 수용:** Compose 기본 배포와 Python client, PVE 서버 중계·CA 검증·TOTP 우선, 첫 단위 M1-1을 검토한다. 제품 합의를 재선택하는 질문은 하지 않는다. 이 `DRAFT`는 고위험 구현/배포 승인이나 실행 증거가 아니다.
- **대상 환경 정보:** 실제 PVE/package 버전·realm/MFA, macOS/Linux OS/CPU, 원격 Gjallar의 TLS/CA와 접근 경로가 필요하다. 현재 조사에서 실제 host 또는 secret을 읽어 추정하지 않았다. 이는 fixture·지원 행렬을 고정할 때 확인하며 M1-1 mock 구현을 막는 정보는 아니다.
- **token 등록 착수 전:** custom role 목록·지원 PVE의 exact privilege codec·scope filtering·Operation read 권한·새 schema/transaction/admission API를 확정하고 crash/동시성/key 복원 시험을 한다. owner service-account 선택·90일 만료는 등록 시 사용자에게 보이는 선택이며 지금 실제 계정/권한을 바꾸지 않는다.
- **운영 실행 전 별도 승인:** 설치 위치/volume/기존 DB 식별, migration revision/backup, exact PVE endpoint·owner·token ID·ACL tuple·expire와 폐기/복구 영향. 이번 세션에는 승인이나 실행을 요청하지 않는다.

### 12. 이번 세션 검증과 결과

설계·공식 source 조사와 문서 갱신을 완료했다. 기능/설치 검증과 분리해 아래에 이번 실행 결과를 기록한다. 위 `2026-09-16`의 전체 테스트·container 결과는 재실행 결과가 아니다.

- `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/contracts/test_legacy_backend_cleanup.py`: **10 passed**. 문서 구조·상대 링크·anchor와 레거시 제거 계약을 이번 checkout에서 실행했다. fixture의 격리된 임시 SQLite만 사용하며 실제 PostgreSQL 검증이 아니다.
- `git diff --check`: 통과. 미추적 work도 `git diff --no-index --check /dev/null project-docs/work/2026-09-16-m1-installation-connection.md`로 검사해 whitespace 진단이 없음을 확인했다. no-index의 exit 1은 새 파일과 `/dev/null`의 차이이며, 이를 후속 명령 성공으로 간주하지 않고 문서 테스트/diff 검사를 따로 실행했다.
- 설치, 서비스 기동, 실제 DB migration, Proxmox login/조회/token/ACL/live smoke는 미실행이다. 공개 upstream source의 read-only HTTP 조회만 수행했다.
- 문서만 변경하므로 `pnpm run verify`, `pnpm run verify:container`는 이번 범위에서 실행하지 않는다. 새 설계의 OS/CPU·PostgreSQL·MFA·암호화/복원·발급 복구 동작은 모두 구현/검증 대기다.

## 2026-09-17 M1-1·M1-2 구현 승인과 실행 계획 (`APPROVED`)

사용자가 이번 요청으로 두 단위의 구현 착수를 승인했다. 앞선 DRAFT의 구현 미승인 문구는 이번 두 단위에 한해 대체한다. 전체 M1·PVE credential 등록 설계는 승인/구현 완료로 승격하지 않는다. HEAD는 `8feae46cddb88aca47c149df9f1a9e24da880c07`, staged 변경은 없고 PRD·architecture·roadmap·work index의 기존 수정과 이 미추적 work를 보존한다. commit/push는 하지 않는다.

### 구체적 변경·위험·검증·복구

1. **M1-1 먼저:** 독립 `client/` wheel, HTTPX API adapter, versioned atomic config, 명시적 keyring/memory store, 공통 application, argparse CLI와 동기식 메뉴 TUI. 최소 조회 TUI에 Textual/Typer를 추가하지 않는 이유는 비동기 화면·VM mutation 없이도 승인된 기능을 제공하고 두 frontend의 흐름과 오류 처리를 하나로 유지하기 위해서다. 동기 실행으로 전환 중 늦은 요청 자체를 만들지 않는다. API/DB schema 변경 없음.
2. **session 위험:** profile UUID·canonical origin에 묶인 cookie 한 개만 보관한다. 원격 HTTP/userinfo/path/query/redirect를 거부하고 TLS 검증을 유지한다. macOS Keychain/Linux SecretService 구현만 허용하며 미지원/잠긴 keyring은 오류와 명시적 `--session-mode memory` 안내다. 비밀번호는 비표시 입력·메모리만, 서버 응답/예외 원문은 오류에 출력하지 않는다. session 삭제 실패와 서버 revoke 불확실성은 분리한다. mock transport/fake keyring/임시 경로로 중단·만료·오류·전환·secret 비노출을 검증한 뒤 M1-2로 진행한다.
3. **M1-2:** 같은 client의 별도 bootstrap 모듈과 wheel에 포함한 Compose 자산, 기존 single image를 사용하는 신규 explicit maintenance/serve 경로. legacy entrypoint는 기존 배포 호환용으로 유지하되 새 Compose는 이를 우회한다. 새 PostgreSQL 17 전용 volume, superuser와 제한된 app role, credential 전용 0600 파일·0700 directory를 사용한다. 일반 manifest/Compose에는 secret 참조만 둔다. 관리자 비밀번호는 maintenance stdin으로만 전달한다.
4. **초기화 위험:** 고유 installation identity·새 volume 확인·DB 내부 identity를 결합하고 unknown existing volume/config/DB를 가져오지 않는다. DB 내부 설치 marker와 users table write lock 아래 zero-user·업무 row 부재를 확인하여 최초 관리자와 완료 marker를 같은 transaction에 기록한다. marker는 새 관리형 설치 전용의 별도 infrastructure table이며 기존 DB에 migration으로 추가하지 않는다. migration은 confirmed fresh DB에서만 수행하고 중단된 init은 같은 identity 아래 재개한다. 일반 serve는 schema head/완료 marker를 검사하고 migration·계정 생성을 하지 않는다. 기존 users·jobs·artifacts·password를 덮어쓰지 않는다.
5. **배포 위험:** 고정 argv·shell=False Docker/Compose runner, 깨끗한 Compose 환경, OS/CPU·Docker/Compose·daemon·port·설치 경로·volume 확인. Docker 설치/권한 자동 변경 없음. loopback 고정이며 원격 공개 옵션은 제공하지 않는다. SSH tunnel 또는 별도 승인된 TLS proxy에서 HTTPS origin/Secure cookie 정책을 준비한 뒤에만 원격 공개한다. 이미지 upgrade는 명시적으로 구분하되 DB revision 변경은 자동 적용하지 않고 별도 backup·migration 승인 절차로 중단한다. PostgreSQL major 변경·데이터 이동·삭제 경로 없음.
6. **검증:** 외부 실행은 모두 fake runner; 실패 전후 manifest/secret/volume identity 보존, 동시 bootstrap lock, admin commit 후 응답 유실, 초기화 중단·재실행, start/status/stop, secret argv/output 비노출. backend 임시 SQLite는 transaction 논리만 검증하며 실제 PostgreSQL 동시성·OS keyring·VM 설치 검증을 대체하지 않는다. 실제 설치·기동을 실행하지 않는다. `git diff --check`, 관련 tests, `pnpm run verify`, build-only `pnpm run verify:container`를 이번 checkout에서 실행한다.
7. **복구:** 실패하면 파일·volume·DB·계정·이력을 보존하고 같은 설치 경로에서 재실행한다. secret/identity 누락·충돌은 자동 재생성하지 않는다. client rollback은 사용 중단/session revoke와 이전 artifact 복귀. 배포 rollback은 기존 image/config/volume 보존, schema 동일 버전만 허용; schema 변경이 필요한 upgrade는 별도 승인 전 보류. 자동 down -v, DB downgrade, 기존 계정 reset, Proxmox 호출 없음.

공식 근거 재확인: [keyring backend 문서](https://keyring.readthedocs.io/en/stable/), [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/), [Compose readiness](https://docs.docker.com/compose/how-tos/startup-order/). secret mount는 암호화 저장소가 아니며 전용 secret 파일의 host 접근 통제·별도 backup이 필요하다.

### M1-1 구현·검증 게이트

- 독립 client의 config/transport/session/application/CLI/메뉴 TUI 구현. 실제 API 대조 후 endpoint 추가 없이 연결했다.
- `backend/venv/bin/python -m pytest -q client/tests`: **24 passed**.
- `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/contracts/test_python_client.py client/tests`: **25 passed**, HTTPX의 기존 TestClient deprecation warning 1개. 임시 SQLite/서버 in-process transport이며 실제 네트워크·OS keyring은 호출하지 않았다.
- wheel dependency는 `client/uv.lock`과 hash가 있는 `requirements.lock`으로 고정했다. uv의 sandbox macOS system-configuration panic 후 저장소 내부 cache/venv만 쓰는 승인된 dependency 설치를 재실행해 성공했다. backend dependency에는 client를 추가하지 않는다.
- 1단계 검증 게이트를 통과했으므로 M1-2 구현으로 진행한다. 전체 regression/container/wheel 검사는 두 단위 최종 상태에서 실행한다.

### M1-2 구현 결과와 최종 검토

- `client/bootstrap.py`는 Docker/Compose/OS·engine·image CPU/port/path 검사, 고유 named volume, secret 파일·Compose 생성, 초기화, 일반 start/status/stop, 동일 schema image upgrade를 제공한다. 실행은 고정 argv·shell 없이 하며 subprocess 원문 출력은 금지한다. 신규 이미지 release registry가 없어 이번 코드로 빌드한 로컬 image를 입력받고 실제 ID를 고정한다. PostgreSQL 17 tag도 처음에만 resolve하고 ID를 보존한다. 공개 release patch/digest 검증은 아직 남았다.
- `client/assets/`의 PostgreSQL root wrapper가 host 0600 secret을 컨테이너 tmpfs의 postgres 소유 0400 파일로 전달한다. 제한된 app role의 생성은 비밀번호를 stdin SQL에만 넣고, 기존 role password는 변경하지 않는다. 임시 initdb 서버를 정상 readiness로 오인하지 않도록 PostgreSQL health는 TCP loopback으로 확인한다.
- `backend/app/installation/`은 빈 DB marker → 명시적 migration/seed → users 전체 0·업무 이력 부재 → 관리자/account audit/ready의 transaction을 구현한다. 새 `GJALLAR_DATABASE_URL_FILE`은 URL env와 동시 사용을 거부한다. 기존 migration, 일반 계정 관리, VM recovery/lock은 변경하지 않았다. legacy entrypoint는 호환용으로 유지하며 새 Compose는 explicit serve를 사용한다.
- manifest 상태는 `preparing → prepared → storage_ready → ready`다. DB 실행 전에 volume 준비를 durable 기록하고 그 뒤 missing volume은 절대 재생성하지 않는다. 관리자 commit 후 응답 유실도 기존 ready 상태로 재개한다. secret은 원자적 신규 파일 생성/fsync를 사용하고 기존 파일을 덮어쓰지 않는다. 부분 initdb 자체 복구, 손상/유실된 파일·volume 복구는 자동 삭제 없이 수동 복구로 남긴다.
- upgrade 후보는 현재 DB revision 검사를 통과한 경우만 전환한다. 이전 설정 backup과 journal을 유지하고 파일 교체 중단을 재개한다. pending upgrade 중 stop도 서비스를 시작하지 않고 정지한다. DB schema 변경·major upgrade·데이터 이동·삭제는 제공하지 않는다.
- 연결은 profile UUID+origin+cookie 이름에 대해 session 하나를 유지한다. 같은 서버의 여러 계정은 별도 profile을 사용한다. 메뉴 TUI는 동기식이므로 이전 서버의 늦은 화면 응답이 생기지 않고, 조회 시작 시 선택한 profile을 고정한다. password input의 echo fallback도 거부한다.
- 현재 증거: 1차 전체 local verify와 container verify 통과 후, volume 유실·upgrade 중단·secret 파일 durability·PostgreSQL readiness 경계를 보강했다. 최종 실행 결과는 아래에 별도로 기록한다. 임시 SQLite에서 관리자 원자성·이력 보존을 확인했으며 PostgreSQL EXCLUSIVE/advisory lock 검사는 opt-in 테스트 두 개를 추가했다. 실제 PostgreSQL로 실행하지 않은 검사는 성공으로 간주하지 않는다.
- 현재 문서(PRD/architecture/development/roadmap/work index)를 실제 구현 상태에 맞췄다. 기존 문서 변경과 역사적 DRAFT를 보존하면서 이번 두 단위의 승인·구현 상태를 구분했다. M1-3~5·새 PVE 로그인/MFA/token/ACL/암호화 저장/env 전환은 여전히 미구현이다.

### 최종 검증 (`2026-09-17`, 이번 checkout 실행)

M1-1·M1-2는 **`IMPLEMENTED` — 코드·격리 검증 완료**다. 실제 배포/설치 지원 검증과 전체 M1 완료를 뜻하지 않는다.

| 실행 | 이번 결과 |
|---|---|
| `git diff --check` | 통과 |
| 관련 client/backend/문서 계약 검사 | 보강 과정의 65 passed; 마지막 client 단독 46 passed |
| `pnpm run verify` | 성공: client **46 passed**, backend **773 passed, 25 skipped, 32 subtests passed**, frontend tests·ESLint·production build 통과 |
| `pnpm run verify:container` | 성공: Python 3.13 client **46 passed**, backend **773 passed, 25 skipped**, production image build 성공. Node 24 frontend 단계는 Docker cache 재사용 |
| 두 PostgreSQL 준비 script의 `sh -n` | 통과 (실제 script 실행/DB 기동 아님) |
| 합성 secret·가짜 image ID로 생성한 Compose의 `docker compose ... config --quiet` | 통과. 설정 문법 검사만 수행, pull/up/run/DB 없음 |
| `uv build --project client --wheel --out-dir client/dist` | 최종 wheel 생성, 포함 코드·두 배포 script가 source와 일치함을 확인 |
| 별도 저장소 내부 wheel venv에 hash lock+wheel 설치 | help와 명시적 memory TUI 진입→q 종료 성공. 서버 연결·keyring·서비스 조작 없음 |

- local Node `26.8.1`은 저장소 기준 `24`와 달라 engine 경고가 있다. container는 Node 24/Python 3.13 기준이다. backend 경고 95개는 기존 HTTPX TestClient/Alembic 설정 deprecation이며 실패는 없다.
- PostgreSQL 전용 25개 skip은 테스트 URL 미설정이다. 이번에 추가한 installation concurrency/advisory lock 두 개도 여기에 포함된다. SQLite 결과로 PostgreSQL 동시성 성공을 주장하지 않는다.
- 첫 container 실행은 sandbox Docker socket 접근 실패로 중단됐고, build-only 범위 권한 확장 후 최종 명령은 성공했다. 초기 실패를 성공 기록으로 덮지 않고 구분한다.
- 최종 실행 로그는 `/tmp/gjallar-m1-verify-final.log`, `/tmp/gjallar-m1-container-final.log`, `/tmp/gjallar-m1-wheel.log`에 있다. 임시 로그·wheel/venv·합성 Compose 파일은 공동 문서/소스에 커밋하지 않는다.
- 실제 Gjallar 설치·서비스 기동, 기존/운영 DB migration·데이터 변경, live Proxmox·token/ACL 호출은 **실행하지 않았다**. OS keyring, PostgreSQL 실제 동시성, Linux VM/macOS 설치·재기동, 원격 TLS proxy·브라우저 cookie, live env inventory 동등성은 **미검증**이다.
- 다음 검증은 [개발 안내의 실제 환경 순서](../development.md)의 disposable VM 새 설치 → 관리자/웹·CLI 로그인 → 중단·재실행·계정/이력 보존 → TUI 종료와 서비스 stop/start 구분 → 동일 schema upgrade 복구 → OS keyring/전용 PostgreSQL 동시성 순서다. live Proxmox 조회는 별도 exact target 승인 뒤 수행한다. 신규 PVE token 연결은 구현된 것처럼 표시하지 않는다.
- 기존 문서 변경을 보존했고 staged 변경은 없다. HEAD는 `8feae46cddb88aca47c149df9f1a9e24da880c07` 그대로이며 commit·push·rebase·reset을 수행하지 않았다.
