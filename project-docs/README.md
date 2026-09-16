# Gjallar 문서 안내

- 상태: `APPROVED`
- 최종 검토일: `2026-09-07`
- 부분 검토: `2026-09-14`, 요청 파일 잠금 제거와 프리셋·이력 보존 정책

Gjallar는 Proxmox의 상태·위험·운영 근거를 관찰하고 설명하며, 필요한 경우 템플릿 기반 VM 생성·시작·정상 종료·Guided `qm unlock`을 제공한다. 이 디렉터리가 제품과 구현의 공동 기준 문서다.

## 어디서 시작할까

| 알고 싶은 것 | 기준 문서 | 설명하는 범위 |
|---|---|---|
| 어떤 제품이며 어디까지 만들 것인가 | [프로젝트 명세](specifications/project-specification.md) | 목적, 사용자, 제품 범위와 요구사항 |
| 현재 코드가 어떻게 동작하는가 | [아키텍처](architecture/overview.md) | 구현 현황, 의존성, 남은 호환 구조 |
| 어느 도메인이 책임지는가 | [도메인 지도](domains/domain-map.md) | 목표 책임과 현재 구현의 차이 |
| API는 무엇을 받거나 반환하는가 | [현재 API](api/current-api-v1.md) | 실제 route, 권한, 응답과 오류 계약 |
| DB에는 무엇을 왜 저장하는가 | [현재 DB](database/current-schema-and-ownership.md) | table, 소유권, transaction, migration 기준 |
| 작업이 성공하거나 중단되면 어떻게 되는가 | [작업 흐름](flows/verified-operation-lifecycle.md) | 실행, 검증, 불명확한 결과와 복구 |
| 어떻게 설치·실행·검증·운영하는가 | [Runbook](operations/runbook.md) | 명령, 환경 변수, 장애 대응과 live 작업 경계 |
| 작업 전에 무엇을 확인하는가 | [프로젝트 프로필](project-profile.md) | 저장소 지도, 기준 runtime, 위험과 검증 명령 |
| 왜 이렇게 결정했는가 | [ADR 인덱스](decisions/README.md) | 유효한 결정과 대체·철회 관계 |
| 다음에 무엇을 바꾸며 어디까지 승인됐는가 | [계획 인덱스](plans/README.md) | 후속 방향과 활성 Plan |
| 과거 문서·검증 원본은 어디에 있는가 | [보관 문서 안내](archive/README.md) | 완료·대체·철회된 계획, 조사와 원본 evidence |

처음 읽는 사람은 **명세 → 아키텍처 → 필요한 API·DB·흐름** 순서로 읽는다. 설치와 운영은 Runbook에서 시작한다. 모든 문서를 작업마다 일괄해서 읽지 않는다.

## 현재 구현과 다음 수정 방향

- 템플릿 직접 입력과 선택적 DB 프리셋을 제공하며 검토 계산·저장을 분리한다. 현재 상태는 직전 Proxmox 관찰로 판단한다.
- [ADR-011](decisions/adr-011-create-legacy-retirement.md)에 따라 current-workload writer·완료 VMID 독점·readiness owner 추정·네 action의 파일 잠금을 제거했다. PostgreSQL은 입력·감사·이력 및 잠금·복구를 담당한다. 기존 사용자 데이터는 보존한다.
- Create 입력은 partial inventory에서도 가능하다. 실행은 guest agent 외 source의 complete 관찰을 요구하며 guest agent 실패는 static IP에서 차단, DHCP에서 경고다. 다른 action의 gate는 유지한다.
- [ADR-012](decisions/adr-012-create-preset-and-history-retention.md)에 따라 선택적 프리셋은 DB에 유지하고, 현재 저장 단위의 입력·검토·승인·작업 기록은 자동 만료·삭제 없이 보존한다. 모든 수정본의 불변 보존이나 장기 archive 이관을 의미하지 않는다. 실제 구현·검증 상태는 [계획 인덱스](plans/README.md)에서 확인한다.

## 문서의 역할과 우선순위

1. 사용자가 가장 최근에 명시하거나 승인한 방향
2. 현재 `APPROVED` 명세
3. 같은 범위에서 대체 관계상 최신 `ACCEPTED` ADR
4. 현재 `APPROVED` 구현 Plan
5. 코드와 테스트가 보여주는 실제 동작

이 순서는 제품 의도와 구현 권한을 판단하는 기준이다. **현재 실행 동작은 코드로 확인**하며 의도와 다르면 현재 문서에 차이를 쓴다. ADR 채택, Plan 승인, 코드 구현, 검증 실행, 운영 배포는 서로 다른 상태다.

