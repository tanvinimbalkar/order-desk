"""Morning brief and draft templates. The model may write only a short summary."""

from __future__ import annotations

from artwork_agent.checks import grounded
from artwork_agent.config import Config
from artwork_agent.db import Database, new_id
from artwork_agent.ingest import audit
from artwork_agent.llm import generate
from artwork_agent.records import project_rows, setting

WAITING = {
    "customer": "customer",
    "designer": "designer",
    "factory": "factory",
    "us": "us",
    "human": "a person",
}


def waiting_phrase(code: str | None) -> str:
    who = WAITING.get(code or "", "a person")
    if who.startswith("a "):
        return who
    return f"the {who}"


def summary_sentence(projects: list[dict]) -> str:
    stuck = [item for item in projects if item["risk"] != "green"]
    if not stuck:
        return "Nothing needs attention today."
    first = stuck[0]
    who = waiting_phrase(first.get("waiting_on"))
    return (
        f"{len(stuck)} artwork projects are stuck. "
        f"{first['brand']} is waiting on {who} for {first['days_waiting']} days."
    )


def _draft(project: dict, company: str) -> dict | None:
    latest = project["version"] or "the latest version"
    brand = project["brand"]
    if project["conflicts"]:
        quotes = []
        for item in project["checklist"]:
            if item["status"] == "needs_human":
                quotes.append(item["request"])
        body = (
            f"Hello,\n\n{brand} needs a human decision. Do not choose a finish for the customer.\n\n"
            + "\n".join(quotes)
            + f"\n\nCurrent file: {latest}.\nShip date: {project.get('ship_date') or ''}.\n\nThank you,\n{company}"
        )
        return {"issue": "Needs human decision", "subject": f"Needs human decision: {brand}", "body": body, "to": "team"}
    if project["stale"]:
        old = project["stale"][0]
        body = (
            f"Hello {old.get('approver') or ''},\n\n"
            f"The approval on {old.get('version_label')} does not cover {latest}.\n"
            f"Quote on file: \"{old.get('quote') or ''}\"\n\n"
            f"Please approve {latest} or tell us to hold it.\n\nThank you,\n{company}"
        )
        return {"issue": "Approval on old version", "subject": f"Please approve {latest}: {brand}", "body": body, "to": "customer"}
    if project["approval_on_latest"] and any(item in project["gaps"] for item in ("Pantone colors", "quantity", "dieline", "final files")):
        missing = ", ".join(item for item in project["gaps"] if item != "approval")
        body = (
            f"Hello {project.get('customer_name') or ''},\n\n"
            f"{brand} {latest} is approved, and we still need {missing} before the factory can start.\n"
            f"Ship date on file: {project.get('ship_date') or ''}.\n\nThank you,\n{company}"
        )
        return {"issue": "Missing spec", "subject": f"Missing details for {brand}", "body": body, "to": project.get("customer_email") or "customer"}
    open_items = [item for item in project["checklist"] if item["status"] == "not_done"]
    if open_items:
        item = open_items[0]
        body = (
            f"Hello,\n\n{brand} {latest} does not include this request yet:\n\"{item['request']}\"\n"
            f"Source: {item.get('message_id') or 'the message log'}.\n\nThank you,\n{company}"
        )
        return {"issue": "Revision requested", "subject": f"Revision still open: {brand}", "body": body, "to": "designer"}
    if not project["approval_on_latest"] and project["risk"] != "green":
        body = (
            f"Hello {project.get('customer_name') or ''},\n\n"
            f"Please approve {brand} {latest}.\n"
            f"This has been waiting {project['days_waiting']} days.\n"
            f"Ship date: {project.get('ship_date') or ''}.\n\nThank you,\n{company}"
        )
        return {"issue": project["stage"], "subject": f"Approval needed: {brand} {latest}", "body": body, "to": project.get("customer_email") or "customer"}
    return None


