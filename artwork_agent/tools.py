"""Ask-the-agent tools. Answers cite a stored message, file, or version."""

from __future__ import annotations

from artwork_agent.checks import compare_checklist, grounded
from artwork_agent.config import Config
from artwork_agent.db import Database
from artwork_agent.ingest import audit
from artwork_agent.llm import generate
from artwork_agent.matching import find_codes
from artwork_agent.records import project_detail, project_rows, search_messages, timeline

TOOL_NAMES = [
    "list_projects",
    "get_project",
    "get_timeline",
    "get_checklist",
    "get_versions",
    "compare_versions",
    "get_specs",
    "search_messages",
]


def list_projects(db: Database, config: Config) -> list[dict]:
    rows = project_rows(db, config.as_of, config.nudge_days)
    return [
        {
            "id": row["id"],
            "brand": row["brand"],
            "stage": row["stage"],
            "version": row["version"],
            "waiting_on": row.get("waiting_on") or "",
            "days_waiting": row["days_waiting"],
            "ship_date": row.get("ship_date") or "",
            "risk": row["risk"],
            "order_id": row.get("order_id") or "",
        }
        for row in rows
    ]


def answer_question(db: Database, config: Config, question: str, at: str) -> dict:
    steps = ["list_projects()"]
    projects = project_rows(db, config.as_of, int(config.nudge_days))
    by_code = {item["code"]: item for item in projects}
    codes = [code for code in find_codes(question, config.project_code_pattern) if code in by_code]
    lowered = question.lower()
    cited = []
    lines = []
    if "coffee" in lowered and "approv" in lowered:
        for project in projects:
            brand = project["brand"].lower()
            product = (project["specs"].get("product_type") or {}).get("value", "").lower()
            if "coffee" not in brand and "coffee" not in product and "roaster" not in brand:
                continue
            steps.append(f"get_versions(project={project['id']})")
            steps.append(f"get_timeline(project={project['id']})")
            if project["approval_on_latest"] and not project.get("order_id"):
                approval = project["approval_on_latest"][0]
                lines.append(
                    f"{project['brand']} is approved on {project['version']} and is not shipped. "
                    f"Source: {approval.get('message_id')} on {approval.get('approved_at')}, \"{approval.get('quote')}\"."
                )
                cited.append(approval.get("message_id") or project["version"])
            elif not project["approval_on_latest"]:
                lines.append(f"{project['brand']} {project['version']} is not approved. Source: version {project['version']}.")
                cited.append(project["version"])
    elif codes:
        for code in codes:
            project = by_code[code]
            steps.append(f"get_project(project={code})")
            steps.append(f"get_checklist(project={code})")
            lines.append(f"{project['brand']} is {project['stage']} on {project['version']}. Source: {project['id']}.")
            cited.append(project["id"])
    elif "checklist" in lowered or "revision" in lowered:
        for project in projects:
            if project["checklist"]:
                steps.append(f"get_checklist(project={project['id']})")
                for item in project["checklist"]:
                    lines.append(f"{project['brand']}: {item['request']} ({item['status']}). Source: {item.get('message_id') or project['id']}.")
                    cited.append(item.get("message_id") or project["id"])
    else:
        found = search_messages(db, question[:80])
        steps.append("search_messages()")
        if found:
            for item in found[:5]:
                lines.append(f"{item['source']} {item['id']} from {item['sender']}: {item['body']}")
                cited.append(item["id"])
        else:
            lines.append("I can't find that in the stored records.")
    rule = "\n".join(lines) if lines else "I can't find that in the stored records."
    allowed = {item["id"] for item in projects}
    allowed.update(item["code"] for item in projects)
    allowed.update(item["version"] for item in projects)
    for project in projects:
        if project.get("order_id"):
            allowed.add(project["order_id"])
        for message in timeline(db, project["id"]):
            allowed.add(message["id"])
    text = rule
    if config.trial:
        model_text, model_error = generate(config, rule)
        if model_error:
            audit(db, "agent", "skip_answer", model_error, at)
            text = f"{rule}\n\n{model_error}"
        elif model_text and grounded(model_text, allowed):
            text = model_text
        elif model_text:
            audit(db, "agent", "drop_answer", "Answer named a record that is not stored.", at)
    audit(db, "agent", "ask", question[:300], at)
    return {"steps": steps, "answer": text, "sources": [item for item in cited if item]}


def compare(db: Database, config: Config, project_id: str, left: str, right: str, model_items=None) -> dict:
    detail = project_detail(db, project_id, config.as_of, config.nudge_days)
    if not detail:
        return {"error": "I don't see that project."}
    labels = {item["version_label"] for item in detail["versions"]}
    if left not in labels or right not in labels:
        return {"error": "I don't see that version.", "versions": sorted(labels)}
    return {"project_id": project_id, "a": left, "b": right, "items": compare_checklist(detail["checklist"], detail["versions"], right, model_items)}
