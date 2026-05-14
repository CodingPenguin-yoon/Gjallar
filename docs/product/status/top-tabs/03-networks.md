# Networks

평가일: 2026-05-13

검증 기준: coordinator가 backend `PYTHONPATH=backend backend/venv/bin/pytest -q backend/tests` -> 92 passed, frontend `for test_file in frontend/tests/*.mjs; do node "$test_file"; done` -> passed, `pnpm --dir frontend lint` -> passed, `pnpm --dir frontend build` -> passed를 기록했다.

## 구현 수준

현재 Networks는 bridge inventory와 IaC-backed NetworkPolicy 편집 화면이다. Proxmox network 자체를 변경하지 않고, guard된 IaC policy write만 수행한다.

## 구현 API/endpoints

- `GET /api/v1/networks`
- `GET /api/v1/networks/policy`
- `PUT /api/v1/networks/policy`

## 관련 파일

- Frontend: [frontend/src/components/NetworkPolicyScreen.jsx](../../../../frontend/src/components/NetworkPolicyScreen.jsx), [frontend/src/utils/networkPolicy.js](../../../../frontend/src/utils/networkPolicy.js), [frontend/src/services/apiV1.js](../../../../frontend/src/services/apiV1.js)
- Backend: [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py), [backend/app/network_policy.py](../../../../backend/app/network_policy.py), [backend/app/manifests/models.py](../../../../backend/app/manifests/models.py), [backend/app/manifests/loader.py](../../../../backend/app/manifests/loader.py)
- Tests: [frontend/tests/networkPolicy.test.mjs](../../../../frontend/tests/networkPolicy.test.mjs), [backend/tests/contracts/test_api_v1_network_policy.py](../../../../backend/tests/contracts/test_api_v1_network_policy.py), [backend/tests/manifests/test_network_profile.py](../../../../backend/tests/manifests/test_network_profile.py)

## 현재 구현

`GET /networks`는 live/read-only bridge inventory를 반환한다. `GET /networks/policy`는 관찰된 bridge와 IaC `manifests/networks/network-profiles.yaml` policy를 합쳐 등록 여부, 누락 bridge, static IP range 등을 보여준다.

`PUT /networks/policy`는 IaC root 아래 정책 파일만 정규화해서 쓰고 git commit을 시도한다. 경로 escape와 policy 오류는 실패 처리된다. Proxmox bridge 생성, 삭제, 수정은 하지 않는다.

## Create VM target gap

Target Create VM networking은 Network tab policy나 `network_id`/`server-net`를
source of truth로 사용하지 않는다. Target은 사용자가 target node를 선택한 뒤
그 node의 active live bridge를 선택하는 방식이다. Static mode는
`static_ip`, `prefix`, `gateway`를 모두 요구하고, DHCP는 later
guest-agent/inventory discovery warning과 함께 허용한다.

현재 code는 아직 Create VM에서 `network_id`/`server-net`와 bridge mapping을
사용한다. Static mode는 이제 `static_ip`, `prefix`, `gateway`를 명시적으로
요구하고, native create는 static IP에서 `.1` gateway 또는 `/24` prefix를
추론하지 않는다. 이 Networks tab은 current/legacy policy support 또는 future
recommendation/validation evidence로 남을 수 있지만, target Create VM source
of truth는 아니다.

## DRS Advisor 기준 gaps

[DRS recommendation/route 목표](../../prd/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md) 대비 route feasibility 판단에 필요한 shared storage 접근성, HA 상태, active task, config lock, passthrough, route unknown/blocked evidence가 없다.

현재 network policy는 Create VM/static IP와 bridge 등록에 가깝다. DRS migration route의 authoritative final pre-check로 쓰기에는 evidence 범위가 부족하다.

## 리스크/메모

IaC policy write는 side effect가 있는 기능이다. 다만 Proxmox network mutation은 아니며, DRS 실행 허가를 부여하지 않는다. route status Unknown은 migration 불가로 취급해야 한다.

## 다음 구현 slice

Networks는 편집 범위를 유지하고, DRS용 route evidence는 별도 read-only backend model로 추가한다. 첫 slice는 source/target/node bridge mapping, shared storage presence, missing evidence를 `Feasible/Warning/Blocked/Unknown`으로 정규화하는 계약 테스트다.
