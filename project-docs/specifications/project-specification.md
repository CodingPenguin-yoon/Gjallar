# 프로젝트 명세: Gjallar Observe-first Operations Intelligence

- 상태: `APPROVED`
- 최종 검토일: `2026-08-24`
- 최종 승인자: `사용자`
- 관련 ADR: [`ADR-007`](../decisions/adr-007-observe-first-operations-intelligence.md)

## 1. 해결할 문제

- Proxmox는 VM·node·task의 actual state와 실행 기능을 제공하지만, 상태의 freshness·provenance, 변화 맥락, 운영 작업과 결과 evidence를 한 흐름으로 설명하지 않는다.
- inventory, Jobs, risk·readiness·capacity와 operation evidence가 분리되면 운영자는 현재 어떤 상태인지뿐 아니라 무엇이 변했고 왜 주의가 필요한지를 직접 조합해야 한다.
- 상태를 바꾸는 작업이 필요할 때도 사전 점검, 실행 권한, 불확실성 처리, 결과 검증과 감사 증거가 일관된 흐름으로 연결돼야 한다.
- 기존 DRS policy·approval·migration·reconciliation은 Gjallar가 배치 의도와 migration 상태기계를 장기 소유하게 만들어 권한, 복구와 Proxmox 환경 결합을 키운다.

성공하면 운영자는 변경 작업보다 먼저 현재 상태, freshness, 위험과 변화 근거를 Gjallar에서 이해하고, 지원되는 작업이 필요할 때만 검증된 action lifecycle을 사용한다.

## 2. 사용자와 이해관계자

| 대상 | 목표 | 현재 어려움 | 주요 사용 흐름 |
|---|---|---|---|
| `viewer` | workload 상태, 변화, 위험과 evidence 이해 | actual state, freshness와 운영 맥락이 분리됨 | Workload Cockpit → Insights → 관련 operation/evidence 조회 |
| `operator` | 상태를 이해한 뒤 필요한 변경만 안전하게 수행 | 조회, 실행, 검증과 복구가 여러 도구에 흩어짐 | observe → explain → 지원 action 선택 → pre-check/실행 → verification |
| `admin` | 연결, 계정, 권한과 action capability 관리 | credential·mode·권한 경계가 여러 설정에 흩어짐 | Setup/Integration, 사용자·session, capability·policy 관리 |
| 시스템 관리자 | 배포와 DB·Proxmox 연결 유지 | runtime, migration, source health와 recovery 기준이 분산됨 | migration, seed, secret binding, 연결·recovery 장애 대응 |

## 3. 목표

- Proxmox를 VM, node, task, config와 low-level execution actual state의 source of truth로 유지한다.
- node, VM, storage, network와 task observation에 `source`, `observed_at`, `freshness`와 availability를 명시한다.
- workload 상태, derived insight, operation history와 evidence를 연결해 현재 상태와 변화 원인을 설명한다.
- Gjallar는 actual state의 전량 mirror가 아니라 local metadata, observation provenance, derived finding, operation intent, verification, evidence와 audit를 소유한다.
- 지원 mutation을 Create VM, VM Start, graceful VM Shutdown과 allowlist 기반 Guided `qm unlock`으로 제한한다.
- 지원 action에 RBAC, fresh pre-check, 필요한 approval 또는 acknowledgement, idempotency, target lock, action별 external task 또는 operator attestation correlation과 direct after-state verification을 적용한다.
- DRS policy·approval·execution·reconciliation과 automatic migration을 승인된 순서로 제거한다.
- insight와 recommendation은 approval 또는 operation을 자동 생성·dispatch하지 않는다.
- stale, unknown, unavailable과 ambiguous state를 정상·성공 또는 low risk로 축소하지 않는다.
- 다른 Proxmox 환경으로의 배포를 방해하는 provider-specific locator와 node/profile 하드코딩을 adapter·configuration 경계로 이동한다.
- 기존 `/api/v1`, active frontend route와 DB migration history를 명시적인 deprecation과 forward migration 전까지 보호한다.

정량 제품 지표는 첫 observe-first 구현 slice에서 확정한다. 초기 후보는 observation freshness 명시율, 근거가 있는 finding 비율, finding과 operation/evidence 상관 연결률, 지원 action의 after-state verification 완료율과 ambiguous operation의 reconciliation 해결 시간이다.

## 4. 비목표

