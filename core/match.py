"""Match 850 / 856 / 810 documents and flag chargeback exceptions.

Matching is by po_number, then by style_code. Dollar exposure is computed
per rule. A line that is absent is a missing line, not a short shipment.
"""

from __future__ import annotations

from decimal import Decimal

from core.models import (
    ChargebackRisk,
    ExceptionRecord,
    InboundShipment,
    Invoice,
    InvoiceLine,
    IssueRule,
    LineView,
    OrderMatch,
    POLine,
    PurchaseOrder,
    ShipLine,
    ShipmentNotice,
    Tone,
    cents,
    format_money,
    pretty_date,
)

_SHORT_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

RISK_ORDER = {
    ChargebackRisk.HIGH: 0,
    ChargebackRisk.MEDIUM: 1,
    ChargebackRisk.LOW: 2,
}


def match_orders(
    orders: list[PurchaseOrder],
    shipments: list[ShipmentNotice],
    invoices: list[Invoice],
    inbound: list[InboundShipment] | None = None,
) -> list[OrderMatch]:
    """Pair each purchase order to the shipment and invoice with the same PO number."""
    shipments_by_po = _unique_by_po(shipments, "shipment notice")
    invoices_by_po = _unique_by_po(invoices, "invoice")
    results = [
        match_one(
            order,
            shipments_by_po.get(order.po_number),
            invoices_by_po.get(order.po_number),
        )
        for order in orders
    ]
    _apply_inbound(results, orders, inbound or [])
    return results


def inbound_log_line(containers: list[InboundShipment], retailer_for: dict[str, str]) -> str:
    """One morning-check line for the inbound containers on this day."""
    late = [item for item in containers if item.eta > item.launch_date]
    if not late:
        return "Checking inbound containers... ✓ On time"
    notes = []
    for item in late:
        retailer = retailer_for[item.po_number]
        arrived = f"{_SHORT_MONTHS[item.eta.month - 1]} {item.eta.day}"
        launch = f"{_SHORT_MONTHS[item.launch_date.month - 1]} {item.launch_date.day}"
        notes.append(
            f"⚠️ Container {item.container_id} now arrives {arrived}, "
            f"after {retailer}'s {launch} program launch"
        )
    return "Checking inbound containers... " + " ".join(notes)


def _apply_inbound(
    results: list[OrderMatch],
    orders: list[PurchaseOrder],
    inbound: list[InboundShipment],
) -> None:
    """A revised ETA after the program launch is a high-risk delay for the whole PO."""
    by_po = {order.po_number: order for order in orders}
    by_result = {result.po_number: result for result in results}
    for container in inbound:
        if container.eta <= container.launch_date:
            continue
        order = by_po.get(container.po_number)
        result = by_result.get(container.po_number)
        if order is None or result is None:
            continue
        impact = cents(sum((extend(line.qty, line.unit_price) for line in order.line_items), Decimal("0")))
        result.exceptions.append(
            ExceptionRecord(
                po_number=order.po_number,
                retailer=order.retailer,
                invoice_number=result.invoice_number,
                style_code=None,
                description=None,
                rule=IssueRule.INBOUND_DELAY,
                risk=ChargebackRisk.HIGH,
                dollar_impact=impact,
                explanation=(
                    f"Container {container.container_id} from {container.factory} "
                    f"({container.origin_port}) now arrives {pretty_date(container.eta)}, "
                    f"after {order.retailer}'s {pretty_date(container.launch_date)} program launch. "
                    f"The purchase order value of {format_money(impact)} is at risk."
                ),
                audience="retailer",
                ship_date=container.eta,
                cancel_date=container.launch_date,
            )
        )
        result.status = "Needs attention"


