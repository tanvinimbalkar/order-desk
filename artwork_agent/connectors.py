"""Optional connectors. Gmail can save drafts. Nothing is sent from this app."""

from __future__ import annotations

from artwork_agent.config import Config
from artwork_agent.crypto import decrypt_token, encrypt_token
from artwork_agent.db import Database
from artwork_agent.ingest import add_message, audit, read_secret, store_secret
from artwork_agent.matching import match_message
from artwork_agent.whatsapp import parse_export, read_export

MAX_BYTES = 25_000_000
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def set_status(db: Database, name: str, enabled: bool, status: str, detail: str, synced: str) -> None:
    db.execute("DELETE FROM connectors WHERE name = ?", (name,))
    db.execute(
        "INSERT INTO connectors (name, enabled, status, detail, last_synced) VALUES (?, ?, ?, ?, ?)",
        (name, 1 if enabled else 0, status, detail[:500], synced),
    )


def _projects(db: Database) -> list[dict]:
    return db.fetchall("SELECT * FROM projects")


def _rules(db: Database) -> list[dict]:
    return db.fetchall("SELECT * FROM match_rules")


def apply_gmail_messages(db: Database, config: Config, rows: list[dict], at: str) -> dict:
    imported = 0
    duplicates = 0
    for row in rows:
        text = f"{row.get('subject') or ''}\n{row.get('body') or ''}"
        decision = match_message(
            text,
            pattern=config.project_code_pattern,
            projects=_projects(db),
            sender_email=row.get("from_email") or "",
            rules=_rules(db),
            threshold=config.confidence_threshold,
        )
        result = add_message(
            db,
            source="email",
            sender=row.get("sender") or row.get("from_email") or "",
            sent_at=row.get("sent_at") or "",
            body=row.get("body") or "",
            subject=row.get("subject") or "",
            external_id=row.get("external_id") or "",
            project_ids=[item["project_id"] for item in decision["links"]],
            reason=decision["links"][0]["reason"] if decision["links"] else "",
            confidence=decision["links"][0]["confidence"] if decision["links"] else None,
            at=at,
        )
        if result["duplicate"]:
            duplicates += 1
        else:
            imported += 1
    return {"imported": imported, "duplicates": duplicates}


def gmail_draft_raw(sender: str, to_addr: str, subject: str, body: str) -> str:
    """RFC822 draft. This string is stored or handed to drafts.create, never send."""
    lines = [
        f"From: {sender}",
        f"To: {to_addr}",
        f"Subject: {subject}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "",
        body,
    ]
    return "\n".join(lines)