- Proxmox hypervisor, PVE/PDM 전체 기능 또는 actual-state authority의 대체
- Proxmox actual state의 전량 영구 mirror
- generic metric collector, 범용 TSDB, dashboard·alert delivery 전체를 소유하는 독립 monitoring platform
- DRS, scheduled balancing, automatic 또는 standalone VM migration
- insight가 mutation을 시작하는 automatic remediation
- raw interactive shell, backend SSH executor, 임의 `qm` command 또는 embedded terminal
- API 실패 후 확인 없이 manual action으로 fallback하거나 같은 mutation을 자동 재시도하는 것
- 지원 목록 밖의 broad VM lifecycle parity와 destructive action
- Proxmox 외 provider를 즉시 지원하는 multi-provider control plane
- CI/CD, application deployment, Terraform/GitOps orchestrator
- 초기 단계의 multi-cluster federation, microservice, message broker와 external queue
- PBS/backup 제품화, SSO/OAuth/2FA와 compliance-grade WORM audit의 무승인 도입

## 5. 범위

### 목표 제품 범위

- local authentication, server-side session과 `viewer < operator < admin` RBAC
- explicit `unconfigured`/`live`/`degraded` connection truth와 test fixture 격리
- source·observed time·freshness·availability를 가진 Proxmox node, VM, template, storage, network와 task observation
- Workload Cockpit과 상태·변화·operation evidence의 연결
- risk, readiness, capacity와 placement/topology health finding
- Create VM, VM Start, graceful VM Shutdown과 allowlist 기반 Guided `qm unlock`
- 지원 action의 intent, action별 gate, idempotency, lock, external task 또는 operator attestation correlation, post-check와 reconciliation
- evidence/audit timeline, artifact provenance와 secret redaction
- DRS 전용 UI·API·runtime·schema contract 제거와 shared operation/evidence 보존

### 과도기 호환 범위

- `/jobs`, `/risks`, shared job/artifact와 Create VM compatibility record는 승인된 consumer 전환 전까지 유지한다.
- historical `drs_migration` job/artifact renderer와 `/insights`의 `drs_advisor`·`drs-rec-*` 값은 기존 evidence/response compatibility로 유지하지만 DRS runtime이나 신규 producer를 의미하지 않는다.
- compatibility 보존은 신규 기능, generic owner로의 자동 승격 또는 장기 제품 범위를 의미하지 않는다.

### 제외

- DRS policy·approval·execution·reconciliation과 migration의 목표 제품 기능
- placement recommendation에서 자동 migration 또는 operation 생성으로 이어지는 경로
- generic TSDB·범용 alerting platform과 automatic remediation
- arbitrary `qm`, backend SSH executor와 silent fallback
- multi-provider와 broad multi-cluster orchestration
- 승인 전 DB 재설계, data retention, telemetry collector, scheduler와 신규 운영 dependency

## 6. 기능 요구사항

| ID | 요구사항 | 우선순위 | 인수 조건 |
|---|---|---|---|
| FR-001 | 시스템은 connection mode와 actual-state freshness를 명시해야 한다. | 필수 | product runtime에서 fake data를 표시하지 않고 `unconfigured`/`live`/`degraded`, `source`, `observed_at`, `freshness`와 availability를 제공한다. |
| FR-002 | 시스템은 workload 상태와 운영 맥락을 함께 제공해야 한다. | 필수 | VM actual state, source-scoped identity, current location, freshness, derived finding, 최근 operation과 evidence를 연결해 조회한다. |
| FR-003 | 모든 지원 mutation은 operation intent로 추적해야 한다. | 필수 | actor, target identity, idempotency identity, plan digest, mode, 상태 전이와 attempt가 operation에 연결된다. |
| FR-004 | managed API action은 action별 사전 조건과 실행 결과를 검증해야 한다. | 필수 | RBAC, fresh pre-check, 필요한 policy/approval 또는 acknowledgement, lock, task poll과 direct after-state를 거쳐야 `succeeded`가 된다. |
| FR-005 | guided manual action은 구조화되고 검증 가능한 절차여야 한다. | 필수 | allowlisted template과 typed parameter만 사용하고 target, expiry, plan digest, expected result와 verification procedure를 포함하며 arbitrary input이나 secret을 command에 넣지 않는다. |
| FR-006 | managed와 manual mode 사이에 silent fallback이 없어야 한다. | 필수 | dispatch 결과가 불확실하면 다른 mode로 재실행하지 않고 `needs_reconciliation`으로 전환한다. |
| FR-007 | Create VM은 표준화된 verified action이어야 한다. | 필수 | draft/preflight/plan/exact approval/create/post-check가 하나의 operation 및 생성된 workload identity와 연결된다. |
| FR-008 | operation 결과는 append-only evidence와 감사 추적을 제공해야 한다. | 필수 | actor/action/before/after/task/provenance/checksum을 조회할 수 있고 secret은 저장·노출되지 않는다. |
| FR-009 | partial failure와 ambiguous state를 보수적으로 보존해야 한다. | 필수 | timeout, missing UPID, crash-after-dispatch, task/post-check mismatch와 evidence 저장 실패를 성공으로 표시하지 않는다. |
| FR-010 | Insights는 observe-first 운영 맥락을 제공하고 실행 권한과 분리돼야 한다. | 필수 | risk, readiness, capacity와 placement/topology finding은 source·근거·rule/model version·observed time·freshness를 제공하고 operation을 자동 생성하거나 dispatch하지 않는다. DRS persistence와 migration client에 의존하지 않는다. |
| FR-011 | 인증·권한은 trusted server-side actor를 사용해야 한다. | 필수 | browser payload의 actor를 신뢰하지 않고 read/operator/admin 경계를 backend에서 검증한다. |
| FR-012 | 기존 소비자는 명시적인 전환 전까지 동작해야 한다. | 필수 | 현재 active `/api/v1` endpoint, canonical frontend route와 shared DB history는 승인된 deprecation·migration 전 compatibility 계약으로 유지한다. 제거가 승인된 DRS route/client는 active contract에 포함하지 않는다. |
| FR-013 | 지원 mutation 범위와 DRS 폐기 경계를 명시해야 한다. | 필수 | product action은 Create VM, VM Start, graceful VM Shutdown과 allowlist 기반 Guided `qm unlock`으로 제한하며 DRS, migration, automatic remediation과 arbitrary command를 제공하지 않는다. active DRS UI/API/runtime/schema producer가 없고 shared lock·job·artifact는 보존된다. |

