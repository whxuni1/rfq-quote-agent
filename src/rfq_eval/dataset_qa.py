"""Integrity checks for the labeled dataset.

These checks do not score the product. A failing check withholds product scores.
"""

from pathlib import Path

import pdfplumber
from openpyxl import load_workbook

from rfq_eval.documents import write_pdf, write_xlsx
from rfq_eval.label_audit import gates_from_facts, piece_price, project_value
from rfq_eval.schema import DatasetQAItem, DocumentCase, EvalDataset
from rfq_eval.thresholds import GATE_TYPES

_REQUIRED_CONTROLS = (
    "gate-margin-at-floor",
    "gate-connector-single",
    "gate-nre-equal",
    "gate-warranty-36",
    "neg-clean",
    "neg-currency-conflict",
    "adv-soc-meters",
    "adv-formula-qty",
    "adv-inject-zero",
    "adv-inject-exfil",
    "cost-missing-volume",
    "cost-chain-trap",
    "rec-review-timeout",
)


def run_dataset_qa(dataset: EvalDataset, work_dir: Path) -> list[DatasetQAItem]:
    checks = [
        _ids(dataset),
        _counts(dataset),
        _scope(dataset),
        _bom_structure(dataset),
        _quotes_in_source(dataset),
        _isolation_tokens(dataset),
        _injection_tokens(dataset),
        _oracles(dataset),
        _controls(dataset),
        _price_card(dataset),
        _pdf_extractable(dataset, work_dir),
        _xlsx_roundtrip(dataset, work_dir),
    ]
    return checks


def qa_passed(items: list[DatasetQAItem]) -> bool:
    return all(item.passed for item in items)


def _item(check_id: str, passed: bool, observed: str, limitation: str) -> DatasetQAItem:
    return DatasetQAItem(check_id=check_id, passed=passed, observed=observed, limitation=limitation)


def _source(case: DocumentCase) -> str:
    chunks: list[str] = []
    for section in case.sections:
        chunks.append(section.title)
        chunks.extend(section.paragraphs)
        for table in section.tables:
            for row in table:
                chunks.extend(row)
    for sheet in case.sheets:
        chunks.append(sheet.name)
        chunks.extend(sheet.headers)
        for row in sheet.rows:
            chunks.extend(row)
    return "\n".join(chunks)


def _ids(dataset: EvalDataset) -> DatasetQAItem:
    seen: set[str] = set()
    dupes: list[str] = []
    for case_id in _all_ids(dataset):
        if case_id in seen:
            dupes.append(case_id)
        seen.add(case_id)
    return _item(
        "unique_ids",
        not dupes,
        f"{len(seen)} ids, duplicates={dupes}",
        "Duplicate ids would make failure files ambiguous.",
    )


def _all_ids(dataset: EvalDataset) -> list[str]:
    ids = [case.case_id for case in dataset.documents]
    ids.extend(case.case_id for case in dataset.gates)
    ids.extend(case.case_id for case in dataset.costs)
    ids.extend(case.case_id for case in dataset.recovery)
    ids.extend(pair.pair_id for pair in dataset.isolation)
    return ids


def _counts(dataset: EvalDataset) -> DatasetQAItem:
    polarities = [case.polarity for case in dataset.documents]
    nominal = polarities.count("nominal")
    negative = polarities.count("negative")
    adversarial = polarities.count("adversarial")
    ok = nominal >= 8 and negative >= 5 and adversarial >= 8 and len(dataset.costs) >= 20
    ok = ok and len(dataset.gates) >= 12 and len(dataset.recovery) >= 5 and len(dataset.isolation) >= 6
    return _item(
        "case_counts",
        ok,
        f"documents nominal={nominal} negative={negative} adversarial={adversarial}; "
        f"gates={len(dataset.gates)} costs={len(dataset.costs)} "
        f"recovery={len(dataset.recovery)} isolation={len(dataset.isolation)}",
        "These are labeled cases, not a production sample. See the production minimum of 73.",
    )


def _scope(dataset: EvalDataset) -> DatasetQAItem:
    ok = (
        dataset.manifest.synthetic
        and not dataset.manifest.ocr_in_scope
        and not dataset.manifest.scanned_pdf_in_scope
        and all(case.synthetic for case in dataset.documents)
    )
    return _item(
        "synthetic_scope",
        ok,
        "synthetic=true ocr_in_scope=false scanned_pdf_in_scope=false",
        "This dataset does not measure scanned drawings or OCR.",
    )


def _bom_structure(dataset: EvalDataset) -> DatasetQAItem:
    problems: list[str] = []
    for case in dataset.documents:
        keys = [line.match_key for line in case.bom]
        if len(keys) != len(set(keys)):
            problems.append(f"{case.case_id} duplicate match key")
        keyset = set(keys)
        for line in case.bom:
            if line.parent_match_key is not None and line.parent_match_key not in keyset:
                problems.append(f"{case.case_id} missing parent {line.parent_match_key}")
        if case.accept_full_rejection and not case.expect_parse_error:
            problems.append(f"{case.case_id} rejection without parse error")
        for line in case.bom:
            if line.part_no and line.part_no not in _source(case):
                problems.append(f"{case.case_id} part {line.part_no} missing from source")
    cockpit = next(case for case in dataset.documents if case.case_id == "nom-cockpit-core")
    if not any(line.level == 2 for line in cockpit.bom):
        problems.append("cockpit has no level-2 line")
    return _item(
        "bom_structure",
        not problems,
        "ok" if not problems else "; ".join(problems[:8]),
        "Parent links are checked against this dataset, not against a product parser.",
    )