def match_one(
    order: PurchaseOrder,
    shipment: ShipmentNotice | None,
    invoice: Invoice | None,
) -> OrderMatch:
    if shipment is not None and shipment.po_number != order.po_number:
        shipment = None
    if invoice is not None and invoice.po_number != order.po_number:
        invoice = None

    po_lines = _by_style(order.line_items, order.po_number)
    ship_lines = _by_style(shipment.line_items, shipment.po_number) if shipment else {}
    invoice_lines = _by_style(invoice.line_items, invoice.po_number) if invoice else {}
    late = shipment is not None and shipment.ship_date > order.cancel_date
    invoice_number = invoice.invoice_number if invoice else None

    exceptions: list[ExceptionRecord] = []
    if late and shipment is not None:
        impact = cents(sum((extend(line.qty, line.unit_price) for line in order.line_items), Decimal("0")))
        exceptions.append(
            ExceptionRecord(
                po_number=order.po_number,
                retailer=order.retailer,
                invoice_number=invoice_number,
                style_code=None,
                description=None,
                rule=IssueRule.LATE_SHIP,
                risk=ChargebackRisk.HIGH,
                dollar_impact=impact,
                explanation=(
                    f"Shipment left on {pretty_date(shipment.ship_date)}, after the cancel date "
                    f"of {pretty_date(order.cancel_date)}. The purchase order value of "
                    f"{format_money(impact)} can be refused."
                ),
                audience="warehouse",
                ship_date=shipment.ship_date,
                cancel_date=order.cancel_date,
            )
        )

    style_codes = list(po_lines)
    for code in ship_lines:
        if code not in po_lines and code not in style_codes:
            style_codes.append(code)
    for code in invoice_lines:
        if code not in po_lines and code not in style_codes:
            style_codes.append(code)

    lines: list[LineView] = []
    for code in style_codes:
        po_line = po_lines.get(code)
        ship_line = ship_lines.get(code)
        invoice_line = invoice_lines.get(code)
        exceptions.extend(
            _line_exceptions(
                order,
                invoice_number,
                po_line,
                ship_line,
                invoice_line,
                code,
            )
        )
        lines.append(_line_view(po_line, ship_line, invoice_line, code, late))

    status = "Needs attention" if exceptions else "Clean"
    return OrderMatch(
        po_number=order.po_number,
        retailer=order.retailer,
        po_date=order.po_date,
        ship_by=order.ship_by,
        cancel_date=order.cancel_date,
        ship_date=shipment.ship_date if shipment else None,
        invoice_number=invoice_number,
        lines=lines,
        exceptions=exceptions,
        status=status,
    )


def ranked_exceptions(results: list[OrderMatch]) -> list[ExceptionRecord]:
    """Exceptions for every list: High, then Medium, then Low, then dollars."""
    found = [item for order in results for item in order.exceptions]
    return sorted(found, key=lambda item: (RISK_ORDER[item.risk], -item.dollar_impact, item.po_number, item.key))


def ranked_for_brief(results: list[OrderMatch]) -> list[ExceptionRecord]:
    """Exceptions for the COO brief: chargeback risk, then dollar impact."""
    found = [item for order in results for item in order.exceptions]
    return sorted(found, key=lambda item: (RISK_ORDER[item.risk], -item.dollar_impact, item.po_number, item.key))