## 7. 품질 요구사항

| 영역 | 요구사항 | 검증 방법 |
|---|---|---|
| 관찰 정확성 | source failure, stale·unknown·unavailable과 partial observation을 정상 값으로 축소하지 않는다. | connection, inventory, Insights availability·freshness contract tests |
| 보안·권한 | role, origin, acknowledgement, allowlist와 secret redaction을 신뢰 경계에서 검증한다. | auth/admin/API, command-template와 redaction tests |
| action 정합성 | plan/approval/identity binding, target-scoped concurrency, attempt와 evidence 상관관계를 보존한다. | DB constraint, concurrency, replay와 crash-window tests |
| 가용성·복구 | 외부 mutation과 DB가 원자적이지 않음을 상태기계로 드러내고 restart 후 read-only observation recovery 또는 operator reconciliation을 제공한다. | failure injection, restart/reconciliation tests |
| 사용성 | 사용자는 먼저 상태·freshness·근거를 이해하고, action이 제공될 때 mode, 위험, approval과 다음 복구 행동을 구분할 수 있어야 한다. | flow test, UI review와 operator usability check |
| 이식성 | core read rule이 raw Proxmox endpoint·UPID 문자열을 직접 해석하지 않고 provider-specific transport는 adapter에 둔다. | architecture contract와 adapter tests |
| 유지보수성 | public application contract를 통해 domain별 vertical slice를 독립 변경·검증한다. | dependency review, unit/contract/full suite |

성능 SLA, observation cadence, retention, alert integration과 접근성 정량 기준은 후속 구현 slice에서 별도 확정한다.

## 8. 핵심 업무 규칙

- 기본 사용자 흐름은 `observe → explain → 필요 시 verified action`이다.
- Proxmox는 VM/node/config/power/location/storage/network/task actual state를 소유한다.
- Gjallar는 local metadata, observation provenance/freshness, derived finding, 지원 action intent, approval, verification, evidence와 audit를 소유한다.
- current node와 power state는 관찰·검증 입력이지 Gjallar가 장기 소유하는 배치 권위가 아니다.
- recommendation과 insight는 approval이나 operation을 자동 생성·dispatch하지 않는다.
- 지원 action 목록 밖 mutation을 generic executor로 제공하지 않는다.
- 제거된 DRS compatibility state를 신규 generic Operations/Policy owner로 이전하지 않는다.
- historical DRS job/artifact evidence와 `/insights` legacy 문자열 보존을 active DRS API/runtime 복원이나 장기 제품 결정으로 해석하지 않는다.
- mutation 전에 intent와 idempotency identity를 저장하고 fresh target identity와 provider capability를 확인한다.
- exact plan/evidence digest와 승인 대상이 달라지면 재승인한다.
- external dispatch 불확실성은 retry가 아니라 `needs_reconciliation`이다.
- manual attestation과 pasted output은 보조 evidence일 뿐 성공의 기술적 권위가 아니다.
- action contract가 요구하는 terminal task 또는 authenticated operator attestation을 상관 연결하고, required direct after-state와 evidence가 모두 확인·저장된 뒤에만 `succeeded`가 된다. attestation 자체는 성공 권위가 아니다.
- raw password, session token, API token, SSH private material과 secret-looking payload는 command, API, artifact와 log에 남기지 않는다.
- 적용된 Alembic migration 이력은 덮어쓰거나 삭제하지 않는다.

