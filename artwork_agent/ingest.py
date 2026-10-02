"""Store messages once, detect WeTransfer links, and keep an audit trail."""

from __future__ import annotations

import re

from artwork_agent.checks import is_vague, message_hash
from artwork_agent.db import Database, new_id

WETRANSFER = re.compile(r"https?://(?:we\.tl|wetransfer\.com)/\S+", re.I)


def audit(db: Database, actor: str, action: str, detail: str, at: str) -> None:
    db.execute(
        "INSERT INTO audit_log (id, at, actor, action, detail) VALUES (?, ?, ?, ?, ?)",
        (new_id(), at, actor, action, detail[:2000]),
    )


def wetransfer_urls(text: str) -> list[str]:
    return WETRANSFER.findall(text or "")


def add_message(
    db: Database,
    *,
    source: str,
    sender: str,
    sent_at: str,
    body: str,
    subject: str = "",
    external_id: str = "",
    project_ids: list[str] | None = None,
    reason: str = "",
    confidence: float | None = None,
    original_body: str = "",
    translation: str = "",
    at: str = "",
    message_id: str = "",
) -> dict:
    vague = is_vague(body)
    digest = message_hash(sender, sent_at, body)
    if external_id:
        existing = db.fetchone("SELECT id FROM messages WHERE external_id = ?", (external_id,))
        if existing:
            return {"id": existing["id"], "duplicate": True}
    existing = db.fetchone("SELECT id FROM messages WHERE content_hash = ?", (digest,))
    if existing:
        return {"id": existing["id"], "duplicate": True}
    message_id = message_id or new_id()
    db.execute(
        """
        INSERT INTO messages
        (id, external_id, content_hash, source, sender, sent_at, subject, body, original_body, translation, unclear)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message_id,
            external_id or None,
            digest,
            source,
            sender,
            sent_at,
            subject,
            body,
            original_body or body,
            translation,
            1 if vague else 0,
        ),
    )
    links = project_ids or []
    if links:
        for project_id in links:
            db.execute(
                """
                INSERT INTO message_links (message_id, project_id, reason, confidence)
                VALUES (?, ?, ?, ?)
                """,
                (message_id, project_id, reason, confidence),
            )
    else:
        db.execute("INSERT INTO unsorted (message_id) VALUES (?)", (message_id,))
    for url in wetransfer_urls(f"{subject}\n{body}"):
        for project_id in links:
            db.execute(
                "INSERT INTO related_files (id, project_id, kind, name, drive_file_id, note) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id(), project_id, "wetransfer", url, "", "files received via WeTransfer"),
            )
    audit(db, "agent", "read_message", f"{source} {message_id} from {sender}", at or sent_at)
    return {"id": message_id, "duplicate": False, "unclear": vague}


def assign_message(db: Database, message_id: str, project_id: str, pattern: str, kind: str, at: str) -> None:
    db.execute("DELETE FROM unsorted WHERE message_id = ?", (message_id,))
    already = db.fetchone(
        "SELECT message_id FROM message_links WHERE message_id = ? AND project_id = ?",
        (message_id, project_id),
    )
    if not already:
        db.execute(
            "INSERT INTO message_links (message_id, project_id, reason, confidence) VALUES (?, ?, ?, ?)",
            (message_id, project_id, "assigned by a person", 1.0),
        )
    if pattern:
        db.execute(
            "INSERT INTO match_rules (id, pattern, project_id, kind) VALUES (?, ?, ?, ?)",
            (new_id(), pattern, project_id, kind),
        )
    audit(db, "person", "assign_message", f"{message_id} -> {project_id} rule {kind} {pattern}", at)


def store_secret(db: Database, name: str, ciphertext: str) -> None:
    db.execute("DELETE FROM secrets WHERE name = ?", (name,))
    db.execute("INSERT INTO secrets (name, ciphertext) VALUES (?, ?)", (name, ciphertext))


def read_secret(db: Database, name: str) -> str:
    row = db.fetchone("SELECT ciphertext FROM secrets WHERE name = ?", (name,))
    return row["ciphertext"] if row else ""
