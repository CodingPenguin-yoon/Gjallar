# 현재 아키텍처 기준선

- 상태: `APPROVED`
- 최종 검토일: `2026-07-21`
- 관련 ADR: 승인된 목표 [`ADR-001`](../decisions/adr-001-proxmox-gjallar-authority-boundary.md), [`ADR-002`](../decisions/adr-002-modular-monolith-domain-boundaries.md), [`ADR-003`](../decisions/adr-003-production-inventory-connection-truth.md), [`ADR-004`](../decisions/adr-004-postgresql-durable-operation-recovery.md)

이 문서는 2026-07-21 코드에 구현된 현재 구조를 설명한다. ADR과 전환 Plan의 목표 구조는 승인·구현 전까지 현재 구조가 아니다.

## 1. 시스템 목적과 경계

- 현재 해결 범위: 인증된 운영자에게 Workload Cockpit, 공통 Operations 목록·evidence timeline, Create VM, VM Start, graceful VM Shutdown, 첫 Guided `qm unlock`, observe-only Insights, DRS maintenance/policy/제한된 migration, jobs/legacy risks를 제공한다.
- 현재 시스템 책임: local user/session, Gjallar-owned operational records, `/api/v1`, React operator UI, Proxmox API 연동.
- 외부 책임: VM/node/task/config actual state와 실제 hypervisor mutation은 Proxmox가 소유한다.
- 현재 비범위: generic shell/SSH execution, broad lifecycle parity, VM Start/Shutdown 외 action의 자동 recovery, multi-cluster control.

## 2. 시스템 컨텍스트

```mermaid
flowchart LR
    Operator["viewer / operator / admin"] --> UI["React SPA"]
    UI --> API["FastAPI /api/v1"]
    API --> PG["PostgreSQL"]
    API --> PVE["Proxmox VE API"]
    API --> Files["Local runtime lock files"]
    API -. opt-in lifespan .-> Runner["Recovery observer"]
    Runner --> PG
    Runner --> PVE
    PVE --> API
```

- production image는 built React SPA를 FastAPI가 같은 origin에서 제공한다.
- startup은 Alembic upgrade, Create VM profile seed, optional bootstrap admin 후 Uvicorn을 시작한다.
- product runtime의 inventory는 authoritative Proxmox API만 사용한다. 필수 설정 누락은 `unconfigured`, snapshot 성공은 `live`, configured connection 실패는 `degraded`로 노출하며 fake fixture로 fallback하지 않는다.

## 3. 현재 아키텍처

- 구조: 단일 FastAPI application과 React SPA를 유지하며 feature-oriented layered monolith에서 domain-oriented modular monolith로 점진 전환 중이다.
- 선택 배경: 기능별 package와 단일 배포를 유지하며 빠르게 운영 기능을 확장해 왔다.
- 현재 장점: deployment가 단순하고 feature code와 contract test가 이미 존재하며 test-only fake adapter injection으로 주요 흐름을 검증할 수 있다.
- 현재 단점: VM Start·Shutdown·Create VM·Guided `qm`은 Operations 경계와 공통 lifecycle을 사용하지만 큰 router·screen과 Create VM compatibility workflow·DRS workflow는 여전히 DB, jobs, Proxmox 구현을 직접 조정한다. dual record transaction 의미와 전환되지 않은 기능의 책임도 아직 분산돼 있다.
- 재검토 이유: 제품을 Verified Operations Control Plane으로 전환하려면 operation, policy, evidence의 공통 경계가 필요하다.

## 4. 구성 요소와 책임

