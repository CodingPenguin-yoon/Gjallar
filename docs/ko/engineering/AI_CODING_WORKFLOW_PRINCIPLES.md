# AI Coding Workflow Principles

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 AI coding workflow principles](../../engineering/AI_CODING_WORKFLOW_PRINCIPLES.md), [Gjallar current work plan](../../engineering/GJALLAR_CURRENT_WORK_PLAN.md), [Current implemented state](../current/README.md).

이 문서는 Gjallar에서 AI coding agent가 작업할 때 지켜야 할 repo-local 원칙을 한국어로 설명합니다. 제품 요구사항 자체는 [product/drs-advisor](../product/drs-advisor/README.md)와 [current state](../current/README.md)를 따릅니다.

## 피해야 할 문제

- Requirement drift: 합의한 요청보다 더 하거나, 덜 하거나, 다른 일을 하는 것.
- Context loss: 프로젝트 conventions, UX rules, architecture, safety boundaries를 매번 다시 찾는 것.
- Code quality erosion: 테스트/검토 없이 AI output을 받아들이는 것.
- Architecture decay: 작은 변경이 누적되어 다음 변경을 어렵게 만드는 것.

## 작업 원칙

모호하면 질문하고, 큰 구현 전에 관련 product/technical decision doc을 갱신합니다. Behavior change에는 가능한 한 focused tests를 먼저 또는 함께 추가합니다. 실패는 재현, 가설, 직접 검증, 확정 원인 수정 순서로 진단합니다.

Gjallar에서는 특히 Proxmox mutation behavior, approval gates, job/artifact audit semantics, DRS Advisor product scope, Create VM target contracts, destructive operations를 조심해야 합니다.

## Repo-local defaults

AGENTS.md는 non-trivial task에서 explorer, reviewer, docs_researcher, worker 순서를 요구합니다. Worker만 code edit을 합니다. Current-vs-target language를 명확히 유지하고, silent behavior change를 피하며, validation 결과와 remaining risk를 명시합니다.
