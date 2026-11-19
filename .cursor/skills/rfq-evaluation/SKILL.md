---
name: rfq-evaluation
description: Runs and interprets the Coregraph RFQ golden evaluation. Use when checking QuoteDraft output, cost tolerance, risk capture, review gates, or tests/eval.
---

# RFQ evaluation

Evaluate the quote pipeline against the harness specified in `tasks/30-eval-harness.md`. Do not edit product code, golden files, or fixtures from this skill. Do not add test dependencies.

## When to use

Use after a change to `src/rfq_agent/runner.py`, agents, tools, `tests/eval/`, or `tests/fixtures/`, and when someone asks whether a quote draft passes.

## Checks

1. Confirm these paths exist before claiming a result: `tests/eval/test_eval_suite.py`, `tests/eval/golden/`, and `tests/fixtures/case1_simple_pcba/`, `case2_cockpit_core/`, `case3_adas_camera/`. If any are missing, report the harness as not implemented.
2. Run `pytest tests/eval/test_eval_suite.py`. For a full task gate, also run `pytest tests/`, `mypy --strict`, and `ruff check`.
3. Apply the assertions written in `tasks/30-eval-harness.md`: piece price and NRE at relative tolerance `0.02`, total project value at `0.05`, risk counts, review-trail length, and `incomplete_reason is None`. `AGENTS.md` also states a project cost tolerance of ±5%. Report both. Do not pick a new tolerance.
4. Case expectations from the same task: `case1` finishes with no gate; `case2` merges its gates into one review packet; `case3` applies the scripted override and reruns procurement.
5. Coverage targets, once the suite exists, are the documented ones: `pytest --cov` at or above 80% overall (`AGENTS.md`), and tool-layer coverage at or above 95% via `pytest tests/unit/` (`tasks/20-tool-layer.md`). Do not install coverage tooling in order to evaluate.

## Report

State commands, exit codes, failed assertion names, and missing files. Do not print fixture bodies, prices from real programs, or secrets. Eval tests must not use the network. `src/rfq_agent/llm/mock.py` is test-only.
