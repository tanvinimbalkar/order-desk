"""Ask-the-agent tools. Answers come from tool results, with a saved fallback."""

from __future__ import annotations

import logging
import re
from decimal import Decimal

from core.email import draft_email
from core.match import ranked_exceptions
from core.models import ExceptionRecord, OrderMatch, format_money

CHIPS = (
    "What needs attention at BrightMart?",
    "Why is PO-850-1005 high risk?",
    "Draft a note to Coastal Pharmacy",
)
QUESTION_LIMIT = 10
UNKNOWN = "I don't see that in today's orders"
OFF_TOPIC = "I can help with today's orders, shipments, invoices and fixes"
OFFLINE = "I'm offline right now; try one of the suggested questions."
LIMIT_MESSAGE = "Demo limit reached for this session. Refresh to start again."

_STOP = {
    "what", "why", "how", "when", "where", "who", "draft", "note", "high", "medium", "low",
    "risk", "the", "a", "an", "is", "at", "to", "for", "of", "and", "or", "please", "can",
    "you", "i", "me", "today", "order", "orders", "shipment", "shipments", "invoice",
    "invoices", "fix", "fixes", "attention", "chargeback", "desk", "linden", "supply",
    "monday", "tuesday", "po", "needs", "need", "about", "this", "that", "with", "from",
    "resolve", "resolved", "approve", "email", "message", "bag", "bags",
}


def _payload(item: ExceptionRecord) -> dict:
    return {
        "po_number": item.po_number,
        "retailer": item.retailer,
        "risk": item.risk.value,
        "dollar_impact": format_money(item.dollar_impact),
        "explanation": item.explanation,
    }


def po_numbers(results: list[OrderMatch]) -> list[str]:
    return [order.po_number for order in results]


def list_exceptions(results: list[OrderMatch], retailer: str | None = None) -> dict:
    ranked = ranked_exceptions(results)
    if retailer:
        needle = retailer.strip().lower()
        ranked = [item for item in ranked if needle in item.retailer.lower()]
        known = {order.retailer.lower() for order in results}
        if needle not in known and not any(needle in name for name in known):
            return {"error": UNKNOWN, "po_numbers": po_numbers(results)}
    return {"exceptions": [_payload(item) for item in ranked]}


def get_order(results: list[OrderMatch], po_number: str) -> dict:
    order = next((item for item in results if item.po_number == po_number), None)
    if order is None:
        return {"error": UNKNOWN, "po_numbers": po_numbers(results)}
    return {
        "po_number": order.po_number,
        "retailer": order.retailer,
        "ship_date": order.ship_date.isoformat() if order.ship_date else None,
        "cancel_date": order.cancel_date.isoformat(),
        "exceptions": [_payload(item) for item in ranked_exceptions([order])],
    }


def draft_message(results: list[OrderMatch], po_number: str, recipient: str | None = None) -> dict:
    order = next((item for item in results if item.po_number == po_number), None)
    if order is None:
        return {"error": UNKNOWN, "po_numbers": po_numbers(results)}
    items = [item for item in ranked_exceptions(results) if item.po_number == po_number]
    if not items:
        return {"po_number": po_number, "messages": [], "note": "This order is clean."}
    messages = []
    for item in items:
        draft = draft_email(item)
        who = recipient.strip() if recipient else draft.to
        messages.append({"to": who, "subject": draft.subject, "body": draft.rendered})
    return {"po_number": po_number, "messages": messages}


def mark_resolved(results: list[OrderMatch], po_number: str, resolved_keys: set[str]) -> dict:
    if po_number not in set(po_numbers(results)):
        return {"error": UNKNOWN, "po_numbers": po_numbers(results)}
    pending = [
        item
        for item in ranked_exceptions(results)
        if item.po_number == po_number and item.key not in resolved_keys
    ]
    if not pending:
        return {"ok": True, "po_number": po_number, "already_resolved": True, "keys": []}
    return {
        "ok": True,
        "po_number": po_number,
        "already_resolved": False,
        "keys": [item.key for item in pending],
        "removed": format_money(sum((item.dollar_impact for item in pending), Decimal("0"))),
    }


