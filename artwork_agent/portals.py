"""Expiring proof and factory links. No login on the public pages."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from artwork_agent.checks import expired_message, latest_label, link_status
from artwork_agent.db import Database, new_id
from artwork_agent.ingest import audit


def _expires(now: datetime, days: int = 30) -> str:
    return (now + timedelta(days=days)).replace(microsecond=0).isoformat()


def create_proof_link(db: Database, project_id: str, version_label: str, now: datetime, reviewers: list[str] | None = None) -> str:
    token = secrets.token_urlsafe(18)
    db.execute(
        "INSERT INTO proof_links (token, project_id, version_label, expires_at, revoked) VALUES (?, ?, ?, ?, 0)",
        (token, project_id, version_label, _expires(now)),
    )
    for email in reviewers or []:
        db.execute(
            "INSERT INTO proof_reviewers (id, token, name, email, decision, decided_at) VALUES (?, ?, '', ?, 'pending', '')",
            (new_id(), token, email),
        )
    audit(db, "person", "proof_link", f"{project_id} {version_label}", now.isoformat())
    return token


def create_factory_link(db: Database, project_id: str, now: datetime) -> str:
    token = secrets.token_urlsafe(18)
    db.execute(
        "INSERT INTO factory_links (token, project_id, expires_at, revoked) VALUES (?, ?, ?, 0)",
        (token, project_id, _expires(now)),
    )
    audit(db, "person", "factory_link", project_id, now.isoformat())
    return token


def revoke(db: Database, token: str, kind: str, at: str) -> None:
    table = "proof_links" if kind == "proof" else "factory_links"
    db.execute(f"UPDATE {table} SET revoked = 1 WHERE token = ?", (token,))
    audit(db, "person", "revoke_link", token, at)


def proof_view(db: Database, token: str, now: datetime, company: str) -> dict:
    row = db.fetchone("SELECT * FROM proof_links WHERE token = ?", (token,))
    status = link_status(row, now)
    if status != "open":
        return {"status": status, "message": expired_message(company)}
    reviewers = db.fetchall("SELECT * FROM proof_reviewers WHERE token = ?", (token,))
    comments = db.fetchall(
        "SELECT * FROM comments WHERE project_id = ? AND version_label = ? ORDER BY created_at",
        (row["project_id"], row["version_label"]),
    )
    return {"status": "open", "link": row, "reviewers": reviewers, "comments": comments}


def submit_proof(
    db: Database,
    token: str,
    *,
    name: str,
    decision: str,
    now: datetime,
    company: str,
    comment: str = "",
    pin_x: float | None = None,
    pin_y: float | None = None,
) -> dict:
    view = proof_view(db, token, now, company)
    if view["status"] != "open":
        return view
    if decision == "approved" and not (name or "").strip():
        return {"status": "open", "error": "Type your name to approve."}
    link = view["link"]
    versions = db.fetchall("SELECT * FROM versions WHERE project_id = ?", (link["project_id"],))
    latest = latest_label(versions)
    if comment:
        db.execute(
            """
            INSERT INTO comments (id, project_id, version_label, author, body, pin_x, pin_y, created_at, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')
            """,
            (new_id(), link["project_id"], link["version_label"], name or "Customer", comment, pin_x, pin_y, now.isoformat()),
        )
    if decision == "changes":
        db.execute(
            "UPDATE approvals SET counts = 0 WHERE project_id = ? AND version_label = ?",
            (link["project_id"], latest),
        )
        db.execute("UPDATE projects SET stage = 'Revisions', waiting_on = 'designer', waiting_since = ? WHERE id = ?", (now.date().isoformat(), link["project_id"]))
        audit(db, name or "customer", "reset_approval", f"{link['project_id']} change request after approval", now.isoformat())
    if decision == "approved":
        counts = 1 if link["version_label"] == latest else 0
        db.execute(
            """
            INSERT INTO approvals (id, project_id, version_label, approver, approved_at, quote, message_id, counts)
            VALUES (?, ?, ?, ?, ?, ?, '', ?)
            """,
            (new_id(), link["project_id"], link["version_label"], name.strip(), now.date().isoformat(), "Approved.", counts),
        )
        if counts:
            db.execute("UPDATE projects SET stage = 'Approved', waiting_on = '', waiting_since = '' WHERE id = ?", (link["project_id"],))
        audit(db, name.strip(), "proof_decision", f"{link['project_id']} {link['version_label']} counts={counts}", now.isoformat())
    if decision in {"approved", "changes"}:
        db.execute(
            "INSERT INTO proof_reviewers (id, token, name, email, decision, decided_at) VALUES (?, ?, ?, '', ?, ?)",
            (new_id(), token, name.strip(), decision, now.isoformat()),
        )
    return {"status": "saved", "decision": decision}


def factory_view(db: Database, token: str, now: datetime, company: str) -> dict:
    row = db.fetchone("SELECT * FROM factory_links WHERE token = ?", (token,))
    status = link_status(row, now)
    if status != "open":
        return {"status": status, "message": expired_message(company)}
    return {"status": "open", "link": row}


def add_factory_event(db: Database, project_id: str, kind: str, body: str, file_name: str, at: str) -> str:
    event_id = new_id()
    db.execute(
        "INSERT INTO factory_events (id, project_id, kind, body, file_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (event_id, project_id, kind, body, file_name, at),
    )
    audit(db, "factory", kind, f"{project_id} {file_name or body[:80]}", at)
    return event_id


def move_factory_event(db: Database, event_id: str, project_id: str, at: str) -> None:
    db.execute("UPDATE factory_events SET project_id = ? WHERE id = ?", (project_id, event_id))
    audit(db, "person", "move_factory_file", f"{event_id} -> {project_id}", at)
