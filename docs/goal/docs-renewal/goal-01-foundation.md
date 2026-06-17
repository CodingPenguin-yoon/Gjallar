# Goal 1: Documentation Foundation

Status: planned.

## 목표

Gjallar 문서의 새 기반을 만든다. 새 독자가 첫 페이지에서 프로젝트가 무엇인지,
무엇을 읽어야 하는지, 어떤 문서가 현재 기준인지 알 수 있어야 한다.

이 골은 skeleton과 독자 경로를 만드는 단계다. 모든 feature, API,
operations 문서를 끝까지 다시 쓰는 단계는 아니다.

## 하지 않을 일

- `docs/current/`를 이 단계에서 완전히 제거하지 않는다.
- `docs/ko/`를 이 단계에서 완전히 제거하지 않는다.
- 모든 feature 문서를 이 단계에서 완성하지 않는다.
- application behavior, runtime config, code를 바꾸지 않는다.
- archive/legacy PRD를 active source of truth로 되살리지 않는다.

## 대상 파일

새로 만들거나 다시 쓴다.

- `docs/README.md`
- `docs/start/README.md`
- `docs/start/new-reader.md`
- `docs/start/for-dev.md`
- `docs/start/for-ops.md`
- `docs/start/for-product.md`
- `docs/start/backend-for-beginners.md`
- `docs/overview/current-state.md`
- `docs/overview/system-summary.md`
- `docs/overview/glossary.md`
- `docs/decisions/README.md`

필요하면 갱신한다.

- `docs/archive/README.md`
- `docs/goal/docs-renewal/README.md`
- `docs/goal/docs-renewal/00-docs-principles.md`

## `docs/README.md` 요구사항

첫 페이지는 아래 순서로 쓴다.

1. Gjallar가 무엇인지
2. 현재 구현 상태 요약
3. 문서 대시보드
4. 학습 경로
5. source-of-truth 정책
6. archive 정책

사용자가 처음 여는 문서로 충분해야 한다. 단순 링크 모음이면 실패다.

## `docs/start/*` 요구사항

`docs/start`는 독자가 처한 상황별 읽기 경로다. 독자는 여전히 한 명이다.
Gjallar를 잘 모르는 사람이 어떤 목적을 가지고 읽느냐만 다르다.

- `new-reader.md`: 처음 30-60분 동안 읽을 순서
- `for-dev.md`: 수정 전 code, tests, contracts를 찾는 방법
- `for-ops.md`: runtime, deploy, account, Proxmox, troubleshooting 문서를
  찾는 방법
- `for-product.md`: 현재 기능, deferred 기능, product boundary를 이해하는
  방법
- `backend-for-beginners.md`: Gjallar 기준으로 route, endpoint, API client,
  domain logic, database session, job artifact, dependency, auth session,
  Proxmox client가 무엇인지 설명

## `docs/overview/*` 요구사항

- `current-state.md`: 기존 `docs/current/README.md`의 현재 구현 요약 역할을
  흡수한다.
- `system-summary.md`: 짧은 설명과 Mermaid system overview diagram을 둔다.
- `glossary.md`: 프로젝트 안에서만 쓰이는 용어를 정의한다.

## `docs/decisions/README.md` 요구사항

ADR index를 만들고 아래 ADR을 planned로 등록한다.

- `0001-proxmox-native-create-vm.md`
- `0002-remove-legacy-iac-readiness.md`
- `0003-local-auth-sessions-and-roles.md`
- `0004-approval-gated-drs-migration.md`
- `0005-db-backed-jobs-and-artifacts.md`
- `0006-read-only-inventory-baseline.md`

ADR 본문은 이 골에서 시간이 되면 작성해도 된다. 부족하면 Goal 3에서
작성하되, index에는 planned 상태가 보여야 한다.

## Mermaid 요구사항

최소한 아래 diagram을 포함한다.

- `docs/overview/system-summary.md`: system overview `flowchart`
- `docs/start/backend-for-beginners.md`: 첫 요청 흐름 diagram

## 완료 체크리스트

- [ ] 새 문서 skeleton이 존재한다.
- [ ] `docs/README.md`가 한국어 중심이고 프로젝트 설명으로 시작한다.
- [ ] 학습 경로가 존재한다.
- [ ] archive가 historical only로 명시되어 있다.
- [ ] `docs/ko/`는 임시 흡수 대상이지 영구 병렬 문서 트리가 아니다.
- [ ] `docs/current/`는 임시 흡수 대상이지 영구 source-of-truth 폴더가
      아니다.
- [ ] source-of-truth 순서에서 PRD/archive가 active 기준으로 취급되지 않는다.
- [ ] 새 페이지의 링크가 resolve된다.
- [ ] `git diff --check`가 통과한다.

## 권장 검증

```bash
find docs/start docs/overview docs/decisions -maxdepth 2 -type f -name '*.md' | sort
rg -n "historical only|source of truth|기준" docs/README.md docs/start docs/overview docs/decisions docs/archive/README.md
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend backend/venv/bin/python -m pytest -q -p no:cacheprovider backend/tests/contracts/test_legacy_backend_cleanup.py
git diff --check
```

## Goal 2 인계 메모

Goal 2는 독자 모델이나 폴더 전략을 다시 논의하지 않는다. Goal 1에서 심각한
문제가 발견된 경우만 예외다.

Goal 2는 `00-docs-principles.md`의 템플릿을 사용해서 feature, API,
implementation 문서를 본격적으로 작성한다.
