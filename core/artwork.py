"""Artwork, proof, and factory-handoff rules. Figures come only from the JSON book."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from core.models import pretty_date

ROOT = Path(__file__).resolve().parents[1]
ART_DIR = ROOT / "data" / "artwork"
CACHE_PATH = ROOT / "data" / "cache" / "artwork.json"

SOURCE_LABELS = {
    "email": "Email",
    "whatsapp": "WhatsApp",
    "text": "Text",
    "clickup": "ClickUp",
    "wetransfer": "WeTransfer",
}

WAITING_LABELS = {
    "customer": "Customer",
    "designer": "Designer",
    "factory": "Factory",
    "human": "Human",
}

RISK_ORDER = {"red": 0, "yellow": 1, "green": 2}


def load_people() -> dict:
    return json.loads((ART_DIR / "people.json").read_text(encoding="utf-8"))


def load_projects() -> list[dict]:
    return json.loads((ART_DIR / "projects.json").read_text(encoding="utf-8"))


def as_of_date() -> date:
    return date.fromisoformat(load_people()["as_of"])


def normalize_workspace(value: object) -> str:
    """Unknown or missing workspace values stay on Orders & Shipments."""
    if value == "artwork":
        return "artwork"
    return "orders"


def project_by_id(project_id: str) -> dict | None:
    needle = (project_id or "").strip().lower()
    for project in load_projects():
        if project["id"].lower() == needle or project["brand"].lower() == needle:
            return project
    for project in load_projects():
        if needle and needle in project["brand"].lower():
            return project
    return None


def latest_version(project: dict) -> dict:
    return project["versions"][-1]


def version_index(project: dict, version_id: str) -> int | None:
    for index, version in enumerate(project["versions"]):
        if version["id"] == version_id:
            return index
    return None


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def approvals_that_count(project: dict) -> list[dict]:
    return [item for item in project["approvals"] if item.get("counts")]


def approval_on_latest(project: dict) -> dict | None:
    latest = latest_version(project)["id"]
    for item in approvals_that_count(project):
        if item["version"] == latest:
            return item
    return None


def stale_approvals(project: dict) -> list[dict]:
    latest = latest_version(project)["id"]
    return [item for item in approvals_that_count(project) if item["version"] != latest]


def vague_messages(project: dict) -> list[dict]:
    return [item for item in project["messages"] if item.get("unclear")]


def days_waiting(project: dict, today: date | None = None) -> int:
    if project["stage"] == "Handed off" or not project.get("waiting_since"):
        return 0
    start = _parse_day(project["waiting_since"])
    if start is None:
        return 0
    return max(0, ((today or as_of_date()) - start).days)


def risk_for(project: dict) -> str:
    """Green is healthy, yellow is waiting, red needs a person before anyone proceeds."""
    if project["conflicts"] or stale_approvals(project):
        return "red"
    if project["stage"] == "Needs human decision":
        return "red"
    if project["stage"] == "Handed off" and not preflight_gaps(project):
        return "green"
    if project["stage"] in {"Missing spec", "Approval on old version"}:
        return "red"
    if days_waiting(project) >= 5 or project["stage"] == "Revision requested":
        return "yellow"
    if project["stage"] == "Waiting on customer":
        return "yellow"
    return "green"


def message_by_id(project: dict, message_id: str) -> dict | None:
    return next((item for item in project["messages"] if item["id"] == message_id), None)


def sorted_messages(project: dict) -> list[dict]:
    return sorted(project["messages"], key=lambda item: item["at"])


def activity_line(project: dict) -> str:
    if not project["messages"]:
        return "No activity yet."
    return ""


def checklist_rows(project: dict) -> list[dict]:
    rows = []
    for item in project["checklist"]:
        done_in = item.get("done_in")
        rows.append(
            {
                "id": item["id"],
                "request": item["request"],
                "message_id": item["message_id"],
                "done_in": done_in,
                "status": f"done in {done_in}" if done_in else "not done",
            }
        )
    return rows


def preflight_gaps(project: dict) -> list[str]:
    gaps = []
    if not project.get("pantone"):
        gaps.append("Pantone colors")
    if not project.get("quantity"):
        gaps.append("quantity")
    if not project.get("dieline"):
        gaps.append("dieline")
    if approval_on_latest(project) is None:
        if stale_approvals(project):
            gaps.append("approval not on latest version")
        else:
            gaps.append("approval")
    return gaps


def handoff_projects() -> list[dict]:
    """Projects with an approval on file, including approvals that are no longer current."""
    found = []
    for project in load_projects():
        if approvals_that_count(project) or project["stage"] == "Handed off":
            found.append(project)
    return found


def ready_for_factory(project: dict) -> bool:
    return not preflight_gaps(project)


def stuck_projects() -> list[dict]:
    found = [project for project in load_projects() if risk_for(project) != "green"]
    return sorted(found, key=lambda project: (RISK_ORDER[risk_for(project)], -days_waiting(project), project["id"]))


def draft_for(project: dict) -> dict:
    """Template note filled only with fields already stored on the project."""
    people = load_people()
    latest = latest_version(project)
    brand = project["brand"]
    if project["conflicts"]:
        quotes = "\n".join(
            f"{item['contact']} by {SOURCE_LABELS.get(item['source'], item['source'])}: \"{item['quote']}\""
            for item in project["conflicts"]
        )
        body = (
            f"Hello {people['account_manager']['name']},\n\n"
            f"{brand} needs a human decision. Do not choose a finish for the customer.\n\n"
            f"{quotes}\n\n"
            f"Current file: {latest['id']}, uploaded {pretty_date(_parse_day(latest['uploaded']))}.\n"
            f"Ship date: {pretty_date(_parse_day(project['ship_date']))}.\n\n"
            "Thank you,\nOrder Desk\nLinden Supply"
        )
        return {
            "key": project["id"],
            "to": people["account_manager"]["email"],
            "subject": f"Needs human decision: {brand}",
            "body": body,
            "flag": "Needs human decision",
        }
    if stale_approvals(project):
        old = stale_approvals(project)[0]
        body = (
            f"Hello {old['from']},\n\n"
            f"The approval on {old['version']} ({pretty_date(_parse_day(old['at']))}) "
            f"does not cover {latest['id']}, uploaded {pretty_date(_parse_day(latest['uploaded']))}.\n\n"
            f"Please approve {latest['id']} or tell us to hold it.\n"
            f"Quote on file: \"{old['quote']}\"\n\n"
            "Thank you,\nMia\nLinden Supply"
        )
        return {
            "key": project["id"],
            "to": "customer",
            "subject": f"Please approve {latest['id']}: {brand}",
            "body": body,
            "flag": "Approval on old version",
        }
    gaps = preflight_gaps(project)
    if approval_on_latest(project) and gaps:
        missing = ", ".join(gaps)
        approved = approval_on_latest(project)
        greeting = f"Hello {approved['from']}," if approved and approved.get("from") else "Hello,"
        body = (
            f"{greeting}\n\n"
            f"{brand} {latest['id']} is approved, and we still need {missing} before the factory can start.\n"
            f"Ship date on file: {pretty_date(_parse_day(project['ship_date']))}.\n\n"
            "Thank you,\nPriya\nLinden Supply"
        )
        return {
            "key": project["id"],
            "to": "customer",
            "subject": f"Missing details for {brand}",
            "body": body,
            "flag": "Missing spec",
        }
    open_items = [row for row in checklist_rows(project) if row["done_in"] is None]
    if open_items:
        request = open_items[0]
        source = message_by_id(project, request["message_id"])
        spoken = source["text"] if source else request["request"]
        body = (
            f"Hello {people['designer']['name']},\n\n"
            f"{brand} {latest['id']} does not include this request yet:\n"
            f"\"{spoken}\"\n\n"
            f"Source: {source['id'] if source else request['message_id']}.\n\n"
            "Thank you,\nMia\nLinden Supply"
        )
        return {
            "key": project["id"],
            "to": people["designer"]["email"],
            "subject": f"Revision still open: {brand}",
            "body": body,
            "flag": "Revision requested",
        }
    body = (
        f"Hello,\n\n"
        f"Please approve {brand} {latest['id']}, uploaded {pretty_date(_parse_day(latest['uploaded']))}.\n"
        f"This has been waiting {days_waiting(project)} days.\n"
        f"Ship date: {pretty_date(_parse_day(project['ship_date']))}.\n\n"
        "Thank you,\nMia\nLinden Supply"
    )
    return {
        "key": project["id"],
        "to": "customer",
        "subject": f"Approval needed: {brand} {latest['id']}",
        "body": body,
        "flag": project["stage"],
    }


def factory_draft(project: dict) -> dict:
    gaps = preflight_gaps(project)
    if gaps:
        question = draft_for(project)
        return {"ready": False, "gaps": gaps, "question": question, "english": "", "chinese": ""}
    people = load_people()
    latest = latest_version(project)
    approval = approval_on_latest(project)
    pantone = ", ".join(project["pantone"])
    quantity = f"{project['quantity']:,}"
    english = (
        f"Hello {people['factory']['name']},\n\n"
        f"Please produce {project['brand']}, {project['product_type']}, {project['size']}.\n"
        f"Material: {project['material']}. Finish: {project['finish']}. Quantity: {quantity}.\n"
        f"Pantone: {pantone}. Dieline: on file.\n"
        f"Final artwork: {latest['id']}, uploaded {pretty_date(_parse_day(latest['uploaded']))}, "
        f"approved {pretty_date(_parse_day(approval['at']))}.\n"
        f"Ship date: {pretty_date(_parse_day(project['ship_date']))}.\n"
        f"Order: {project['order_id']}.\n\n"
        f"Thank you,\n{people['production']['name']}\nLinden Supply"
    )
    chinese = (
        f"{people['factory']['name']}您好，\n\n"
        f"请按以下规格生产 {project['brand']}（{project['product_type']}，{project['size']}）。\n"
        f"材质：{project['material']}。表面：{project['finish']}。数量：{quantity}。\n"
        f"潘通色：{pantone}。刀版：已附。\n"
        f"最终稿：{latest['id']}，上传日期 {latest['uploaded']}，确认日期 {approval['at']}。\n"
        f"出货日：{project['ship_date']}。\n"
        f"订单：{project['order_id']}。\n\n"
        f"谢谢，\n{people['production']['name']}\nLinden Supply"
    )
    return {"ready": True, "gaps": [], "question": None, "english": english, "chinese": chinese}


def summary_for(projects: list[dict]) -> str:
    stuck = [project for project in projects if risk_for(project) != "green"]
    stuck.sort(key=lambda project: (RISK_ORDER[risk_for(project)], -days_waiting(project), project["id"]))
    if not stuck:
        return "Nothing needs attention today."
    first = stuck[0]
    who = WAITING_LABELS.get(first["waiting_on"] or "", "no one")
    return (
        f"{len(stuck)} artwork projects are stuck. "
        f"{first['brand']} is waiting on the {who.lower()} for {days_waiting(first)} days."
    )


def rule_summary() -> str:
    return summary_for(load_projects())


def rule_compare(project: dict, left: str, right: str) -> list[dict]:
    right_index = version_index(project, right)
    rows = []
    for item in checklist_rows(project):
        done_in = item["done_in"]
        done_index = version_index(project, done_in) if done_in else None
        if done_index is not None and right_index is not None and done_index <= right_index:
            status = "done"
            reason = f"Present in {done_in}."
        elif done_in is None:
            status = "not_done"
            reason = "Not on the later version."
        else:
            status = "not_done"
            reason = f"Marked for {done_in}, which is not in this pair."
        rows.append(
            {
                "id": item["id"],
                "request": item["request"],
                "status": status,
                "reason": reason,
                "message_id": item["message_id"],
            }
        )
    return rows


def _numbers_in(text: str) -> list[str]:
    return re.findall(r"\d[\d,]*(?:\.\d+)?", text)


def reason_is_grounded(reason: str, project: dict) -> bool:
    blob = json.dumps(project)
    return all(number in blob for number in _numbers_in(reason))


def compare_versions(project_id: str, left: str, right: str, model_items: list[dict] | None = None) -> dict:
    project = project_by_id(project_id)
    if project is None:
        return {"error": "I don't see that project.", "projects": [item["id"] for item in load_projects()]}
    known = {item["id"] for item in project["versions"]}
    if left not in known or right not in known:
        return {"error": "I don't see that version.", "versions": [item["id"] for item in project["versions"]]}
    rules = rule_compare(project, left, right)
    if not model_items:
        return {"project_id": project["id"], "a": left, "b": right, "items": rules, "source": "rules"}
    by_id = {item["id"]: item for item in rules}
    clean = []
    for raw in model_items:
        item_id = str(raw.get("id") or "")
        if item_id not in by_id:
            continue
        status = raw.get("status")
        if status not in {"done", "not_done", "unclear"}:
            continue
        reason = str(raw.get("reason") or "")
        if raw.get("confidence") == "low" or not reason_is_grounded(reason, project):
            status = "unclear"
            reason = "unclear, check manually."
        clean.append(
            {
                "id": item_id,
                "request": by_id[item_id]["request"],
                "status": status,
                "reason": reason,
                "message_id": by_id[item_id]["message_id"],
            }
        )
    seen = {item["id"] for item in clean}
    for item in rules:
        if item["id"] not in seen:
            clean.append(item)
    return {"project_id": project["id"], "a": left, "b": right, "items": clean, "source": "vision"}


def project_summary(project: dict) -> dict:
    latest = latest_version(project)
    return {
        "id": project["id"],
        "brand": project["brand"],
        "stage": project["stage"],
        "version": latest["id"],
        "waiting_on": WAITING_LABELS.get(project["waiting_on"] or "", "—"),
        "days_waiting": days_waiting(project),
        "ship_date": project["ship_date"],
        "risk": risk_for(project),
        "order_id": project.get("order_id"),
        "flag": "Needs human decision" if project["conflicts"] else project["stage"],
    }


def get_artwork_projects() -> dict:
    return {"as_of": load_people()["as_of"], "projects": [project_summary(item) for item in load_projects()]}


def get_messages(project_id: str) -> dict:
    project = project_by_id(project_id)
    if project is None:
        return {"error": "I don't see that project.", "projects": [item["id"] for item in load_projects()]}
    if not project["messages"]:
        return {"project_id": project["id"], "brand": project["brand"], "messages": [], "note": "No activity yet."}
    return {
        "project_id": project["id"],
        "brand": project["brand"],
        "messages": sorted_messages(project),
    }


def get_checklist(project_id: str) -> dict:
    project = project_by_id(project_id)
    if project is None:
        return {"error": "I don't see that project.", "projects": [item["id"] for item in load_projects()]}
    return {"project_id": project["id"], "brand": project["brand"], "checklist": checklist_rows(project)}


def get_versions(project_id: str) -> dict:
    project = project_by_id(project_id)
    if project is None:
        return {"error": "I don't see that project.", "projects": [item["id"] for item in load_projects()]}
    return {
        "project_id": project["id"],
        "brand": project["brand"],
        "versions": [
            {"id": item["id"], "uploaded": item["uploaded"], "file": item["file"]} for item in project["versions"]
        ],
    }


def _is_coffee(project: dict) -> bool:
    blob = f"{project['brand']} {project['product_type']}".lower()
    return "coffee" in blob or "roaster" in blob


def coffee_not_shipped_answer() -> dict:
    steps = ["get_artwork_projects()"]
    lines = []
    for project in load_projects():
        if not _is_coffee(project):
            continue
        steps.append(f"get_versions(project={project['id']})")
        steps.append(f"get_messages(project={project['id']})")
        latest = latest_version(project)["id"]
        approval = approval_on_latest(project)
        if approval and not project.get("order_id"):
            message = message_by_id(project, approval["message_id"])
            lines.append(
                f"{project['brand']} is approved on {latest} and is not shipped. "
                f"Source: {message['source']} {message['id']} on {approval['at']}, \"{approval['quote']}\"."
            )
        elif approval is None:
            lines.append(
                f"{project['brand']} {latest} is not approved, so it is not an approved order waiting to ship."
            )
    if not lines:
        lines.append("No coffee artwork is approved and waiting to ship.")
    return {"steps": steps, "answer": " ".join(lines), "resolve": []}


def _artwork_question(question: str) -> bool:
    text = question.lower()
    keywords = (
        "artwork", "proof", "pantone", "dieline", "whatsapp", "handoff", "gloss", "matte",
        "version", "coffee", "candle", "bakery", "roaster", "snack", "kettle", "ridgeline",
        "bloom", "pine", "sol snacks", "north fork", "copper kettle",
    )
    if any(word in text for word in keywords):
        return True
    return any(project["brand"].lower() in text or project["id"].lower() in text for project in load_projects())


def artwork_reply(question: str) -> dict | None:
    """Answer from artwork tools only. Returns None when the question is about orders."""
    if not _artwork_question(question):
        return None
    if "coffee" in question.lower() and "approv" in question.lower():
        return coffee_not_shipped_answer()
    named = project_by_id(question) if False else None
    for project in load_projects():
        if project["brand"].lower() in question.lower() or project["id"].lower() in question.lower():
            named = project
            break
    if named is not None:
        steps = [
            f"get_messages(project={named['id']})",
            f"get_checklist(project={named['id']})",
            f"get_versions(project={named['id']})",
        ]
        messages = get_messages(named["id"])
        checklist = get_checklist(named["id"])
        versions = get_versions(named["id"])
        latest = versions["versions"][-1]["id"]
        bits = [f"{named['brand']} current version {latest}. Stage: {named['stage']}."]
        if named["conflicts"]:
            bits.append("Needs human decision.")
            for item in named["conflicts"]:
                bits.append(f"{item['contact']} ({item['message_id']}): \"{item['quote']}\".")
        if messages.get("note"):
            bits.append(messages["note"])
        elif messages["messages"]:
            last = messages["messages"][-1]
            bits.append(f"Latest message {last['id']} from {last['from']}: \"{last['text']}\".")
        open_items = [row for row in checklist["checklist"] if row["done_in"] is None]
        for row in open_items:
            bits.append(f"Checklist {row['id']} is not done ({row['message_id']}).")
        return {"steps": steps, "answer": " ".join(bits), "resolve": []}
    listing = get_artwork_projects()
    stuck = [item for item in listing["projects"] if item["risk"] != "green"]
    if not stuck:
        return {"steps": ["get_artwork_projects()"], "answer": "Nothing needs attention today.", "resolve": []}
    bits = []
    for item in stuck:
        bits.append(
            f"{item['brand']} {item['version']} is {item['stage']}, waiting on {item['waiting_on']}, "
            f"{item['days_waiting']} days, ship {item['ship_date']}."
        )
    return {"steps": ["get_artwork_projects()"], "answer": " ".join(bits), "resolve": []}


def artwork_cache_payload() -> dict:
    comparisons = {}
    messages = {}
    checklists = {}
    versions = {}
    for project in load_projects():
        messages[project["id"]] = get_messages(project["id"])
        checklists[project["id"]] = get_checklist(project["id"])
        versions[project["id"]] = get_versions(project["id"])
        ids = [item["id"] for item in project["versions"]]
        if len(ids) >= 2:
            comparisons[f"{project['id']}|{ids[0]}|{ids[-1]}"] = compare_versions(project["id"], ids[0], ids[-1])
        elif ids:
            comparisons[f"{project['id']}|{ids[0]}|{ids[0]}"] = compare_versions(project["id"], ids[0], ids[0])
    coffee = "Which coffee orders are approved but not shipped?"
    return {
        "source": "rules",
        "summary": rule_summary(),
        "tools": {
            "get_artwork_projects": get_artwork_projects(),
            "get_messages": messages,
            "get_checklist": checklists,
            "get_versions": versions,
            "compare_versions": comparisons,
        },
        "answers": {coffee: coffee_not_shipped_answer()},
    }


def write_artwork_cache(path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artwork_cache_payload(), indent=2) + "\n", encoding="utf-8")


def version_file(project: dict, version_id: str) -> Path | None:
    for version in project["versions"]:
        if version["id"] == version_id:
            return ART_DIR / version["file"]
    return None
