# 남은 파일 잠금·저장 정책·검증과 운영 작업 마감

- 상태: `IMPLEMENTED` (A 범위 완료, B·C는 별도 후속 작업)
- 작성일: `2026-09-14`
- 완료일: `2026-09-14`
- 사용자 목표: 남은 코드·문서·환경·Git 작업의 처리 가능성을 확인하고 완료까지 진행할 범위를 구체화한다.
- 승인자·승인일: 사용자, `2026-09-14`
- 진행 근거: 코드·정책·문서·검증 범위 제시 후 프로젝트 스킬과 강제 호출 지침을 제거했고, 사용자가 남은 작업 진행을 요청했다. A를 진행한다. B의 live 변경과 C의 commit/push는 구체적인 대상·내용을 확인한 뒤 별도 명시 요청을 받는다.
- 기준: [ADR-011](../../decisions/adr-011-create-legacy-retirement.md), [ADR-009](../../decisions/adr-009-proxmox-state-authority-and-create-history.md), [프로젝트 프로필](../../project-profile.md).

이 문서는 승인 당시 조사·범위와 완료 결과를 보존한다. 아래 현재·목표와 추천안은 작성 시점 기준이며, 최종 결과는 마지막 완료 기록과 [ADR-012](../../decisions/adr-012-create-preset-and-history-retention.md)를 따른다. B·C는 [후속 방향](../../plans/README.md)에 남아 있다.

## 현재와 목표

공통 target lock은 PostgreSQL로 전환됐지만 Start·Shutdown의 요청별 파일 잠금이 실제 실행 경로에 남아 있다. `vm_actions/start.py`와 `shutdown.py`의 adapter가 `vm_start.lock`·`vm_shutdown.lock`을 만들고, 각 workflow와 port가 acquire/release를 호출한다. 네 action의 파일 잠금을 모두 제거했다는 현재 문서와 차이가 있다. 종료된 Plan의 완료 기록은 보존하고 이번 Plan에서 잔여 구현을 다룬다.

목표는 Proxmox의 실제 상태와 실행 권위를 유지하면서 PostgreSQL의 기존 locator lock·Operation·recovery fence로 실행을 조정하는 것이다. 파일 잠금 제거가 중복 mutation이나 완료 이력 훼손을 만들면 완료로 처리하지 않는다.

Create의 템플릿 직접 입력·선택적 DB 프리셋과 입력·검토·승인·작업 기록은 이미 동작한다. 저장 방식과 보존 정책의 추천안은 현재 DB 저장 단위를 유지하고 자동 만료·삭제를 도입하지 않는 것이다. `job_runs`는 최신 상태, `job_artifacts`는 동일 identity upsert이므로 모든 수정본을 불변 이력으로 보존한다는 뜻은 아니다.

## A. 이번 승인으로 구현할 범위

### 1. Start·Shutdown 파일 잠금 제거와 경합 보완

- 기존 Operation 준비와 exact intent 검증을 유지하고 PostgreSQL target lock 획득 직후 Jobs·Operation을 다시 조회해 replay 또는 실행 여부를 확정한다.
- 선행 요청이 완료된 뒤 후행 요청이 lock을 얻어도 완료 Jobs를 running으로 덮거나 mutation을 재실행하지 않는다.
- 같은 owner의 lock 충돌은 기존 replay/in-progress 응답으로 처리하며 진행 중인 owner Operation을 blocked로 덮지 않는다. 다른 요청의 target 충돌과 동시 상태 전이도 기존 공개 오류 계약 안에서 처리한다.
- pre-dispatch terminal replay, exact owner·lock ID·Operation version/checksum과 recovery lease fence를 유지한다. lease 경쟁 패자는 mutation·projection·lock release를 수행하지 않는다.
- Start·Shutdown request file lock helper·adapter method·port·cleanup과 불필요해진 import를 제거한다. 새 mutex 테이블이나 migration은 추가하지 않는다.
- 저장된 과거 `pre_dispatch_file_guard_cleaned` evidence의 읽기 alias는 유지한다. 기존 lock 파일은 읽거나 자동 삭제하지 않는다.

