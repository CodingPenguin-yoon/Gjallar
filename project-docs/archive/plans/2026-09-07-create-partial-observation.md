# Create 입력과 관찰 조건 분리

- 상태: `IMPLEMENTED`
- 날짜: `2026-09-07`
- 승인자: 사용자
- 승인 근거: 실제 guest agent 실패 조사 후 입력·실행 조건 분리를 먼저 진행한다는 제안에 “ㅇㅇ 진행해”로 승인
- 기준: [ADR-009](../../decisions/adr-009-proxmox-state-authority-and-create-history.md)

## 범위와 선택

partial base inventory가 있으면 Create 입력·검토 화면을 연다. 권한과 실행 적격성을 구분한다. 전체 snapshot의 partial 표시는 그대로 유지한다. Create만 guest agent 실패를 별도 평가하며 storage/network/VM config/detail 등 나머지 source 실패는 계속 실행을 차단한다. 대상별로 모든 source 범위를 축소하는 변경은 이번 단계에서 하지 않는다.

static IP 모드에서 guest agent 관찰이 불완전하면 충돌 없음으로 판단하지 않고 red 검토 결과로 차단한다. DHCP는 기존 discovery 위험 승인과 실행 후 readiness 검증을 유지한다. 입력 단계에서 incomplete source와 실패 대상을 검토 결과로 보여준다. 최초 실행 gate와 fresh 재검증에 같은 source 조건을 적용한다.

모든 partial을 live로 바꾸거나 오류를 무시하는 대안은 채택하지 않는다. 보수적으로 유지하는 static IP 차단은 불완전한 IP 근거에서 안전한 할당을 증명할 수 없다는 단점이 있다. 완전 관찰도 외부 네트워크 전체의 IP 미사용을 보장하지 않으며 기존 관찰 범위 내 검증이다.

## 구현·인수 조건

1. Create 전용 관찰 gate와 preflight source 검사를 추가한다. guest 실패+DHCP는 검토 가능, guest 실패+static은 red, 기타 source 실패는 차단한다. 시작·종료·unlock의 complete-live gate는 유지한다.
2. Create route를 읽기 inventory boundary로 바꾸고 권한으로 입력·검토 버튼을 제어한다. backend 검토 결과가 승인·실행을 결정한다.
3. fresh 관찰에서도 동일 조건을 확인하고 승인 drift·중복 방지·recovery 테스트를 유지한다. backend 전체·frontend tests/lint/build·문서 검사·독립 quality-review를 수행한다.

## 영향·복구와 비범위

API payload·DB schema·잠금·recovery transaction은 변경하지 않는다. 변경은 새 preflight check와 Create 관찰 허용 조건이다. 조회 실패는 fail closed이며 기록 실패를 숨기지 않는다. 권한·secret redaction·승인 binding을 보존한다. 새 코드만 되돌릴 수 있으며 저장된 검토 이력은 지우지 않는다. 다른 action gate 변경 또는 관찰 누락을 정상으로 표현하는 경우 중단한다.

이 승인은 Create 입력·검토 경계와 guest agent 실패의 모드별 실행 조건 변경을 의미하며 VM agent 설정 수정·실제 생성·배포·레거시 기록/잠금 제거를 의미하지 않는다.

## 구현·검증 결과

- partial inventory에서 Create 입력·검토를 허용하고 Create 전용 initial/fresh 관찰 조건을 적용했다. static IP는 incomplete 관찰에서 IP 미충돌로 표시하지 않는다. 실패 source와 대상은 검토 화면에 표시한다.
- 독립 quality-review에서 최초 wrapper가 fresh 조회·VMID 제안을 잃는 문제와 UI 오류 설명 누락을 찾아 수정했다. 최종 재검토에서 미해결 확정 결함은 없었다.
- backend 전체 **637 passed, 6 skipped**, 관련 targeted **22 passed**. frontend 17개 테스트 스크립트·ESLint·Vite build 통과. 문서 계약 검사와 diff 검사 통과. Python 3.14/Node 26 로컬 검증이며 기준 container·PostgreSQL 통합 검증은 이번 실행에 포함하지 않았다.
- 실제 Proxmox GET으로 initial→fresh 경로와 static의 guest 관찰 red/DHCP yellow 분류를 확인했다. Chrome에서 PARTIAL 상태로 템플릿·사양 입력 화면이 열리는 것을 확인했다. 실제 VM 생성·agent 설정 변경은 수행하지 않았다. 로컬 backend는 변경 코드로 재시작했고 background recovery는 disabled다.
- DHCP는 해당 환경에 DHCP 서비스가 있다는 보증이 아니다. static IP는 guest agent 정보 부족 시 계속 차단하며, storage/network/config/detail 관찰 범위는 여전히 전체 snapshot 기준이다. 기록·잠금 레거시 제거는 별도 계획이다.
