"""Password checks for the private trial app. The public demo does not ask for a login."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from artwork_agent.db import Database


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, digest = stored.split("$", 1)
    check = hash_password(password, salt).split("$", 1)[1]
    return hmac.compare_digest(check, digest)


def login(db: Database, email: str, password: str) -> dict | None:
    row = db.fetchone("SELECT * FROM team WHERE email = ?", (email.strip().lower(),))
    if row and verify_password(password, row.get("password_hash") or ""):
        return row
    return None
