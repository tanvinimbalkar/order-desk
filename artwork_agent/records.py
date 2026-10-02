"""Read the database into the shapes the brief, tools, and pages use."""

from __future__ import annotations

from artwork_agent.checks import (
    RISK_ORDER,
    approvals_that_count,
    days_between,
    latest_label,
    preflight_gaps,
    risk_for,
    stale_approvals,
)
from artwork_agent.db import Database


def setting(db: Database, key: str, default: str) -> str:
    row = db.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def specs_map(db: Database, project_id: str) -> dict[str, dict]:
    rows = db.fetchall("SELECT field, value, source FROM specs WHERE project_id = ?", (project_id,))
    return {row["field"]: row for row in rows}


def versions_for(db: Database, project_id: str) -> list[dict]:
    return db.fetchall(
        "SELECT * FROM versions WHERE project_id = ? ORDER BY uploaded_at, version_label",
        (project_id,),
    )


def project_rows(db: Database, as_of: str, nudge_days: int) -> list[dict]:
    rows = []
    for project in db.fetchall("SELECT * FROM projects ORDER BY brand"):
        rows.append(project_detail(db, project["id"], as_of, nudge_days))
    rows.sort(key=lambda item: (RISK_ORDER[item["risk"]], -item["days_waiting"], item["id"]))
    return rows


def project_detail(db: Database, project_id: str, as_of: str, nudge_days: int) -> dict:
    project = db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
    if project is None:
        return {}
    versions = versions_for(db, project_id)
    approvals = db.fetchall("SELECT * FROM approvals WHERE project_id = ?", (project_id,))
    checklist = db.fetchall("SELECT * FROM checklist_items WHERE project_id = ?", (project_id,))
    specs = specs_map(db, project_id)
    files = db.fetchall("SELECT * FROM related_files WHERE project_id = ?", (project_id,))
    plain = {key: (value["value"] or "") for key, value in specs.items()}
    has_dieline = any(item["kind"] == "dieline" for item in files) or plain.get("dieline") == "yes"
    gaps = preflight_gaps(plain, versions, approvals, has_dieline)
    conflicts = [item for item in checklist if item["status"] == "needs_human"]
    days = days_between(project.get("waiting_since") or "", as_of) if project.get("waiting_on") else 0
    latest = latest_label(versions)
    return {
        **project,
        "versions": versions,
        "approvals": approvals,
        "checklist": checklist,
        "specs": specs,
        "files": files,
        "gaps": gaps,
        "conflicts": conflicts,
        "days_waiting": days,
        "version": latest,
        "risk": risk_for(project["stage"], days, gaps, bool(conflicts), nudge_days),
        "approval_on_latest": approvals_that_count(approvals, latest),
        "stale": stale_approvals(approvals, latest),
    }


def timeline(db: Database, project_id: str) -> list[dict]:
    rows = []
    linked = db.fetchall(
        """
        SELECT messages.* FROM messages
        JOIN message_links ON message_links.message_id = messages.id
        WHERE message_links.project_id = ?
        """,
        (project_id,),
    )
    for item in linked:
        rows.append(
            {
                "at": item["sent_at"] or "",
                "source": item["source"],
                "who": item["sender"] or "",
                "text": item["body"] or "",
                "original": item["original_body"] or "",
                "translation": item["translation"] or "",
                "id": item["id"],
                "unclear": bool(item["unclear"]),
                "kind": "message",
            }
        )
    for item in db.fetchall("SELECT * FROM comments WHERE project_id = ?", (project_id,)):
        rows.append(
            {
                "at": item["created_at"] or "",
                "source": "proof",
                "who": item["author"] or "",
                "text": item["body"] or "",
                "original": "",
                "translation": "",
                "id": item["id"],
                "unclear": False,
                "kind": "comment",
                "pin_x": item["pin_x"],
                "pin_y": item["pin_y"],
            }
        )
    for item in db.fetchall("SELECT * FROM factory_events WHERE project_id = ?", (project_id,)):
        rows.append(
            {
                "at": item["created_at"] or "",
                "source": "factory",
                "who": "Factory",
                "text": item["body"] or item["file_name"] or "",
                "original": "",
                "translation": "",
                "id": item["id"],
                "unclear": False,
                "kind": item["kind"],
            }
        )
    rows.sort(key=lambda item: item["at"])
    return rows


def search_messages(db: Database, query: str) -> list[dict]:
    needle = f"%{query.strip()}%"
    return db.fetchall(
        "SELECT id, source, sender, sent_at, subject, body FROM messages WHERE body LIKE ? OR subject LIKE ? ORDER BY sent_at",
        (needle, needle),
    )
