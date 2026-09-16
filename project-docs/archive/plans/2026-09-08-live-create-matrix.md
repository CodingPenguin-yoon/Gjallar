# 서버 3 생성 실증과 테스트 VM 정리

- 상태: `IMPLEMENTED`
- 승인자: 사용자
- 승인일: `2026-09-08`
- 완료일: `2026-09-09`
- 승인 근거: VMID 10000–10100 중 임의 사용, 서버 3, 스토리지·네트워크 재량과 DHCP, 복수 VM 테스트, 종료 후 삭제 요청

## 범위와 완료 조건

`yoonmanserver3`에서 Ubuntu(118)·Rocky(3000) 각각 stopped/boot_and_verify 네 조합을 순차 검증한다. 후보 10000–10003은 현재 비어 있음을 확인했다. 템플릿 source는 yoonmanserver, storage는 nas-server, bridge는 vmbr0, 2 CPU/4096 MB/50 GB, DHCP다. 이번 테스트용 SSH 공개키만 입력하며 private key는 외부에 전송하지 않는다.

Create UI의 입력→검토→승인→실제 생성과 Operation 결과를 확인한다. 추천 VMID는 예약이 아니므로 직전 부재·충돌 검증을 유지한다. 실패·불명확 결과는 같은 mutation을 재실행하지 않고 task·actual state·Operation으로 확인한다.

테스트마다 이번 실행에서 생성한 정확한 VMID·고유 이름과 가능한 VM identity를 대조하고 원격 task가 종료된 뒤 정리한다. running이면 종료 후 삭제하며, 이름 불일치·기존 VM·활성 task가 있으면 삭제를 중지한다. DB 이력·공통 잠금 row를 직접 삭제하거나 force-complete하지 않는다. 기존 VM·템플릿·스토리지·네트워크 설정은 변경하지 않는다.

기존 대상에 대한 영향이나 추적 불가능한 원격 task가 나타나면 다음 테스트를 중단한다. 완료 조건은 각 조합의 실제 성공/실패·원인 기록과 이번 테스트 VM 부재 확인이다. 운영 DB schema 변경·배포·기존 VM 삭제는 범위가 아니다.

이 승인은 지정 범위 테스트 VM의 생성·부팅·검증·종료·삭제를 의미하며 기존 VM/템플릿 수정이나 안전장치 우회를 의미하지 않는다. 실패 시 Proxmox actual state를 관찰한 후 이번 테스트 산출물만 정리한다.

## 실증 중 발견한 차단점

### 승인 충돌 수정 범위 (`2026-09-09` 사용자 승인)

사용자가 승인 충돌 원인 설명 후 “수정하자”고 승인했다. DHCP의 `inventory_guest_agent_incomplete` 관찰 경고만 exact plan의 risk summary에서 제외하고, preflight에는 상세 관찰을 유지한다. DHCP의 `dhcp_requires_discovery` 경고와 yellow acknowledgement는 유지한다. static IP, 다른 source 누락, VMID·템플릿·사양·배치·접속 조건은 기존 비교·차단을 유지한다. 전체 risk 비교 제거는 채택하지 않는다.

재현 테스트로 guest agent 실패 대상 변경·복구·새 누락에도 DHCP 검토 checksum 및 승인이 유지되고, static IP와 필수 조건 변경은 차단됨을 확인한다. 그 뒤 전체 backend 회귀 검사와 코드 검토를 수행하고 기존 네 조합 실증을 재개한다. 기존 계획은 새 검토로 갱신하며 DB 이력을 직접 변경하지 않는다. 문제가 있으면 코드 변경을 되돌리고 실증을 멈춘다. 이 승인은 DHCP의 비차단 관찰과 생성 조건의 비교 분리를 의미하며 live 안전장치나 static IP 충돌 검증 해제를 의미하지 않는다.

Ubuntu stopped/VMID 10000의 UI 검토까지 진행했으나 승인 단계에서 `PROXMOX_CREATE_IDEMPOTENCY_CONFLICT`가 발생했다. 첫 요청은 같은 guest agent 실패 대상 목록의 병렬 완료 순서가 바뀌어 동일 계획이 다른 digest로 계산됐다. inventory 실패 목록을 정렬하는 최소 수정과 실패 재현→통과 테스트를 적용했다.

새 검토에서도 `yoonmanserver2:300`의 guest agent가 응답 여부를 바꾸면서 실패 대상이 3개에서 2개로 바뀌었다. DHCP의 관찰 경고 상세가 exact plan identity에 포함되고 approve가 plan을 다시 계산·저장하여 충돌한다. 관찰 경고와 실행에 필요한 조건의 비교·저장 경계를 후속 수정하기 전에는 실증 완료로 처리하지 않는다. 현재 변경은 순서 안정화만이며, 승인 비교나 실행 전 검증을 완화하지 않았다.