| 구성 요소·모듈 | 현재 책임 | 공개 계약 | 현재 소유 데이터 | 주요 의존 대상 |
|---|---|---|---|---|
| `app/main.py`, auth routers | app lifecycle, middleware, login/admin API, SPA fallback | `/health`, `/api/v1/auth/*`, `/api/v1/admin/*` | user/session/account audit | DB, FastAPI |
| `api/v1/router.py` | inventory, jobs, DRS, VM actions, Create VM HTTP orchestration | `/api/v1/*` | 없음 | 거의 모든 feature module |
| `setup_integration` | redacted Proxmox connection truth와 failure 분류 | `ProxmoxConnectionStatus` | persistent state 없음 | Proxmox adapter |
| `workloads` | authoritative inventory availability application boundary | `WorkloadInventoryQuery` | actual state는 Proxmox 소유 | Setup/Integration, Proxmox adapter |
| `operations/core` | 공통 Operation 상태 전이, digest, projection/event repository 계약 | `OperationSpec`, `OperationSnapshot`, `OperationStore` | `operations`, `operation_events` | domain과 SQLAlchemy infrastructure adapter |
| `operations/locks`, `operations/recovery` | cluster/VMID durable locator coordination, due item, lease/generation fencing, allowlisted observation recovery | durable target lock repository, `RecoveryStorePort`, `OperationRecoveryRunner` | `operation_locks`, `operation_recovery_items` | PostgreSQL, Operations core, Proxmox read/task observation |
| `operations/vm_start` | VM Start command·stable intent, application use case, 검증 workflow와 외부 port 계약 | `VmStartCommand`, `VmStartUseCase`, `VmStartExecutionPorts` | 공통 operation/event와 기존 job/artifact dual record | 추상 Workloads/Mutation/Jobs/Evidence/Lock port |
| `operations/vm_shutdown` | graceful VM Shutdown command·stable intent, running pre-check, 검증 workflow와 외부 port 계약 | `VmShutdownCommand`, `VmShutdownUseCase`, `VmShutdownExecutionPorts` | 공통 operation/event/recovery와 기존 job/artifact dual record | 추상 Workloads/Mutation/Jobs/Evidence/Lock/Recovery port |
| `operations/vm_create` | Create VM stable intent, plan·approval·preview·dispatch·result·replay tracking과 common lifecycle mapping | `VmCreateOperationTracker`, facade functions | 공통 operation/event와 기존 request/job/artifact dual record | Operations core store; HTTP facade가 compatibility workflow와 조립 |
| `operations/guided_qm` | 고정 `qm unlock` 계획, operator handoff, attestation, API verification | `GuidedQmUnlockUseCase`, typed command DTO | 공통 operation/event | Proxmox observation port, shared target lock |
| `proxmox` | read inventory와 mutation client | Python dataclass/client methods | actual state는 Proxmox 소유 | Proxmox VE API |
| `vm_create` | draft/preflight/plan/approval/native create compatibility 정책·runner | workflow functions, `/vm-create/*` | profile, request, instance linkage, job/artifact | Operations Create VM tracking, DB, jobs, Proxmox |
| `vm_actions` | VM Start/Shutdown compatibility facade·infrastructure adapter와 post-create readiness | `run_vm_start`, `run_vm_shutdown`, action endpoint | 전용 table 없음; job/artifact compatibility 유지 | Operations VM lifecycle, inventory, jobs, Proxmox |
| `drs` | identity, policy, recommendation, approval, migration, reconciliation | workflow functions, `/drs/*` | DRS identity/policy/approval/job/lock/reconciliation | DB, inventory, jobs, DRS client |
| `jobs` | job projection과 artifact metadata/content | helper functions, `/jobs`, `/risks` | `job_runs`, `job_artifacts` | DB |
| `insights` | risk/readiness/capacity/placement의 availability-aware derived read model | `InsightsQueryService`, `/insights` | persistent data 없음 | Workloads observation, strict job read, DRS advisor adapter |
| `frontend/src/app` | auth/session, connection-aware route gate, shell, navigation composition | canonical route와 legacy alias | browser-local transient state | pages, shared |
| `frontend/src/pages`, `features`, `entities`, `shared` | route composition, Workload inventory, Operations·Guided `qm` 흐름, observe-only Insights, Operation·Insight read model, API/auth/connection 공통 계약 | `/instances`, `/operations*`, `/insights*`, `/api/v1` consumer | browser-local transient state | backend API; 미전환 page adapter는 기존 components/utils |

## 5. 현재 의존성 규칙

### 실제로 보호되는 관계

