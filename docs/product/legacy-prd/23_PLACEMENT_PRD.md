# Gjallar Placement PRD

## Current-direction note

이 문서는 역사적 Placement/read-only advisor 설계를 보존한다.
Current MVP product source of truth is `drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.
`/placement` route는 유지할 수 있지만, 상단 라벨과 제품 의미는 DRS Advisor로 전환한다.
새 방향은 read-only placement가 아니라 Proxmox-native migration/HA를 관찰하고, CPU/Memory 중심 추천을 만들고, Allowed VM에 대해 manual approved live migration을 실행/추적하는 advisor/control tower다.
DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.
아래 내용은 과거 1차 read-only Placement 설계로 읽는다.
하단의 open questions, test-first 계획, 구현 순서, 현재 결정까지 모두 historical Placement context다. 다음 작업 순서는 `drs-advisor/05_IMPLEMENTATION_PLAN.md`가 정한다.

## 0. 목적

Placement는 VMware DRS라는 제품 용어를 그대로 가져오지 않고, Proxmox 운영자가 이해할 수 있는 방식으로 VM 배치 상태와 이동 추천을 보여주는 Gjallar 화면이다.

첫 구현의 목표는 자동 이동이 아니다.
목표는 클러스터 안에서 VM이 어느 노드에 몰려 있는지, 어느 노드가 여유로운지, 어떤 이동을 검토하면 좋은지 읽기 전용으로 설명하는 것이다.

```text
Placement = read-only VM placement advisor
```

## 1. 제품 원칙

- Gjallar는 사람이 보는 운영 콘솔이다.
- Heimdall은 장기적으로 자동 판단/스케줄링 엔진 역할을 맡을 수 있다.
- Placement의 첫 화면은 Gjallar에 둔다.
- 자동 마이그레이션은 첫 구현 범위가 아니다.
- 추천은 실행보다 설명이 먼저다.
- 모든 실행 가능 동작은 기존 Gjallar 원칙처럼 risk, preflight, approval gate를 통과해야 한다.

역할 분리:

| 영역 | 책임 |
|---|---|
| Gjallar | Placement 화면, 상태 가시화, 추천 검토, 정책 표시, 승인/거절 UX, 이력 |
| Heimdall | 주기적 분석, 추천 계산 고도화, 자동 모드 판단, 장기 제어 루프 |

## 2. 용어

UI 상단 메뉴명은 `Placement`를 사용한다.

사용하지 않을 표현:

- DRS
- vMotion 자동화
- VMware 호환 DRS

화면 내부 표현:

- `Cluster Balance`
- `Node Load`
- `VM Distribution`
- `Placement Recommendations`
- `Placement Rules`
- `Placement History`

한국어 화면을 별도로 만든다면:

- `배치`
- `클러스터 균형`
- `노드 부하`
- `이동 추천`
- `배치 규칙`
- `실행 이력`

## 3. 상단 메뉴 위치

Placement는 `Create VM` 다음에 둔다.

```text
Dashboard | Infra Explorer | Networks | Create VM | Placement | Jobs/Runs | Risks/Alerts
```

이 위치가 자연스러운 이유:

- `Create VM`은 새 VM을 어디에 둘지 결정한다.
- `Placement`는 이미 존재하는 VM들이 어디에 놓여 있는지 평가한다.
- 둘 다 "VM 배치"라는 운영 흐름에 속한다.

## 4. 1차 구현 범위

1차 구현은 read-only dashboard다.

포함:

- 상단 메뉴 `Placement`
- `/placement` route
- `PlacementScreen`
- 기존 `/api/v1` inventory 데이터를 조합한 화면
- 노드별 CPU/Memory/VM 수 비교
- 불균형 상태 계산
- 이동 후보 추천 카드
- 추천 사유와 risk 표시
- 실행 버튼 없음

사용 가능한 기존 API:

```http
GET /api/v1/cluster/summary
GET /api/v1/nodes
GET /api/v1/vms
GET /api/v1/storage
GET /api/v1/networks
GET /api/v1/risks
GET /api/v1/jobs
```

1차 구현에서는 새 백엔드 API를 필수로 만들지 않는다.
프론트 순수 유틸로 Placement view model을 먼저 만든다.

## 5. 1차 비범위

첫 구현에서 하지 않는다:

- VM live migration 실행
- 자동 migration
- Proxmox write action
- affinity/anti-affinity 규칙 저장
- Heimdall 연동
- 백그라운드 스케줄러
- 장기 히스토리 DB 설계
- 리밸런싱 정책 저장
- 노드 maintenance mode 자동 처리

첫 구현에서 버튼을 표시해야 한다면 disabled/read-only 상태만 허용한다.

```text
Action: Review only
Execution: Not available in this slice
```

## 6. 화면 구성

### 6.1 Cluster Balance

클러스터 전체 균형 상태를 요약한다.

표시:

- 전체 노드 수
- online 노드 수
- 전체 VM 수
- running VM 수
- 가장 바쁜 노드
- 가장 여유 있는 노드
- CPU imbalance
- Memory imbalance
- 상태: `Balanced`, `Watch`, `Imbalanced`

상태 기준 초안:

| 상태 | 조건 |
|---|---|
| Balanced | 노드 간 CPU/Memory 차이가 작고 red risk가 없음 |
| Watch | 한 노드가 70% 이상이거나 노드 간 차이가 의미 있게 벌어짐 |
| Imbalanced | 한 노드가 85% 이상이거나 red risk/심한 쏠림이 있음 |

### 6.2 Node Load

노드별 부하를 비교한다.

표시:

- node name
- status
- CPU usage
- memory usage
- storage free
- running VM count
- total VM count
- visible network/bridge summary

예:

```text
yoonmanserver2  CPU 82%  Memory 76%  Running VMs 14
yoonmanserver3  CPU 31%  Memory 42%  Running VMs 6
```

### 6.3 VM Distribution

VM이 어떤 노드에 몰려 있는지 보여준다.

표시:

- 노드별 VM 개수
- running/stopped 구분
- template 제외 여부
- guest-agent/IP 확인 가능 VM 수
- risk가 있는 VM 수

목적은 "왜 이 노드가 무거운지"를 사람이 바로 이해하게 하는 것이다.

### 6.4 Placement Recommendations

이동 추천을 표시한다.

예:

```text
Move candidate: ubuntu-app-03
From: yoonmanserver2
To: yoonmanserver3
Reason: source node is hotter and target node has capacity
Risk: yellow
Execution: manual approval required in a later slice
```

추천 카드 필드:

- candidate VM
- source node
- target node
- reason
- estimated effect
- risk level
- blockers
- evidence
- execution availability

1차에서는 recommendation이 "실행 가능한 작업"이 아니라 "검토할 제안"임을 명확히 표시한다.

### 6.5 Placement Rules

1차에서는 규칙 저장/편집을 구현하지 않는다.
대신 앞으로 필요한 규칙의 자리를 화면에 둔다.

미래 규칙 후보:

- 특정 VM은 같은 노드에 두지 않기
- 특정 VM은 특정 노드 그룹 안에서만 실행
- DB VM은 자동 이동 제외
- 특정 storage/network가 있는 노드만 후보
- 운영 VM은 manual approval required
- 특정 시간대에는 이동 금지

1차 화면에서는 아래 상태로 표시할 수 있다.

```text
Rules: display only
Policy editing: deferred
```

### 6.6 Placement History

1차에서는 실제 실행 이력이 없을 수 있다.
Jobs/Runs와 연결할 자리만 정의한다.

미래 표시 항목:

- recommendation generated
- approved
- rejected
- migration started
- migration completed
- migration failed
- skipped by rule

## 7. 1차 추천 로직

처음 로직은 단순해야 한다.
정확한 자동화보다 설명 가능한 추천이 중요하다.

입력:

- nodes
- vms
- storage
- networks
- risks

기본 계산:

- 노드별 running VM 수
- 노드별 CPU usage
- 노드별 memory usage
- 노드별 storage free
- 노드별 red/yellow risk 수

추천 후보 조건 초안:

1. source node가 `Watch` 또는 `Imbalanced` 상태다.
2. target node가 online이고 source보다 여유롭다.
3. VM이 running 상태다.
4. VM에 red risk가 없다.
5. target node에 필요한 network/bridge가 있다.
6. target node의 storage 제약을 위반하지 않는다.

추천하지 않는 경우:

- source/target 정보가 불완전함
- target node offline
- VM에 red risk 있음
- network/bridge evidence 부족
- storage evidence 부족
- template VM
- stopped VM은 낮은 우선순위 또는 제외

첫 scoring 예:

```text
source_pressure = max(cpu_usage_percent, memory_usage_percent)
target_headroom = 100 - max(target_cpu_usage_percent, target_memory_usage_percent)
imbalance_delta = source_pressure - target_pressure
recommend when source_pressure >= 70 and imbalance_delta >= 25
```

이 수치는 제품 기본값이며 나중에 Settings/Profile에서 조정 가능하게 만들 수 있다.

## 8. Risk / Approval 정책

1차 Placement는 read-only라서 approval이 필요 없다.

하지만 추천에는 risk를 반드시 표시한다.

Risk level:

| Risk | 의미 |
|---|---|
| Green | 추천 검토 가능. 알려진 blocker 없음 |
| Yellow | 추천은 가능하지만 운영자 확인 필요 |
| Red | 추천하지 않음. 실행 후보에서 제외 |

Red 예:

- target node offline
- bridge 없음
- storage evidence 없음 또는 부족
- VM에 기존 red risk 있음
- Proxmox inventory stale
- migration capability evidence 없음

Yellow 예:

- source가 바쁘지만 target도 여유가 크지 않음
- guest-agent 미응답
- VM IP 확인 불가
- 최근 job 실패 이력
- storage/network evidence 일부 부족

미래 실행 slice 정책:

- migration 실행은 반드시 approval-gated action이다.
- red risk는 승인으로 우회하지 않는다.
- yellow risk는 경고 체크박스가 필요하다.
- 실행 전 preflight를 다시 수행한다.
- 실행 결과는 Jobs/Runs와 Placement History에 기록한다.

## 9. API 방향

1차는 기존 inventory API와 프론트 유틸로 충분하다.

2차부터 백엔드 API를 추가할 수 있다.

후보:

```http
GET /api/v1/placement/summary
GET /api/v1/placement/recommendations
GET /api/v1/placement/rules
POST /api/v1/placement/recommendations/{recommendation_id}/approve
POST /api/v1/placement/recommendations/{recommendation_id}/execute
```

1차에서 `approve`와 `execute`는 만들지 않는다.

`GET /api/v1/placement/recommendations` 응답 초안:

```json
{
  "status": "watch",
  "recommendations": [
    {
      "recommendation_id": "placement_rec_xxx",
      "vmid": 142,
      "vm_name": "ubuntu-app-03",
      "source_node_id": "yoonmanserver2",
      "target_node_id": "yoonmanserver3",
      "risk_level": "yellow",
      "reason": "source node is hotter and target node has capacity",
      "estimated_effect": {
        "source_cpu_after": 68,
        "source_memory_after": 65
      },
      "blockers": [],
      "evidence": {
        "source_cpu_usage_percent": 82,
        "target_cpu_usage_percent": 31,
        "network_bridge_verified": true
      },
      "execution": {
        "available": false,
        "reason": "migration execution is deferred"
      }
    }
  ]
}
```

## 10. UI acceptance criteria

1차 구현이 완료됐다고 볼 수 있는 조건:

- 상단 메뉴에 `Placement`가 보인다.
- `/placement` route가 있다.
- Placement 화면은 기존 `/api/v1` read-only data만 사용한다.
- 노드별 부하를 비교할 수 있다.
- 클러스터 균형 상태가 `Balanced` / `Watch` / `Imbalanced` 중 하나로 표시된다.
- 최소 하나 이상의 설명 가능한 recommendation model을 만들 수 있다.
- 추천 카드에는 source, target, reason, risk, execution availability가 표시된다.
- migration 실행 버튼은 없거나 disabled다.
- red risk recommendation은 실행 후보로 보이지 않는다.
- 화면 텍스트는 DRS/VMware 용어에 의존하지 않는다.

## 11. Test-first 계획

프론트 순수 유틸 테스트부터 시작한다.

후보 파일:

```text
frontend/src/utils/placement.js
frontend/tests/placement.test.mjs
frontend/src/components/PlacementScreen.jsx
```

테스트해야 할 것:

1. 균형 잡힌 노드는 `Balanced`로 계산된다.
2. 한 노드가 70% 이상이고 차이가 크면 `Watch`가 된다.
3. 한 노드가 85% 이상이면 `Imbalanced`가 된다.
4. source가 바쁘고 target이 여유로우면 recommendation이 생성된다.
5. target offline이면 recommendation이 생성되지 않는다.
6. VM에 red risk가 있으면 이동 후보에서 제외된다.
7. network/bridge evidence가 없으면 red/yellow risk로 표시된다.
8. recommendation은 read-only action model을 반환한다.
9. UI navigation에 `/placement`가 포함된다.
10. `DRS` 문자열은 화면/유틸 출력에 등장하지 않는다.

백엔드 API는 2차에서 contract test를 추가한다.

## 12. 구현 순서

권장 순서:

1. `frontend/tests/placement.test.mjs` 추가
2. `frontend/src/utils/placement.js` 추가
3. 기존 mock inventory shape에 맞춘 Placement view model 구현
4. `PlacementScreen.jsx` 추가
5. `App.jsx` nav와 route에 `Placement` 연결
6. frontend `.mjs` tests 실행
7. `pnpm lint`
8. `pnpm build`
9. 필요할 때만 `/api/v1/placement/*` 백엔드 API 설계로 승격

## 13. Open questions

- CPU/Memory threshold 기본값은 70/85가 적절한가?
- stopped VM도 배치 추천 대상에 넣을 것인가?
- storage가 shared가 아닌 경우 target node 후보를 어떻게 제한할 것인가?
- Proxmox live migration capability를 어떤 read-only evidence로 확인할 것인가?
- affinity/anti-affinity 규칙은 Gjallar IaC manifest에 둘 것인가, Heimdall policy에 둘 것인가?
- recommendation 이력은 Jobs/Runs로 충분한가, 별도 Placement history가 필요한가?
- Heimdall이 붙기 전까지 추천 계산을 프론트에 둘 것인가, 백엔드 read-only API로 빨리 옮길 것인가?

## 14. 현재 결정

Historical note: 이 섹션의 결정도 현재 제품 결정이 아니다. Current MVP product source of truth is `drs-advisor/`; next implementation work follows `drs-advisor/05_IMPLEMENTATION_PLAN.md`.

- 상단 메뉴명은 `Placement`다.
- 첫 구현은 read-only다.
- 첫 구현은 자동 migration을 포함하지 않는다.
- 첫 구현은 기존 `/api/v1` inventory 데이터를 조합한다.
- Gjallar는 화면/승인/감사 흐름을 담당한다.
- Heimdall은 미래 자동 판단/제어 엔진 후보로 둔다.
