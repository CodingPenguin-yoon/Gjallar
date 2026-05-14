# AI Coding Workflow Principles

Source: `/Users/yoon/Library/Mobile Documents/com~apple~CloudDocs/AI 설계.txt`

This file records the repo-local operating principles to use when working on
Gjallar with AI coding agents. Treat it as workflow guidance, not product
requirements. Product behavior still follows `docs/product/prd/drs-advisor/`
and the current implementation status docs.

## Core Problems To Avoid

- Requirement drift: implementation does more, less, or different work than the
  agreed request.
- Repeated context loss: project conventions, UX rules, architecture, and
  safety boundaries must not be rediscovered from scratch every time.
- Code quality erosion: do not accept AI output without tests, review, or
  clear ownership of behavior.
- Architecture decay: avoid incremental changes that make later changes scary
  or ambiguous.

## Working Principles

### 1. Grill Me

When requirements, scope, UX, data flow, safety, or ownership are ambiguous,
ask focused questions before broad implementation. Keep this as pair
programming: narrow the decision, confirm the tradeoff, then implement.

For Gjallar, ask especially when a change may affect:

- Proxmox mutation behavior
- approval gates
- job/artifact audit semantics
- DRS Advisor product scope
- Create VM target contracts
- destructive or irreversible operations

### 2. PRD First

Before large implementation, write or update the relevant product/technical
decision document. Include:

- problem
- target behavior
- user/operator workflow
- implementation decisions
- explicit out-of-scope items
- validation expectations

For this repo, prefer updating current docs under:

- `docs/product/prd/drs-advisor/`
- `docs/product/status/`
- `docs/engineering/architecture/`

### 3. TDD Before Broad Implementation

For behavior changes, update or add focused tests before or alongside the
implementation. Do not write tests that simply bless an old flawed behavior.

Use the smallest useful feedback loop:

- backend unit/contract tests for API and safety behavior
- frontend model tests for payload/view-model changes
- build/lint only after focused tests pass

### 4. Diagnose Systematically

When something fails:

1. Reproduce the failure.
2. Form one concrete hypothesis.
3. Verify it directly with a targeted command or read.
4. Fix the confirmed cause.

Do not repeatedly guess or make unrelated refactors while debugging.

### 5. Improve Architecture

Read the existing code path before editing. Preserve local module boundaries and
remove real duplication or stale paths when they cause confusion. Refactor only
when it supports the agreed task and improves maintainability.

For Gjallar, this means:

- Proxmox native Create VM is the active create path.
- Terraform Create VM code is legacy/deprecated and should be removed through a
  planned cleanup slice.
- Read-only inventory and mutation clients must stay separate.
- DRS Advisor migration work must not reuse Create VM mutation semantics as if
  they were migration authorization.

### 6. User Owns Interfaces

The user owns product workflow, UX, and high-level architecture decisions. AI
agents implement the agreed design, surface tradeoffs, and avoid silently
changing contracts.

### 7. Review Separately

After significant implementation, run a review pass focused on:

- regressions
- missing tests
- safety gate bypasses
- stale docs
- architectural drift

Prefer a fresh reviewer context when the implementation was substantial.

## Gjallar Defaults

- Keep the main session as coordinator.
- Follow `AGENTS.md` for non-trivial work: explorer, reviewer,
  docs_researcher, then worker.
- Keep implementation slices small and validated.
- Avoid silent behavior changes.
- Maintain a living remaining-work document for multi-step cleanups.
- For infrastructure automation, prefer preview, dry-run, approval, execution,
  post-check, and auditable artifacts.