- `/api/v1`은 기본적으로 authenticated `viewer`를 요구하고 mutation은 `operator`, account admin은 `admin`을 요구한다.
- inventory read adapter와 mutation client는 분리돼 있다.
- product environment mode는 live-only이고 test fixture는 direct injection으로만 연결된다.
- inventory-dependent route는 Workloads query boundary에서 non-live 상태를 `503`으로 차단한다.
- VM Start/Shutdown HTTP path는 compatibility facade를 통해 infrastructure-free command와 application use case로 진입한다. use case가 사용하는 Workloads, mutation, Jobs, Evidence, lock, recovery 의존성은 명시적 port로 전달된다.
- VM Start, VM Shutdown, Create VM tracking과 Guided `qm unlock`은 공통 Operation projection과 checksum-linked event repository를 사용한다. projection 전이와 event append는 한 DB transaction으로 저장한다.
- VM Start, VM Shutdown, Create VM, Guided `qm unlock`, DRS의 같은 `cluster_id`/VMID locator는 PostgreSQL partial unique lock을 공유한다. local file lock은 전환 중 compatibility guard로 DB lock 뒤에 획득한다.
- VM Start/Shutdown은 external dispatch 전 recovery item과 foreground lease를 저장하고 task polling 중 heartbeat한다. opt-in recovery runner는 만료된 lease를 `SKIP LOCKED`로 하나씩 claim하며 저장된 task와 direct VM state만 GET으로 재관찰한다.
- Create VM plan은 `operation_id=job_id`인 `vm_create` operation을 만들고 approval·preview·dispatch·running·verifying·success/reconciliation을 event로 기록한다. 기존 request/workload/job/artifact는 별도 transaction의 compatibility record로 유지한다.
- Guided `qm`은 fixed template과 typed parameter만 받으며 backend shell/SSH executor가 없다. operator attestation만으로 성공하지 않고 Proxmox API의 config lock·active task를 다시 확인한다.
- DRS migration은 일반 Proxmox mutation client와 다른 전용 client를 사용한다.
- browser가 제출한 actor가 아니라 server-side session actor를 사용한다.
- secret-like field를 API와 evidence에서 거부·redact하는 경로가 있다.
- Insights는 `api facade → application → domain/read ports` 방향으로 risk와 inventory source를 독립 수집한다. source 실패는 section별 `unavailable`로 격리하고 어떤 approval·operation·mutation port도 제공하지 않는다.
- frontend 전환 영역은 `app → pages/features → entities/shared` 방향을 source contract로 검사한다. app은 legacy component를 직접 import하지 않고, Workload inventory, Guided `qm`, Insights는 feature public boundary를 사용한다.

### 일관되게 보호되지 않는 관계

- Create VM HTTP compatibility facade·DRS와 일부 route/workflow는 아직 DB session, ORM model, job/artifact helper, Proxmox concrete implementation을 직접 알 수 있다.
- 미전환 backend domain과 legacy frontend screen에는 public contract와 private implementation 경계가 일관되게 적용되지 않았다.
- Create VM·DRS maintenance·Jobs·legacy Risks·Admin frontend 내부는 page adapter 아래 기존 component/utils 구조를 유지한다.
- DRS는 공통 operation state machine이나 event repository를 아직 사용하지 않는다. Create VM은 공통 lifecycle을 dual record하지만 기존 request/jobs/artifacts도 compatibility 모델로 남아 있다.

## 6. 현재 책임과 데이터

| 현재 책임 영역 | 핵심 책임 | 소유 상태·데이터 | 다른 영역과의 현재 계약 |
|---|---|---|---|
| Auth | 사용자, role, session, account audit | `users`, `sessions`, `account_audit_events` | FastAPI dependency, authenticated actor |
| Inventory | Proxmox state read/normalization | actual state는 Proxmox; adapter cache는 transient | nodes/VMs/templates/storage/networks model |
| VM Create | profile, request, create workflow | `create_vm_profiles`, `vm_create_requests`, `vm_instances` 및 job/artifact | `/vm-create/*`, Proxmox client |
| VM Actions | existing VM action/readiness | 전용 table 없이 `job_runs`, `job_artifacts` | action endpoint, inventory, Proxmox client |
| Operations | operation current projection, append-only event, durable target coordination와 recovery lease | `operations`, `operation_events`, `operation_locks`, `operation_recovery_items` | VM Start/Shutdown, Create VM, Guided `qm`, DRS locator lock, additive operation API |
| DRS | identity, policy, recommendation, execution/reconciliation | DRS 관련 8개 table과 job/artifact | `/drs/*`, inventory, DRS client |
| Jobs/Risks | 최신 job projection, artifact, derived risk | `job_runs`, `job_artifacts` | `/jobs`, `/risks`, producer helper |
| Insights | source별 derived finding과 availability | persistent state 없음; request-time projection | `/insights`, Workloads observation, Jobs risk, DRS recommendation |

물리적인 ORM model은 대부분 `backend/app/db/models.py`에 함께 있다. Operations core의 두 model은 `backend/app/operations/core/infrastructure/models.py`로 분리됐지만 Create VM·DRS 등 나머지 repository ownership은 아직 분리되지 않았다. 목표 logical ownership은 [`domains/domain-map.md`](../domains/domain-map.md)에 제안한다.

## 7. 트랜잭션과 정합성