## 9. 외부 제약과 의존성

- 외부 시스템: Proxmox VE API, PostgreSQL, operator가 직접 접근하는 Proxmox UI/CLI.
- 초기 production provider는 Proxmox 하나다. provider-neutral internal contract는 즉시 multi-provider parity를 의미하지 않는다.
- 기존 호환성: `/api/v1`, success envelope, active error semantics, canonical frontend route와 DB migration history.
- 운영 제약: live Proxmox mutation과 smoke는 정확한 target과 side effect에 대한 사용자 승인이 필요하다.
- 인증 제약: 현재 API token과 Proxmox interactive console의 인증 능력은 같지 않으므로 raw embedded console은 범위에서 제외한다.
- telemetry 제약: generic metric collector·TSDB·alert delivery는 현재 dependency가 아니며 도입에는 별도 요구사항과 고위험 Plan이 필요하다.

## 10. 실패와 경계 조건

- connection 설정 누락: `unconfigured`; fake inventory 없음.
- configured source 관찰 실패: `degraded` 또는 source별 `unavailable`; stale 값을 live로 표시하지 않음.
- 일부 observation 누락: finding을 정상·ready로 축소하지 않고 `unknown` 또는 incomplete evidence로 표시.
- 잘못된 action 입력·권한·pre-check 실패: `blocked`, `side_effects=[]`.
- approval reject·expire·plan drift: `rejected` 또는 `expired`; 외부 호출 없음.
- Proxmox가 side effect 없이 명확히 거절: `failed`.
- POST timeout, missing UPID, dispatch 직후 crash, task 상태 불명: `needs_reconciliation`; target lock을 즉시 재사용하지 않음.
- task `OK`지만 after-state 불일치: `needs_reconciliation`.
- manual bundle 발급 후 확인 대기: `awaiting_operator`; attestation 후 API 검증 대기는 `awaiting_verification`.
- evidence 저장 실패: actual effect가 있어도 성공을 공표하지 않고 복구 가능한 상태와 lock을 보존.
- DB 조회 실패: 빈 데이터로 fail-open하지 않고 degraded/unavailable을 반환.

## 11. 미확정 사항

- neutral Placement의 target recommendation을 placement/topology health finding으로 축소할 범위
- shared Jobs/Artifacts의 historical DRS evidence retention과 archive 정책
- observation cadence, durable history와 retention 및 외부 telemetry 연동 경계
- finding acknowledge/silence/resolve와 외부 notification 연동의 필요 시점
- separate `approver` role과 separation of duties 도입 시점
- application-level checksum audit과 external WORM audit 중 목표 수준
- Create VM·Guided action의 durable recovery 범위
- operation·attempt·evidence compatibility table의 장기 migration·retention 전략
- 정량 SLA와 접근성 기준

## 12. 승인 기록

### 2026-08-24 제품 방향 재정렬

- 승인 문장: `Gjallar의 제품 중심을 Proxmox observe-first Operations Intelligence로 전환하고 Create VM·VM Start·graceful VM Shutdown·Guided qm unlock만 선택적 verified action으로 유지하며 DRS policy·approval·execution·reconciliation과 automatic migration을 안전하게 폐기한다.`
- 이 승인이 의미하지 않는 것: `Proxmox actual state 영구 mirror, generic metric TSDB·독립 alerting platform, automatic remediation, arbitrary shell, 즉시 multi-provider 지원 또는 consumer·retention 확인 전 DRS API·UI·data 삭제`
- 승인자: `사용자`
- 승인일: `2026-08-24`

### 2026-08-24 DRS repository 제거

- 승인 내용: 운영 중인 배포·저장소 밖 consumer·보존할 production DRS state가 없다는 사용자 전제에 따라 DRS 전용 frontend·API·runtime·config·schema contract를 제거하고 shared lock/job/artifact와 `/insights` 공개 compatibility 값은 보존한다.
- 제외: production DB migration 적용·data 삭제, 외부 credential revoke와 live Proxmox mutation.
- 승인자: `사용자`
- 승인일: `2026-08-24`

### 역사적 기준선

- 2026-07-20: Proxmox actual-state authority, verified operation mode, modular monolith, connection truth와 점진 전환 승인.
- 2026-07-21: PostgreSQL durable target lock, VM Start/Shutdown GET-only recovery와 graceful shutdown 승인.
- 2026-07-23: DRS maintenance 단계적 폐기와 neutral Placement/Capacity의 Insights 통합 승인.
- 위 결정의 유효한 안전 원칙은 [`ADR-007`](../decisions/adr-007-observe-first-operations-intelligence.md)이 계승하며 기존 ADR과 Plan은 역사로 보존한다.
