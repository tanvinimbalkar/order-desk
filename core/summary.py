"""Desk totals. Pandas ranks exceptions by chargeback risk, then dollars."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from core.match import RISK_ORDER, ranked_exceptions
from core.models import ExceptionRecord, OrderMatch, cents


def desk_numbers(results: list[OrderMatch], resolved: set[str] | None = None) -> dict:
    """Orders, never-exception clean, still-open orders, fully approved orders, open dollars."""
    done = resolved or set()
    clean = 0
    need_attention = 0
    resolved_orders = 0
    exposure = Decimal("0")
    for order in results:
        still_open = [item for item in order.exceptions if item.key not in done]
        exposure += sum((item.dollar_impact for item in still_open), Decimal("0"))
        if not order.exceptions:
            clean += 1
        elif not still_open:
            resolved_orders += 1
        else:
            need_attention += 1
    return {
        "orders": len(results),
        "clean": clean,
        "need_attention": need_attention,
        "resolved": resolved_orders,
        "at_risk": cents(exposure),
    }


def ordered_exceptions(results: list[OrderMatch]) -> list[ExceptionRecord]:
    ranked = ranked_exceptions(results)
    if not ranked:
        return []
    frame = pd.DataFrame(
        {
            "key": [item.key for item in ranked],
            "risk": [RISK_ORDER[item.risk] for item in ranked],
            "cents": [int(item.dollar_impact * 100) for item in ranked],
        }
    )
    frame = frame.sort_values(["risk", "cents"], ascending=[True, False], kind="mergesort")
    by_key = {item.key: item for item in ranked}
    return [by_key[key] for key in frame["key"].tolist()]
