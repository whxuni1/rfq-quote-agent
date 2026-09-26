"""Append-only, hash-chained audit log."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from personal_agent.schemas.common import utcnow
from personal_agent.store.db import Database

_GENESIS = "0" * 64


class AuditLog:
    def __init__(self, db: Database) -> None:
        self._db = db

    def append(self, kind: str, payload: dict[str, Any], goal_id: str | None = None) -> str:
        row = self._db.conn.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        prev = row["hash"] if row else _GENESIS
        at = utcnow().isoformat()
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(f"{prev}|{at}|{kind}|{goal_id}|{body}".encode()).hexdigest()
        self._db.conn.execute(
            "INSERT INTO audit (at, kind, goal_id, payload, prev_hash, hash) VALUES (?,?,?,?,?,?)",
            (at, kind, goal_id, body, prev, digest),
        )
        return digest

    def entries(self, goal_id: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM audit" + (" WHERE goal_id = ?" if goal_id else "") + " ORDER BY seq"
        rows = self._db.conn.execute(q, (goal_id,) if goal_id else ()).fetchall()
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    def verify(self) -> bool:
        prev = _GENESIS
        for r in self._db.conn.execute("SELECT * FROM audit ORDER BY seq"):
            expect = hashlib.sha256(
                f"{prev}|{r['at']}|{r['kind']}|{r['goal_id']}|{r['payload']}".encode()
            ).hexdigest()
            if r["prev_hash"] != prev or r["hash"] != expect:
                return False
            prev = r["hash"]
        return True