def record_drive_file(
    db: Database,
    *,
    project_id: str,
    name: str,
    drive_file_id: str,
    uploaded_at: str,
    uploader: str,
    byte_size: int,
    version_label: str = "",
) -> dict:
    if drive_file_id:
        existing = db.fetchone("SELECT id FROM versions WHERE drive_file_id = ?", (drive_file_id,))
        if existing:
            return {"id": existing["id"], "duplicate": True, "preview_available": 0}
    preview = 1
    note = ""
    lower = name.lower()
    if byte_size and byte_size > MAX_BYTES:
        preview = 0
        note = "Stored metadata only."
    if lower.endswith(".ai"):
        preview = 0
        note = "preview not available"
    if not version_label:
        count = db.fetchone("SELECT COUNT(*) AS n FROM versions WHERE project_id = ?", (project_id,))
        version_label = f"v{int(count['n']) + 1}"
    from artwork_agent.db import new_id

    version_id = new_id()
    db.execute(
        """
        INSERT INTO versions
        (id, project_id, version_label, uploaded_at, uploader, drive_file_id, file_name, preview_path, preview_available, final_for_production, byte_size)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (version_id, project_id, version_label, uploaded_at, uploader, drive_file_id, name, "", preview, byte_size or 0),
    )
    if note and preview == 0:
        db.execute(
            "INSERT INTO related_files (id, project_id, kind, name, drive_file_id, note) VALUES (?, ?, ?, ?, ?, ?)",
            (new_id(), project_id, "artwork", name, drive_file_id, note),
        )
    return {"id": version_id, "duplicate": False, "preview_available": preview, "note": note, "version_label": version_label}


def import_whatsapp(db: Database, config: Config, text: str, at: str) -> dict:
    imported = 0
    duplicates = 0
    for item in parse_export(text):
        decision = match_message(
            item["body"],
            pattern=config.project_code_pattern,
            projects=_projects(db),
            rules=_rules(db),
            threshold=config.confidence_threshold,
        )
        result = add_message(
            db,
            source="whatsapp",
            sender=item["sender"],
            sent_at=item["sent_at"],
            body=item["body"],
            external_id="",
            project_ids=[link["project_id"] for link in decision["links"]],
            reason=decision["links"][0]["reason"] if decision["links"] else "",
            at=at,
        )
        if result["duplicate"]:
            duplicates += 1
        else:
            imported += 1
    set_status(db, "whatsapp", True, "connected", f"{imported} new, {duplicates} already imported", at)
    return {"imported": imported, "duplicates": duplicates}


def import_whatsapp_file(db: Database, config: Config, data: bytes, name: str, at: str) -> dict:
    return import_whatsapp(db, config, read_export(data=data, name=name), at)


def clickup_request(token: str, list_id: str) -> tuple[str, str]:
    """Read-only URL. The method is always GET."""
    url = f"https://api.clickup.com/api/v2/list/{list_id}/task?include_closed=true"
    return "GET", url


def hubspot_request(deal_id: str = "") -> tuple[str, str]:
    if deal_id:
        return "GET", f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
    return "GET", "https://api.hubapi.com/crm/v3/objects/deals"


def sync_clickup(db: Database, config: Config, tasks: list[dict], at: str) -> None:
    enabled = bool((config.connectors.get("clickup") or {}).get("enabled"))
    if not enabled:
        set_status(db, "clickup", False, "off", "Not switched on in the tenant file.", at)
        return
    try:
        for task in tasks:
            decision = match_message(
                f"{task.get('name') or ''}\n{task.get('text') or ''}",
                pattern=config.project_code_pattern,
                projects=_projects(db),
                clickup_task=task.get("id") or "",
                rules=_rules(db),
                threshold=config.confidence_threshold,
            )
            add_message(
                db,
                source="clickup",
                sender=task.get("user") or "ClickUp",
                sent_at=task.get("at") or at,
                body=task.get("text") or task.get("name") or "",
                external_id=f"clickup:{task.get('comment_id') or task.get('id')}",
                project_ids=[item["project_id"] for item in decision["links"]],
                reason=decision["links"][0]["reason"] if decision["links"] else "",
                at=at,
            )
        set_status(db, "clickup", True, "connected", f"{len(tasks)} comments read", at)
    except Exception as exc:
        set_status(db, "clickup", True, "error", str(exc), at)
        audit(db, "agent", "connector_error", f"clickup {exc.__class__.__name__}", at)


def sync_hubspot(db: Database, config: Config, deals: list[dict], at: str) -> None:
    enabled = bool((config.connectors.get("hubspot") or {}).get("enabled"))
    if not enabled:
        set_status(db, "hubspot", False, "off", "Not switched on in the tenant file.", at)
        return
    try:
        for deal in deals:
            decision = match_message(
                deal.get("name") or "",
                pattern=config.project_code_pattern,
                projects=_projects(db),
                hubspot_deal=deal.get("id") or "",
                sender_email=deal.get("email") or "",
                rules=_rules(db),
                threshold=config.confidence_threshold,
            )
            if decision["links"]:
                add_message(
                    db,
                    source="hubspot",
                    sender=deal.get("contact") or "HubSpot",
                    sent_at=deal.get("at") or at,
                    body=deal.get("name") or "",
                    external_id=f"hubspot:{deal.get('id')}",
                    project_ids=[item["project_id"] for item in decision["links"]],
                    reason=decision["links"][0]["reason"],
                    at=at,
                )
        set_status(db, "hubspot", True, "connected", f"{len(deals)} deals read", at)
    except Exception as exc:
        set_status(db, "hubspot", True, "error", str(exc), at)
        audit(db, "agent", "connector_error", f"hubspot {exc.__class__.__name__}", at)


def save_token(db: Database, config: Config, name: str, secret: str) -> None:
    store_secret(db, name, encrypt_token(secret, config.token_key))


def load_token(db: Database, config: Config, name: str) -> str:
    ciphertext = read_secret(db, name)
    if not ciphertext:
        return ""
    return decrypt_token(ciphertext, config.token_key)


def mark_connector(db: Database, name: str, enabled: bool, status: str, detail: str, at: str) -> None:
    set_status(db, name, enabled, status, detail, at)


def gmail_can_send() -> bool:
    """The Gmail connector creates drafts only."""
    return False


def create_gmail_draft(service, sender: str, to_addr: str, subject: str, body: str):
    """Save a Gmail draft. There is no send call on this path."""
    import base64

    raw = gmail_draft_raw(sender, to_addr, subject, body)
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")
    return service.users().drafts().create(userId="me", body={"message": {"raw": encoded}}).execute()
