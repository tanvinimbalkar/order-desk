"""Draft emails use the exception's own figures."""

from datetime import date
from decimal import Decimal

from core.email import draft_email
from core.match import match_one
from core.models import (
    ChargebackRisk,
    ExceptionRecord,
    Invoice,
    InvoiceLine,
    IssueRule,
    POLine,
    PurchaseOrder,
    ShipLine,
    ShipmentNotice,
)


def _match(shipped, billed, po_price, invoice_price, ship_date=date(2026, 9, 10), cancel=date(2026, 9, 20)):
    po = PurchaseOrder(
        po_number="PO-850-5001",
        retailer="BrightMart",
        po_date=date(2026, 9, 4),
        ship_by=date(2026, 9, 14),
        cancel_date=cancel,
        line_items=[POLine(style_code="RB-SHOP-03", description="Shopping bag, wide gusset", qty=100, unit_price=Decimal(po_price))],
    )
    return match_one(
        po,
        ShipmentNotice(
            po_number=po.po_number,
            ship_date=ship_date,
            line_items=[ShipLine(style_code="RB-SHOP-03", qty_shipped=shipped)],
        ),
        Invoice(
            invoice_number="INV-810-5001",
            po_number=po.po_number,
            line_items=[InvoiceLine(style_code="RB-SHOP-03", qty_billed=billed, unit_price=Decimal(invoice_price))],
        ),
    )


def test_short_shipment_email_goes_to_the_warehouse_with_the_real_gap():
    result = _match(80, 80, "2.00", "2.00")
    found = next(item for item in result.exceptions if item.rule == IssueRule.SHORT_SHIP)
    draft = draft_email(found)
    assert draft.audience == "warehouse"
    assert draft.to == "shipping@lindensupply.example"
    rendered = draft.rendered
    assert "PO-850-5001" in rendered
    assert "BrightMart" in rendered
    assert "$40.00" in rendered
    assert found.explanation in rendered
    assert found.risk == ChargebackRisk.MEDIUM


def test_late_shipment_email_asks_the_buyer_to_accept_it():
    result = _match(100, 100, "6.50", "6.50", ship_date=date(2026, 9, 18), cancel=date(2026, 9, 17))
    result.exceptions[0].retailer = "Coastal Pharmacy"
    found = next(item for item in result.exceptions if item.rule == IssueRule.LATE_SHIP)
    draft = draft_email(found)
    assert draft.to == "buyer@coastalpharmacy.example"
    assert draft.subject == "Request to accept late shipment: PO-850-5001"
    assert "accept this shipment rather than refuse it" in draft.rendered
    assert "$650.00" in draft.rendered
    assert "September 18, 2026" in draft.rendered
    assert "September 17, 2026" in draft.rendered


def test_inbound_delay_email_asks_the_buyer_for_a_split_or_a_new_launch():
    found = ExceptionRecord(
        po_number="PO-850-2006",
        retailer="BrightMart",
        invoice_number="INV-810-2006",
        style_code=None,
        description=None,
        rule=IssueRule.INBOUND_DELAY,
        risk=ChargebackRisk.HIGH,
        dollar_impact=Decimal("3408.00"),
        explanation=(
            "Container MSKU-4471 from Linden Cut-and-Sew, Ningbo (Ningbo) now arrives October 14, 2026, "
            "after BrightMart's October 10, 2026 program launch. The purchase order value of $3,408.00 is at risk."
        ),
        audience="retailer",
    )
    draft = draft_email(found)
    assert draft.to == "buyer@brightmart.example"
    assert draft.subject == "Inbound container delay: PO-850-2006"
    assert "split shipment" in draft.rendered
    assert "revised launch date" in draft.rendered
    assert "$3,408.00" in draft.rendered
    assert "October 14, 2026" in draft.rendered
    assert "October 10, 2026" in draft.rendered
    assert "shipping@lindensupply.example" not in draft.rendered


def test_price_email_goes_to_the_retailer():
    result = _match(100, 100, "3.40", "3.85")
    found = next(item for item in result.exceptions if item.rule == IssueRule.PRICE)
    draft = draft_email(found)
    assert draft.audience == "retailer"
    assert draft.to == "accounts@brightmart.example"
    assert "INV-810-5001" in draft.rendered
    assert "$45.00" in draft.rendered
    assert "hold any deduction" in draft.rendered