- DB transaction: `session_scope()`를 호출하는 helper/service 단위이며 정상 commit, exception rollback이다.
- 공통 Operations repository는 projection 변경과 event append를 한 transaction으로 처리하고 sequence/version 충돌을 거부한다. recovery transition은 lease fencing, event/projection, recovery status와 target lock release를 같은 transaction으로 처리한다. 기존 job/artifact compatibility 기록은 별도 transaction이다.
- 강한 정합성: 단일 DB transaction 안의 unique/foreign-key/checksum/last-admin 같은 local invariant.
- 최종 정합성: Proxmox mutation, UPID/task, post-check와 Gjallar job/DRS state. 외부 API와 PostgreSQL은 원자적이지 않다.
- 멱등성·동시성: VM Start, VM Shutdown, Create VM, Guided `qm unlock`, DRS는 현재 한 configured cluster의 VMID locator에 대해 같은 PostgreSQL open-lock unique constraint를 공유한다. Start/Shutdown/Create/Guided는 transition 기간 local file guard도 함께 사용한다. recovery lease expiry는 observer takeover만 허용하며 target lock을 해제하지 않는다.
- 실패 처리: VM Start, VM Shutdown, Create VM과 Guided `qm`은 공통 `needs_reconciliation` taxonomy와 Operation event를 사용한다. Shutdown은 force fallback 없이 task/direct stopped 불일치를 retained lock으로 보존하고, Create VM은 외부 effect 뒤 compatibility/evidence 저장 실패에서도 success를 공표하지 않는다. DRS는 dispatch 전 `prepared` attempt와 prepared/no-UPID crash window를 자체 상태로 보존한다.

## 8. 외부 시스템

| 시스템 | 목적 | 호출 방향 | 현재 실패 격리 | 계약 위치 |
|---|---|---|---|---|
| Proxmox VE API | inventory, VM create/start/graceful shutdown/migrate, task/post-check | Gjallar → Proxmox | adapter/client 분리, timeout, workflow별 gate와 task evidence | `backend/app/proxmox/` |
| PostgreSQL | Gjallar-owned users와 operational state | Gjallar → PostgreSQL | `session_scope`, Alembic, test-only SQLite guard | `backend/app/db/`, `backend/alembic/` |
| Browser | operator UI와 session cookie | Browser ↔ Gjallar | HttpOnly cookie, origin validation, RBAC | `frontend/src/`, auth/API routers |
| Local filesystem | VM Start/Shutdown/Create VM/Guided `qm` compatibility target guard | backend local process | PostgreSQL durable lock 뒤 dual acquire; container 내 구버전 경로 방어 | `backend/app/operations/target_lock.py` |

Queue, scheduler, cache는 현재 active dependency가 아니다. recovery observer는 별도 서비스가 아니라 같은 FastAPI image의 opt-in lifespan task다.

## 9. 현재 주요 실행 흐름

- Create VM: draft → preflight → plan과 common operation 준비 → approve/preview event → replay/VMID guard → target lock → common dispatch 기록 → native create → running/verifying event → compatibility request/workload/job/artifact → common success → clear result에서만 lock 해제.
- VM Start: API facade → Operations command/use case → explicit execution ports → `operations/vm_start/workflow.py` 순으로 진입한다. acknowledgement/idempotency → operation intent/event → durable+file target lock → fresh pre-check → recovery item/foreground lease → start → lease heartbeat/task poll → running post-check → fenced operation event + 기존 job/artifact → clear result에서만 lock 해제 순서를 유지한다.
- VM Start restart recovery: foreground lease expiry → opt-in runner claim → stored UPID task GET → direct VM status GET → fenced transition/evidence. runner는 mutation POST를 받지 않으며 missing UPID·task/state mismatch는 `needs_reconciliation`/`paused`와 retained target lock으로 남긴다.
- VM Shutdown: 같은 의존 방향과 durable ordering을 사용하되 running non-template pre-check 뒤 QEMU `status/shutdown`만 호출한다. task `stopped/OK`와 direct VM `stopped`가 모두 확인되고 Jobs projection이 저장된 뒤 fenced completion과 lock release를 수행한다.
- VM Shutdown restart recovery: `vm_shutdown_observation` handler는 stored UPID task와 direct VM status GET만 사용한다. shutdown POST, hard stop, reboot capability가 없으며 missing UPID·task/state mismatch는 paused reconciliation과 retained lock이다.
- Guided `qm unlock`: Workload Cockpit 또는 Operations UI → typed input/ack → shared target lock → `Sys.Audit` 권한·active task·config lock pre-check → 5분 instruction bundle과 operation/event 저장 → 외부 node shell 실행 → trusted attestation → Proxmox API verification → lock 해제 또는 reconciliation 순서다. backend는 명령을 실행하지 않으며 UI는 만료·reconciliation instruction의 신규 실행을 경고한다.
- DRS: recommendation/check → identity/policy → approval packet/job → final pre-check/DB operation lock → durable prepared attempt → migrate → accepted UPID → task/post-check → completion 또는 reconciliation.
- Insights: authenticated read → strict Jobs risk와 Proxmox connection observation 독립 수집 → live이면 readiness/capacity와 DRS placement 계산 → source별 provenance·version·freshness·bounded finding 조합. non-live에서는 stored risk만 유지하고 inventory section은 `unavailable`이며 실행 경로는 없다.
- 목표 공통 lifecycle 중 projection/event core, VM Start·graceful VM Shutdown·Create VM·Guided `qm unlock`, Workload Cockpit·Operations list/detail/timeline UI가 구현됐다. DRS의 공통 Operation 통합은 남아 있다.

