"""Product adapter.

Missing entry points return None. They do not return empty success, and the
probe duration is not recorded as RFQ latency.
"""

import importlib
from pathlib import Path

from rfq_eval.schema import (
    BOMLinePrediction,
    CostCase,
    CostPrediction,
    DocumentCase,
    DocumentPrediction,
    GateCase,
    GatePrediction,
    IsolationPair,
    IsolationPrediction,
    LatencyPrediction,
    RecoveryCase,
    RecoveryPrediction,
)


class AdapterSchemaError(ValueError):
    """Product output does not match the documented fields."""


class ProductAdapter:
    """Calls documented rfq_agent entry points when they exist."""

    modules = (
        "rfq_agent.tools.pdf_extract",
        "rfq_agent.tools.xlsx_bom",
        "rfq_agent.tools.cost_rollup",
        "rfq_agent.tools.gate_eval",
        "rfq_agent.runner",
    )

    def __init__(self) -> None:
        self.availability = {name: _probe(name) for name in self.modules}
        self.schema_errors: list[str] = []

    def predict_document(
        self,
        case: DocumentCase,
        pdf_path: Path,
        xlsx_path: Path,
    ) -> DocumentPrediction | None:
        del case, pdf_path, xlsx_path
        pdf_state = self.availability["rfq_agent.tools.pdf_extract"]
        bom_state = self.availability["rfq_agent.tools.xlsx_bom"]
        if pdf_state != "present" and bom_state != "present":
            return None
        # A structural parser is not scored as zero accuracy. Field, citation,
        # and flag predictions stay absent until an ingestion result is mapped.
        self.schema_errors.append(
            "document parsers are importable; this harness does not yet map them onto labeled fields"
        )
        return None

    def predict_cost(self, case: CostCase) -> CostPrediction | None:
        del case
        if self.availability["rfq_agent.tools.cost_rollup"] != "present":
            return None
        self.schema_errors.append("cost_rollup is importable but the eval call is withheld until BOMTree construction is mapped")
        return None

    def predict_gates(self, case: GateCase) -> GatePrediction | None:
        del case
        if self.availability["rfq_agent.tools.gate_eval"] != "present":
            return None
        self.schema_errors.append("gate_eval is importable but Blackboard construction is not mapped")
        return None

    def predict_recovery(self, case: RecoveryCase) -> RecoveryPrediction | None:
        del case
        return None

    def predict_isolation(
        self,
        pair: IsolationPair,
        left: DocumentCase,
        right: DocumentCase,
    ) -> IsolationPrediction | None:
        del pair, left, right
        return None

    def predict_latency(self, case: DocumentCase) -> LatencyPrediction | None:
        del case
        return None

    def reported_model_id(self) -> str | None:
        return None


def map_spec(spec: object) -> tuple[list[str], str, list[str]]:
    sections = getattr(spec, "sections", None)
    if not isinstance(sections, list):
        raise AdapterSchemaError("SpecDoc.sections is missing")
    titles: list[str] = []
    texts: list[str] = []
    cells: list[str] = []
    for section in sections:
        title = getattr(section, "title", None)
        text = getattr(section, "text", None)
        tables = getattr(section, "tables", [])
        if not isinstance(title, str) or not isinstance(text, str) or not isinstance(tables, list):
            raise AdapterSchemaError("SpecSection fields are not strings")
        titles.append(title)
        texts.append(text)
        for table in tables:
            if not isinstance(table, list):
                raise AdapterSchemaError("table is not a list")
            for row in table:
                if not isinstance(row, list):
                    raise AdapterSchemaError("table row is not a list")
                for cell in row:
                    if not isinstance(cell, str):
                        raise AdapterSchemaError("table cell is not a string")
                    cells.append(cell)
    return titles, "\n".join(texts), cells


def map_bom(tree: object) -> tuple[list[BOMLinePrediction], str | None]:
    from decimal import Decimal

    nodes = getattr(tree, "nodes", None)
    if not isinstance(nodes, list):
        raise AdapterSchemaError("BOMTree.nodes is missing")
    currency = getattr(tree, "currency_hint", None)
    if currency is not None and not isinstance(currency, str):
        raise AdapterSchemaError("currency_hint is not a string")
    keys: dict[str, str] = {}
    for node in nodes:
        part_no = _text(node, "part_no")
        description = _text(node, "part_desc")
        keys[_text(node, "line_no")] = part_no if part_no else f"desc:{description}"
    predictions: list[BOMLinePrediction] = []
    for node in nodes:
        line_no = _text(node, "line_no")
        part_no = _text(node, "part_no")
        description = _text(node, "part_desc")
        level = getattr(node, "level", None)
        parent = getattr(node, "parent_line_no", None)
        qty = getattr(node, "qty_per", None)
        uom = getattr(node, "uom", None)
        if not isinstance(level, int) or isinstance(qty, float) or not isinstance(qty, Decimal):
            raise AdapterSchemaError("BOMLine level or quantity is invalid")
        if not isinstance(uom, str):
            raise AdapterSchemaError("uom is not a string")
        if parent is not None and not isinstance(parent, str):
            raise AdapterSchemaError("parent_line_no is not a string")
        parent_key = None
        if isinstance(parent, str):
            parent_key = keys.get(parent)
            if parent_key is None:
                raise AdapterSchemaError(f"parent line {parent} is missing")
        predictions.append(
            BOMLinePrediction(
                match_key=keys[line_no],
                part_no=part_no,
                description=description,
                level=level,
                parent_match_key=parent_key,
                qty_per=qty,
                uom=uom,
            )
        )
    return predictions, currency


def _text(node: object, name: str) -> str:
    value = getattr(node, name, None)
    if not isinstance(value, str):
        raise AdapterSchemaError(f"{name} is not a string")
    return value


def _probe(module_name: str) -> str:
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError:
        return "missing"
    return "present"