def format_step(name: str, args: dict | None) -> str:
    kept = []
    for key, value in (args or {}).items():
        if value is None or value == "":
            continue
        kept.append(f"{key}={value}")
    joined = ", ".join(kept)
    return f"{name}({joined})"


def execute_tool(name: str, args: dict, results: list[OrderMatch], resolved_keys: set[str]) -> dict:
    args = args or {}
    if name == "list_exceptions":
        return list_exceptions(results, args.get("retailer"))
    if name == "get_order":
        return get_order(results, str(args.get("po_number") or ""))
    if name == "draft_email":
        return draft_message(results, str(args.get("po_number") or ""), args.get("recipient"))
    if name == "mark_resolved":
        return mark_resolved(results, str(args.get("po_number") or ""), resolved_keys)
    return {"error": "Unknown tool"}


def unknown_reply(results: list[OrderMatch]) -> str:
    listed = ", ".join(po_numbers(results))
    return f"{UNKNOWN}. Today's purchase orders are {listed}."


def off_topic_reply() -> str:
    chips = " ".join(f'"{chip}"' for chip in CHIPS)
    return f"{OFF_TOPIC}. Try {chips}."


def _mentions(question: str, results: list[OrderMatch]) -> str | None:
    found = re.findall(r"PO-\d{3}-\d{4}", question, flags=re.IGNORECASE)
    known = {po.upper() for po in po_numbers(results)}
    if any(po.upper() not in known for po in found):
        return unknown_reply(results)
    retailers = [order.retailer for order in results]
    words = re.findall(r"[A-Za-z][A-Za-z']+", question)
    for word in words:
        if word.lower() in _STOP or word.isupper():
            continue
        if word[0].islower():
            continue
        if any(word.lower() in retailer.lower() for retailer in retailers):
            continue
        return unknown_reply(results)
    topic = re.search(
        r"order|shipment|invoice|chargeback|risk|fix|approve|exception|attention|draft|note|email|resolve|\bpo\b",
        question,
        flags=re.IGNORECASE,
    )
    if topic or found:
        return None
    return off_topic_reply()


def _money_join(rows: list[dict]) -> str:
    if not rows:
        return "Nothing is open there."
    bits = [
        f"{row['risk']} risk {row['po_number']} ({row['dollar_impact']}): {row['explanation']}"
        for row in rows
    ]
    return " ".join(bits)


def build_chip_cache(results: list[OrderMatch]) -> dict[str, dict]:
    """Saved answers for the three chips. Built only from tool results."""
    bright = list_exceptions(results, "BrightMart")
    why = get_order(results, "PO-850-1005")
    coastal = list_exceptions(results, "Coastal Pharmacy")
    chips = {
        CHIPS[0]: {
            "steps": ["list_exceptions(retailer=BrightMart)"],
            "answer": _money_join(bright.get("exceptions", [])),
        },
        CHIPS[1]: {
            "steps": ["get_order(po_number=PO-850-1005)"],
            "answer": (
                unknown_reply(results)
                if why.get("error")
                else _money_join(why.get("exceptions", [])) or f"{why['po_number']} is clean."
            ),
        },
    }
    steps = ["list_exceptions(retailer=Coastal Pharmacy)"]
    messages = []
    for row in coastal.get("exceptions", []):
        drafted = draft_message(results, row["po_number"], "Coastal Pharmacy")
        steps.append(f"draft_email(po_number={row['po_number']}, recipient=Coastal Pharmacy)")
        for message in drafted.get("messages", []):
            messages.append(message["body"])
    if not messages:
        answer = "Coastal Pharmacy has no open problems to write up."
    else:
        answer = "\n\n".join(messages)
    chips[CHIPS[2]] = {"steps": steps, "answer": answer}
    return chips


