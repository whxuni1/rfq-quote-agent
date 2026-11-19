"""Write the regression report from a completed evaluation."""

import json
from pathlib import Path

from rfq_eval.schema import EvaluationReport, FailureExample
from rfq_eval.thresholds import thresholds


def write_outputs(report: EvaluationReport, failures: list[FailureExample], out_dir: Path) -> None:
    report_dir = out_dir / "reports"
    failure_dir = out_dir / "failures"
    report_dir.mkdir(parents=True, exist_ok=True)
    failure_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "regression_report.json").write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / "regression_report.md").write_text(render_markdown(report), encoding="utf-8")
    (out_dir / "THRESHOLDS.md").write_text(render_thresholds(), encoding="utf-8")
    (out_dir / "ERROR_TAXONOMY.md").write_text(render_taxonomy(report), encoding="utf-8")
    lines = [failure.model_dump_json() for failure in failures]
    (failure_dir / "latest.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def render_markdown(report: EvaluationReport) -> str:
    decision = "NOT PRODUCTION-READY" if not report.production_ready else "PRODUCTION GATES PASSED"
    rows = [
        "| Gate | Status | Decision | Value | Scored cases | Wilson low | Suite |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for gate in report.gates:
        value = "withheld" if gate.value is None else format(gate.value, "f")
        low = "n/a" if gate.wilson_low is None else format(gate.wilson_low, "f")
        rows.append(
            f"| {gate.gate_id} | {gate.status} | {gate.decision} | {value} | "
            f"{gate.independent_cases_scored}/{gate.independent_cases_labeled} | {low} | {gate.suite_met} |"
        )
    qa_rows = ["| Check | Passed | Observed |", "| --- | --- | --- |"]
    for item in report.dataset_qa:
        qa_rows.append(f"| {item.check_id} | {item.passed} | {item.observed} |")
    recommendations: list[str] = []
    for action in report.recommendations:
        recommendations.append(
            f"### {action.rank}. {action.title}\n\nEvidence: {action.evidence}\n\nAction: {action.action}\n"
        )
    versions = report.versions
    limitations = "\n".join(f"- {line}" for line in report.confidence_limitations)
    taxonomy = "\n".join(f"- {line}" for line in report.taxonomy)
    shanghai = report.generated_at_shanghai.strftime("%Y-%m-%d %H:%M:%S")
    utc = report.generated_at_utc.strftime("%Y-%m-%d %H:%M:%S")
    return f"""# RFQ agent regression report

**Decision: {decision}**

{report.decision_summary}

This report records only metrics produced by `python -m rfq_eval`. It does not fill in accuracy, latency, or USD when the product did not return a prediction.

## Reproduce

```bash
python -m rfq_eval
pytest
```

The command loads the persisted labels in `eval/dataset`. It rewrites that directory only with `--regenerate`, or on a first run when no manifest is present. It then rebuilds the text PDFs and workbooks, probes `rfq_agent`, and overwrites this report. Dataset QA failures withhold product scores.

## Run

- Run id: `{report.run_id}`
- Generated: {shanghai} Asia/Shanghai ({utc} UTC)
- Harness: `{versions.harness_version}`
- Dataset: `{versions.dataset_version}` sha256 `{versions.dataset_sha256}`
- Git: `{versions.git_sha or "unknown"}`
- Model id: `{versions.model_id or "absent"}` (source `{versions.model_source}`)
- Reported model id: `{versions.reported_model_id or "absent"}`
- Prompt hashes: `{json.dumps(versions.prompt_hashes, sort_keys=True)}`
- Missing prompt files: `{', '.join(versions.missing_prompt_files) if versions.missing_prompt_files else "none"}`
- Price-card models: `{', '.join(versions.price_card_models) if versions.price_card_models else "none"}`
- Failure examples: `{report.failure_count}` in `eval/failures/latest.jsonl`

## Sample size and confidence

{limitations}

## Gates

{chr(10).join(rows)}

`review_pass` means the labeled suite met its bar and the confidence floor for production did not. `fail` with status `not_measured` means no gate value is claimed.

## Dataset QA

These checks validate labels and fixtures. They are not product accuracy.

{chr(10).join(qa_rows)}

## Deterministic and model-based evaluation

Deterministic gates compare labeled values with equality, set membership, and Decimal arithmetic.

Model-based status: `{report.model_based.status}`.

{report.model_based.reason}

Rubrics defined and not scored:

{chr(10).join(f"- {item}" for item in report.model_based.rubrics)}

## Error taxonomy

{taxonomy}

## Top 5 reliability improvements

{chr(10).join(recommendations)}
"""


def render_thresholds() -> str:
    lines = [
        "# Pass/fail thresholds",
        "",
        "Review bars apply to the labeled set. Production also requires the case-level",
        "95% Wilson lower bound and the minimum independent-case count.",
        "A perfect score reaches a Wilson lower bound of 0.95 at 73 cases.",
        "A missing prediction is fail-closed and is not scored as zero.",
        "",
        "| Gate | Review rule | Primary bar | Production minimum | Wilson floor | Zero tolerance |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in thresholds():
        bar = "n/a" if item.primary_bar is None else format(item.primary_bar, "f")
        floor = "n/a" if item.production_wilson_floor is None else format(item.production_wilson_floor, "f")
        lines.append(
            f"| {item.gate_id} | {item.review_rule} | {bar} | {item.production_min_cases} | {floor} | {item.zero_tolerance} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_taxonomy(report: EvaluationReport) -> str:
    lines = [
        "# Error taxonomy",
        "",
        "Codes are the regression identifiers stored in `eval/failures/latest.jsonl`.",
        "A code marked release_blocker fails a production decision when it is present on a gate that did not pass.",
        "",
    ]
    lines.extend(f"- {line}" for line in report.taxonomy)
    lines.append("")
    return "\n".join(lines)