def _line_exceptions(
    order: PurchaseOrder,
    invoice_number: str | None,
    po_line: POLine | None,
    ship_line: ShipLine | None,
    invoice_line: InvoiceLine | None,
    style_code: str,
) -> list[ExceptionRecord]:
    found: list[ExceptionRecord] = []
    description = po_line.description if po_line else "Not on the purchase order"

    if po_line and ship_line is None and invoice_line is None:
        impact = extend(po_line.qty, po_line.unit_price)
        found.append(
            _exception(
                order,
                invoice_number,
                IssueRule.MISSING_LINE,
                ChargebackRisk.HIGH,
                impact,
                (
                    f"{description} ({style_code}) is on the purchase order for "
                    f"{po_line.qty:,} units and is missing from the shipment and the invoice "
                    f"({format_money(impact)})."
                ),
                "warehouse",
                style_code,
                description,
                ordered_qty=po_line.qty,
                po_price=po_line.unit_price,
            )
        )
        return found

    if po_line and ship_line is None:
        impact = extend(po_line.qty, po_line.unit_price)
        found.append(
            _exception(
                order,
                invoice_number,
                IssueRule.MISSING_LINE,
                ChargebackRisk.HIGH,
                impact,
                (
                    f"{description} ({style_code}) is on the purchase order for "
                    f"{po_line.qty:,} units and is missing from the shipment ({format_money(impact)})."
                ),
                "warehouse",
                style_code,
                description,
                ordered_qty=po_line.qty,
                billed_qty=invoice_line.qty_billed if invoice_line else None,
                po_price=po_line.unit_price,
                invoice_price=invoice_line.unit_price if invoice_line else None,
            )
        )
    elif po_line and ship_line and ship_line.qty_shipped < po_line.qty:
        gap = po_line.qty - ship_line.qty_shipped
        impact = extend(gap, po_line.unit_price)
        found.append(
            _exception(
                order,
                invoice_number,
                IssueRule.SHORT_SHIP,
                ChargebackRisk.MEDIUM,
                impact,
                (
                    f"Shipped {ship_line.qty_shipped:,} of {po_line.qty:,} {description} ({style_code}). "
                    f"{gap:,} units did not ship ({format_money(impact)})."
                ),
                "warehouse",
                style_code,
                description,
                ordered_qty=po_line.qty,
                shipped_qty=ship_line.qty_shipped,
                po_price=po_line.unit_price,
            )
        )

    if po_line and invoice_line is None:
        qty = ship_line.qty_shipped if ship_line else po_line.qty
        impact = extend(qty, po_line.unit_price)
        shipped_note = f"shipped ({qty:,} units) but is" if ship_line else "is"
        found.append(
            _exception(
                order,
                invoice_number,
                IssueRule.MISSING_LINE,
                ChargebackRisk.HIGH,
                impact,
                (
                    f"{description} ({style_code}) {shipped_note} missing from the invoice "
                    f"({format_money(impact)})."
                ),
                "retailer",
                style_code,
                description,
                ordered_qty=po_line.qty,
                shipped_qty=ship_line.qty_shipped if ship_line else None,
                po_price=po_line.unit_price,
            )
        )
    elif invoice_line and po_line is None:
        price = invoice_line.unit_price
        impact = extend(invoice_line.qty_billed, price)
        found.append(
            _exception(
                order,
                invoice_number,
                IssueRule.MISSING_LINE,
                ChargebackRisk.HIGH,
                impact,
                (
                    f"{style_code} is on the shipment or invoice and is missing from the purchase order "
                    f"({format_money(impact)})."
                ),
                "retailer",
                style_code,
                description,
                shipped_qty=ship_line.qty_shipped if ship_line else None,
                billed_qty=invoice_line.qty_billed,
                invoice_price=price,
            )
        )

    if ship_line and invoice_line and invoice_line.qty_billed != ship_line.qty_shipped:
        gap = abs(invoice_line.qty_billed - ship_line.qty_shipped)
        impact = extend(gap, invoice_line.unit_price)
        found.append(
            _exception(
                order,
                invoice_number,
                IssueRule.QTY_BILLED,
                ChargebackRisk.MEDIUM,
                impact,
                (
                    f"The invoice bills {invoice_line.qty_billed:,} of {description} ({style_code}), "
                    f"but {ship_line.qty_shipped:,} shipped. The {gap:,}-unit difference is {format_money(impact)}."
                ),
                "retailer",
                style_code,
                description,
                ordered_qty=po_line.qty if po_line else None,
                shipped_qty=ship_line.qty_shipped,
                billed_qty=invoice_line.qty_billed,
                po_price=po_line.unit_price if po_line else None,
                invoice_price=invoice_line.unit_price,
            )
        )

    if po_line is None and ship_line is not None and invoice_line is None:
        found.append(
            _exception(
                order,
                invoice_number,
                IssueRule.MISSING_LINE,
                ChargebackRisk.HIGH,
                Decimal("0.00"),
                (
                    f"{style_code} is on the shipment ({ship_line.qty_shipped:,} units) and is missing "
                    f"from the purchase order. No invoice price was on file, so the exposure is {format_money(Decimal('0.00'))}."
                ),
                "warehouse",
                style_code,
                description,
                shipped_qty=ship_line.qty_shipped,
            )
        )
        return found

    if po_line and invoice_line and invoice_line.unit_price != po_line.unit_price:
        delta = abs(invoice_line.unit_price - po_line.unit_price)
        impact = extend(invoice_line.qty_billed, delta)
        found.append(
            _exception(
                order,
                invoice_number,
                IssueRule.PRICE,
                ChargebackRisk.LOW,
                impact,
                (
                    f"Invoice price for {description} ({style_code}) is {format_money(invoice_line.unit_price)}, "
                    f"but the purchase order price is {format_money(po_line.unit_price)}. "
                    f"The difference on {invoice_line.qty_billed:,} units is {format_money(impact)}."
                ),
                "retailer",
                style_code,
                description,
                ordered_qty=po_line.qty,
                billed_qty=invoice_line.qty_billed,
                po_price=po_line.unit_price,
                invoice_price=invoice_line.unit_price,
            )
        )
    return found