| 종류 | 위치·명명 | 관리 규칙 |
|---|---|---|
| 현재 기준 | 주제별 디렉터리의 명세·아키텍처·API·DB·흐름·Runbook | 현재 설명을 갱신한다. 같은 내용을 날짜별 복사본으로 만들지 않는다. |
| 결정 | `decisions/adr-NNN-<subject>.md` | 이유와 선택을 보존한다. 의미가 바뀌면 새 ADR과 대체 관계를 기록한다. |
| 활성 구현 계획 | `plans/YYYY-MM-DD-<subject>.md` | 승인할 구체적 변경, 검증·복구 범위를 작성한다. 일반 변경 요약에는 사용하지 않는다. |
| 종료 계획 | `archive/plans/` | `IMPLEMENTED`, `SUPERSEDED`, `CANCELLED`, `ROLLED_BACK` Plan을 보존한다. |
| 종료 조사 | `archive/assessments/` | 해결·철회된 조사와 당시 선택지를 보존한다. |
| 과거 검증 원본 | `evidence/legacy-live-smoke/` | 당시 환경의 증거다. 원문과 checksum을 보존한다. |
| 과거 rewrite 원본 | 저장소의 `artifacts/rewrite-baseline/` | 옛 PRD·runbook·snapshot이다. 현재 문서 체계 밖의 원본 보관소다. |

ADR은 인용 경로와 결정 번호를 유지하기 위해 폐기 상태여도 `decisions/`에 남긴다. 종료 Plan과 조사는 현재 문서 디렉터리에서 분리한다. 종료 Plan의 전체 목록은 [보관 목록](archive/plans/README.md)에만 유지하고 활성 계획 페이지에는 보관 링크만 둔다. 이동 시 내부 링크를 갱신하고 [계획](plans/README.md)·[보관](archive/README.md) 인덱스에서 찾을 수 있게 한다.

## 상태와 검토일

- 현재 기준 문서의 `APPROVED`는 합의된 제품·문서 기준을 뜻한다. 문서 속 모든 목표가 구현됐다는 뜻은 아니다.
- ADR: `PROPOSED → ACCEPTED`; 대체되면 `SUPERSEDED`, 채택하지 않거나 철회하면 `REJECTED`.
- Plan: `DRAFT → APPROVED → IMPLEMENTED`; 후속 계획으로 대체되면 `SUPERSEDED`, 취소하면 `CANCELLED`, 구현을 되돌렸으면 `ROLLED_BACK`.
- 역사 자료의 `HISTORICAL`, 해결된 조사의 `RESOLVED`는 현재 구현 지시가 아니다.
- `최종 검토일`은 해당 범위를 근거와 대조한 날짜다. 부분 검토라면 범위를 명시한다. 과거 승인일·실행일·테스트 결과를 현재 날짜로 바꾸지 않는다.
- 완료 Plan에 남은 검증·배포 제한은 계속 유효하다. `IMPLEMENTED`를 production 배포나 live mutation 검증의 증거로 쓰지 않는다.

## 변경할 때의 규칙

1. 사실의 소유 문서를 먼저 수정한다. README와 다른 문서는 짧은 요약과 링크를 사용한다.
2. 제품 범위 변경은 명세·ADR, 실제 구현 변경은 관련 아키텍처·API·DB·흐름·Runbook에 반영한다.
3. 후속 방향은 `미구현` 또는 `후속 설계`로 표시한다. 상세 API·schema·migration을 근거 없이 확정하지 않는다.
4. 과거 Plan·ADR의 당시 조사·승인·검증 본문은 현재 사실로 덮어쓰지 않는다. 상태·대체 안내와 이동에 따른 링크만 정리한다.
5. 과거 raw evidence의 오래된 경로·명령은 기록의 일부로 보존하며 재실행 절차로 사용하지 않는다. 현재 문서는 해당 raw 경로를 정상적인 구현 경로처럼 참조하지 않는다.
6. 일반 변경 이력은 Git이 담당한다. 작업별 요약·중복 roadmap·별도 CURRENT_STATE 문서를 늘리지 않는다.
7. 상대 링크와 heading anchor, 문서 간 현재/목표 일치, 보관 원본 checksum을 확인한다. 문서만 바꾼 경우 기존 문서 계약 테스트와 `git diff --check`를 실행하고, 제품 동작을 재검증한 것으로 표현하지 않는다.

프로젝트 작업 규율과 고위험 변경·live 작업 승인 경계는 [AGENTS.md](../AGENTS.md)와 [프로젝트 프로필](project-profile.md)을 따른다.
