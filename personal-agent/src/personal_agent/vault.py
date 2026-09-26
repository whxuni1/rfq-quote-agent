"""Credential vault: AES-GCM at rest, key derived from a passphrase via scrypt.

The agent and the LLM only ever see CredentialHandle. Secrets are resolved by the
ToolRunner right before a tool executes, passed to the sandboxed worker over stdin,
and scrubbed from the tool's output.
"""

from __future__ import annotations

import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from personal_agent.ids import new_id
from personal_agent.schemas.credentials import CredentialHandle
from personal_agent.store.db import Database


class VaultError(RuntimeError):
    pass


class Vault:
    def __init__(self, db: Database, passphrase: str) -> None:
        if not passphrase:
            raise VaultError("vault passphrase is empty")
        self._db = db
        row = db.conn.execute("SELECT value FROM vault_meta WHERE key='salt'").fetchone()
        if row is None:
            salt = os.urandom(16)
            db.conn.execute("INSERT INTO vault_meta (key, value) VALUES ('salt', ?)", (salt,))
        else:
            salt = bytes(row["value"])
        key = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(passphrase.encode())
        self._aead = AESGCM(key)

    def put(self, service: str, secret: dict[str, Any], scopes: list[str]) -> CredentialHandle:
        handle = CredentialHandle(handle_id=new_id("cred"), service=service, scopes=sorted(scopes))
        nonce = os.urandom(12)
        ct = self._aead.encrypt(nonce, json.dumps(secret).encode(), handle.handle_id.encode())
        self._db.conn.execute(
            "INSERT INTO vault (handle_id, service, scopes, nonce, ciphertext) VALUES (?,?,?,?,?)",
            (handle.handle_id, service, json.dumps(handle.scopes), nonce, ct),
        )
        return handle

    def handles(self) -> list[CredentialHandle]:
        rows = self._db.conn.execute("SELECT handle_id, service, scopes FROM vault").fetchall()
        return [
            CredentialHandle(handle_id=r["handle_id"], service=r["service"], scopes=json.loads(r["scopes"]))
            for r in rows
        ]

    def find(self, scope: str) -> CredentialHandle | None:
        return next((h for h in self.handles() if scope in h.scopes), None)

    def resolve(self, handle_id: str, required_scopes: list[str]) -> dict[str, Any]:
        """Only the ToolRunner may call this."""
        row = self._db.conn.execute("SELECT * FROM vault WHERE handle_id=?", (handle_id,)).fetchone()
        if row is None:
            raise VaultError(f"unknown credential {handle_id}")
        missing = set(required_scopes) - set(json.loads(row["scopes"]))
        if missing:
            raise VaultError(f"credential {handle_id} lacks scopes {sorted(missing)}")
        try:
            plain = self._aead.decrypt(bytes(row["nonce"]), bytes(row["ciphertext"]), handle_id.encode())
        except Exception as e:  # InvalidTag: wrong passphrase or tampering
            raise VaultError("cannot decrypt credential (wrong passphrase?)") from e
        secret: dict[str, Any] = json.loads(plain)
        return secret

    def delete(self, handle_id: str) -> None:
        self._db.conn.execute("DELETE FROM vault WHERE handle_id=?", (handle_id,))


def secret_values(secret: dict[str, Any]) -> list[str]:
    return [str(v) for v in secret.values() if isinstance(v, str | int) and len(str(v)) >= 4]


def redact(value: Any, secrets: list[str]) -> Any:
    """Recursively replace any secret value appearing in a tool output."""
    if not secrets:
        return value
    if isinstance(value, str):
        for s in secrets:
            value = value.replace(s, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()}
    return value
