"""Label-echo adapter used only to test the scorer.

This is not a product and the CLI never constructs it.
"""

from pathlib import Path

from rfq_eval.adapt import ProductAdapter
from rfq_eval.schema import (
    BOMLinePrediction,
    CitationPrediction,
    CostCase,
    CostPrediction,
    DocumentCase,
    DocumentPrediction,
    FieldPrediction,
    FlagPrediction,
    GateCase,
    GatePrediction,
    IsolationPair,
    IsolationPrediction,
    RecoveryCase,
    RecoveryPrediction,
)
from rfq_eval.thresholds import REQUIRED_OPTIONS


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


def _cells(case: DocumentCase) -> list[str]:
    cells: list[str] = []
    for section in case.sections:
        for table in section.tables:
            for row in table:
                cells.extend(row)
    return cells


class EchoAdapter(ProductAdapter):
    def predict_document(
        self,
        case: DocumentCase,
        pdf_path: Path,
        xlsx_path: Path,
    ) -> DocumentPrediction:
        del pdf_path, xlsx_path
        lines: list[BOMLinePrediction] = []
        parse_error = None
        if case.accept_full_rejection:
            parse_error = "rejected"
        else:
            for gold in case.bom:
                qty = gold.qty_per
                if gold.qty_rule == "omit_or_exact":
                    qty = gold.accept_qty[0]
                lines.append(
                    BOMLinePrediction(
                        match_key=gold.match_key,
                        part_no=gold.part_no,
                        description=gold.description,
                        level=gold.level,
                        parent_match_key=gold.parent_match_key,
                        qty_per=qty,
                        uom=gold.uom,
                    )
                )
        return DocumentPrediction(
            fields=[FieldPrediction(path=field.path, value=field.value) for field in case.fields],
            section_titles=[section.title for section in case.sections],
            section_text=_source(case),
            table_cells=_cells(case),
            bom_lines=lines,
            flags=[
                FlagPrediction(
                    category=flag.category,
                    related_part_no=flag.related_part_no,
                    severity=flag.severity,
                )
                for flag in case.flags
            ],
            citations=[
                CitationPrediction(
                    claim_path=field.path,
                    quote=field.quote,
                    locator=field.locator or "page:1",
                    file_role=field.file_role or "spec_pdf",
                )
                for field in case.fields
                if field.quote is not None and field.locator is not None and field.file_role is not None
            ],
            parse_error=parse_error,
            output_text=_source(case),
            complete_artifact=True,
        )

    def predict_cost(self, case: CostCase) -> CostPrediction:
        return CostPrediction(
            piece_price=case.piece_price,
            nre_total=case.nre_total,
            total_project_value=case.total_project_value,
            currency=case.currency,
            data_missing=case.expect_data_missing,
        )

    def predict_gates(self, case: GateCase) -> GatePrediction:
        options: dict[str, list[str]] = {}
        for gate_type in case.expected_gate_types:
            required = REQUIRED_OPTIONS.get(gate_type)
            options[gate_type] = list(required) if required is not None else ["选项甲", "选项乙"]
        return GatePrediction(
            gate_types=list(case.expected_gate_types),
            packet_count=1 if case.expected_gate_types else 0,
            options_by_type=options,
            questions_nonempty=bool(case.expected_gate_types),
            context_json_safe=True,
        )

    def predict_recovery(self, case: RecoveryCase) -> RecoveryPrediction:
        if case.failure_mode == "review_timeout":
            return RecoveryPrediction(
                status="blocked",
                incomplete_reason="review_timeout: packet-1",
                priced_quote_emitted=False,
                raised_exception_type=None,
                retries=None,
            )
        if case.failure_mode == "tool_exception":
            return RecoveryPrediction(
                status=None,
                incomplete_reason=None,
                priced_quote_emitted=False,
                raised_exception_type="ToolError",
                retries=None,
            )
        if case.failure_mode == "llm_exhausted":
            return RecoveryPrediction(
                status="awaiting_review",
                incomplete_reason=None,
                priced_quote_emitted=False,
                raised_exception_type=None,
                retries=2,
                gate_types=["DATA_MISSING"],
            )
        if case.failure_mode == "invalid_override":
            return RecoveryPrediction(
                status=None,
                incomplete_reason=None,
                priced_quote_emitted=False,
                raised_exception_type="ValidationError",
                retries=None,
            )
        return RecoveryPrediction(
            status="blocked",
            incomplete_reason="missing engineering report",
            priced_quote_emitted=False,
            raised_exception_type=None,
            retries=None,
        )

    def predict_isolation(
        self,
        pair: IsolationPair,
        left: DocumentCase,
        right: DocumentCase,
    ) -> IsolationPrediction:
        del pair
        return IsolationPrediction(
            artifact_a=_source(left),
            artifact_b=_source(right),
            artifact_a_after_b=_source(left),
            artifact_b_after_a=_source(right),
        )
