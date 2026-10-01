"""Every matching rule: short ship, billed qty, price, missing line, late ship."""

from datetime import date
from decimal import Decimal

import pytest

from core.match import inbound_log_line, match_one, match_orders
from core.models import (
    ChargebackRisk,
    InboundShipment,
    Invoice,
    InvoiceLine,
    IssueRule,
    POLine,
    PurchaseOrder,
    ShipLine,
    ShipmentNotice,
    Tone,
)


def order(lines, cancel=date(2026, 9, 20), po_number="PO-850-2001", retailer="Northfield Grocers"):
    return PurchaseOrder(
        po_number=po_number,
        retailer=retailer,
        po_date=date(2026, 9, 2),
        ship_by=date(2026, 9, 12),
        cancel_date=cancel,
        line_items=lines,
    )


def line(style="RB-GROC-22", description="Grocery sack, heavy duty", qty=1000, price="2.10"):
    return POLine(style_code=style, description=description, qty=qty, unit_price=Decimal(price))


def ship(po_number, items, ship_date=date(2026, 9, 10)):
    return ShipmentNotice(po_number=po_number, ship_date=ship_date, line_items=items)


def invoice(po_number, items, number="INV-810-2001"):
    return Invoice(invoice_number=number, po_number=po_number, line_items=items)


def test_short_shipment_is_medium_and_prices_the_unshipped_units():
    po = order([line()])
    result = match_one(
        po,
        ship(po.po_number, [ShipLine(style_code="RB-GROC-22", qty_shipped=720)]),
        invoice(po.po_number, [InvoiceLine(style_code="RB-GROC-22", qty_billed=720, unit_price=Decimal("2.10"))]),
    )
    assert len(result.exceptions) == 1
    found = result.exceptions[0]
    assert found.rule == IssueRule.SHORT_SHIP
    assert found.risk == ChargebackRisk.MEDIUM
    assert found.dollar_impact == Decimal("588.00")
    assert found.audience == "warehouse"
    assert "280" in found.explanation
    assert result.lines[0].shipped_tone == Tone.AMBER
    assert result.lines[0].invoiced_tone == Tone.OK
    assert result.lines[0].ordered_tone == Tone.OK
    assert result.status == "Needs attention"


def test_qty_billed_not_equal_to_shipped_is_medium():
    po = order([line(qty=100, price="5.00")])
    result = match_one(
        po,
        ship(po.po_number, [ShipLine(style_code="RB-GROC-22", qty_shipped=100)]),
        invoice(po.po_number, [InvoiceLine(style_code="RB-GROC-22", qty_billed=80, unit_price=Decimal("5.00"))]),
    )
    assert len(result.exceptions) == 1
    found = result.exceptions[0]
    assert found.rule == IssueRule.QTY_BILLED
    assert found.risk == ChargebackRisk.MEDIUM
    assert found.dollar_impact == Decimal("100.00")
    assert found.audience == "retailer"
    assert result.lines[0].invoiced_tone == Tone.AMBER


def test_qty_billed_above_shipped_uses_the_absolute_gap():
    po = order([line(qty=100, price="5.00")])
    result = match_one(
        po,
        ship(po.po_number, [ShipLine(style_code="RB-GROC-22", qty_shipped=100)]),
        invoice(po.po_number, [InvoiceLine(style_code="RB-GROC-22", qty_billed=120, unit_price=Decimal("5.00"))]),
    )
    found = result.exceptions[0]
    assert found.rule == IssueRule.QTY_BILLED
    assert found.dollar_impact == Decimal("100.00")


def test_invoice_price_difference_is_low_and_uses_billed_qty():
    po = order([line(style="RB-SHOP-03", description="Shopping bag, wide gusset", qty=400, price="3.40")])
    result = match_one(
        po,
        ship(po.po_number, [ShipLine(style_code="RB-SHOP-03", qty_shipped=400)]),
        invoice(
            po.po_number,
            [InvoiceLine(style_code="RB-SHOP-03", qty_billed=400, unit_price=Decimal("3.85"))],
        ),
    )
    assert len(result.exceptions) == 1
    found = result.exceptions[0]
    assert found.rule == IssueRule.PRICE
    assert found.risk == ChargebackRisk.LOW
    assert found.dollar_impact == Decimal("180.00")
    assert found.audience == "retailer"
    assert result.lines[0].invoiced_tone == Tone.AMBER
    assert result.lines[0].shipped_tone == Tone.OK


