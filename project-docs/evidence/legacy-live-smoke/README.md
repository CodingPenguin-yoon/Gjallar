# Historical Live-Smoke Evidence

- 상태: `HISTORICAL`
- 이동일: `2026-07-20`
- 용도: 과거 승인된 live 검증과 운영 준비 기록의 원본 보존

이 directory의 문서는 기존 `docs/`에서 내용 변경 없이 이동했다. 당시 코드·환경·제품 방향을 기록한 historical evidence이며 현재 요구사항, runbook, 재실행 승인으로 사용하지 않는다.

현재 제품·운영 기준은 다음 문서가 우선한다.

- [`../../specifications/project-specification.md`](../../specifications/project-specification.md)
- [`../../architecture/overview.md`](../../architecture/overview.md)
- [`../../operations/runbook.md`](../../operations/runbook.md)

## 보존 파일과 SHA-256

| 파일 | 성격 | SHA-256 |
|---|---|---|
| `create-vm-live-smoke-2026-05-03.md` | 초기 Create VM end-to-end smoke | `f3ff903f847d6a5237103a4376ccdef0a72a52c39b4c127f7ec7ec93b5038425` |
| `create-vm-live-smoke-2026-05-28.md` | Create VM live smoke | `329bf7df9ca246c80a8b7ef80e853c3122d01d57f03a7b00917e066eb38202b8` |
| `create-vm-live-smoke-2026-06-01.md` | Create VM/DRS 준비 live evidence | `cf2097f6802e4f919f2b1adc57f611d7b457a01a7bc2e647351dada4482cfce0` |
| `drs-explicit-test-candidate-prep-2026-06-03.md` | DRS explicit candidate와 reconciliation evidence | `509671815e07b42be52fec4b866cf85f49d965ac5fe870293f5d78c3c6bc2a44` |
| `legacy-operations-readme.md` | 기존 archive operations 안내 | `4164bc624c89bfa1aa66ccded115ab169c8a9b13051b1c65a1bbf2246533f1a2` |
| `legacy-operations-runbook.md` | 기존 archive runbook stub | `786cf5f6167aafc12fa8e9dc16a7c69e7415c60a9adda9bb272ebd248de082a4` |

## 사용 규칙

- future live mutation에는 새로운 target·side effect·rollback 확인과 사용자 승인이 필요하다.
- 문서 안의 credential, host, VMID를 현재 환경의 권위 있는 값으로 가정하지 않는다.
- 원본을 수정해야 할 이유가 생기면 수정 대신 별도 correction note와 새 checksum을 추가한다.
- active specification과 충돌하면 active `project-docs/`가 우선한다.
