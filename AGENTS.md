# AGENTS.md

## Heimdall operating mode
- The main session is the coordinator.
- For non-trivial tasks, delegate to explorer, reviewer, docs_researcher, then worker.
- Only worker is allowed to edit code.
- Do not start worker until explorer and reviewer have returned.
- Prefer concise summaries over raw logs and long command dumps.
- Keep the main thread focused on requirements, decisions, and final output.

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
