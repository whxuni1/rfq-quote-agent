"""IngestionAgent：RFQ 包（PDF + Excel）→ RFQPackage。pipeline 唯一入口。

顺序：pdf_extract → xlsx_bom → 确定性歧义规则 → LLM 理解（QuoteIntent 草稿 + 补充歧义）。
确定性规则覆盖 docs 中可机械判定的歧义；LLM 只补充规则看不到的语义歧义，不产生任何数字计算。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog
from pydantic import TypeAdapter, ValidationError

from rfq_agent.llm.base import LLMClient, LLMError
from rfq_agent.prompts import load_prompt
from rfq_agent.schemas.bom import BOMTree, MaterialClass
from rfq_agent.schemas.intent import QuoteIntent
from rfq_agent.schemas.rfq import AmbiguityFlag, DrawingRef, RFQPackage, SpecDoc
from rfq_agent.tools import ToolError
from rfq_agent.tools.pdf_extract import extract_spec, section_raw_text
from rfq_agent.tools.xlsx_bom import classify_material, collect_part_quantities, parse_bom

AGENT_NAME = "ingestion"
SECTION_TEXT_LIMIT = 1500  # 送入 LLM 的单章节字符上限

# 必须按"个数"计量的物料类别；用长度/重量单位计量视为 UOM 歧义
COUNT_UOM_CLASSES: frozenset[MaterialClass] = frozenset(
    {
        MaterialClass.SOC,
        MaterialClass.MCU,
        MaterialClass.MEMORY,
        MaterialClass.DISPLAY,
        MaterialClass.CAMERA,
        MaterialClass.SENSOR,
        MaterialClass.OPTICS,
        MaterialClass.PCBA,
        MaterialClass.CONNECTOR,
        MaterialClass.HOUSING,
    }
)
NON_COUNT_UOMS: frozenset[str] = frozenset({"M", "MM", "CM", "KM", "G", "KG", "L", "ML", "M2"})
PLACEHOLDER_PART_NOS: frozenset[str] = frozenset({"TBD", "TBA", "N/A", "NA", "-", "?", "XXX"})

_DRAWING_REF = re.compile(
    r"\b(DWG-[A-Z0-9][A-Z0-9-]*[A-Z0-9])(?:\s*Rev\.?\s*([A-Z0-9]+))?", re.IGNORECASE
)
_FILE_REVISION = re.compile(r"rev[._-]?([A-Z0-9]+)$", re.IGNORECASE)
_CUSTOMER = re.compile(r"^\s*(?:customer|客户)\s*[:：]\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_PROJECT = re.compile(r"^\s*(?:project|项目)\s*[:：]\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_FLAG_LIST = TypeAdapter(list[AmbiguityFlag])

UNKNOWN = "UNKNOWN"


class IngestionError(Exception):
    """Ingestion 失败，不进入 pipeline。`details` 列出失败文件/页/行或校验错误。"""

    def __init__(self, message: str, details: Sequence[str] = ()) -> None:
        super().__init__(message if not details else f"{message}: {'; '.join(details)}")
        self.details = list(details)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IngestionAgent:
    def __init__(
        self,
        llm: LLMClient,
        clock: Callable[[], datetime] = _utcnow,
        max_retries: int = 1,
    ) -> None:
        self._llm = llm
        self._clock = clock
        self._max_retries = max_retries
        self._system_prompt = load_prompt(AGENT_NAME)

    async def run(
        self,
        pdf_path: str,
        xlsx_path: str,
        rfq_id: str,
        package_dir: str | None = None,
    ) -> tuple[RFQPackage, QuoteIntent]:
        """解析 RFQ 包。返回 RFQPackage 与 LLM 产出的 QuoteIntent 草稿。

        `package_dir`：用于查找图纸文件的目录（递归），默认取 PDF 所在目录。
        """
        log = structlog.get_logger().bind(rfq_id=rfq_id, agent=AGENT_NAME)
        received_at = self._clock()

        log.info("start", step="pdf_extract")
        spec = await self._tool(extract_spec, pdf_path)
        customer, project_name = _header_fields(spec)

        log.info("start", step="xlsx_bom")
        project_label = project_name if project_name != UNKNOWN else rfq_id
        tree = await self._tool(parse_bom, xlsx_path, rfq_id, project_label)
        part_qtys = await self._tool(collect_part_quantities, xlsx_path)

        search_dir = Path(package_dir) if package_dir else Path(pdf_path).parent
        drawing_refs, drawing_files = _find_drawing_refs(spec, tree, search_dir)

        rule_flags = _rule_flags(spec, tree, part_qtys, drawing_refs, customer, project_name)
        log.info("rule_flags", step="ambiguity_rules", count=len(rule_flags))

        context = _llm_context(rfq_id, customer, project_name, spec, tree, drawing_refs, rule_flags)
        intent, llm_flags = await self._understand(context, log)

        flags = _merge_flags(rule_flags, llm_flags)
        try:
            package = RFQPackage(
                rfq_id=rfq_id,
                customer=customer,
                project_name=project_name,
                received_at=received_at,
                spec_doc=spec,
                bom_tree=tree,
                drawing_refs=drawing_refs,
                ambiguity_flags=flags,
                raw_files=[pdf_path, xlsx_path, *drawing_files],
            )
        except ValidationError as exc:
            raise IngestionError("RFQPackage 校验失败", [str(exc)]) from exc
        log.info("done", step="assemble_package", flags=len(flags), bom_lines=tree.total_lines)
        return package, intent

    async def _tool(self, fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return await asyncio.to_thread(fn, *args)
        except ToolError as exc:
            raise IngestionError(f"{getattr(fn, '__name__', 'tool')} 失败", [str(exc)]) from exc

    async def _understand(
        self, context: dict[str, Any], log: Any
    ) -> tuple[QuoteIntent, list[AmbiguityFlag]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
        ]
        errors: list[str] = []
        for attempt in range(1 + self._max_retries):
            try:
                raw = await self._llm.chat(messages)
            except LLMError as exc:
                errors.append(f"attempt {attempt + 1}: LLM 调用失败: {exc}")
                log.warning("llm_failed", step="llm_understand", attempt=attempt + 1)
                continue
            try:
                result = _parse_llm_output(raw)
                log.info("llm_ok", step="llm_understand", attempt=attempt + 1)
                return result
            except (ValueError, ValidationError) as exc:
                errors.append(f"attempt {attempt + 1}: {exc}")
                log.warning("llm_invalid", step="llm_understand", attempt=attempt + 1)
                messages = [
                    *messages,
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "上一次输出未通过 schema 校验，请只返回修正后的 JSON 对象。错误：\n"
                            f"{exc}"
                        ),
                    },
                ]
        raise IngestionError("LLM 理解步骤失败", errors)


# ---------------------------------------------------------------------------
# 确定性辅助函数
# ---------------------------------------------------------------------------


def _header_fields(spec: SpecDoc) -> tuple[str, str]:
    text = "\n".join(s.text for s in spec.sections)
    customer = _CUSTOMER.search(text)
    project = _PROJECT.search(text)
    return (
        customer.group(1).strip() if customer else UNKNOWN,
        project.group(1).strip() if project else UNKNOWN,
    )


def _find_drawing_refs(
    spec: SpecDoc, tree: BOMTree, search_dir: Path
) -> tuple[list[DrawingRef], list[str]]:
    refs: dict[str, dict[str, str | None]] = {}
    for section in spec.sections:
        for match in _DRAWING_REF.finditer(section_raw_text(section)):
            entry = refs.setdefault(match.group(1).upper(), {"revision": None, "line_no": None})
            if match.group(2) and entry["revision"] is None:
                entry["revision"] = match.group(2).upper()
    for node in tree.nodes:
        for match in _DRAWING_REF.finditer(node.attributes.get("drawing", "")):
            entry = refs.setdefault(match.group(1).upper(), {"revision": None, "line_no": None})
            if entry["line_no"] is None:
                entry["line_no"] = node.line_no

    files = sorted(p for p in search_dir.rglob("*") if p.is_file()) if search_dir.is_dir() else []
    drawing_refs: list[DrawingRef] = []
    found_files: list[str] = []
    for ref_id in sorted(refs):
        entry = refs[ref_id]
        match_file = next((p for p in files if p.stem.upper().startswith(ref_id)), None)
        revision = entry["revision"]
        if match_file is not None:
            found_files.append(str(match_file))
            rev_match = _FILE_REVISION.search(match_file.stem)
            if revision is None and rev_match:
                revision = rev_match.group(1).upper()
        drawing_refs.append(
            DrawingRef(
                ref_id=ref_id,
                file_name=match_file.name if match_file is not None else "",
                revision=revision,
                referenced_in_line_no=entry["line_no"],
            )
        )
    return drawing_refs, found_files


def _rule_flags(
    spec: SpecDoc,
    tree: BOMTree,
    part_qtys: dict[str, list[tuple[str, Decimal]]],
    drawing_refs: Sequence[DrawingRef],
    customer: str,
    project_name: str,
) -> list[AmbiguityFlag]:
    flags: list[AmbiguityFlag] = []

    def add(category: Any, description: str, line_no: str | None, severity: Any) -> None:
        flags.append(
            AmbiguityFlag(
                flag_id=f"RULE-{len(flags) + 1}",
                category=category,
                description=description,
                related_line_no=line_no,
                severity=severity,
            )
        )

    # spec_gap：规格章节标题指向某物料类别，但 BOM 中无该类别物料
    bom_classes = {n.material_class for n in tree.nodes}
    for section in spec.sections:
        material_class = classify_material(section.title)
        if material_class is not MaterialClass.OTHER and material_class not in bom_classes:
            add(
                "spec_gap",
                f"Spec section '{section.title}' requires {material_class.value} "
                f"but BOM has no {material_class.value} line",
                None,
                "high",
            )

    for node in tree.nodes:
        # uom_ambiguous：计件类物料用长度/重量单位
        if node.material_class in COUNT_UOM_CLASSES and node.uom.upper() in NON_COUNT_UOMS:
            add(
                "uom_ambiguous",
                f"{node.part_no} ({node.material_class.value}) quantified in {node.uom}, "
                "expected a count unit",
                node.line_no,
                "medium",
            )
        # source_conflict：指定厂商但无料号
        if node.source_hint and node.part_no.strip().upper() in PLACEHOLDER_PART_NOS:
            add(
                "source_conflict",
                f"Vendor '{node.source_hint}' specified for '{node.part_desc}' "
                "but part number is missing",
                node.line_no,
                "medium",
            )

    # qty_ambiguous：同一料号在不同 sheet 用量不同
    line_by_part = {n.part_no: n.line_no for n in reversed(tree.nodes)}
    for part_no in sorted(part_qtys):
        occurrences = part_qtys[part_no]
        if len({qty for _, qty in occurrences}) > 1:
            detail = ", ".join(f"{sheet}={qty}" for sheet, qty in occurrences)
            add(
                "qty_ambiguous",
                f"{part_no} quantity differs across sheets: {detail}",
                line_by_part.get(part_no),
                "medium",
            )

    # drawing_missing：引用的图纸在文件包中找不到
    for ref in drawing_refs:
        if not ref.file_name:
            add(
                "drawing_missing",
                f"Drawing {ref.ref_id} referenced but not found in package",
                ref.referenced_in_line_no,
                "high",
            )

    # term_undefined：无法从规格书识别客户/项目
    if customer == UNKNOWN:
        add("term_undefined", "Customer name not found in spec", None, "low")
    if project_name == UNKNOWN:
        add("term_undefined", "Project name not found in spec", None, "low")
    return flags


def _llm_context(
    rfq_id: str,
    customer: str,
    project_name: str,
    spec: SpecDoc,
    tree: BOMTree,
    drawing_refs: Sequence[DrawingRef],
    rule_flags: Sequence[AmbiguityFlag],
) -> dict[str, Any]:
    class_counts: dict[str, int] = {}
    for node in tree.nodes:
        class_counts[node.material_class.value] = class_counts.get(node.material_class.value, 0) + 1
    return {
        "rfq_id": rfq_id,
        "customer": customer,
        "project_name": project_name,
        "spec_sections": [
            {"title": s.title, "text": section_raw_text(s)[:SECTION_TEXT_LIMIT]}
            for s in spec.sections
        ],
        "quantity_req": spec.quantity_req.model_dump(mode="json") if spec.quantity_req else None,
        "delivery_req": spec.delivery_req.model_dump(mode="json") if spec.delivery_req else None,
        "quality_req": spec.quality_req.model_dump(mode="json") if spec.quality_req else None,
        "commercial_req_raw": spec.commercial_req_raw,
        "bom_stats": {
            "total_lines": tree.total_lines,
            "max_level": max(n.level for n in tree.nodes),
            "material_class_counts": class_counts,
            "currency_hint": tree.currency_hint,
        },
        "bom_lines": [
            {
                "line_no": n.line_no,
                "level": n.level,
                "part_no": n.part_no,
                "part_desc": n.part_desc,
                "material_class": n.material_class.value,
                "qty_per": str(n.qty_per),
                "uom": n.uom,
                "source_hint": n.source_hint,
            }
            for n in tree.nodes
        ],
        "drawing_refs": [r.model_dump(mode="json") for r in drawing_refs],
        "rule_flags": [f.model_dump(mode="json") for f in rule_flags],
    }


def _parse_llm_output(raw: str) -> tuple[QuoteIntent, list[AmbiguityFlag]]:
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("输出中没有 JSON 对象")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict) or "quote_intent" not in data:
        raise ValueError("缺少顶层字段 quote_intent")
    intent = QuoteIntent.model_validate(data["quote_intent"])
    flags = _FLAG_LIST.validate_python(data.get("ambiguity_flags", []))
    return intent, flags


def _merge_flags(
    rule_flags: Sequence[AmbiguityFlag], llm_flags: Sequence[AmbiguityFlag]
) -> list[AmbiguityFlag]:
    """规则 flag 优先；LLM flag 与规则 flag 同 (category, related_line_no) 时视为重复丢弃。
    合并后按顺序重新编号为 AMB-001...，保证 ID 稳定可复现。"""
    covered = {(f.category, f.related_line_no) for f in rule_flags}
    extra = [f for f in llm_flags if (f.category, f.related_line_no) not in covered]
    merged = [*rule_flags, *extra]
    return [f.model_copy(update={"flag_id": f"AMB-{i:03d}"}) for i, f in enumerate(merged, 1)]