def test_price_difference_below_po_price_is_still_flagged():
    po = order([line(qty=10, price="4.00")])
    result = match_one(
        po,
        ship(po.po_number, [ShipLine(style_code="RB-GROC-22", qty_shipped=10)]),
        invoice(po.po_number, [InvoiceLine(style_code="RB-GROC-22", qty_billed=10, unit_price=Decimal("3.50"))]),
    )
    assert result.exceptions[0].rule == IssueRule.PRICE
    assert result.exceptions[0].dollar_impact == Decimal("5.00")


def test_missing_line_is_high_and_is_not_also_a_short_shipment():
    po = order(
        [
            line(style="RB-SACK-11", description="Bulk sack, flat bottom", qty=300, price="5.00"),
            line(style="RB-MESH-19", description="Fine mesh bag", qty=200, price="2.50"),
        ]
    )
    result = match_one(
        po,
        ship(po.po_number, [ShipLine(style_code="RB-SACK-11", qty_shipped=300)]),
        invoice(po.po_number, [InvoiceLine(style_code="RB-SACK-11", qty_billed=300, unit_price=Decimal("5.00"))]),
    )
    missing = [item for item in result.exceptions if item.style_code == "RB-MESH-19"]
    assert len(missing) == 1
    assert missing[0].rule == IssueRule.MISSING_LINE
    assert missing[0].risk == ChargebackRisk.HIGH
    assert missing[0].dollar_impact == Decimal("500.00")
    assert missing[0].audience == "warehouse"
    assert "shipment and the invoice" in missing[0].explanation
    assert all(item.rule != IssueRule.SHORT_SHIP for item in result.exceptions)
    mesh = next(row for row in result.lines if row.style_code == "RB-MESH-19")
    assert mesh.shipped_tone == Tone.RED
    assert mesh.invoiced_tone == Tone.RED
    assert mesh.ordered_tone == Tone.OK


def test_line_missing_from_invoice_only_is_high():
    po = order([line(qty=40, price="2.00")])
    result = match_one(
        po,
        ship(po.po_number, [ShipLine(style_code="RB-GROC-22", qty_shipped=40)]),
        invoice(po.po_number, []),
    )
    assert len(result.exceptions) == 1
    found = result.exceptions[0]
    assert found.rule == IssueRule.MISSING_LINE
    assert found.risk == ChargebackRisk.HIGH
    assert found.dollar_impact == Decimal("80.00")
    assert found.audience == "retailer"
    assert result.lines[0].invoiced_tone == Tone.RED
    assert result.lines[0].shipped_tone == Tone.OK


def test_line_on_invoice_but_missing_from_po_is_high():
    po = order([line(qty=10, price="2.00")])
    result = match_one(
        po,
        ship(
            po.po_number,
            [
                ShipLine(style_code="RB-GROC-22", qty_shipped=10),
                ShipLine(style_code="RB-EXTRA-01", qty_shipped=4),
            ],
        ),
        invoice(
            po.po_number,
            [
                InvoiceLine(style_code="RB-GROC-22", qty_billed=10, unit_price=Decimal("2.00")),
                InvoiceLine(style_code="RB-EXTRA-01", qty_billed=4, unit_price=Decimal("8.00")),
            ],
        ),
    )
    extra = next(item for item in result.exceptions if item.style_code == "RB-EXTRA-01")
    assert extra.rule == IssueRule.MISSING_LINE
    assert extra.risk == ChargebackRisk.HIGH
    assert extra.dollar_impact == Decimal("32.00")
    assert extra.audience == "retailer"