## 10. 런타임과 배포 제약

- 실행 단위: React build와 FastAPI를 포함한 single Docker image.
- 환경 경계: local dev는 Vite `5173`과 FastAPI `8000`; production은 same-origin SPA/API.
- 성능·확장: 정량 SLA와 horizontal scale contract가 없다. PostgreSQL lock/lease는 multi-replica claim을 조정하지만 recovery는 API process와 resource를 공유하고 concurrency 1로 제한된다.
- 시크릿·네트워크: PostgreSQL과 Proxmox credential은 environment/orchestrator secret으로 주입한다.

## 11. 테스트 경계

- 단위: DRS 판단, identity, preflight, view model, normalization 등 순수·준순수 로직.
- 통합·계약: FastAPI `/api/v1`, auth/RBAC, SQLAlchemy/Alembic, jobs/artifacts, static SPA, frontend client/route.
- 외부 대역: test에서 직접 주입한 fake inventory/mutation client와 test-only SQLite를 기본 사용한다. product runtime environment에는 fake inventory mode가 없다.
- canonical Python 3.13 container backend 전체 `504 passed, 2 skipped`, canonical Node 24/pnpm 10 frontend test 17개·ESLint·Vite production build와 production image build를 확인했다. opt-in PostgreSQL integration은 실제 PostgreSQL 18.4에서 별도 `2 passed`였다. live Proxmox 실행과 browser 수동 확인은 수행하지 않았다.

## 12. 알려진 위험과 기술 부채

- `api/v1/router.py`, DRS/Create VM workflow와 미전환 큰 screen/view-model에 책임이 집중돼 있다. root `App.jsx` 집중은 해소됐지만 page adapter 아래 legacy component는 남아 있다.
- VM Start/Shutdown과 Create VM lifecycle은 Operations로 이동했지만 기존 `job_runs`/`job_artifacts`, Create VM request/workload linkage와 compatibility facade가 남아 있다. 어느 시점에 compatibility projection을 종료할지는 미결정이다.
- 기존 `/jobs`·`/risks`가 사용하는 `list_job_runs()`의 DB exception → empty list fallback은 호환성 때문에 남아 있다. `/insights`는 `list_job_runs_strict()`로 risk source 장애를 `unavailable`로 표시한다.
- `job_runs`는 최신 projection, `job_artifacts`는 upsert 성격이라 immutable operation audit가 아니다.
- durable restart recovery는 VM Start/Shutdown observation에 구현됐다. Create VM, Guided `qm`, DRS에는 공통 자동 handler가 없고 generic operator recovery/unlock API도 없다.
- local file guard는 container 교체 시 유실될 수 있지만 canonical 충돌 방어는 PostgreSQL locator lock이다. rolling deploy에서 구버전 replica가 durable lock을 무시하지 않도록 mutation drain이 필요하다.
- Guided instruction이 발급된 뒤 외부 Proxmox 도구가 별도 작업을 시작하는 경쟁은 local lock으로 차단할 수 없다. active-task double read, 짧은 expiry, API after-state verification으로 성공 오판을 방지하지만 live cluster 검증은 수행하지 않았다.
- 현재 target identity는 한 configured cluster 안의 VMID를 전제한다. multi-cluster를 지원하려면 stable cluster identity를 포함해야 한다.
- target identity는 configured `GJALLAR_CLUSTER_ID`와 VMID를 사용한다. multi-cluster connection profile과 cluster별 worker partition은 아직 없다.
- stale snapshot persistence가 없어 Proxmox가 `degraded`이면 이전 inventory를 read-only로 열람할 수 없다.
- `live` connection은 inventory read 성공을 뜻할 뿐 token의 mutation permission discovery는 아직 제공하지 않는다. mutation은 기존 RBAC·approval·Proxmox response gate를 계속 사용한다.
- backend dependency lock은 마련됐지만 formatter/lint/type-check 기준은 아직 없다.