영향 파일은 `backend/app/vm_actions/{start,shutdown}.py`, `backend/app/operations/vm_{start,shutdown}/{ports,workflow}.py`와 관련 계약·복구·PostgreSQL 테스트다. 공개 route·권한·요청 필드·DB schema·Proxmox mutation 종류를 변경하지 않는다.

### 2. 저장 정책 확정과 현재 문서 일치

- 추천안: 선택적 프리셋은 기존 DB에 유지하고 템플릿 직접 입력은 계속 프리셋에 의존하지 않는다.
- 현재 저장 단위의 입력·검토·승인·작업 기록을 자동 만료·삭제 없이 유지한다. 기존 approval/replay/recovery/artifact consumer를 보존한다.
- 승인이 나면 ADR에 정책 선택과 비용을 기록하고 명세·DB 문서의 해당 미확정 항목을 갱신한다. revision별 불변 원본 보존이나 장기 archive/migration 전체를 확정한 것으로 쓰지 않는다.
- 파일 잠금 구현이 실제로 제거된 뒤 아키텍처·작업 흐름·API·Runbook의 해당 설명을 코드와 맞춘다. 역사적 승인·검증 원문을 새 결과로 덮지 않는다.

### 3. 검증과 독립 검토

1. 회귀 테스트로 현재 파일 잠금 잔존과 stale replay 판단을 재현한다. 기존 사용자 변경은 그대로 보존한다.
2. Start·Shutdown 각각 동일 key/intent 동시 진입, 동일 key의 다른 intent, 다른 key의 같은 VM 및 Start 대 Shutdown의 배제를 확인한다. mutation은 최대 한 번이어야 한다.
3. 첫 Jobs 조회 뒤 선행 요청 완료·lock 해제, foreign lock busy 동시 처리, terminal replay와 recovery 경쟁을 검증한다. 완료 projection 보존과 안정적인 loser 응답을 확인한다.
4. 오래된 요청 잠금 파일이 있어도 실행·replay를 방해하지 않으며 파일 자체를 변경·삭제하지 않는지 확인한다.
5. 로컬 backend 전체, frontend 테스트·Lint·빌드와 `git diff --check`를 실행한다. pnpm wrapper가 멈추면 저장소 script와 같은 하위 명령을 실행하고 차이를 보고한다.
6. Docker의 Python 3.13 backend-test와 Node.js 24 production build를 실행한다. 별도 임시 PostgreSQL에서 기존 integration 8개와 추가 동시성 검증을 실행한다. 운영 DB를 테스트 URL로 사용하지 않고 임시 컨테이너·데이터만 정리한다.
7. 구현에 참여하지 않은 reviewer가 실제 diff와 검증 결과를 검토한다. 필요한 수정·검증을 끝내고 A의 완료와 B·C의 미완료를 구분한다.

## 선택지와 비용

| 항목 | 추천안 | 대안과 비용 |
|---|---|---|
| 요청 조정 | 기존 DB locator lock 뒤 상태 재조회 | 새 request mutex는 schema·복구·잠금 순서가 늘어 ADR-011의 단일 조정 방향에 맞지 않는다. |
| 프리셋 | 선택적 DB 저장 유지 | JSON/YAML 이관은 수정·조회 consumer와 전환 규칙을 추가로 설계해야 한다. |
| 이력 | 현재 저장 단위를 자동 삭제 없이 유지 | 기간별 삭제는 감사·replay·recovery 소비자와 retention 경계를 설계해야 한다. 추천안은 저장량이 계속 늘어날 수 있다. |

## B. 운영 환경: 현재 관찰과 후속 변경 경계

`2026-09-14` Proxmox GET 조회로 다음 상태를 확인했다. 인증 정보·게스트 네트워크 원문은 기록하지 않았다.

