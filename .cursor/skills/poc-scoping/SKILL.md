---
name: poc-scoping
description: Scopes a Coregraph RFQ-quote proof of concept to the existing task order, synthetic fixtures, and documented acceptance commands. Use when asked to scope a POC, pilot, or first slice. Does not implement product code.
---

# POC scoping

Produce a bounded scope. Do not create modules, dependencies, fixtures, or runtime configuration from this skill.

## When to use

Use when asked for a POC, pilot, demo slice, or what to build first.

## Steps

1. Read `AGENTS.md`, `docs/00-architecture.md`, `docs/01-repo-structure.md`, `docs/02-shared-schemas.md`, and `tasks/40-iteration-loop.md`.
2. State the POC question in one sentence. The default question is whether one synthetic RFQ package can become a `QuoteDraft` with deterministic costs and a review gate.
3. Include only tasks that already exist, in the order in `tasks/40-iteration-loop.md`. Do not pull a later task forward.
4. Inputs are synthetic files shaped like `tests/fixtures/case1_simple_pcba/`. Do not use a real customer RFQ.
5. Leave out ERP and PLM connectors, network APIs, new third-party libraries, combining the four sub-agents into one prompt, and any price calculated by an LLM.
6. Name the acceptance commands already written for the included tasks. The project gate remains `pytest tests/`, `mypy --strict`, and `ruff check`. Include `pytest tests/eval/test_eval_suite.py` only when task 30 is inside the slice.
7. Deliver included tasks, excluded tasks, inputs, outputs, commands, and open blockers.

## Blocker format

When two docs disagree, stop and record this. Do not choose a side.

```
[BLOCKER] task=<id>
问题：...
依据：...
候选：...
```
