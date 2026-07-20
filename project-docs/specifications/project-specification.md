# 프로젝트 명세: Gjallar Verified Operations Control Plane

- 상태: `APPROVED`
- 최종 검토일: `2026-07-20`
- 최종 승인자: `사용자`

## 1. 해결할 문제

- Proxmox GUI만으로 일상 운영을 수행하면 반복 작업, 사전 점검, 승인, 변경 후 검증, 감사 증거가 서로 분리된다.
- GUI에서 지원하지 않거나 불편한 작업은 운영자가 `qm` 등 CLI로 전환해야 하지만, 명령 생성부터 결과 검증까지의 안전한 공통 흐름이 없다.
- 현재 Gjallar는 inventory, Create VM, VM Start, DRS, jobs를 제공하지만 기능별 workflow와 evidence로 분절돼 있어 하나의 control plane으로 느껴지지 않는다.
- DRS 자체는 Proxmox의 native 기능과 경쟁 우위가 약하다. Gjallar의 차별점은 자동 배치가 아니라 API와 guided manual operation을 동일한 검증·승인·증거 모델로 운영하는 데 둔다.

성공하면 최초 연결·비상 복구를 제외한 day-2 운영은 Gjallar에서 시작하고, 실행 상태와 실제 결과 확인까지 Gjallar에서 끝난다.

## 2. 사용자와 이해관계자

| 대상 | 목표 | 현재 어려움 | 주요 사용 흐름 |
|---|---|---|---|
| `viewer` | workload와 운영 상태, 위험, evidence 확인 | Proxmox actual state와 운영 맥락이 분리됨 | Workload Cockpit, Operations, Insights 조회 |
| `operator` | 반복 작업을 안전하고 빠르게 실행 | API·GUI·`qm` 절차와 검증이 분리됨 | plan → approval → managed API 또는 guided manual → verification |
| `admin` | 계정, 연결, 정책과 break-glass 권한 관리 | credential·mode·권한 경계가 여러 설정에 흩어짐 | Setup/Integration, 사용자·session 관리, policy 관리 |
| 시스템 관리자 | 배포와 DB·Proxmox 연결 유지 | runtime과 migration, live readiness 기준이 분산됨 | migration, seed, secret binding, 장애 복구 |

## 3. 목표

- Proxmox를 actual state와 low-level task execution의 source of truth로 유지한다.
- Gjallar가 workload metadata, operation intent, policy, approval, verification, evidence, audit와 derived insight를 소유한다.
- Create VM과 주요 day-2 작업을 workload 중심 UI에서 관리한다.
- Proxmox API 경로와 allowlist 기반 guided `qm` 절차를 동일한 operation lifecycle로 표현한다.
- task 접수나 `UPID`만으로 성공 처리하지 않고 direct after-state와 필요한 evidence를 확인한다.
- stale, unknown, unavailable, ambiguous state를 성공 또는 실행 가능으로 축소하지 않는다.
- 기존 `/api/v1`과 active frontend 경로를 점진 전환 동안 호환 facade로 유지한다.

정량 제품 지표는 첫 product slice에서 확정한다. 초기 후보는 day-2 작업의 Gjallar 시작 비율, operation verification 완료율, manual handoff 후 재검증율, reconciliation 평균 해결 시간이다.

## 4. 비목표

- Proxmox hypervisor, PVE/PDM 전체 기능, actual-state authority의 대체
- autonomous DRS, scheduled balancing, 자동 remediation
- generic shell·SSH executor 또는 임의 command terminal
- API 실패 후 확인 없이 `qm`으로 자동 fallback하거나 동일 mutation을 자동 재시도하는 것
- 모든 destructive lifecycle action을 한 번에 지원하는 것
- CI/CD, application deployment, Terraform/GitOps orchestrator
- 초기 단계의 multi-cluster federation, microservice, message broker, external queue
- PBS/backup 제품화, SSO/OAuth/2FA, compliance-grade WORM audit의 무승인 도입

## 5. 범위

### 포함