| 대상 | 현재 관찰 | 변경 전에 구체화할 사항 |
|---|---|---|
| `yoonmanserver2` VM 101 | running, agent 설정 1, guest network 조회 HTTP 500 | guest OS 관리 접근으로 설치·서비스·채널 상태 확인. 필요한 서비스 시작/설치와 재시작 영향을 특정한다. |
| `yoonmanserver2` VM 900 | running, agent 설정 없음, guest network 조회 HTTP 500 | OS와 agent 지원을 확인하고 게스트 설치·서비스 및 Proxmox agent 설정 변경, 재부팅 필요 여부를 특정한다. |
| `yoonmanserver` 템플릿 3000 | stopped template, agent 설정 1 | 9월 9일 clone의 guest-exec 금지 기록은 있으나 이번에는 guest 내부 정책을 재확인하지 않았다. 원본 정책 유지 또는 변경/별도 템플릿 사용을 결정해야 한다. |

guest OS 관리자 접근 가능 여부는 아직 확인하지 않았다. 기존 VM의 서비스·패키지·Proxmox 설정, Rocky 템플릿 보안 정책, VM 재부팅·clone 실증은 A에 포함하지 않는다. 대상의 현재 identity와 실제 조치·중단 영향을 확인해 승인 가능한 변경안으로 만든다. 환경 제약은 A가 완료돼도 해결된 것으로 표시하지 않는다.

## C. Git 마감

조사 시점 `main`은 로컬 `origin/main` 참조보다 3 commit 앞서 있고 기존 미커밋 변경·신규 파일이 다수 있다. 원격 최신 상태와 실제 배포는 이번 조사에서 확인하지 않았다.

기존 변경을 보존하면서 최종 diff·신규/이동 파일·시크릿 제외·검증 결과를 검토하고 commit 단위와 대상 목록을 제시한다. 과거부터 쌓인 변경을 이번 수정으로 오인하지 않는다. commit/push는 최종 대상과 원격 반영 의도를 사용자가 명시한 뒤 수행한다. rebase·force push·hard reset은 이 Plan의 범위가 아니다.

## 중단과 복구

- 중복 mutation, terminal 이력 덮어쓰기, foreign/stale owner의 lock release, 승인 비교 약화가 발견되면 A를 완료 처리하지 않고 해당 회귀를 먼저 해결한다.
- 파일 잠금은 단순 rollback 시 혼합 버전 실행을 안전하게 만들지 않는다. 배포 시 mutation worker를 중지하고 진행 중 작업을 관찰·정리한 뒤 단일 버전으로 전환한다. 실제 배포는 A에 포함하지 않는다.
- schema·사용자 데이터·운영 환경을 변경하지 않은 A 구현은 이번 diff만 되돌릴 수 있다. 기존 변경을 `git reset`/`restore`로 일괄 되돌리지 않는다. 기존 운영 이력·lock 파일·DB row를 임의 삭제하지 않는다.
- VM 내부 접근이나 보안 정책 선택이 없으면 B의 실제 수정을 보류하고 필요한 정확한 정보를 보고한다. Git 명시 요청 전에는 C의 검토 결과만 준비한다.

## 승인 문장

이 승인은 **A의 Start·Shutdown 요청 파일 잠금 제거와 기존 DB 조정 보완, 선택적 DB 프리셋 및 현재 저장 단위 이력의 자동 삭제 없는 보존 정책 확정, 관련 문서·회귀 테스트·격리 PostgreSQL/컨테이너 검증과 독립 검토**를 의미하며 **기존 VM/템플릿 변경·guest-exec 정책 해제·live 생성/재부팅/삭제·운영 DB 변경·production 배포·git commit/push**를 의미하지 않는다. B와 C는 각각 정확한 실행 범위를 확인한 뒤 명시적으로 승인한다.

## 작성 시점 확인

