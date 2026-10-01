"""The seeded book: three retailers, six orders, four planted problems."""

from decimal import Decimal

from core.match import match_orders
from core.models import IssueRule
from core.summary import desk_numbers
from data.sample import SEED, as_edi, build_inbound, build_sample


def _matched(packets, day: str):
    return match_orders(
        [packet.purchase_order for packet in packets],
        [packet.shipment for packet in packets],
        [packet.invoice for packet in packets],
        build_inbound(day),
    )


def _results(seed=SEED):
    packets = build_sample(seed)
    return packets, _matched(packets, "monday")


def test_seed_42_is_stable_and_changes_when_the_seed_changes():
    first = [packet.model_dump(mode="json") for packet in build_sample(42)]
    second = [packet.model_dump(mode="json") for packet in build_sample(42)]
    other = [packet.model_dump(mode="json") for packet in build_sample(7)]
    assert first == second
    assert first != other


def test_sample_shape_and_planted_problems():
    packets, results = _results()
    assert len(packets) == 6
    retailers = [packet.purchase_order.retailer for packet in packets]
    assert retailers.count("Northfield Grocers") == 2
    assert retailers.count("BrightMart") == 2
    assert retailers.count("Coastal Pharmacy") == 2
    issues = [packet.injected_issue for packet in packets]
    assert issues.count("clean") == 2
    assert set(issues) == {"clean", "short_ship", "price_mismatch", "missing_line", "late_ship"}

    by_po = {item.po_number: item for item in results}
    for packet in packets:
        result = by_po[packet.purchase_order.po_number]
        if packet.injected_issue == "clean":
            assert result.status == "Clean"
            assert result.exceptions == []
        else:
            assert result.status == "Needs attention"
            assert any(item.rule.value == packet.injected_issue for item in result.exceptions)


def test_edi_records_use_the_simplified_fields():
    packet = build_sample(42)[0]
    edi = as_edi(packet)
    assert set(edi) == {"850", "856", "810"}
    assert set(edi["850"]) == {"po_number", "retailer", "po_date", "ship_by", "cancel_date", "line_items"}
    assert set(edi["850"]["line_items"][0]) == {"style_code", "description", "qty", "unit_price"}
    assert set(edi["856"]) == {"po_number", "ship_date", "line_items"}
    assert set(edi["856"]["line_items"][0]) == {"style_code", "qty_shipped"}
    assert set(edi["810"]) == {"invoice_number", "po_number", "line_items"}
    assert set(edi["810"]["line_items"][0]) == {"style_code", "qty_billed", "unit_price"}


def test_seed_42_exceptions_rank_by_risk_then_dollars():
    from core.summary import ordered_exceptions

    _packets, results = _results()
    impacts = [item.dollar_impact for item in ordered_exceptions(results)]
    assert impacts == [
        Decimal("4086.00"),
        Decimal("300.00"),
        Decimal("74.00"),
        Decimal("384.00"),
    ]


def test_program_names_replace_the_old_item_names():
    packets, _results_for_day = _results()
    names = [line.description for packet in packets for line in packet.purchase_order.line_items]
    assert "Holiday 2026 insulated tote (Northfield program)" in names
    assert "Earth Month printed tote (BrightMart)" in names
    assert "Everyday recycled PET tote (Coastal Pharmacy)" in names
    assert "Grocery sack, heavy duty" not in names
    monday_inbound = build_inbound("monday")
    assert monday_inbound
    assert all(item.eta <= item.launch_date for item in monday_inbound)


def test_desk_numbers_match_the_sample_book():
    _packets, results = _results()
    numbers = desk_numbers(results)
    assert numbers["orders"] == 6
    assert numbers["clean"] == 2
    assert numbers["need_attention"] == 4
    assert numbers["at_risk"] == Decimal("4844.00")


def test_resolving_an_exception_drops_it_from_the_totals():
    from core.summary import ordered_exceptions

    _packets, results = _results()
    late = next(item for item in ordered_exceptions(results) if item.dollar_impact == Decimal("4086.00"))
    numbers = desk_numbers(results, {late.key})
    assert numbers["orders"] == 6
    assert numbers["clean"] == 2
    assert numbers["need_attention"] == 3
    assert numbers["resolved"] == 1
    assert numbers["at_risk"] == Decimal("758.00")


def test_tuesday_is_a_different_book():
    first = [packet.model_dump(mode="json") for packet in build_sample(99, day="tuesday")]
    second = [packet.model_dump(mode="json") for packet in build_sample(99, day="tuesday")]
    monday = build_sample(42, day="monday")
    tuesday = build_sample(99, day="tuesday")
    assert first == second
    monday_pos = {packet.purchase_order.po_number for packet in monday}
    tuesday_pos = {packet.purchase_order.po_number for packet in tuesday}
    assert monday_pos.isdisjoint(tuesday_pos)
    assert tuesday_pos == {f"PO-850-200{n}" for n in range(1, 7)}
    issues = [packet.injected_issue for packet in tuesday]
    assert issues.count("clean") == 2
    assert set(issues) == {"clean", "short_ship", "price_mismatch", "missing_line", "late_ship"}
    results = _matched(tuesday, "tuesday")
    numbers = desk_numbers(results)
    assert numbers["orders"] == 6
    assert numbers["clean"] == 1
    assert numbers["need_attention"] == 5
    assert numbers["at_risk"] == Decimal("13760.00")
    delay = next(item for item in results if item.po_number == "PO-850-2006").exceptions
    assert len(delay) == 1
    assert delay[0].rule == IssueRule.INBOUND_DELAY
    assert delay[0].risk.value == "High"
    assert delay[0].dollar_impact == Decimal("3408.00")
    assert "MSKU-4471" in delay[0].explanation
    assert "October 14, 2026" in delay[0].explanation
    assert "October 10, 2026" in delay[0].explanation