- local authentication, server-side session, `viewer < operator < admin` RBAC
- explicit `unconfigured`/`live`/`degraded` connection truth와 Proxmox capability discovery; product runtime의 demo/mock inventory 제외
- node, VM, template, storage, network inventory와 workload identity/freshness
- Workload Cockpit, standardized Create VM, verified VM lifecycle operation
- operation intent, plan, approval, idempotency, lock, task correlation, post-check, reconciliation
- `managed_api`, `guided_manual`, `observe_only` 실행 모드
- allowlist 기반 `qm` instruction bundle과 외부 실행 후 API 재검증
- evidence/audit timeline, artifact redaction, operations and risk/health insights
- placement/capacity recommendation as insight; 기존 DRS execution은 별도 승인 전 유지보수 범위

### 제외

- raw interactive Proxmox shell embedding과 arbitrary `qm` execution
- backend가 운영자 대신 SSH 접속해 command를 실행하는 기능
- 무승인 destructive action, broad VM lifecycle parity, automatic migration
- Proxmox actual state의 전량 영구 mirror
- 승인 전 DB 재설계, queue/worker, 신규 운영 dependency

## 6. 기능 요구사항

| ID | 요구사항 | 우선순위 | 인수 조건 |
|---|---|---|---|
| FR-001 | 시스템은 연결 mode와 actual-state freshness를 명시해야 한다. | 필수 | product runtime에서 fake data를 표시하지 않고 `unconfigured`/`live`/`degraded`, `source`, `observed_at`, `freshness`를 제공한다. |
| FR-002 | 시스템은 workload 중심 조회와 운영 맥락을 제공해야 한다. | 필수 | VM actual state, stable identity, owner/environment/profile, 최근 operation과 evidence를 한 컨텍스트에서 조회한다. |
| FR-003 | 모든 mutation은 operation intent로 추적해야 한다. | 필수 | actor, target identity, idempotency identity, plan digest, mode, 상태 전이와 attempt가 operation에 연결된다. |
| FR-004 | managed API operation은 사전 조건과 실행 결과를 검증해야 한다. | 필수 | RBAC, fresh pre-check, policy/approval, lock, task poll, direct after-state를 거쳐야 `succeeded`가 된다. |
| FR-005 | guided manual은 구조화되고 검증 가능한 절차여야 한다. | 필수 | allowlisted template만 사용하고 target, expiry, plan digest, expected result, verification procedure를 포함하며 arbitrary input이나 secret을 command에 넣지 않는다. |
| FR-006 | API와 manual mode 사이에 silent fallback이 없어야 한다. | 필수 | dispatch 결과가 불확실하면 다른 mode로 재실행하지 않고 `needs_reconciliation`으로 전환한다. |
| FR-007 | Create VM은 표준화된 workload 생성 operation이어야 한다. | 필수 | draft/preflight/plan/exact approval/create/post-check가 하나의 operation 및 생성된 workload identity로 연결된다. |
| FR-008 | operation 결과는 append-only evidence와 감사 추적을 제공해야 한다. | 필수 | actor/action/before/after/task/provenance/checksum을 조회할 수 있고 secret은 저장·노출되지 않는다. |
| FR-009 | partial failure와 ambiguous state를 보수적으로 보존해야 한다. | 필수 | timeout, missing UPID, crash-after-dispatch, task/post-check mismatch, evidence 저장 실패를 성공으로 표시하지 않는다. |
| FR-010 | insights는 실행 권한과 분리해야 한다. | 필수 | risk, readiness, capacity, placement recommendation은 근거·version·freshness를 제공하지만 자체적으로 mutation을 시작하지 않는다. |
| FR-011 | 인증·권한은 trusted server-side actor를 사용해야 한다. | 필수 | browser payload의 actor를 신뢰하지 않고 read/operator/admin 경계를 backend에서 검증한다. |
| FR-012 | 기존 소비자는 점진 전환 동안 동작해야 한다. | 필수 | active `/api/v1` endpoint와 canonical frontend route는 deprecation 결정 전 compatibility facade로 유지한다. |

## 7. 품질 요구사항

| 영역 | 요구사항 | 검증 방법 |
|---|---|---|
| 보안·권한 | role, origin, acknowledgement, secret redaction을 신뢰 경계에서 검증한다. | auth/admin/API contract, command-template, redaction tests |
| 데이터 정합성 | plan/approval/identity binding, target-scoped concurrency, operation attempt와 evidence 상관관계를 보존한다. | DB constraint, concurrency, replay, crash-window tests |
| 가용성·복구 | 외부 mutation과 DB가 원자적이지 않음을 상태기계로 드러내고 restart 후 resume/reconcile할 수 있어야 한다. | failure injection, restart/reconciliation tests |
| 사용성 | 사용자는 실행 mode, 위험, approval, 현재 상태와 다음 복구 행동을 한 operation 화면에서 이해할 수 있어야 한다. | flow test, UI review, operator usability check |
| 관찰성 | operation과 Proxmox task를 correlation하고 stale/unknown을 명시한다. | operation timeline, log/artifact contract tests |
| 유지보수성 | public application API를 통해 domain별 vertical slice를 독립 변경·검증한다. | dependency review, unit/contract/full suite |