실제 Create 버튼은 실행하지 않았다. 읽기 전용 Proxmox cluster inventory에서 10000–10100 전체 부재를 확인했으며 삭제할 테스트 VM은 없다. 네 조합의 실제 생성·부팅·삭제 검증은 미완료다. DB 검토·Operation 이력은 보존했다.

### 수정 검증 결과 (`2026-09-09`)

DHCP 비차단 guest agent 관찰 경고를 plan risk summary에서 분리했다. preflight 관찰·DHCP discovery acknowledgement·static IP 차단·필수 조건의 최초 mutation 전 검증은 유지했다. 실패 대상 변경/복구/새 누락의 승인 회귀 테스트를 수정 전 실패→수정 후 통과로 확인했다. DHCP·static 모두 VMID/템플릿/bridge/storage/offline/필수 source 누락/관찰 실패 시 mutation client와 runner 미호출 검증이 통과했다. 기존 exact plan/검토 checksum 내용은 DHCP 관찰 변화로 바뀌지 않는다. 기존 plan 재구성·artifact 저장 구조 자체는 변경하지 않았다.

전체 backend `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests`: 680 passed, 8 skipped. `git diff --check` 통과. frontend 코드는 변경하지 않았고 container 검증은 이번 수정에서 실행하지 않았다. quality-review 기준의 동일 에이전트 별도 검토에서 이번 변경의 추가 결함은 확인하지 않았다. API·작업 흐름 문서에 비교 경계를 반영했다. 개발 서버를 재시작했으며 브라우저가 `/login`으로 이동하여 실증은 사용자 로그인 대기 중이다. 네 조합 실증까지 완료한 상태는 아니다.

### 재개 중 발견 사항 (`2026-09-09`)

사용자가 실증 재개와 Dashboard 관찰 경고 수정을 요청했다. guest agent만 불완전하고 나머지 source와 endpoint 조회가 정상인 경우에만 Dashboard 안내를 VM 내부 IP 관찰 누락으로 제한하고, 노드 상태 표시는 노드 관찰을 기준으로 한다. 실제 누락 metadata나 다른 source/HTTP 실패는 기존 오류 안내를 유지한다.

첫 실제 요청(VMID 10000, `gjallar-test-0909-ubuntu-stopped-10000`)은 approval/dispatch를 통과했으나 token-authenticated UPID의 `!` 문자를 허용하지 않는 evidence sanitizer 때문에 `needs_reconciliation`으로 멈췄다. Proxmox clone은 정상 완료했고 서버 3의 exact 이름·vmgenid·smbios UUID 및 task 종료·stopped를 대조한 뒤 삭제했다. 부재 확인 완료. 원래 Operation 이력과 lock은 임의 수정하지 않았다. API 토큰 UPID의 정상 문자 `!`를 보존하는 최소 수정과 locator injection 거부 회귀 테스트를 추가했다. 기존 요청의 clone은 재실행하지 않는다.

Ubuntu boot(10001)은 clone/config/start/DHCP IP 관찰까지 성공했으나 테스트 계정 `operator`가 OS의 기존 그룹과 충돌해 cloud-init users_groups 오류가 발생했다. 정상 종료 후 읽기 전용 복구로 needs_reconciliation을 기록하고 exact identity 확인 후 삭제·부재 확인했다. 후속 테스트는 `gjallartest` 계정명을 사용한다.

긴 cloud-init --wait 동안 guest-exec polling에서 foreground heartbeat를 전달하지 않아 lease가 만료되는 결함을 함께 수정했다. 각 status poll마다 기존 heartbeat를 호출하며 갱신 실패는 전파해 계속 실행하지 않는다. lease 갱신/갱신 실패 중단/runner 전달 회귀 테스트를 추가했고 backend 전체 689 passed, 8 skipped다. 장시간 대기 중 검증·결과 저장이 유지되는지 후속 부팅 실증에서 확인한다.

Rocky stopped(10002, Operation `ui-a4856c99-d3ed-4a01-8c63-80bfdc6a87cc`)은 UI에서 succeeded/readiness completed, Proxmox에서 서버 3·stopped·DHCP·gjallartest·2 CPU/4096 MB/50 GB를 확인했다. identity 대조 후 삭제·부재 확인 완료. Rocky boot(10003)는 다음 실증으로 진행한다. Ubuntu 두 조합은 수정된 코드와 `gjallartest` 계정으로 빈 VMID 10004·10005에서 재검증한다.

