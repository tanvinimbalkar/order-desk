"""The rule-based brief and the cache stay inside the exception facts."""

import json
from decimal import Decimal
from pathlib import Path

from core.brief import (
    brief_lines,
    build_facts,
    grounding_issues,
    read_cached_brief,
    resolve_brief,
    rule_based_brief,
)
from core.match import match_one
from core.models import Invoice, InvoiceLine, POLine, PurchaseOrder, ShipLine, ShipmentNotice
from datetime import date


def _one_clean_result():
    po = PurchaseOrder(
        po_number="PO-850-4001",
        retailer="Coastal Pharmacy",
        po_date=date(2026, 9, 2),
        ship_by=date(2026, 9, 12),
        cancel_date=date(2026, 9, 20),
        line_items=[POLine(style_code="RB-PHRM-07", description="Pharmacy tote, small", qty=10, unit_price=Decimal("4.00"))],
    )
    return match_one(
        po,
        ShipmentNotice(po_number=po.po_number, ship_date=date(2026, 9, 10), line_items=[ShipLine(style_code="RB-PHRM-07", qty_shipped=10)]),
        Invoice(invoice_number="INV-810-4001", po_number=po.po_number, line_items=[InvoiceLine(style_code="RB-PHRM-07", qty_billed=10, unit_price=Decimal("4.00"))]),
    )


def _one_short_result():
    po = PurchaseOrder(
        po_number="PO-850-4002",
        retailer="Northfield Grocers",
        po_date=date(2026, 9, 2),
        ship_by=date(2026, 9, 12),
        cancel_date=date(2026, 9, 20),
        line_items=[POLine(style_code="RB-GROC-22", description="Grocery sack, heavy duty", qty=100, unit_price=Decimal("2.00"))],
    )
    return match_one(
        po,
        ShipmentNotice(po_number=po.po_number, ship_date=date(2026, 9, 10), line_items=[ShipLine(style_code="RB-GROC-22", qty_shipped=60)]),
        Invoice(invoice_number="INV-810-4002", po_number=po.po_number, line_items=[InvoiceLine(style_code="RB-GROC-22", qty_billed=60, unit_price=Decimal("2.00"))]),
    )


def test_rule_based_brief_is_four_to_six_lines_and_uses_real_figures():
    results = [_one_short_result(), _one_clean_result()]
    facts = build_facts(results)
    text = rule_based_brief(facts)
    lines = brief_lines(text)
    assert 4 <= len(lines) <= 6
    assert facts["dollars_at_risk"] in text
    assert "Northfield Grocers" in text
    assert "PO-850-4002" in text
    assert grounding_issues(text, facts) == []
    assert "Walmart" not in text


def test_grounding_allows_a_capitalized_risk_phrase():
    facts = build_facts([_one_short_result()])
    brief = (
        "At High risk, Northfield Grocers PO-850-4002 needs attention for $80.00.\n"
        "At Medium risk the gap stays $80.00.\n"
        "The same order is still open for $80.00.\n"
        "Fourth line repeats $80.00."
    )
    issues = grounding_issues(brief, facts)
    assert not any("At High" in issue or "At Medium" in issue for issue in issues)


def test_grounding_rejects_an_invented_amount_and_po():
    facts = build_facts([_one_short_result()])
    issues = grounding_issues("Please review Walmart PO-850-9999 for $9,999.00 today.", facts)
    assert any("9,999.00" in issue for issue in issues)
    assert any("PO-850-9999" in issue for issue in issues)
    assert any("Walmart" in issue for issue in issues)


def test_missing_cache_uses_the_rule_based_brief(tmp_path: Path):
    results = [_one_short_result()]
    text, source = resolve_brief(results, tmp_path / "missing.json")
    assert source == "rules"
    assert "PO-850-4002" in text


def test_valid_gemini_cache_is_used_and_a_bad_cache_falls_back(tmp_path: Path):
    results = [_one_short_result()]
    facts = build_facts(results)
    good = tmp_path / "good.json"
    brief = rule_based_brief(facts)
    good.write_text(
        json.dumps({"brief": brief, "source": "gemini", "model": "gemini-3.8-flash"}),
        encoding="utf-8",
    )
    text, source = resolve_brief(results, good)
    assert source == "gemini"
    assert text == "\n".join(brief_lines(brief))

    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "brief": "Call Target about PO-850-4002.\nThe gap is $1.00.\nThird line.\nFourth line.",
                "source": "gemini",
            }
        ),
        encoding="utf-8",
    )
    text, source = resolve_brief(results, bad)
    assert source == "rules"
    assert "Target" not in text


def test_each_sample_day_reads_its_own_cached_brief(tmp_path: Path):
    results = [_one_short_result()]
    facts = build_facts(results)
    monday = rule_based_brief(facts)
    tuesday = "Coastal Pharmacy PO-850-4001 is clean.\nNo dollars are open.\nThird line for Tuesday.\nFourth line for Tuesday."
    path = tmp_path / "days.json"
    path.write_text(
        json.dumps(
            {
                "days": {
                    "monday": {"brief": monday, "source": "gemini"},
                    "tuesday": {"brief": tuesday, "source": "gemini"},
                }
            }
        ),
        encoding="utf-8",
    )
    text, source = resolve_brief(results, path, day="monday")
    assert source == "gemini"
    assert "PO-850-4002" in text
    cached = read_cached_brief(path, day="tuesday")
    assert cached is not None
    assert "PO-850-4001" in cached["brief"]
    text, source = resolve_brief(results, path, day="tuesday")
    assert source == "rules"
    assert "PO-850-4002" in text


def test_app_does_not_embed_the_api_key():
    app = Path("app.py").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY" not in app
    assert "AQ." not in app
