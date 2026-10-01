"""Daily ops brief. The app reads a cache; only precompute calls Gemini."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

from core.match import ranked_for_brief
from core.models import OrderMatch, cents, format_money

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "cached_brief.json"
CACHE_DIR = ROOT / "data" / "cache"

# Real chains that must never appear. The sample book uses fictional retailers only.
_DENIED_NAMES = (
    "Walmart",
    "Target",
    "Costco",
    "Kroger",
    "Amazon",
    "CVS",
    "Walgreens",
    "Safeway",
    "Publix",
    "Aldi",
    "Tesco",
)


class BriefError(Exception):
    """A problem the precompute script can explain in one sentence."""


def build_facts(results: list[OrderMatch]) -> dict:
    """The only numbers and names the brief is allowed to use."""
    ranked = ranked_for_brief(results)
    clean = sum(1 for order in results if order.status == "Clean")
    exposure = cents(sum((order.exposure for order in results), Decimal("0")))
    return {
        "order_count": len(results),
        "clean_count": clean,
        "attention_count": len(results) - clean,
        "problem_count": len(ranked),
        "retailer_count": len({item.retailer for item in ranked}),
        "dollars_at_risk": format_money(exposure),
        "retailers": sorted({order.retailer for order in results}),
        "po_numbers": [order.po_number for order in results],
        "exceptions_ranked": [
            {
                "retailer": item.retailer,
                "po_number": item.po_number,
                "risk": item.risk.value,
                "dollar_impact": format_money(item.dollar_impact),
                "explanation": item.explanation,
            }
            for item in ranked
        ],
    }


def rule_based_brief(facts: dict) -> str:
    """Four to six lines built only from the exception list."""
    order_count = facts["order_count"]
    attention = facts["attention_count"]
    clean = facts["clean_count"]
    order_word = "order" if order_count == 1 else "orders"
    order_verb = "is" if order_count == 1 else "are"
    need_verb = "needs" if attention == 1 else "need"
    clean_verb = "is" if clean == 1 else "are"
    lines = [
        (
            f"{order_count} {order_word} {order_verb} on the desk today. "
            f"{attention} {need_verb} attention and {clean} {clean_verb} clean, "
            f"with {facts['dollars_at_risk']} at risk."
        )
    ]
    ranked = facts["exceptions_ranked"]
    if not ranked:
        lines.extend(
            [
                "No shipment, price, or invoice breaks are open.",
                "Nothing needs a note to a retailer or the warehouse today.",
                "The order book can stay on watch.",
            ]
        )
        return "\n".join(lines)

    top = ranked[0]
    lines.append(
        f"Start with {top['retailer']} {top['po_number']} "
        f"({top['risk']} risk, {top['dollar_impact']}): {top['explanation']}"
    )
    if len(ranked) > 1:
        nxt = ranked[1]
        lines.append(
            f"Next is {nxt['retailer']} {nxt['po_number']} "
            f"({nxt['risk']} risk, {nxt['dollar_impact']}): {nxt['explanation']}"
        )
    rest = ranked[2:]
    if rest:
        bits = ", ".join(
            f"{item['po_number']} ({item['risk']}, {item['dollar_impact']})" for item in rest
        )
        lines.append(f"Also open: {bits}.")
    else:
        lines.append("No other exceptions are open.")
    lines.append(
        "Work high chargeback risk first, then the largest dollar gaps. "
        "Drafts for the retailer or the warehouse are on the Exceptions tab."
    )
    lines = [line for line in lines if line.strip()]
    if len(lines) < 4:
        lines.append("The figures above are the full exception list.")
    return "\n".join(lines[:6])


def brief_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        line = re.sub(r"^([-*•]|\d+[.)])\s+", "", line)
        if line:
            lines.append(line)
    return lines


def grounding_issues(brief: str, facts: dict) -> list[str]:
    """Return reasons a brief used a number or name that is not in the facts."""
    blob = json.dumps(facts)
    issues: list[str] = []
    for amount in re.findall(r"\$\d[\d,]*\.\d{2}", brief):
        if amount not in blob:
            issues.append(f"Amount {amount} is not in the exception facts.")
    for number in re.findall(r"\d[\d,]*(?:\.\d+)?", brief):
        if number not in blob:
            issues.append(f"Number {number} is not in the exception facts.")
    allowed_pos = set(facts.get("po_numbers", []))
    for po_number in re.findall(r"PO-[A-Za-z0-9-]+", brief):
        if po_number not in allowed_pos:
            issues.append(f"{po_number} is not in the exception facts.")
    for name in _DENIED_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", brief, flags=re.IGNORECASE):
            issues.append(f"The brief names {name}, which is not in the facts.")
    allowed_names = set(facts.get("retailers", [])) | {"Linden Supply", "Order Desk"}
    ordinary = {
        "a", "an", "the", "at", "also", "and", "or", "of", "for", "to", "on", "in",
        "high", "medium", "low", "risk", "chargeback", "open", "today",
    }
    for phrase in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", brief):
        if all(word.lower() in ordinary for word in phrase.split()):
            continue
        if phrase not in allowed_names:
            issues.append(f"The name {phrase} is not in the exception facts.")
    if facts.get("exceptions_ranked") and not re.search(r"\$\d", brief):
        issues.append("The brief left out the dollar amounts.")
    return issues


def _brief_entry(entry: object) -> dict | None:
    if not isinstance(entry, dict):
        return None
    brief = entry.get("brief")
    if not isinstance(brief, str) or not brief.strip():
        return None
    return {"brief": brief.strip(), "source": str(entry.get("source", ""))}


def read_cached_brief(path: Path = CACHE_PATH, day: str | None = None) -> dict | None:
    try:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if day:
        days = payload.get("days")
        if isinstance(days, dict) and day in days:
            return _brief_entry(days[day])
        if day == "monday":
            return _brief_entry(payload)
        return None
    return _brief_entry(payload)


def resolve_brief(results: list[OrderMatch], path: Path = CACHE_PATH, day: str | None = None) -> tuple[str, str]:
    """Return (brief text, source). Source is 'gemini' or 'rules'. Never calls the API."""
    facts = build_facts(results)
    cached = read_cached_brief(path, day)
    if cached:
        text = "\n".join(brief_lines(cached["brief"]))
        count = len(brief_lines(text))
        if cached["source"] == "gemini" and 4 <= count <= 6 and not grounding_issues(text, facts):
            return text, "gemini"
    return rule_based_brief(facts), "rules"


def gemini_settings() -> tuple[str, str]:
    """Read the key and model from Streamlit secrets."""
    try:
        import streamlit as st

        key = str(st.secrets["GEMINI_API_KEY"]).strip()
        model = str(st.secrets["MODEL"]).strip()
    except Exception as exc:
        raise BriefError(
            "Add GEMINI_API_KEY and MODEL to .streamlit/secrets.toml. "
            "Copy .streamlit/secrets.toml.example to start."
        ) from exc
    if not key or "your-key" in key.lower() or key.lower().startswith("paste"):
        raise BriefError("GEMINI_API_KEY in .streamlit/secrets.toml is still a placeholder.")
    if not model:
        raise BriefError("Set MODEL in .streamlit/secrets.toml to a free-tier Gemini Flash model.")
    return key, model


def build_prompt(facts: dict, feedback: str = "") -> str:
    correction = f"\nFix this and try again: {feedback}\n" if feedback else ""
    return (
        "You write the daily ops brief for the COO of Linden Supply, a reusable bag company.\n"
        "Use ONLY the JSON facts below. Do not invent retailers, PO numbers, dollar amounts, dates, or events.\n"
        "Use order_count, problem_count, retailer_count, and dollars_at_risk verbatim.\n"
        "Write 4 to 6 lines of plain business language. No title, no bullets, no markdown.\n"
        "Say what needs attention today.\n"
        "Rank items by chargeback risk (High, then Medium, then Low) and, within a risk level, by dollar impact.\n"
        "Copy dollar amounts exactly, including the dollar sign and cents.\n"
        "Every retailer and PO number you name must appear in the facts.\n"
        f"{correction}\n"
        f"FACTS:\n{json.dumps(facts, indent=2)}\n"
    )


def call_gemini(api_key: str, model: str, prompt: str) -> str:
    import time

    from google import genai

    client = genai.Client(api_key=api_key)
    config = _generation_config()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            if config is None:
                response = client.models.generate_content(model=model, contents=prompt)
            else:
                response = client.models.generate_content(model=model, contents=prompt, config=config)
        except Exception as exc:
            message = str(exc)
            if "429" in message or "RESOURCE_EXHAUSTED" in message:
                raise
            busy = "503" in message or "UNAVAILABLE" in message
            if config is not None and not busy:
                try:
                    response = client.models.generate_content(model=model, contents=prompt)
                except Exception as retry_exc:
                    last_error = retry_exc
                    retry_message = str(retry_exc)
                    if "429" in retry_message or "RESOURCE_EXHAUSTED" in retry_message:
                        raise
                    if attempt < 2 and ("503" in retry_message or "UNAVAILABLE" in retry_message):
                        time.sleep(2)
                        continue
                    raise
            elif busy and attempt < 2:
                last_error = exc
                time.sleep(2)
                continue
            else:
                raise
        text = getattr(response, "text", None)
        if text and str(text).strip():
            return str(text).strip()
        last_error = BriefError("Gemini returned an empty brief. Check that MODEL is a free-tier Flash model.")
        if attempt < 2:
            time.sleep(1)
            continue
    if isinstance(last_error, BriefError):
        raise last_error
    raise BriefError("Gemini returned an empty brief. Check that MODEL is a free-tier Flash model.")


def _generation_config():
    try:
        from google.genai import types
    except Exception:
        return None
    kwargs: dict = {"max_output_tokens": 2048}
    thinking = getattr(types, "ThinkingConfig", None)
    level = getattr(types, "ThinkingLevel", None)
    if thinking is not None and level is not None and hasattr(level, "LOW"):
        try:
            kwargs["thinking_config"] = thinking(thinking_level=level.LOW)
        except Exception:
            pass
    try:
        return types.GenerateContentConfig(**kwargs)
    except Exception:
        return None


def generate_gemini_brief(results: list[OrderMatch]) -> tuple[str, str]:
    """Call Gemini once (with a single retry). Returns the brief and the model name."""
    facts = build_facts(results)
    api_key, model = gemini_settings()
    feedback = ""
    for _ in range(2):
        raw = call_gemini(api_key, model, build_prompt(facts, feedback))
        cleaned = "\n".join(brief_lines(raw))
        issues: list[str] = []
        count = len(brief_lines(cleaned))
        if not 4 <= count <= 6:
            issues.append(f"Write between 4 and 6 lines. That draft had {count}.")
        if cleaned and cleaned[-1] not in ".!?":
            issues.append("Finish the last line as a complete sentence.")
        issues.extend(grounding_issues(cleaned, facts))
        if not issues:
            return cleaned, model
        feedback = " ".join(issues)
    raise BriefError(
        "Gemini's brief added facts that are not in the exception list, so nothing was saved. "
        "The app will keep using the rule-based brief."
    )


def save_day_briefs(day_briefs: dict[str, str], model: str, path: Path = CACHE_PATH) -> None:
    """Save one Gemini brief per sample day. The app only reads this file."""
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = {
        "source": "gemini",
        "model": model,
        "generated_at": stamp,
        "days": {
            day: {"brief": text, "source": "gemini", "model": model, "generated_at": stamp}
            for day, text in day_briefs.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_gemini_brief(results: list[OrderMatch], path: Path = CACHE_PATH) -> str:
    """Call Gemini and save a single brief. Used by precompute only."""
    text, model = generate_gemini_brief(results)
    save_day_briefs({"monday": text}, model, path)
    return text


def cache_file(day: str) -> Path:
    return CACHE_DIR / f"{day}.json"


def read_day_cache(day: str) -> dict | None:
    path = cache_file(day)
    try:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def write_day_cache(day: str, brief: str, chips: dict, source: str) -> None:
    payload = {"brief": brief, "source": source, "chips": chips}
    path = cache_file(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def morning_brief(results: list[OrderMatch], day: str) -> str:
    """Gemini brief when it checks out. Otherwise the saved brief, then the rules."""
    import logging

    facts = build_facts(results)
    try:
        text, _model = generate_gemini_brief(results)
        return text
    except Exception as exc:
        logging.warning("Morning brief used the saved fallback: %s", exc.__class__.__name__)
    cached = read_day_cache(day)
    if cached and isinstance(cached.get("brief"), str):
        text = "\n".join(brief_lines(cached["brief"]))
        count = len(brief_lines(text))
        if 4 <= count <= 6 and not grounding_issues(text, facts):
            return text
    return rule_based_brief(facts)