Dashboard 실제 화면에서 Node inventory 3/3 online과 VM 내부 IP 관찰 누락 안내를 확인했다. 별도 읽기 확인에서 서버 2 VM 101은 agent enabled이지만 not running, 900은 agent 설정 없음, 300은 정상 응답이었다. 기존 VM/템플릿 설정을 임의 변경하지 않았다.

Rocky boot(10003, Operation `ui-abf996a1-3bf3-45f4-b0a6-97830eeebe9c`)은 running/guest agent/DHCP `192.168.2.225`까지 확인했으나 cloud-init guest-exec가 Proxmox HTTP 500으로 거부됐다. 실제 응답은 `Agent error: Command guest-exec has been disabled`였다. 템플릿 정책을 임의 해제하지 않았다. Gjallar는 observed-after와 needs_reconciliation을 정상 저장했고 foreground lease 저장 실패는 재발하지 않았다. exact identity·원격 task 종료를 확인한 뒤 정상 종료·삭제·부재 확인했다.

Ubuntu stopped 재검증(10004, Operation `ui-114b2588-243f-4747-bec6-c35d6ef5e07b`)은 succeeded/readiness completed와 서버 3의 stopped·지정 사양을 확인했다. identity 대조 후 삭제·부재 확인했다.

최종 코드 검증은 local backend 689 passed, 8 skipped, Python 3.13 backend container도 689 passed, 8 skipped다. frontend 17개 테스트 스크립트와 production Docker의 Node.js 24 테스트·Lint·빌드가 통과했다. guest agent 외 다른 endpoint metadata의 source 누락이나 metadata 부재를 정상으로 안내하지 않는 Dashboard 회귀 검사도 포함했다. quality-review 기준의 동일 에이전트 별도 검토를 수행했다. production 배포나 기존 VM/템플릿 정책 변경은 수행하지 않았다.

## 최종 실증 결과 (`2026-09-09`)

Ubuntu boot 재검증(10005, Operation `ui-2052fbd7-ab3d-498d-9483-3a82b55933a1`)은 succeeded/readiness completed로 완료됐다. running·guest agent·DHCP IP `192.168.2.250`·cloud-init completed 네 항목이 모두 verified다. 템플릿의 apt 및 snap 업데이트로 초기화가 약 10분 걸렸으며, 대기 중 foreground lease 갱신과 완료 후 recovery completed·lease 해제를 확인했다. 원격 task 종료·exact identity 확인 후 정상 종료·삭제했다.

| VMID | 조합 | 실제 결과 | 정리 |
|---|---|---|---|
| 10000 | Ubuntu stopped 첫 시도 | clone 완료, API 토큰 UPID 처리 오류로 reconciliation. 코드 수정 후 10004 재검증 | 삭제·부재 확인 |
| 10001 | Ubuntu boot 첫 시도 | 부팅·DHCP 확인, operator 그룹 충돌로 cloud-init 실패 및 대기 lease 만료. 수정 후 10005 재검증 | 삭제·부재 확인 |
| 10002 | Rocky stopped | succeeded, readiness completed | 삭제·부재 확인 |
| 10003 | Rocky boot | 부팅·DHCP 확인, guest-exec 금지로 cloud-init 검증 불가. needs_reconciliation 정상 기록 | 삭제·부재 확인 |
| 10004 | Ubuntu stopped 재검증 | succeeded, readiness completed | 삭제·부재 확인 |
| 10005 | Ubuntu boot 재검증 | succeeded, 부팅·agent·IP·cloud-init 검증 완료 | 삭제·부재 확인 |

최종 live 조회에서 VMID 10000–10100 전체 VM 부재와 nas-server의 이번 테스트 VM 10000–10005 디스크 부재를 확인했다. 실패 Operation의 감사·복구 기록을 임의 삭제하거나 성공으로 변경하지 않았다. 네 조합의 실제 결과와 테스트 산출물 정리라는 완료 조건을 충족했다. 모든 템플릿의 boot_and_verify 성공을 의미하지 않는다.

남은 환경 조건은 기존 서버 2 VM 101·900의 guest agent 관찰 불가와 Rocky 템플릿의 guest-exec 금지다. Dashboard는 VM 내부 IP 관찰 누락을 안내하면서 정상 노드·CPU·메모리·스토리지 관찰을 표시한다. 기존 VM/템플릿 정책은 이번 범위에서 변경하지 않았다. Rocky 초기화 검증 지원과 기존 VM agent 설정은 별도 대상·정책 확인이 필요하다.
