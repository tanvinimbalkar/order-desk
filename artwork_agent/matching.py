"""Matching messages to projects. Low confidence stays in Unsorted."""

from __future__ import annotations

import re


def find_codes(text: str, pattern: str) -> list[str]:
    found = re.findall(pattern, text or "")
    seen = []
    for code in found:
        if code not in seen:
            seen.append(code)
    return seen


def _phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def _domain(email: str) -> str:
    if "@" not in (email or ""):
        return ""
    return email.split("@", 1)[1].strip().lower()


def match_message(
    text: str,
    *,
    pattern: str,
    projects: list[dict],
    sender_email: str = "",
    sender_phone: str = "",
    drive_folder: str = "",
    clickup_task: str = "",
    hubspot_deal: str = "",
    rules: list[dict] | None = None,
    ai_guesses: list[dict] | None = None,
    threshold: float = 0.75,
) -> dict:
    """Return linked projects or mark the message unsorted.

    A guess is a dict with project_id and confidence. One message may link to
    more than one project when it names more than one project code.
    """
    by_code = {item["code"]: item for item in projects}
    by_id = {item["id"]: item for item in projects}
    codes = [code for code in find_codes(text, pattern) if code in by_code or code in by_id]
    if codes:
        links = []
        for code in codes:
            project = by_code.get(code) or by_id[code]
            links.append({"project_id": project["id"], "reason": "project code", "confidence": 1.0})
        return {"links": links, "unsorted": False}

    domain = _domain(sender_email)
    if domain:
        hits = [item for item in projects if (item.get("customer_domain") or "").lower() == domain]
        if hits:
            return {
                "links": [{"project_id": item["id"], "reason": "customer domain", "confidence": 1.0} for item in hits],
                "unsorted": False,
            }
    phone = _phone(sender_phone)
    if phone:
        hits = [item for item in projects if _phone(item.get("customer_phone") or "") == phone]
        if hits:
            return {
                "links": [{"project_id": item["id"], "reason": "customer phone", "confidence": 1.0} for item in hits],
                "unsorted": False,
            }

    for rule in rules or []:
        if rule.get("pattern") and rule["pattern"] in {domain, phone, (sender_email or "").lower()}:
            if rule["project_id"] in by_id:
                return {
                    "links": [{"project_id": rule["project_id"], "reason": "saved rule", "confidence": 1.0}],
                    "unsorted": False,
                }

    if drive_folder:
        hits = [item for item in projects if item.get("drive_folder") and item["drive_folder"].lower() == drive_folder.lower()]
        if hits:
            return {
                "links": [{"project_id": item["id"], "reason": "drive folder", "confidence": 1.0} for item in hits],
                "unsorted": False,
            }
    if clickup_task:
        hits = [item for item in projects if item.get("clickup_task") == clickup_task]
        if hits:
            return {
                "links": [{"project_id": item["id"], "reason": "clickup task", "confidence": 1.0} for item in hits],
                "unsorted": False,
            }
    if hubspot_deal:
        hits = [item for item in projects if item.get("hubspot_deal") == hubspot_deal]
        if hits:
            return {
                "links": [{"project_id": item["id"], "reason": "hubspot deal", "confidence": 1.0} for item in hits],
                "unsorted": False,
            }

    accepted = []
    for guess in ai_guesses or []:
        project_id = guess.get("project_id")
        confidence = float(guess.get("confidence") or 0)
        if project_id in by_id and confidence >= threshold:
            accepted.append({"project_id": project_id, "reason": "ai match", "confidence": confidence})
    if accepted:
        return {"links": accepted, "unsorted": False}
    return {"links": [], "unsorted": True}
