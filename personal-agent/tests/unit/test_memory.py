from __future__ import annotations

from pathlib import Path

from personal_agent.llm.fake import FakeLLMClient
from personal_agent.memory import MemoryService, format_memories
from personal_agent.schemas import MemoryCandidate, MemoryType
from personal_agent.store.db import Database


def cand(pred: str, value: str, subject: str = "user", t: MemoryType = MemoryType.FACT) -> MemoryCandidate:
    return MemoryCandidate(type=t, subject=subject, predicate=pred, value=value, evidence=value)


def svc(tmp_path: Path) -> MemoryService:
    return MemoryService(Database(tmp_path / "m.db"))


def test_dedupe_and_supersede(tmp_path: Path) -> None:
    m = svc(tmp_path)
    a = m.add(cand("email_tone", "正式", t=MemoryType.PREFERENCE), "user_statement")
    assert a is not None
    assert m.add(cand("email_tone", "正式", t=MemoryType.PREFERENCE), "user_statement") is None
    b = m.add(cand("email_tone", "随意", t=MemoryType.PREFERENCE), "user_statement")
    assert b is not None
    assert [x.value for x in m.list_items("active")] == ["随意"]
    old = m.get(a.memory_id)
    assert old is not None and old.status == "superseded"


def test_untrusted_goes_to_pending_and_does_not_supersede(tmp_path: Path) -> None:
    m = svc(tmp_path)
    m.add(cand("diet", "素食"), "user_statement")
    p = m.add(cand("diet", "什么都吃"), "untrusted_content")
    assert p is not None and p.status == "pending_confirm"
    assert [x.value for x in m.list_items("active")] == ["素食"]
    assert m.recall("diet 饮食") and all(x.status == "active" for x in m.recall("diet"))
    confirmed = m.confirm(p.memory_id)
    assert confirmed is not None and confirmed.status == "active"
    assert m.confirm(p.memory_id) is None


def test_sensitive_tagging_and_values(tmp_path: Path) -> None:
    m = svc(tmp_path)
    m.add(cand("allergy", "花生"), "user_statement")
    m.add(cand("favorite_color", "蓝色"), "user_statement")
    assert m.sensitive_values() == ["花生"]


def test_recall_cjk_and_forget(tmp_path: Path) -> None:
    m = svc(tmp_path)
    a = m.add(cand("allergy", "花生过敏"), "user_statement")
    m.add(cand("email", "zs@example.com", subject="contact:张三"), "user_statement")
    assert a is not None
    hits = m.recall("推荐周末聚餐的餐厅，注意过敏")
    assert [h.memory_id for h in hits] == [a.memory_id]
    assert "张三" in format_memories(m.recall("给张三发邮件"))
    assert m.forget(a.memory_id) and not m.forget(a.memory_id)
    assert len(m.export()) == 1
    assert format_memories([]) == "（无相关记忆）"


async def test_extract_marks_explicit(tmp_path: Path) -> None:
    m = svc(tmp_path)
    llm = FakeLLMClient(lambda _r, _m: {"candidates": [
        {"type": "fact", "subject": "user", "predicate": "allergy", "value": "花生", "evidence": "我对花生过敏"}]})
    stored, _ = await m.extract_from_user(llm, "记住：我对花生过敏")
    assert stored[0].source == "user_explicit" and stored[0].sensitive
