# 03 — AI workflow and acceptance

This file is the agent-workflow addendum. Product behavior stays in `AGENTS.md` and `docs/00` through `docs/02`. Those files were not changed.

## Existing conventions

The repository is the Coregraph RFQ quote agent prompt set. `AGENTS.md` is the standing instruction. `docs/00-architecture.md` defines the orchestrator, four sub-agents, blackboard, and review gates. `docs/01-repo-structure.md` defines module boundaries. `docs/02-shared-schemas.md` defines the Pydantic models. `tasks/10` through `tasks/40` are the implementation prompts. Every task file is still `Status: TODO`.

There is no `src/`, `tests/`, `requirements.txt`, `pyproject.toml`, or `.github/workflows/ci.yml` yet. `docs/01-repo-structure.md` names that workflow as the future CI entry (`ruff`, `mypy`, `pytest`). No `.cursor` rules, skills, or subagents existed before this addendum.

Documented commands, to be used once the named files exist:

| Check | Command | Source |
|---|---|---|
| Task gate | `pytest tests/` | `AGENTS.md`, `tasks/40-iteration-loop.md` |
| Types | `mypy --strict` | `AGENTS.md` |
| Lint | `ruff check` | `AGENTS.md` says `ruff` with zero warnings |
| Tool tests | `pytest tests/unit/` | `tasks/20-tool-layer.md` |
| Orchestrator tests | `pytest tests/agents/test_orchestrator.py` | `tasks/10-orchestrator.md` |
| Golden eval | `pytest tests/eval/test_eval_suite.py` | `tasks/30-eval-harness.md` |
| Coverage | `pytest --cov` at or above 80% overall; tool layer at or above 95% | `AGENTS.md`, `tasks/20-tool-layer.md` |

`AGENTS.md` states a project cost tolerance of ±5%. `tasks/30-eval-harness.md` specifies the executable comparisons: piece price and NRE at relative tolerance `0.02`, total project value at `0.05`. This addendum records both and does not choose one.

## Files in this workflow

| File | Purpose |
|---|---|
| `.cursor/rules/coregraph-product-engineering.mdc` | Product engineering rule for agents, schemas, tools, tasks, and tests. Applied when those files are in context, and available from its description. |
| `.cursor/rules/security-data-governance.mdc` | Always-on rule for secrets, customer RFQ data, network boundaries, and logs. |
| `.cursor/skills/rfq-evaluation/SKILL.md` | Procedure for running and reading the golden RFQ evaluation. |
| `.cursor/skills/poc-scoping/SKILL.md` | Procedure for scoping a POC to the existing task order without implementing it. |
| `.cursor/agents/evaluation.md` | Read-only subagent that runs the evaluation and reports pass or fail. |
| `.cursor/agents/security-reviewer.md` | Read-only subagent that reviews diffs for data exposure and boundary violations. |

`AGENTS.md` was left in place. No existing rule or skill was overwritten. No runtime dependency was added.

## How Cursor loads them

- Project rules are `.mdc` files under `.cursor/rules/` with `description`, `globs`, and `alwaysApply`.
- Skills are `SKILL.md` files under `.cursor/skills/<name>/`. `name` matches the folder. The agent selects a skill from its description, or a person invokes it as `/rfq-evaluation` or `/poc-scoping`.
- Subagents are markdown files under `.cursor/agents/`. The parent delegates from the description, or a person invokes `/evaluation` or `/security-reviewer`. Both use `model: inherit` and `readonly: true`.

## Acceptance of this configuration

A change to these files is acceptable when:

1. Existing `AGENTS.md`, `docs/00`–`docs/02`, `tasks/`, and `README.md` are unchanged.
2. Each new file parses, and each skill `name` matches its parent folder.
3. Rules, skills, and subagents use only the frontmatter fields documented by Cursor for that file type.
4. Instructions cite the commands in the table above and do not introduce a package, service, or secret.
5. The security rule and the security subagent tell the agent to report paths and control gaps without quoting payload contents.

Product acceptance is unchanged: three eval fixtures, the tolerances recorded above, review-gate recovery, `pytest --cov` targets, and clean `mypy --strict` and `ruff` runs. Those checks start when the product tasks create the code and tests.

## Limits

These files guide Cursor Agent. They do not run in the quote pipeline, they do not replace review gates, and they do not affect Cursor Tab.

Cursor does not document a subagent `tools` allowlist. None is set. `readonly: true` is the supported write restriction. It may also block shell commands that write, including a pytest cache. If that happens, the evaluation subagent reports the command as not run. The parent still runs the documented pytest command.

A project subagent does not document automatic loading of a skill. The evaluation subagent is told to read the skill file.

The subagent is named `security-reviewer` so it does not reuse the built-in `security-review` task type or the `/review-security` skill. Built-in review remains available.

`alwaysApply: true` ignores `globs` and `description` for routing. The security rule sets `alwaysApply: true` and keeps a description for people reading the file. The product rule sets `alwaysApply: false` with both `description` and `globs`. Cursor documents each of those fields. Its routing table shows description-only and globs-only as separate rows, so a client may attach the product rule on a matching file, on the description, or on both.

Subagent `model` may be a pinned model id. These subagents use `inherit` because a pinned id can be replaced when a plan or admin policy disallows it. `is_background` is left unset and defaults to false.

Team rules, user rules, and synced personal skills are dashboard or machine settings. They are not stored in this repository.
