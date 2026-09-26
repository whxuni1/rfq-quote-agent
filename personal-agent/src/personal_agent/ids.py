"""Time-sortable identifiers (ULID-like, no external dependency)."""

from __future__ import annotations

import secrets
import time


def new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000):012x}{secrets.token_hex(5)}"
