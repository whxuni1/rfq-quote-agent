from __future__ import annotations

from pathlib import Path

import pytest

from personal_agent.audit import AuditLog
from personal_agent.store.db import Database
from personal_agent.vault import Vault, VaultError, redact


def test_vault_roundtrip_and_scopes(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    v = Vault(db, "pw")
    h = v.put("mail", {"username": "me", "password": "hunter22"}, ["mail.read", "mail.send"])
    assert "hunter22" not in h.model_dump_json()
    assert v.find("mail.send") == h
    assert v.resolve(h.handle_id, ["mail.read"])["password"] == "hunter22"
    with pytest.raises(VaultError):
        v.resolve(h.handle_id, ["pay.checkout"])
    # ciphertext at rest
    raw = db.conn.execute("SELECT ciphertext FROM vault").fetchone()[0]
    assert b"hunter22" not in bytes(raw)


def test_vault_wrong_passphrase(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    h = Vault(db, "pw").put("mail", {"password": "x" * 8}, ["mail.read"])
    with pytest.raises(VaultError):
        Vault(db, "other").resolve(h.handle_id, [])
    with pytest.raises(VaultError):
        Vault(db, "")


def test_redact_nested() -> None:
    out = redact({"a": ["token=abcd1234", {"b": "abcd1234"}], "n": 1}, ["abcd1234"])
    assert out == {"a": ["token=[REDACTED]", {"b": "[REDACTED]"}], "n": 1}


def test_audit_chain_detects_tampering(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    log = AuditLog(db)
    log.append("x", {"i": 1}, "g1")
    log.append("y", {"i": 2}, "g1")
    log.append("z", {"i": 3})
    assert log.verify() and len(log.entries("g1")) == 2
    db.conn.execute("UPDATE audit SET payload='{\"i\": 99}' WHERE seq=2")
    assert not log.verify()