def factory_pack(project: dict, company: str) -> dict:
    gaps = [item for item in project["gaps"] if item != "final files" or not any(v.get("final_for_production") for v in project["versions"])]
    if project["gaps"]:
        question = _draft(project, company)
        return {"ready": False, "gaps": project["gaps"], "english": "", "chinese": "", "question": question}
    latest = project["version"]
    approval = project["approval_on_latest"][0]
    specs = project["specs"]
    quantity = specs.get("quantity", {}).get("value") or ""
    pantone = specs.get("pantone", {}).get("value") or ""
    finish = specs.get("finish", {}).get("value") or ""
    material = specs.get("material", {}).get("value") or ""
    size = specs.get("size", {}).get("value") or ""
    product = specs.get("product_type", {}).get("value") or ""
    english = (
        f"Hello,\n\nPlease produce {project['brand']}, {product}, {size}.\n"
        f"Material: {material}. Finish: {finish}. Quantity: {quantity}.\n"
        f"Pantone: {pantone}. Dieline: on file.\n"
        f"Final artwork: {latest}, approved {approval.get('approved_at') or ''}.\n"
        f"Ship date: {project.get('ship_date') or ''}.\n"
        f"Order: {project.get('order_id') or 'not linked'}.\n\nThank you,\n{company}"
    )
    chinese = (
        f"您好，\n\n请按以下规格生产 {project['brand']}（{product}，{size}）。\n"
        f"材质：{material}。表面：{finish}。数量：{quantity}。\n"
        f"潘通色：{pantone}。刀版：已附。\n"
        f"最终稿：{latest}，确认日期 {approval.get('approved_at') or ''}。\n"
        f"出货日：{project.get('ship_date') or ''}。\n"
        f"订单：{project.get('order_id') or '未关联'}。\n\n谢谢，\n{company}"
    )
    return {"ready": True, "gaps": [], "english": english, "chinese": chinese, "question": None}


def build_brief(db: Database, config: Config, at: str, sleep=None) -> dict:
    db.execute("DELETE FROM actions WHERE kind = 'draft' AND status = 'proposed'")
    nudge = int(setting(db, "nudge_days", str(config.nudge_days)))
    as_of = config.as_of or at[:10]
    projects = project_rows(db, as_of, nudge)
    rule = summary_sentence(projects)
    allowed = set()
    for project in projects:
        allowed.add(project["code"])
        allowed.add(project["id"])
        allowed.add(project["version"])
        if project.get("order_id"):
            allowed.add(project["order_id"])
    model_text = None
    model_error = None
    if config.trial:
        model_text, model_error = generate(config, f"Write one sentence: {rule}", sleep=sleep or (lambda _seconds: None))
        if model_error:
            audit(db, "agent", "skip_summary", model_error, at)
        elif model_text and not grounded(model_text, allowed):
            audit(db, "agent", "drop_summary", "Model summary named a record that is not stored.", at)
            model_text = None
    summary = model_text or rule
    drafts = []
    for project in projects:
        if project["risk"] == "green":
            audit(db, "agent", "healthy", project["id"], at)
            continue
        draft = _draft(project, config.company_name)
        if draft is None:
            continue
        action_id = new_id()
        db.execute(
            """
            INSERT INTO actions (id, project_id, kind, status, to_addr, subject, body, issue, created_at)
            VALUES (?, ?, 'draft', 'proposed', ?, ?, ?, ?, ?)
            """,
            (action_id, project["id"], draft["to"], draft["subject"], draft["body"], draft["issue"], at),
        )
        audit(db, "agent", "draft", f"{project['id']} {draft['issue']}", at)
        drafts.append({"id": action_id, "project_id": project["id"], "brand": project["brand"], **draft, "status": "proposed"})
    connectors = db.fetchall("SELECT name, status, detail FROM connectors WHERE status = 'error'")
    lines = [summary]
    for item in connectors:
        lines.append(f"{item['name']} needs attention: {item['detail']}")
    if model_error:
        lines.append(model_error)
    for project in projects:
        if project["risk"] == "green":
            continue
        who = waiting_phrase(project.get("waiting_on"))
        lines.append(f"{project['brand']} is waiting on {who}. Ship date {project.get('ship_date') or 'not set'}.")
    body = "\n".join(lines)
    if not any(item["risk"] != "green" for item in projects):
        body = "Nothing needs attention today."
        summary = body
    brief_id = new_id()
    db.execute(
        "INSERT INTO briefs (id, created_at, summary, body) VALUES (?, ?, ?, ?)",
        (brief_id, at, summary, body),
    )
    audit(db, "agent", "brief", brief_id, at)
    return {"id": brief_id, "summary": summary, "body": body, "drafts": drafts, "projects": projects, "connectors": connectors}


def latest_brief(db: Database) -> dict | None:
    return db.fetchone("SELECT * FROM briefs ORDER BY created_at DESC LIMIT 1")


def save_as_draft(db: Database, action_id: str, at: str) -> dict:
    """Mark a proposed note as a saved draft. This never sends mail."""
    row = db.fetchone("SELECT * FROM actions WHERE id = ?", (action_id,))
    if row is None:
        return {"error": "I don't see that draft."}
    db.execute("UPDATE actions SET status = 'draft_saved' WHERE id = ?", (action_id,))
    audit(db, "person", "save_draft", action_id, at)
    return {"id": action_id, "status": "draft_saved", "sent": False}
