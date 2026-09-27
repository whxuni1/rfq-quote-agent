from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from rfq_agent.schemas.bom import BOMLine, BOMTree, MaterialClass


def _line(line_no: str, level: int, parent: str | None, **kw: Any) -> BOMLine:
    data: dict[str, Any] = {
        "line_no": line_no,
        "level": level,
        "parent_line_no": parent,
        "part_no": f"P{line_no}",
        "part_desc": "x",
        "material_class": MaterialClass.OTHER,
        "qty_per": Decimal(1),
        "uom": "EA",
        "source_hint": None,
        "auto_grade_required": False,
        "single_source_risk": None,
        "attributes": {},
    }
    data.update(kw)
    return BOMLine(**data)


def _tree(nodes: list[BOMLine], **kw: Any) -> BOMTree:
    data: dict[str, Any] = {
        "root": nodes[0],
        "nodes": nodes,
        "currency_hint": None,
        "total_lines": len(nodes),
    }
    data.update(kw)
    return BOMTree(**data)


def test_valid_tree() -> None:
    root = _line("1", 0, None)
    tree = _tree([root, _line("2", 1, "1"), _line("3", 2, "2")])
    assert tree.total_lines == 3


def test_line_is_frozen() -> None:
    with pytest.raises(ValidationError):
        _line("1", 0, None).qty_per = Decimal(2)  # type: ignore[misc]


@pytest.mark.parametrize(
    "kw, message",
    [
        ({"level": 0, "parent": "9"}, "level=0"),
        ({"level": 1, "parent": None}, "level>0"),
        ({"level": 0, "parent": None, "qty_per": Decimal(0)}, "greater than 0"),
    ],
)
def test_line_validation(kw: dict[str, Any], message: str) -> None:
    level, parent = kw.pop("level"), kw.pop("parent")
    with pytest.raises(ValidationError, match=message):
        _line("1", level, parent, **kw)


def test_root_must_be_level0() -> None:
    child = _line("2", 1, "1")
    with pytest.raises(ValidationError, match=r"root\.level"):
        _tree([child, _line("1", 0, None)], root=child)


def test_duplicate_line_no() -> None:
    with pytest.raises(ValidationError, match="重复"):
        _tree([_line("1", 0, None), _line("1", 1, "1")])


def test_root_must_be_in_nodes() -> None:
    with pytest.raises(ValidationError, match="包含 root"):
        _tree([_line("1", 0, None), _line("2", 1, "1")], root=_line("9", 0, None))


def test_exactly_one_level0() -> None:
    with pytest.raises(ValidationError, match="恰有一个"):
        _tree([_line("1", 0, None), _line("2", 0, None)])


def test_parent_must_exist() -> None:
    with pytest.raises(ValidationError, match="不存在"):
        _tree([_line("1", 0, None), _line("2", 1, "7")])


def test_level_must_be_contiguous() -> None:
    with pytest.raises(ValidationError, match="不连续"):
        _tree([_line("1", 0, None), _line("2", 2, "1")])


def test_total_lines_matches() -> None:
    with pytest.raises(ValidationError, match="total_lines"):
        _tree([_line("1", 0, None)], total_lines=5)
