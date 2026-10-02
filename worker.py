"""Morning sync. Streamlit does not run this; a cron job does."""

from __future__ import annotations

import smtplib
from datetime import datetime
from email.message import EmailMessage

from artwork_agent.briefing import build_brief
from artwork_agent.config import load_config
from artwork_agent.connectors import mark_connector
from artwork_agent.db import new_id, open_database
from artwork_agent.ingest import audit
from artwork_agent.seed import seed_demo


def deliver_brief(db, config, brief, at: str) -> str:
    """Save the morning note as a draft, or send it through the company's own SMTP."""
    if config.mode == "trial" and config.brief_delivery == "smtp" and config.smtp_host:
        message = EmailMessage()
        message["From"] = config.brief_sender
        team = db.fetchall("SELECT email FROM team")
        message["To"] = ", ".join(row["email"] for row in team) or config.brief_sender
        message["Subject"] = f"{config.company_name} morning brief"
        message.set_content(brief["body"])
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=20) as client:
            client.starttls()
            if config.smtp_user:
                client.login(config.smtp_user, config.smtp_password)
            client.send_message(message)
        audit(db, "worker", "brief_email", brief["id"], at)
        return "email"
    db.execute(
        """
        INSERT INTO actions (id, project_id, kind, status, to_addr, subject, body, issue, created_at)
        VALUES (?, '', 'brief', 'draft_saved', ?, ?, ?, 'Morning brief', ?)
        """,
        (new_id(), config.brief_sender, f"{config.company_name} morning brief", brief["body"], at),
    )
    audit(db, "worker", "brief_draft", brief["id"], at)
    return "draft"


def note_connector_health(db, config, at: str) -> None:
    if config.mode != "trial":
        return
    from artwork_agent.ingest import read_secret

    for name, options in (config.connectors or {}).items():
        enabled = bool((options or {}).get("enabled"))
        if not enabled:
            mark_connector(db, name, False, "off", "Switched off in the tenant file.", at)
            continue
        if name == "whatsapp":
            mark_connector(db, name, True, "connected", "Upload a chat export. Re-uploads skip messages already stored.", at)
            continue
        if not read_secret(db, name):
            mark_connector(
                db,
                name,
                True,
                "error",
                "Token missing or expired. Reconnect this tool in Settings. Other connectors still run.",
                at,
            )
            continue
        mark_connector(db, name, True, "connected", "Token stored.", at)


def run_once(config=None) -> dict:
    config = config or load_config()
    db = open_database(config)
    if config.mode == "demo":
        seed_demo(db, config)
    at = datetime.now().replace(microsecond=0).isoformat()
    note_connector_health(db, config, at)
    brief = build_brief(db, config, at)
    brief["delivery"] = deliver_brief(db, config, brief, at)
    db.commit()
    return brief


def main() -> None:
    brief = run_once()
    print(brief["summary"])
    print(brief["delivery"])


if __name__ == "__main__":
    main()
