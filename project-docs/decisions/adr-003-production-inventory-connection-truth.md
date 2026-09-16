# ADR-003: Production Inventory 연결 상태와 Test Fixture 격리

- 상태: `ACCEPTED`
- 날짜: `2026-07-20`
- 최신 명확화: `2026-08-26` — base snapshot의 부분 관찰과 read/mutation capability 분리
- 결정자: `사용자`
- 대체하는 ADR: `없음 — 기존 Project Specification과 전환 Plan의 explicit demo mode 결정을 이 ADR이 정정`
- 대체된 ADR: `없음`

> 현재 적용 안내(2026-09-07): 배경의 fake fallback은 결정 당시 제거 대상이었다. 현재 product runtime에는 해당 fallback이 없고, partial snapshot은 읽기에 사용한다. 이후 [Create 관찰 조건 분리](../archive/plans/2026-09-07-create-partial-observation.md)에서 Create 입력을 열고 guest agent 실패를 static/DHCP별로 검증하도록 변경했다. 아래 complete-live 결정은 다른 action에 계속 적용되며 Create의 현재 예외는 해당 계획과 현재 API를 따른다.

## 배경

현재 `GJALLAR_INVENTORY_MODE=auto`는 Proxmox credential이 없으면 fixture 기반 inventory로 fallback한다. 이 동작은 개발에는 편하지만 control plane 화면에서 fake state를 실제 Proxmox state로 오인하게 만들 수 있다. 사용자는 product runtime에서 mock/demo data를 표시하지 않고 연결되지 않은 운영 화면을 숨기는 방향을 승인했다.

## 결정

- product runtime의 connection state는 `unconfigured`, `live`, `degraded`만 사용한다.
- `unconfigured`는 필수 Proxmox 설정이 없거나 mode가 유효하지 않은 상태다.
- `live`는 configured Proxmox adapter가 authoritative snapshot과 기대 sub-source를 완전하게 관측한 상태다.
- `degraded`는 설정은 존재하지만 인증, TLS, timeout, network 또는 API 오류로 base snapshot을 관측하지 못했거나, base snapshot은 있으나 일부 sub-source가 불완전한 상태다. 후자는 `inventory_available=true`, `freshness=partial`, source별 availability로 전자와 구분한다.
- `auto`는 전환 호환을 위해 live 설정 해석만 유지하며 credential 누락이나 연결 실패를 fake로 fallback하지 않는다.
- `fake`/`demo` mode는 product environment contract에서 제거한다.
- `FakeProxmoxInventoryAdapter`는 unit/contract test가 직접 주입하는 fixture로만 남긴다.
- 연결 상태 endpoint는 redacted state와 reason을 반환하지만 credential과 secret-bearing URL을 노출하지 않는다.
- 읽기 가능성과 mutation 가능성을 분리한다. authoritative base snapshot의 `inventory_available=true`이면 partial이어도 Overview, Workloads와 exact VM read를 허용하지만 incomplete source를 정상 empty로 표시하지 않는다.
- Create VM 실행과 VM mutation은 complete `live` observation에서만 허용한다. UI capability뿐 아니라 backend mutation provider도 같은 경계를 검증한다.
- Jobs/Risks와 Account/Admin처럼 Proxmox actual state가 필요 없는 복구·관리 화면은 계속 접근할 수 있다.
- 이 단계에서는 stale inventory를 별도로 저장하거나 표시하지 않는다.

## 이유

control plane의 빈 화면이나 명시적 장애는 잘못된 actual state보다 안전하다. 테스트 fixture를 application runtime 선택지에서 분리하면 개발 가능성을 유지하면서 production truth boundary를 단순하게 만들 수 있다.

## 영향

- API: additive connection status endpoint와 inventory unavailable `503` error contract가 생긴다. 기존 inventory path와 success payload는 live 상태에서 유지한다.
- UI: inventory read route는 `inventory_available`을, Create/mutation capability는 complete `live`를 확인한다. base snapshot 부재에는 setup/degraded 안내를 표시하고 partial snapshot에는 가용 데이터와 불완전 source를 함께 표시한다.
- 설정: `.env.example`은 live connection을 기본으로 설명하며 fake fallback을 안내하지 않는다.
- 데이터베이스: schema와 persistence 변경은 없다.
- 테스트: fake fixture는 environment mode가 아니라 test injection으로 사용한다.

## 감수한 단점

- Proxmox 없이 product UI 전체를 둘러보는 내장 demo 경험이 사라진다.
- base snapshot을 얻지 못한 degraded 상태에서는 마지막 성공 inventory를 보여주지 않으므로 장애 중 조회 기능이 제한된다. partial snapshot은 현재 정상 source만 읽을 수 있다.
- `auto` 이름은 전환 동안 남지만 live-or-unavailable 의미만 가진다.

## 검증 방법

- credential 누락과 invalid mode에서 fake row가 API에 나타나지 않는다.
- configured adapter의 인증/TLS/timeout/network 실패가 안전한 `degraded` reason으로 표현된다.
- live snapshot 응답은 `source`, `observed_at`, `freshness`, connection state를 제공한다.
- partial snapshot은 `degraded/partial`, `inventory_available=true`와 source별 completeness를 제공하고 read 화면은 열리되 backend와 frontend mutation capability는 비활성화된다.
- product runtime에서 `fake` mode를 요청해도 fixture adapter가 선택되지 않는다.
- 테스트는 direct fake injection으로 기존 inventory workflow를 검증한다.

## 재검토 조건

- 별도 sales/demo 배포판이 실제 제품 요구로 승인될 때
- authoritative stale snapshot 저장소와 retention 정책이 도입될 때
- multi-cluster connection profile과 per-cluster availability가 필요할 때
