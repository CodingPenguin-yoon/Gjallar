# React Preset

Project Profile에서 `react`를 선택한 프로젝트에만 적용한다. 이 preset은 framework, build 도구, router, 상태 관리, UI library를 미리 확정하지 않는다.

## 설계 시 결정할 항목

`$project-bootstrap`은 요구사항을 근거로 다음을 비교한다.

- 공식 지원되는 Node 및 React 버전
- Vite, Next.js 또는 프로젝트에 적합한 실행 구조
- 패키지 관리자와 lock 파일
- routing 방식
- server state와 client state 관리 방식
- form, validation, UI component, styling 접근
- 테스트, Lint, 포맷, 타입 검사 도구
- backend API 계약과 인증 방식

선택지를 적합도 순으로 제시하고 선택 이유, 감수한 단점, 공식 정보 확인일을 Project Profile에 기록한다.

## 재현 가능한 환경

- Node 버전을 프로젝트에서 명시한다.
- 하나의 패키지 관리자와 해당 lock 파일을 일관되게 사용한다.
- `node_modules`와 build 산출물은 Git에서 제외한다.
- Codex는 Project Profile에 기록된 명령만 사용한다.
- 사용 중인 lock 파일을 확인하기 전에 임의의 패키지 관리자를 실행하지 않는다.

## 구조와 책임

- 화면이 아니라 업무 기능과 변경 이유를 기준으로 모듈 경계를 정한다.
- 페이지와 route는 조합을 담당하고 핵심 상태 규칙을 독점하지 않는다.
- 재사용 component는 명확한 UI 책임과 contract를 갖는다.
- API client, server state, form state, local UI state의 역할을 구분한다.
- backend의 내부 model이나 파일을 직접 import하지 않고 공개 API 계약을 사용한다.

프로젝트 규모가 작다면 복잡한 feature architecture를 미리 만들지 않는다. 실제로 독립 변경·테스트가 필요한 경계부터 분리한다.

## 상태와 데이터 흐름

- 원격 데이터와 로컬 UI 상태를 같은 전역 store에 무조건 넣지 않는다.
- state를 파생할 수 있으면 중복 저장하지 않는다.
- loading, empty, error, retry 상태를 명시적으로 처리한다.
- optimistic update는 실패 복구와 중복 요청 영향을 설계한다.
- form validation과 server validation의 책임을 구분한다.
- API response를 component 곳곳에서 임의 변환하지 않고 소유 위치를 정한다.

## Component와 Hook

- Component는 렌더링, 상호작용, orchestration 책임을 구분한다.
- Hook은 숨은 global service나 임의의 공통화 수단으로 사용하지 않는다.
- effect는 외부 시스템과의 동기화에 사용하고 파생 state 계산에 남용하지 않는다.
- props와 callback 이름은 상태의 의미와 방향을 드러낸다.
- 재사용 가능성만으로 거대한 범용 component를 만들지 않는다.

## 사용자 경험과 접근성

- keyboard, focus, label, semantic element 등 기본 접근성을 고려한다.
- 오류 메시지는 사용자가 취할 수 있는 다음 행동을 알려준다.
- 비동기 동작은 중복 제출과 취소·재시도를 고려한다.
- 성능 최적화는 측정 없이 memoization을 넓게 적용하지 않는다.

## 테스트와 검증

- 핵심 사용자 행동과 상태 전이를 테스트한다.
- 구현 세부 사항보다 사용자가 관찰하는 결과를 검증한다.
- API boundary는 mock 범위와 실제 계약 검증의 균형을 맞춘다.
- 접근성과 오류·loading 흐름을 포함한다.
- Lint, 타입 검사, 테스트, build 명령은 Project Profile에서 확정한다.

## 피할 패턴

- 모든 상태를 하나의 전역 store에 집중
- 페이지 component에서 API, 변환, 상태 규칙, UI를 모두 처리
- 의미 없는 wrapper component와 custom hook 남발
- backend 내부 타입을 직접 참조
- `any`, 타입 단언, ignore로 계약 문제를 숨김
- effect 의존성 경고를 억제해 순환 갱신을 숨김
