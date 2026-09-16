# 구현 계획: Network readiness 화면 종료와 내비게이션 정리

> 종료된 계획의 당시 조사·승인·검증 기록이다. 현재 구현 지시가 아니며 후속 방향은 [계획 인덱스](../../plans/README.md), 현재 기준은 [문서 안내](../../README.md)를 따른다.

- 상태: `IMPLEMENTED`
- 작성일: `2026-09-07`
- 승인자: 사용자
- 승인 근거: 독립 Network readiness 화면·메뉴·버튼 제거 추천에 대한 “그러면 정리하고” 요청과, 나머지 메뉴의 “중복 진입점과 메뉴 이름부터 정리” 선택.
- 기준: [Specification](../../specifications/project-specification.md), [ADR-007](../../decisions/adr-007-observe-first-operations-intelligence.md), [현재 Architecture](../../architecture/overview.md)

## 목표와 위험

관찰·판단·작업 기록을 찾기 쉽게 만들고, 현재 지원하지 않는 migration의 사전 비교에 집중된 독립 Network readiness 화면을 종료한다. `/instances/networks`의 기존 화면 제공 의미가 바뀌므로 frontend 공개 경로 변경으로 관리한다. 데이터·권한·백엔드 API·실행 및 recovery 로직은 변경하지 않는다.

## 현재·전환·목표 상태

- 현재: Network readiness가 Workloads 하위 메뉴와 Workload Cockpit·Overview 버튼으로 노출된다. Insights의 VM readiness와는 별도 기능이다.
- 전환: `/instances/networks`와 `/networks`는 인증된 VM inventory로 redirect한다. migration 네트워크 비교 화면·전용 helper·전용 테스트는 제거한다.
- 목표: Workloads는 inventory와 Create VM, Insights는 기존 네 category, Operations는 공통 작업 이력과 Jobs 기록, Settings는 계정과 사용자 관리 역할을 유지한다. 기능별 실행 진입점은 필요한 문맥에서 제공한다.

## 승인 범위

- 독립 Network readiness 화면·전용 계산 코드와 연결 메뉴·버튼을 제거한다.
- 기존 Network readiness 주소는 `/instances`로 안내한다.
- Operations의 Guided 하위 메뉴와 빈 목록의 중복 실행 버튼을 정리하고, 목록 상단 및 VM 문맥의 Guided 진입점은 유지한다.
- Insights의 overview/readiness, Operations의 목록/Jobs, Settings의 사용자 관리 메뉴 이름을 실제 역할에 맞게 정리한다.
- 선택지가 하나인 하위 메뉴는 표시하지 않는다.
- 필요한 기존 테스트와 현재 frontend/architecture 문서를 갱신한다.

이 승인은 Network readiness 독립 화면 종료와 중복 진입점·메뉴 이름 정리를 의미하며, Insights category나 Jobs/Artifacts 기능 삭제, 네트워크 inventory API·Create VM 필수 검사·권한 변경, DB migration, live Proxmox mutation을 의미하지 않는다.

## 선택과 단점

- 메뉴만 숨기면 호출되지 않는 독립 화면과 계산 코드가 계속 남는다.
- 승인된 독립 화면을 제거하고 기존 주소를 inventory로 redirect하는 안을 선택한다. 기존 링크가 오류로 끝나지 않지만 노드 간 bridge/CIDR 비교는 더 이상 제공하지 않는다.
- 다른 메뉴는 화면을 통합하지 않는다. Jobs와 Operations의 서로 다른 기록 계약, Insights category별 조회와 exact-target 링크를 보존한다.

## 구현·검증 단계

1. 화면 제거와 경로 안내: production 진입점의 잔여 참조 검색, route 동작 검사, Create VM의 공통 network API 사용 보존 확인.
2. 메뉴와 중복 버튼 정리: 정확히 하나의 활성 항목, operation 상세·Guided·Jobs query 경로, admin/viewer 표시 조건을 기존 계약 테스트로 확인.
3. frontend 전체 테스트·ESLint·production build와 `git diff --check` 실행. UI 변경 범위이므로 backend 전체 및 container 검증은 필요한 경우에만 확대한다.
4. 실행 중인 UI의 Workloads·Insights·Operations·Settings 및 기존 network URL을 브라우저에서 확인한다. 실행 버튼이나 계정 변경을 제출하지 않는다.
5. 구현과 분리된 reviewer가 이번 변경 diff와 검증 근거를 검토하고 현재 문서를 맞춘다.

## 복구·중단 조건

- 기존 사용자 변경은 작업 전 snapshot과 대조하여 보존한다. 되돌림은 이번 frontend·문서 변경만 역적용한다.
- 권한·API·DB·실행 로직 변경 또는 추가 기능 삭제가 필요해지면 현재 범위에서 분리한다.
- runtime 기준은 Node 24/Python 3.13이나 현재 로컬은 Node 26/Python 3.14다. 실행한 도구·결과와 미검증 환경을 구분한다.

## 구현 결과

- 독립 Network readiness Page/Screen/helper와 전용 테스트를 제거하고 Workload Cockpit·Overview의 진입점을 정리했다. 두 기존 URL은 VM inventory로 redirect한다.
- Insights는 Summary·VM readiness 이름을 사용하며 VM readiness 카드·section label도 일치시켰다. 나머지 category와 target/finding 링크는 유지했다.
- Operations는 All operations·Job history로 표시한다. Guided 하위 메뉴와 빈 목록의 반복 버튼만 제거하고 기존 실행 조건, 상단 버튼·VM 문맥 진입점과 route를 유지했다.
- 사용자 관리 메뉴·제목은 Users & sessions로 맞췄고, 일반 사용자의 단일 Account 하위 메뉴는 생략했다.
- frontend README와 현재 Architecture/API 문서에 화면 종료·redirect·메뉴 구성을 반영했다. 기존 recovery 변경은 작업 전 snapshot과 대조해 보존했다.

검증 결과:

- 로컬 Node `26.8.1`에서 `package.json`의 frontend test loop와 동일하게 전체 `.mjs` 17개 실행: 통과. 제거된 1개는 독립 network 비교 전용 테스트다.
- 로컬 ESLint `--ext js,jsx --report-unused-disable-directives --max-warnings 0`: 통과.
- Vite production build: 통과.
- Settings의 admin/non-admin와 Guided URL의 활성 메뉴를 React 정적 렌더링으로 확인: 통과.
- `git diff --check`: 통과.
- 브라우저에서 Workloads·Insights·Operations·Job history·Account·Users & sessions 표시와 이동, 두 network URL의 inventory redirect 확인. Workloads·Insights는 같은 크기의 변경 전후 캡처를 대조했고, 현재 PARTIAL 상태의 조회를 보존했다.
- 독립 Quality Review: 확인된 결함 없음. 이번 raw diff와 기존 사용자 변경 보존, 제거 코드 소비자, 권한·Guided 진입점·Jobs query·문서 범위를 검토했다.

backend 로직·API·DB·실행 계약을 변경하지 않아 backend 전체 테스트와 container 검증은 이번 범위에서 실행하지 않았다. Node 24 환경과 complete-live 상태의 실행 버튼은 별도 검증하지 않았다. live Proxmox mutation·계정 변경·DB migration·commit·push는 수행하지 않았다.
