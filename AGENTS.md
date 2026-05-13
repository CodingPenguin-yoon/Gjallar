# AGENTS.md

## Heimdall operating mode
- The main session is the coordinator.
- For non-trivial tasks, delegate to explorer, reviewer, docs_researcher, then worker.
- Only worker is allowed to edit code.
- Do not start worker until explorer and reviewer have returned.
- Prefer concise summaries over raw logs and long command dumps.
- Keep the main thread focused on requirements, decisions, and final output.

## Multi-agent model policy
- When model control is required, do not use built-in `explorer`, `reviewer`, `docs_researcher`, or `worker` agent types because their model settings may be runtime-fixed.
- Spawn `default` agents with `model: gpt-5.5` and `reasoning_effort: xhigh`.
- Assign the intended role in the prompt text instead: explorer, reviewer, docs_researcher, or worker.
- Preserve the same delegation order and edit restrictions even when roles are assigned by prompt text.

## When to skip multi-agent
- Single-file trivial edits
- Known typo fixes
- Mechanical updates with already-known file targets

## Delegation order
1. explorer scopes code paths, impacted files, symbols, configs, migrations, and likely tests
2. reviewer checks correctness, regressions, security, and missing coverage
3. docs_researcher verifies framework/API/config assumptions
4. worker makes the smallest coherent change

## Definition of done
- Scope is clear
- Change is minimal and targeted
- Relevant validation ran
- Remaining risk is explicitly stated

## Avoid
- broad scans when targeted reads are enough
- speculative refactors
- style-only review comments
- silent changes to behavior or contracts
