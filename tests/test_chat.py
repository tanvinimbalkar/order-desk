"""Suggested questions and the guard rails around them."""

from core.chat import CHIPS, UNKNOWN, build_chip_cache, list_exceptions, unknown_reply
from core.match import match_orders
from data.sample import build_inbound, build_sample


def _results(day: str, seed: int):
    packets = build_sample(seed, day=day)
    return match_orders(
        [packet.purchase_order for packet in packets],
        [packet.shipment for packet in packets],
        [packet.invoice for packet in packets],
        build_inbound(day),
    )


def test_monday_chips_use_the_real_exceptions():
    results = _results("monday", 42)
    chips = build_chip_cache(results)
    bright = chips[CHIPS[0]]
    assert bright["steps"] == ["list_exceptions(retailer=BrightMart)"]
    assert "PO-850-1004" in bright["answer"]
    assert "PO-850-1003" in bright["answer"]
    why = chips[CHIPS[1]]
    assert "get_order(po_number=PO-850-1005)" in why["steps"]
    assert "PO-850-1005" in why["answer"]
    assert "$4,086.00" in why["answer"]
    note = chips[CHIPS[2]]
    assert any(step.startswith("draft_email") for step in note["steps"])
    assert "Coastal Pharmacy" in note["answer"]


def test_tuesday_list_exceptions_includes_the_container_delay():
    results = _results("tuesday", 99)
    listed = list_exceptions(results, "BrightMart")
    explanations = " ".join(row["explanation"] for row in listed["exceptions"])
    assert "MSKU-4471" in explanations
    assert "October 14, 2026" in explanations
    assert "$3,408.00" in explanations


def test_tuesday_chip_for_mondays_po_says_it_is_missing():
    results = _results("tuesday", 99)
    chips = build_chip_cache(results)
    assert UNKNOWN in chips[CHIPS[1]]["answer"]
    assert "PO-850-2001" in chips[CHIPS[1]]["answer"]


def test_unknown_reply_lists_the_days_purchase_orders():
    results = _results("monday", 42)
    text = unknown_reply(results)
    assert "PO-850-1001" in text
    assert "PO-850-1006" in text
