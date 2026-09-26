"""SQLite persistence. Single-user MVP; schema kept Postgres-portable."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goal_events (
    goal_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY (goal_id, seq)
);
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    request_id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL,
    body TEXT NOT NULL,
    decided INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS vault_meta (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS vault (
    handle_id TEXT PRIMARY KEY,
    service TEXT NOT NULL,
    scopes TEXT NOT NULL,
    nonce BLOB NOT NULL,
    ciphertext BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    goal_id TEXT,
    payload TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS todos (
    todo_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    due TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()