def _quotes_in_source(dataset: EvalDataset) -> DatasetQAItem:
    missing: list[str] = []
    for case in dataset.documents:
        blob = _source(case)
        for field in case.fields:
            if field.quote is not None and field.quote not in blob:
                missing.append(f"{case.case_id}:{field.path}")
        for flag in case.flags:
            if flag.source_quote not in blob:
                missing.append(f"{case.case_id}:flag:{flag.category}")
    return _item(
        "quotes_in_source",
        not missing,
        "ok" if not missing else "; ".join(missing[:8]),
        "A label whose quote is not in the source cannot be used as a citation oracle.",
    )


def _isolation_tokens(dataset: EvalDataset) -> DatasetQAItem:
    by_id = {case.case_id: case for case in dataset.documents}
    problems: list[str] = []
    for pair in dataset.isolation:
        left = _source(by_id[pair.case_a])
        right = _source(by_id[pair.case_b])
        for token in pair.tokens_a_forbidden_in_b:
            if token not in left or token in right:
                problems.append(f"{pair.pair_id} token A {token}")
        for token in pair.tokens_b_forbidden_in_a:
            if token not in right or token in left:
                problems.append(f"{pair.pair_id} token B {token}")
    return _item(
        "isolation_tokens",
        not problems,
        "ok" if not problems else "; ".join(problems[:8]),
        "Tokens must be real secrets of one case and absent from the other.",
    )


def _injection_tokens(dataset: EvalDataset) -> DatasetQAItem:
    problems: list[str] = []
    for case in dataset.documents:
        if case.injection is None:
            continue
        blob = _source(case)
        for token in case.injection.forbidden_substrings:
            if token in blob:
                problems.append(f"{case.case_id} contains {token}")
        for path in case.injection.fields_that_must_hold:
            if not any(field.path == path for field in case.fields):
                problems.append(f"{case.case_id} missing field {path}")
    return _item(
        "injection_tokens",
        not problems and any(case.injection is not None for case in dataset.documents),
        "ok" if not problems else "; ".join(problems),
        "Forbidden strings are other customers' secrets and must not be planted in the attack text.",
    )


def _oracles(dataset: EvalDataset) -> DatasetQAItem:
    problems: list[str] = []
    for cost in dataset.costs:
        if cost.piece_price != piece_price(cost):
            problems.append(f"{cost.case_id} piece")
        total, missing = project_value(cost)
        if cost.total_project_value != total or cost.expect_data_missing != missing:
            problems.append(f"{cost.case_id} total")
    covered: set[str] = set()
    for gate in dataset.gates:
        expected = gates_from_facts(gate.facts)
        if expected != gate.expected_gate_types:
            problems.append(f"{gate.case_id} gates")
        if gate.expect_single_packet != bool(expected):
            problems.append(f"{gate.case_id} packet flag")
        covered.update(expected)
    if set(GATE_TYPES) - covered:
        problems.append("missing gate types " + ",".join(sorted(set(GATE_TYPES) - covered)))
    return _item(
        "label_oracles",
        not problems,
        "ok" if not problems else "; ".join(problems[:8]),
        "Cost and gate oracles restate the written rules. They are not product scores.",
    )


def _controls(dataset: EvalDataset) -> DatasetQAItem:
    ids = set(_all_ids(dataset))
    missing = [case_id for case_id in _REQUIRED_CONTROLS if case_id not in ids]
    return _item(
        "required_controls",
        not missing,
        "ok" if not missing else ",".join(missing),
        "Negative and adversarial controls are part of the review set.",
    )


def _price_card(dataset: EvalDataset) -> DatasetQAItem:
    empty = dataset.price_card.models == {}
    return _item(
        "price_card_empty",
        empty,
        f"models={list(dataset.price_card.models)}",
        "No vendor price is invented. USD per RFQ stays unmeasured.",
    )


def _pdf_extractable(dataset: EvalDataset, work_dir: Path) -> DatasetQAItem:
    missing: list[str] = []
    target = work_dir / "qa-pdf"
    for case in dataset.documents:
        path = target / f"{case.case_id}.pdf"
        write_pdf(case, path)
        with pdfplumber.open(path) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        for field in case.fields:
            if field.quote is not None and field.quote not in text:
                missing.append(f"{case.case_id}:{field.path}")
        for section in case.sections:
            for paragraph in section.paragraphs:
                if paragraph not in text:
                    missing.append(f"{case.case_id}:paragraph")
                    break
    return _item(
        "pdf_quotes_extractable",
        not missing,
        "ok" if not missing else "; ".join(missing[:8]),
        "This is fixture extractability with pdfplumber, not product extraction accuracy.",
    )


def _xlsx_roundtrip(dataset: EvalDataset, work_dir: Path) -> DatasetQAItem:
    problems: list[str] = []
    target = work_dir / "qa-xlsx"
    for case in dataset.documents:
        path = target / f"{case.case_id}.xlsx"
        write_xlsx(case, path)
        book = load_workbook(path)
        for sheet in case.sheets:
            grid = book[sheet.name]
            header = [cell.value for cell in next(grid.iter_rows(min_row=1, max_row=1))]
            if header != sheet.headers:
                problems.append(f"{case.case_id}:{sheet.name} header")
            for offset, row in enumerate(sheet.rows, start=2):
                values = [cell.value for cell in next(grid.iter_rows(min_row=offset, max_row=offset))]
                expected = list(row)
                actual = ["" if value is None else str(value) for value in values]
                if actual != expected:
                    problems.append(f"{case.case_id}:{sheet.name} row {offset}")
        book.close()
    return _item(
        "xlsx_roundtrip",
        not problems,
        "ok" if not problems else "; ".join(problems[:8]),
        "Workbook cells match the labeled rows, including formula text.",
    )
