"""Rules the agent is not allowed to break. Every figure comes from a stored row."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime

VAGUE = ("looks good mostly", "mostly good", "looks mostly good", "thumbs up", "👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿")
STAGES = [
    "New",
    "Artwork in progress",
    "Proof sent",
    "Revisions",
    "Approved",
    "Sent to factory",
    "In production",
    "Shipped",
]
RISK_ORDER = {"red": 0, "yellow": 1, "green": 2}


def message_hash(sender: str, sent_at: str, body: str) -> str:
    raw = f"{(sender or '').strip()}|{(sent_at or '').strip()}|{(body or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_vague(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    if lowered in {"👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿", "ok", "okay", "thanks", "thank you"}:
        return True
    return any(phrase in lowered for phrase in VAGUE)


def version_index(label: str) -> int | None:
    match = re.fullmatch(r"v(\d+)", label or "")
    return int(match.group(1)) if match else None


def latest_label(versions: list[dict]) -> str:
    if not versions:
        return ""
    ordered = sorted(versions, key=lambda item: (item.get("uploaded_at") or "", version_index(item.get("version_label") or "") or 0))
    return ordered[-1]["version_label"]


def approvals_that_count(approvals: list[dict], latest: str) -> list[dict]:
    return [item for item in approvals if item.get("counts") and item.get("version_label") == latest]


def stale_approvals(approvals: list[dict], latest: str) -> list[dict]:
    return [item for item in approvals if item.get("counts") and item.get("version_label") != latest]


def parse_day(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def days_between(start: str, as_of: str) -> int:
    left = parse_day(start)
    right = parse_day(as_of) or date.today()
    if left is None:
        return 0
    return max((right - left).days, 0)


def preflight_gaps(specs: dict, versions: list[dict], approvals: list[dict], has_dieline: bool) -> list[str]:
    latest = latest_label(versions)
    gaps = []
    counted = approvals_that_count(approvals, latest)
    if not counted:
        if stale_approvals(approvals, latest):
            gaps.append("approval not on latest version")
        else:
            gaps.append("approval")
    pantone = (specs.get("pantone") or "").strip()
    if not pantone:
        gaps.append("Pantone colors")
    quantity = (specs.get("quantity") or "").strip()
    if not quantity:
        gaps.append("quantity")
    if not has_dieline:
        gaps.append("dieline")
    finals = [item for item in versions if item.get("final_for_production")]
    if not finals:
        gaps.append("final files")
    return gaps


def risk_for(stage: str, days: int, gaps: list[str], conflicts: bool, nudge_days: int) -> str:
    stale = "approval not on latest version" in gaps
    missing = any(item in gaps for item in ("Pantone colors", "quantity", "dieline"))
    if conflicts or stale or (stage == "Approved" and missing):
        return "red"
    if stage in {"In production", "Shipped"} and not any(item in gaps for item in ("Pantone colors", "quantity", "dieline", "approval", "approval not on latest version", "final files")):
        return "green"
    if stage == "Revisions" or days >= max(nudge_days, 5):
        return "yellow"
    if days >= nudge_days:
        return "yellow"
    return "green"


def compare_checklist(items: list[dict], versions: list[dict], right: str, model_items: list[dict] | None = None) -> list[dict]:
    known_versions = {item["version_label"] for item in versions}
    if right not in known_versions:
        return []
    right_index = version_index(right)
    rules = []
    for item in items:
        done_in = item.get("done_in")
        done_index = version_index(done_in) if done_in else None
        if item.get("status") == "needs_human":
            status, reason = "unclear", "Needs human decision."
        elif done_index is not None and right_index is not None and done_index <= right_index:
            status, reason = "done", f"Present in {done_in}."
        else:
            status, reason = "not_done", "Not on the later version."
        rules.append(
            {
                "id": item["id"],
                "request": item["request"],
                "status": status,
                "reason": reason,
                "message_id": item.get("message_id") or "",
            }
        )
    if not model_items:
        return rules
    by_id = {item["id"]: item for item in rules}
    known_blob = " ".join(
        [item["request"] for item in items]
        + [item["version_label"] for item in versions]
        + [item.get("message_id") or "" for item in items]
    )
    clean = []
    for raw in model_items:
        item_id = str(raw.get("id") or "")
        if item_id not in by_id:
            continue
        status = raw.get("status")
        if status not in {"done", "not_done", "unclear"}:
            continue
        reason = str(raw.get("reason") or "")
        numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", reason)
        grounded = all(number in known_blob for number in numbers)
        if raw.get("confidence") == "low" or not grounded:
            status = "unclear"
            reason = "unclear, check manually."
        clean.append({**by_id[item_id], "status": status, "reason": reason})
    seen = {item["id"] for item in clean}
    for item in rules:
        if item["id"] not in seen:
            clean.append(item)
    return clean


def grounded(text: str, allowed: set[str]) -> bool:
    """Drop model text that names a version, project code, or PO the database does not have."""
    tokens = set(re.findall(r"\bv\d+\b", text or ""))
    tokens.update(re.findall(r"\b[A-Z]{2}-\d{2,4}\b", text or ""))
    tokens.update(re.findall(r"\bPO-\d{3}-\d{4}\b", text or ""))
    return all(token in allowed for token in tokens)


def link_status(row: dict | None, now: datetime) -> str:
    if row is None:
        return "missing"
    if row.get("revoked"):
        return "revoked"
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except (TypeError, ValueError):
        return "expired"
    if expires <= now:
        return "expired"
    return "open"


def expired_message(company: str) -> str:
    return f"This link has expired, please contact {company}."