def test_ship_date_after_cancel_date_is_high_and_prices_the_whole_po():
    po = order(
        [
            line(style="RB-PHRM-07", description="Pharmacy tote, small", qty=600, price="4.10"),
            line(style="RB-COOL-15", description="Insulated cooler bag", qty=400, price="2.20"),
        ],
        cancel=date(2026, 9, 12),
    )
    result = match_one(
        po,
        ship(
            po.po_number,
            [
                ShipLine(style_code="RB-PHRM-07", qty_shipped=600),
                ShipLine(style_code="RB-COOL-15", qty_shipped=400),
            ],
            ship_date=date(2026, 9, 15),
        ),
        invoice(
            po.po_number,
            [
                InvoiceLine(style_code="RB-PHRM-07", qty_billed=600, unit_price=Decimal("4.10")),
                InvoiceLine(style_code="RB-COOL-15", qty_billed=400, unit_price=Decimal("2.20")),
            ],
        ),
    )
    assert len(result.exceptions) == 1
    found = result.exceptions[0]
    assert found.rule == IssueRule.LATE_SHIP
    assert found.risk == ChargebackRisk.HIGH
    assert found.dollar_impact == Decimal("3340.00")
    assert found.audience == "warehouse"
    assert found.style_code is None
    assert all(row.shipped_tone == Tone.RED for row in result.lines)
    assert all(row.invoiced_tone == Tone.OK for row in result.lines)


def test_ship_date_on_cancel_date_is_not_late():
    po = order([line(qty=10, price="1.00")], cancel=date(2026, 9, 12))
    result = match_one(
        po,
        ship(po.po_number, [ShipLine(style_code="RB-GROC-22", qty_shipped=10)], ship_date=date(2026, 9, 12)),
        invoice(po.po_number, [InvoiceLine(style_code="RB-GROC-22", qty_billed=10, unit_price=Decimal("1.00"))]),
    )
    assert result.exceptions == []
    assert result.status == "Clean"
    assert result.lines[0].shipped_tone == Tone.OK


def test_clean_order_has_no_exceptions():
    po = order([line(qty=50, price="1.25"), line(style="RB-PROD-08", description="Produce bag, mesh", qty=80, price="2.00")])
    result = match_one(
        po,
        ship(
            po.po_number,
            [
                ShipLine(style_code="RB-GROC-22", qty_shipped=50),
                ShipLine(style_code="RB-PROD-08", qty_shipped=80),
            ],
        ),
        invoice(
            po.po_number,
            [
                InvoiceLine(style_code="RB-GROC-22", qty_billed=50, unit_price=Decimal("1.25")),
                InvoiceLine(style_code="RB-PROD-08", qty_billed=80, unit_price=Decimal("2.00")),
            ],
        ),
    )
    assert result.status == "Clean"
    assert result.exceptions == []


def test_documents_match_only_within_the_same_po_number():
    first = order([line(qty=25, price="2.00")], po_number="PO-850-3001")
    second = order([line(qty=25, price="2.00")], po_number="PO-850-3002", retailer="BrightMart")
    results = match_orders(
        [first, second],
        [
            ship("PO-850-3002", [ShipLine(style_code="RB-GROC-22", qty_shipped=25)]),
        ],
        [
            invoice("PO-850-3001", [InvoiceLine(style_code="RB-GROC-22", qty_billed=25, unit_price=Decimal("2.00"))]),
            invoice("PO-850-3002", [InvoiceLine(style_code="RB-GROC-22", qty_billed=25, unit_price=Decimal("2.00"))], number="INV-810-3002"),
        ],
    )
    by_po = {item.po_number: item for item in results}
    assert any(item.rule == IssueRule.MISSING_LINE for item in by_po["PO-850-3001"].exceptions)
    assert by_po["PO-850-3002"].status == "Clean"


def test_overship_is_not_a_short_shipment():
    po = order([line(qty=10, price="3.00")])
    result = match_one(
        po,
        ship(po.po_number, [ShipLine(style_code="RB-GROC-22", qty_shipped=12)]),
        invoice(po.po_number, [InvoiceLine(style_code="RB-GROC-22", qty_billed=10, unit_price=Decimal("3.00"))]),
    )
    assert all(item.rule != IssueRule.SHORT_SHIP for item in result.exceptions)
    billed = next(item for item in result.exceptions if item.rule == IssueRule.QTY_BILLED)
    assert billed.dollar_impact == Decimal("6.00")
    assert billed.risk == ChargebackRisk.MEDIUM


