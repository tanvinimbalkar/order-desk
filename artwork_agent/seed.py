"""Load the fictional Linden Supply book into the same tables a trial uses."""

from __future__ import annotations

import json
from pathlib import Path

from artwork_agent.briefing import build_brief
from artwork_agent.config import ROOT, Config
from artwork_agent.db import Database, wipe
from artwork_agent.ingest import add_message

ART = ROOT / "data" / "artwork"
STAGE = {
    "Waiting on customer": "Proof sent",
    "Approval on old version": "Revisions",
    "Revision requested": "Revisions",
    "Missing spec": "Approved",
    "Needs human decision": "Revisions",
    "Handed off": "In production",
}
CUSTOMERS = {
    "RC-01": ("Ava Cole", "ava@ridgeline.example", "ridgeline.example", ""),
    "CK-01": ("Noah Patel", "noah@copperkettle.example", "copperkettle.example", ""),
    "BB-01": ("Lila Berg", "lila@bloombakery.example", "bloombakery.example", ""),
    "NF-01": ("Elena Brooks", "elena@northfork.example", "northfork.example", ""),
    "SS-01": ("Jordan Lee", "jordan@solsnacks.example", "solsnacks.example", "+15555550198"),
    "PA-01": ("Chris Hale", "chris@pineandash.example", "pineandash.example", ""),
}


def seed_demo(db: Database, config: Config, force: bool = False) -> None:
    existing = db.fetchone("SELECT id FROM projects LIMIT 1")
    if existing and not force:
        return
    if force:
        wipe(db)
    people = json.loads((ART / "people.json").read_text(encoding="utf-8"))
    projects = json.loads((ART / "projects.json").read_text(encoding="utf-8"))
    at = f"{config.as_of}T08:00:00"
    for person in (people["account_manager"], people["designer"], people["production"]):
        db.execute(
            "INSERT INTO team (email, name, password_hash, role) VALUES (?, ?, '', ?)",
            (person["email"], person["name"], person["role"]),
        )
    for project in projects:
        name, email, domain, phone = CUSTOMERS[project["id"]]
        db.execute(
            """
            INSERT INTO projects
            (id, code, brand, stage, waiting_on, waiting_since, ship_date, customer_name, customer_email,
             customer_domain, customer_phone, drive_folder, clickup_task, hubspot_deal, order_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?)
            """,
            (
                project["id"],
                project["id"],
                project["brand"],
                STAGE.get(project["stage"], "New"),
                project.get("waiting_on") or "",
                project.get("waiting_since") or "",
                project.get("ship_date") or "",
                name,
                email,
                domain,
                phone,
                project["brand"],
                project.get("order_id") or "",
            ),
        )
        specs = {
            "product_type": project.get("product_type") or "",
            "size": project.get("size") or "",
            "material": project.get("material") or "",
            "finish": project.get("finish") or "",
            "pantone": ", ".join(project.get("pantone") or []),
            "quantity": "" if project.get("quantity") is None else str(project["quantity"]),
            "ship_date": project.get("ship_date") or "",
            "dieline": "yes" if project.get("dieline") else "",
        }
        source = project["messages"][0]["id"] if project["messages"] else "seed"
        for field, value in specs.items():
            db.execute(
                "INSERT INTO specs (project_id, field, value, source) VALUES (?, ?, ?, ?)",
                (project["id"], field, value, source),
            )
        if project.get("dieline"):
            db.execute(
                "INSERT INTO related_files (id, project_id, kind, name, drive_file_id, note) VALUES (?, ?, 'dieline', ?, '', 'on file')",
                (f"{project['id']}-dieline", project["id"], f"{project['brand']} dieline"),
            )
        for version in project["versions"]:
            final = 1 if project["id"] == "PA-01" and version["id"] == project["versions"][-1]["id"] else 0
            preview = str(ART / version["file"])
            db.execute(
                """
                INSERT INTO versions
                (id, project_id, version_label, uploaded_at, uploader, drive_file_id, file_name, preview_path,
                 preview_available, final_for_production, byte_size)
                VALUES (?, ?, ?, ?, 'Leo', ?, ?, ?, 1, ?, 0)
                """,
                (
                    f"{project['id']}-{version['id']}",
                    project["id"],
                    version["id"],
                    version["uploaded"],
                    f"drive-{project['id']}-{version['id']}",
                    Path(version["file"]).name,
                    preview,
                    final,
                ),
            )
        for item in project.get("checklist") or []:
            status = "done" if item.get("done_in") else "not_done"
            db.execute(
                "INSERT INTO checklist_items (id, project_id, request, status, done_in, message_id) VALUES (?, ?, ?, ?, ?, ?)",
                (item["id"], project["id"], item["request"], status, item.get("done_in"), item.get("message_id")),
            )
        for index, item in enumerate(project.get("conflicts") or [], start=1):
            db.execute(
                "INSERT INTO checklist_items (id, project_id, request, status, done_in, message_id) VALUES (?, ?, ?, 'needs_human', '', ?)",
                (
                    f"{project['id']}-conflict-{index}",
                    project["id"],
                    f"{item['contact']}: \"{item['quote']}\"",
                    item.get("message_id") or "",
                ),
            )
        for approval in project.get("approvals") or []:
            db.execute(
                """
                INSERT INTO approvals (id, project_id, version_label, approver, approved_at, quote, message_id, counts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{project['id']}-{approval['version']}",
                    project["id"],
                    approval["version"],
                    approval.get("from") or "",
                    approval.get("at") or "",
                    approval.get("quote") or "",
                    approval.get("message_id") or "",
                    1 if approval.get("counts") else 0,
                ),
            )
        for message in project["messages"]:
            add_message(
                db,
                source=message["source"],
                sender=message.get("from") or "",
                sent_at=message.get("at") or "",
                body=message.get("text") or "",
                external_id=message["id"],
                project_ids=[project["id"]],
                reason="seed",
                confidence=1,
                at=at,
                message_id=message["id"],
            )
            if message["source"] == "wetransfer":
                db.execute(
                    "INSERT INTO related_files (id, project_id, kind, name, drive_file_id, note) VALUES (?, ?, 'wetransfer', ?, '', 'files received via WeTransfer')",
                    (f"{message['id']}-wt", project["id"], message["id"]),
                )
    add_message(
        db,
        source="factory",
        sender="Mr. Chen",
        sent_at="2026-09-12T18:00:00",
        body="已收到最终稿 v2，开始生产。",
        original_body="已收到最终稿 v2，开始生产。",
        translation="Final v2 received. Production has started.",
        external_id="pa-zh",
        project_ids=["PA-01"],
        reason="seed",
        at=at,
        message_id="pa-zh",
    )
    defaults = {
        "confidence_threshold": str(config.confidence_threshold),
        "nudge_days": str(config.nudge_days),
        "brief_time": config.brief_time,
        "timezone": config.timezone,
        "retention_days": str(config.retention_days),
        "code_pattern": config.project_code_pattern,
        "minutes_per_issue": str(config.minutes_per_issue),
        "minutes_per_draft": str(config.minutes_per_draft),
        "minutes_per_proof": str(config.minutes_per_proof),
    }
    for key, value in defaults.items():
        db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))
    for name in ("gmail", "drive", "whatsapp", "clickup", "hubspot"):
        db.execute(
            "INSERT INTO connectors (name, enabled, status, detail, last_synced) VALUES (?, 0, 'off', 'Demo mode does not connect to live tools.', ?)",
            (name, at),
        )
    build_brief(db, config, at)
    db.commit()
