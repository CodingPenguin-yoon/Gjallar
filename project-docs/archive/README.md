# 보관 문서 안내

- 상태: `HISTORICAL`
- 분류 검토일: `2026-09-09`

이 영역은 현재 기준과 분리한 종료 계획·조사를 보관한다. 문서 속 `현재`, 명령, API, 경로와 검증 결과는 작성 당시를 뜻한다. 현재 동작·운영 절차는 [문서 안내](../README.md)의 기준 문서를 따른다.

| 자료 | 위치 | 처리 원칙 |
|---|---|---|
| 종료 구현 계획 23개 | [종료 계획 목록](plans/README.md) | 21개 구현 완료·1개 대체·1개 롤백. 승인·검증 본문을 보존하고 상태·후속 관계·링크만 정리 |
| 해결된 DRS·Jobs 조사 | [DRS·Jobs convergence assessment](assessments/drs-jobs-convergence-assessment.md) | DRS 폐기 전 선택지와 결론의 역사. 현재 architecture가 아님 |
| 대체·철회 ADR | [ADR 인덱스](../decisions/README.md) | 결정 번호·기존 인용 경로를 유지하므로 `decisions/`에 그대로 보존 |
| Live-smoke 원문 6개 | [Historical evidence](../evidence/legacy-live-smoke/README.md) | 기존 SHA-256과 원문 보존. 재실행 승인으로 쓰지 않음 |
| Rewrite 원본 52개 | 저장소 `artifacts/rewrite-baseline/README.md` (컨테이너 제외) | 당시 PRD·공유 문서·JSON snapshot 원형 보존. 현재 요구사항이 아님 |

## 현재 방향으로 대체된 내용

- Control-plane-first 제품 중심과 DRS maintenance는 [ADR-007](../decisions/adr-007-observe-first-operations-intelligence.md) 및 이후 제거 구현으로 대체됐다.
- 과거 문서의 Create/Guided recovery 부재는 당시 사실이다. 현재 네 action의 복구와 정확한 완료 순서는 [작업 흐름](../flows/verified-operation-lifecycle.md)을 따른다.
- 독립 Network readiness 화면과 전용 계산은 [2026-09-07 정리](plans/2026-09-07-navigation-cleanup.md)에서 제거했다. network inventory·Create preflight·Insights VM readiness는 유지한다.
- Create의 request/Jobs 병행 기록을 도입한 과거 결정은 현재 구현을 설명하는 역사다. 장기 유지·확장 승인이 아니며 다음 단순화 방향은 [ADR-008](../decisions/adr-008-template-based-create-and-persistence-simplification.md)을 따른다.

## 원본과 링크

종료 Plan·조사는 보관 위치에 맞춰 상대 링크를 조정한다. 과거 실행 evidence와 rewrite snapshot은 내용·checksum 보존을 우선하므로 내부의 옛 경로·명령을 최신 경로로 고치지 않는다. 원본에서 현재 파일을 찾지 못하면 이 인덱스를 통해 현재 문서로 돌아온다. 원본의 호스트·VMID·credential 예시는 현재 환경의 값으로 사용하지 않는다.