def _exception(
    order: PurchaseOrder,
    invoice_number: str | None,
    rule: IssueRule,
    risk: ChargebackRisk,
    impact: Decimal,
    explanation: str,
    audience: str,
    style_code: str | None,
    description: str | None,
    ordered_qty: int | None = None,
    shipped_qty: int | None = None,
    billed_qty: int | None = None,
    po_price: Decimal | None = None,
    invoice_price: Decimal | None = None,
) -> ExceptionRecord:
    return ExceptionRecord(
        po_number=order.po_number,
        retailer=order.retailer,
        invoice_number=invoice_number,
        style_code=style_code,
        description=description,
        rule=rule,
        risk=risk,
        dollar_impact=impact,
        explanation=explanation,
        audience=audience,  # type: ignore[arg-type]
        ordered_qty=ordered_qty,
        shipped_qty=shipped_qty,
        billed_qty=billed_qty,
        po_price=po_price,
        invoice_price=invoice_price,
        cancel_date=order.cancel_date,
    )


def _line_view(
    po_line: POLine | None,
    ship_line: ShipLine | None,
    invoice_line: InvoiceLine | None,
    style_code: str,
    late: bool,
) -> LineView:
    ordered_tone = Tone.OK if po_line else Tone.RED
    if po_line and ship_line is None:
        shipped_tone = Tone.RED
    elif po_line and ship_line and ship_line.qty_shipped < po_line.qty:
        shipped_tone = Tone.AMBER
    elif ship_line and po_line is None:
        shipped_tone = Tone.RED
    else:
        shipped_tone = Tone.OK
    if late and (ship_line is not None or po_line is not None):
        shipped_tone = Tone.RED

    if po_line and invoice_line is None:
        invoiced_tone = Tone.RED
    elif invoice_line and po_line is None:
        invoiced_tone = Tone.RED
    elif invoice_line and po_line and (
        invoice_line.unit_price != po_line.unit_price
        or (ship_line is not None and invoice_line.qty_billed != ship_line.qty_shipped)
    ):
        invoiced_tone = Tone.AMBER
    else:
        invoiced_tone = Tone.OK

    return LineView(
        style_code=style_code,
        description=po_line.description if po_line else "Not on the purchase order",
        ordered_qty=po_line.qty if po_line else None,
        ordered_price=po_line.unit_price if po_line else None,
        shipped_qty=ship_line.qty_shipped if ship_line else None,
        billed_qty=invoice_line.qty_billed if invoice_line else None,
        billed_price=invoice_line.unit_price if invoice_line else None,
        ordered_tone=ordered_tone,
        shipped_tone=shipped_tone,
        invoiced_tone=invoiced_tone,
    )


def _by_style(lines: list, document_id: str) -> dict:
    found: dict = {}
    for line in lines:
        if line.style_code in found:
            raise ValueError(f"Duplicate style {line.style_code} on {document_id}.")
        found[line.style_code] = line
    return found


def _unique_by_po(documents: list, label: str) -> dict:
    found: dict = {}
    for document in documents:
        if document.po_number in found:
            raise ValueError(f"Duplicate {label} for {document.po_number}.")
        found[document.po_number] = document
    return found


def extend(qty: int, price: Decimal) -> Decimal:
    return cents(Decimal(qty) * price)