def test_short_ship_and_price_difference_are_separate_exceptions():
    po = order([line(qty=100, price="2.00")])
    result = match_one(
        po,
        ship(po.po_number, [ShipLine(style_code="RB-GROC-22", qty_shipped=80)]),
        invoice(po.po_number, [InvoiceLine(style_code="RB-GROC-22", qty_billed=80, unit_price=Decimal("2.50"))]),
    )
    rules = {item.rule for item in result.exceptions}
    assert rules == {IssueRule.SHORT_SHIP, IssueRule.PRICE}
    short = next(item for item in result.exceptions if item.rule == IssueRule.SHORT_SHIP)
    price = next(item for item in result.exceptions if item.rule == IssueRule.PRICE)
    assert short.dollar_impact == Decimal("40.00")
    assert price.dollar_impact == Decimal("40.00")


def test_inbound_eta_after_launch_is_high_and_prices_the_whole_po():
    po = order(
        [line(qty=480, price="3.40"), line(style="RB-FLAT-27", description="Earth Month kraft flat bag (BrightMart)", qty=960, price="1.85")],
        po_number="PO-850-2006",
        retailer="BrightMart",
    )
    container = InboundShipment(
        container_id="MSKU-4471",
        origin_port="Ningbo",
        factory="Linden Cut-and-Sew, Ningbo",
        eta=date(2026, 10, 14),
        po_number=po.po_number,
        launch_date=date(2026, 10, 10),
    )
    on_time = InboundShipment(
        container_id="MSKU-4480",
        origin_port="Laem Chabang",
        factory="Linden Cut-and-Sew, Laem Chabang",
        eta=date(2026, 10, 3),
        po_number="PO-850-2002",
        launch_date=date(2026, 10, 9),
    )
    other = order([line(qty=10, price="1.00")], po_number="PO-850-2002", retailer="Coastal Pharmacy")
    results = match_orders(
        [po, other],
        [
            ship(po.po_number, [ShipLine(style_code="RB-GROC-22", qty_shipped=480), ShipLine(style_code="RB-FLAT-27", qty_shipped=960)]),
            ship(other.po_number, [ShipLine(style_code="RB-GROC-22", qty_shipped=10)]),
        ],
        [
            invoice(po.po_number, [
                InvoiceLine(style_code="RB-GROC-22", qty_billed=480, unit_price=Decimal("3.40")),
                InvoiceLine(style_code="RB-FLAT-27", qty_billed=960, unit_price=Decimal("1.85")),
            ]),
            invoice(other.po_number, [InvoiceLine(style_code="RB-GROC-22", qty_billed=10, unit_price=Decimal("1.00"))], number="INV-810-2002"),
        ],
        [container, on_time],
    )
    delayed = next(item for item in results if item.po_number == po.po_number)
    found = next(item for item in delayed.exceptions if item.rule == IssueRule.INBOUND_DELAY)
    assert found.risk == ChargebackRisk.HIGH
    assert found.dollar_impact == Decimal("3408.00")
    assert found.audience == "retailer"
    assert delayed.status == "Needs attention"
    assert next(item for item in results if item.po_number == other.po_number).exceptions == []
    line_text = inbound_log_line([container, on_time], {po.po_number: "BrightMart", other.po_number: "Coastal Pharmacy"})
    assert line_text == (
        "Checking inbound containers... ⚠️ Container MSKU-4471 now arrives Oct 14, "
        "after BrightMart's Oct 10 program launch"
    )


def test_duplicate_style_on_a_document_is_rejected():
    po = order([line(), line()])
    with pytest.raises(ValueError, match="Duplicate style"):
        match_one(
            po,
            ship(po.po_number, [ShipLine(style_code="RB-GROC-22", qty_shipped=1)]),
            invoice(po.po_number, [InvoiceLine(style_code="RB-GROC-22", qty_billed=1, unit_price=Decimal("2.10"))]),
        )