def _from_cache(day: str, question: str, results: list[OrderMatch]) -> dict | None:
    from core.brief import read_day_cache

    cached = read_day_cache(day)
    chips = (cached or {}).get("chips") if isinstance(cached, dict) else None
    if not isinstance(chips, dict) or question not in chips:
        chips = build_chip_cache(results)
    entry = chips.get(question)
    if not isinstance(entry, dict):
        return None
    answer = entry.get("answer")
    steps = entry.get("steps")
    if not isinstance(answer, str) or not isinstance(steps, list):
        return None
    return {"steps": [str(step) for step in steps], "answer": answer, "resolve": []}


def _tool_declarations():
    from google.genai import types

    def decl(name: str, description: str, properties: dict, required: list[str] | None = None):
        return types.FunctionDeclaration(
            name=name,
            description=description,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties=properties,
                required=required or [],
            ),
        )

    string = lambda description: types.Schema(type=types.Type.STRING, description=description)
    return [
        decl(
            "list_exceptions",
            "List today's exceptions, optionally for one retailer. Sorted by chargeback risk, then dollars.",
            {"retailer": string("Retailer name. Omit to list every exception.")},
        ),
        decl(
            "get_order",
            "Get one purchase order, its dates, and its exceptions.",
            {"po_number": string("Purchase order number, such as PO-850-1005.")},
            ["po_number"],
        ),
        decl(
            "draft_email",
            "Draft the fix message for a purchase order. The wording uses the real figures.",
            {
                "po_number": string("Purchase order number."),
                "recipient": string("Who the note is for, such as a retailer or the warehouse."),
            },
            ["po_number"],
        ),
        decl(
            "mark_resolved",
            "Approve the open fixes on a purchase order. Same result as clicking Approve.",
            {"po_number": string("Purchase order number to resolve.")},
            ["po_number"],
        ),
    ]


def _live_answer(question: str, results: list[OrderMatch], resolved_keys: set[str]) -> dict:
    from google.genai import types

    from core.brief import gemini_settings

    _key, model = gemini_settings()
    from google import genai

    client = genai.Client(api_key=_key)
    tool = types.Tool(function_declarations=_tool_declarations())
    config = types.GenerateContentConfig(
        tools=[tool],
        system_instruction=(
            "You are the Order Desk agent for Linden Supply. "
            "Call the tools and answer only from their results. Do not invent figures. "
            f"If a tool says the PO or retailer is missing, reply starting with: {UNKNOWN}. "
            "When you resolve an order, confirm what was approved and the dollars removed."
        ),
    )
    contents: list = [question]
    steps: list[str] = []
    resolve: list[str] = []
    for _ in range(4):
        response = client.models.generate_content(model=model, contents=contents, config=config)
        calls = list(getattr(response, "function_calls", None) or [])
        if not calls:
            text = getattr(response, "text", None) or ""
            if not str(text).strip():
                raise RuntimeError("empty answer")
            return {"steps": steps, "answer": str(text).strip(), "resolve": resolve}
        content = response.candidates[0].content
        contents.append(content)
        parts = []
        for call in calls:
            args = dict(call.args or {})
            steps.append(format_step(str(call.name), args))
            result = execute_tool(str(call.name), args, results, resolved_keys)
            if call.name == "mark_resolved" and result.get("ok") and not result.get("already_resolved"):
                resolve.extend(result.get("keys") or [])
                resolved_keys.update(result.get("keys") or [])
            parts.append(types.Part.from_function_response(name=str(call.name), response=result))
        contents.append(types.Content(role="user", parts=parts))
    raise RuntimeError("tool loop ended without an answer")


def ask(
    question: str,
    results: list[OrderMatch],
    day: str,
    resolved_keys: set[str],
    *,
    cache_only: bool = False,
) -> dict:
    """Answer one question. Chips fall back to the saved cache. Never raises."""
    if question not in CHIPS:
        routed = _mentions(question, results)
        if routed:
            return {"steps": [], "answer": routed, "resolve": []}
    if not cache_only:
        try:
            return _live_answer(question, results, resolved_keys)
        except Exception as exc:
            logging.warning("Agent chat used the saved fallback: %s", exc.__class__.__name__)
    if question in CHIPS:
        cached = _from_cache(day, question, results)
        if cached:
            return cached
    return {"steps": [], "answer": OFFLINE, "resolve": []}