성능 SLA, retention 기간, 접근성 정량 기준은 첫 product slice에서 별도 확정한다.

## 8. 핵심 업무 규칙

- Proxmox는 VM/node/config/power/location/storage/network/HA/task actual state를 소유한다.
- Gjallar는 workload metadata, operation intent, policy, approval, verification, evidence, audit, derived insight를 소유한다.
- recommendation과 insight는 operation dispatch 권한을 갖지 않는다.
- mutation 전에 intent와 idempotency identity를 저장하고 fresh target identity를 확인한다.
- exact plan/evidence digest와 승인 대상이 달라지면 재승인한다.
- 외부 dispatch 불확실성은 retry가 아니라 `needs_reconciliation`이다.
- manual attestation과 pasted output은 보조 evidence일 뿐 성공의 기술적 권위가 아니다.
- API로 after-state를 확인할 수 없는 manual operation은 `awaiting_verification` 또는 `needs_reconciliation`이다.
- task `OK`와 required post-check가 모두 충족된 뒤 evidence를 저장해야 `succeeded`가 된다.
- raw password, session token, API token, SSH private material과 secret-looking payload는 command, API, artifact, log에 남기지 않는다.
- 적용된 Alembic migration 이력은 덮어쓰거나 삭제하지 않는다.

## 9. 외부 제약과 의존성

- 외부 시스템: Proxmox VE API, PostgreSQL, operator가 직접 접근하는 Proxmox UI/CLI.
- 기존 호환성: `/api/v1`, success envelope, active error semantics, canonical frontend route, DB migration history.
- 운영 제약: live Proxmox mutation과 smoke는 정확한 target과 side effect에 대한 사용자 승인이 필요하다.
- 인증 제약: 현재 live API token과 Proxmox interactive console의 인증 능력은 동일하지 않으므로 raw embedded console은 초기 범위에서 제외한다.

## 10. 실패와 경계 조건

- 잘못된 입력·권한·policy·pre-check 실패: `blocked`, `side_effects=[]`.
- 승인 거절·만료·plan drift: `rejected` 또는 `expired`; 외부 호출 없음.
- Proxmox가 side effect 없이 명확히 거절: `failed`.
- POST timeout, missing UPID, dispatch 직후 crash, task 상태 불명: `needs_reconciliation`; target lock을 즉시 재사용하지 않는다.
- task `OK`지만 after-state 불일치: `needs_reconciliation`.
- manual bundle 발급 후 확인 대기: `awaiting_operator`; attestation 후 API 검증 대기는 `awaiting_verification`.
- evidence 저장 실패: actual effect가 있어도 성공을 공표하지 않고 복구 가능한 상태로 유지한다.
- DB 조회 실패: 빈 데이터로 fail-open하지 않고 degraded/unavailable을 반환한다.

## 11. 미확정 사항

- 별도 `approver` role과 separation of duties 도입 시점
- application-level append-only/checksum audit과 external WORM audit 중 목표 수준
- PostgreSQL-backed durable runner/lease 도입 단계
- operation·attempt·evidence의 구체 schema와 기존 table migration 전략
- guided manual 1차 allowlist action과 허용할 `qm` parameter 범위
- 기존 DRS execution/history의 유지보수 기간과 최종 제거 여부
- multi-cluster connection profile과 stale snapshot 보존·표시 계약
- 정량 SLA, metric interval, evidence retention 기간

## 12. 승인 기록

- 승인 범위: `제품 경계, 실행 mode, domain ownership, 점진 전환 Plan과 기존 docs 초기화; product runtime demo 제거와 unconfigured/live/degraded connection truth`
- 감수한 제한: `목표 구조는 점진 구현하며 기존 API와 DB migration 이력은 별도 폐기 승인 전 보존`
- 승인일: `2026-07-20`