- 직전 조사: 로컬 backend 689 passed/8 PostgreSQL skipped, frontend 테스트·Lint·빌드와 diff 검사 통과. 당시 기준 컨테이너 검증은 미실행이었다.
- 이번 조사: Docker daemon 접근 확인, 위 세 대상 Proxmox GET 확인. guest OS 내부 설정이나 실제 수정 가능 권한까지 확인한 것은 아니다.
- 이 Plan과 계획 인덱스 변경 후 문서 계약 검사(`backend/tests/contracts/test_legacy_backend_cleanup.py`) 10 passed, `git diff --check` 통과. 제품 코드·DB·VM·템플릿·Git commit/push는 변경하지 않았다.

## A 완료 기록 — 2026-09-14

- Start·Shutdown의 요청 파일 잠금 helper·adapter·port·cleanup을 제거했다. 기존 파일은 변경하지 않고 과거 evidence alias만 읽기 호환으로 유지했다.
- DB target lock 획득·busy 응답 뒤 Jobs와 Operation을 다시 확인해 동일 요청의 중복 실행과 완료 결과 덮어쓰기를 방지했다. 공통 Operation repository·port에는 정확한 foreign lock을 확인하는 충돌 전이와, recovery가 인계받지 않은 실행 전 실패만 닫는 전이를 추가했다. 새 schema나 migration은 없다.
- 실행 준비 실패와 재요청이 양방향으로 겹치는 경우도 검증했다. recovery 인계 후 foreground가 잠금을 해제하지 않으며, foreground가 먼저 종료한 경우 늦은 replay는 정확한 terminal marker를 확인해 저장된 오류 계약을 유지한다.
- ADR-012에 선택적 DB 프리셋과 현재 저장 단위 이력의 자동 만료·삭제 없는 보존 정책을 확정했다. 명세·아키텍처·API·DB·흐름·Runbook·프로필과 문서 인덱스를 실제 구현에 맞췄다. 모든 수정본의 불변 보존이나 장기 archive 정책을 추가한 것은 아니다.
- 구현과 분리된 검토에서 동일 요청의 정상 running replay를 허용하도록 PostgreSQL 테스트 기대값을 바로잡고, 실행 전 실패와 replay 사이 경합을 수정했다. 재검토에서 미해결 지적 사항은 없었다.

| 검증 | 최종 결과 |
|---|---|
| 로컬 backend 전체 | Python 3.14.6: 715 passed, 23 skipped. PostgreSQL 전용 23개는 별도 실행 |
| 격리 PostgreSQL 통합 | 로컬 Python: 23 passed. 기존 migration·복구 검사 8개와 신규 admission·replay 경합 15개 |
| 기준 backend container | Python 3.13: 715 passed, 23 skipped |
| 기준 container의 PostgreSQL 통합 | Python 3.13과 임시 PostgreSQL 17: 23 passed |
| frontend | 17개 테스트 스크립트·ESLint·Vite production build 통과 |
| production image build | Node.js 24·pnpm 10.34.5 기준 테스트·Lint·빌드와 최종 이미지 생성 통과. 배포 미실행 |
| 문서·diff | 문서 계약 10 passed, `git diff --check` 통과 |

로컬 pnpm wrapper가 응답하지 않아 저장소 script에 대응하는 하위 명령을 직접 실행했고, 기준 버전은 Docker에서 검증했다. 테스트 경고는 남아 있지만 실패는 없었다. PostgreSQL 검사는 이번 작업 전용 임시 DB에서 실행했고 컨테이너를 종료·제거했다. Proxmox mutation은 fake client로 검증했으며 실제 VM·템플릿·운영 DB는 변경하지 않았다.

B의 guest agent·템플릿 정책 조치, production 배포, C의 전체 기존 변경 묶음 검토·commit/push는 완료하지 않았다. 기존 미커밋 변경과 앞선 프로젝트 스킬 제거를 보존했고 이번 구현 diff를 분리해 검토했다. 이 Plan의 종료는 A의 로컬 구현·문서·검증 완료를 의미한다.
