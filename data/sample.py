"""Fictional 850 / 856 / 810 documents. Seed 42 keeps the book stable."""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from core.models import (
    InboundShipment,
    Invoice,
    InvoiceLine,
    OrderPacket,
    POLine,
    PurchaseOrder,
    ShipLine,
    ShipmentNotice,
)

SEED = 42
TUESDAY_SEED = 99

SAMPLE_DAYS = (
    {"id": "monday", "label": "Monday", "when": "September 28, 2026", "seed": SEED},
    {"id": "tuesday", "label": "Tuesday", "when": "September 29, 2026", "seed": TUESDAY_SEED},
)

QTYS = [240, 360, 480, 600, 720, 960]
PRICES = [
    Decimal("1.25"),
    Decimal("1.85"),
    Decimal("2.40"),
    Decimal("3.40"),
    Decimal("4.75"),
    Decimal("6.50"),
]
SHORT_GAPS = [40, 80, 120, 160]
PRICE_DELTAS = [Decimal("0.15"), Decimal("0.25"), Decimal("0.40")]

_SPECS = [
    {
        "po_number": "PO-850-1001",
        "retailer": "Northfield Grocers",
        "issue": "clean",
        "po_date": date(2026, 9, 2),
        "styles": (
            ("RB-TOTE-14", "Holiday 2026 insulated tote (Northfield program)"),
            ("RB-PROD-08", "Harvest mesh produce bag (Northfield program)"),
        ),
    },
    {
        "po_number": "PO-850-1002",
        "retailer": "Northfield Grocers",
        "issue": "short_ship",
        "po_date": date(2026, 9, 3),
        "styles": (
            ("RB-GROC-22", "Store grocery sack (Northfield program)"),
            ("RB-WINE-16", "Holiday bottle sleeve (Northfield program)"),
        ),
    },
    {
        "po_number": "PO-850-1003",
        "retailer": "BrightMart",
        "issue": "price_mismatch",
        "po_date": date(2026, 9, 4),
        "styles": (
            ("RB-SHOP-03", "Earth Month printed tote (BrightMart)"),
            ("RB-FLAT-27", "Earth Month kraft flat bag (BrightMart)"),
        ),
    },
    {
        "po_number": "PO-850-1004",
        "retailer": "BrightMart",
        "issue": "missing_line",
        "po_date": date(2026, 9, 5),
        "styles": (
            ("RB-SACK-11", "Bulk pantry sack (BrightMart)"),
            ("RB-MESH-19", "Fine mesh produce bag (BrightMart)"),
        ),
    },
    {
        "po_number": "PO-850-1005",
        "retailer": "Coastal Pharmacy",
        "issue": "late_ship",
        "po_date": date(2026, 9, 1),
        "styles": (
            ("RB-PHRM-07", "Everyday recycled PET tote (Coastal Pharmacy)"),
            ("RB-COOL-15", "Pharmacy insulated cooler (Coastal Pharmacy)"),
        ),
    },
    {
        "po_number": "PO-850-1006",
        "retailer": "Coastal Pharmacy",
        "issue": "clean",
        "po_date": date(2026, 9, 6),
        "styles": (
            ("RB-LUNCH-31", "Compact lunch tote (Coastal Pharmacy)"),
            ("RB-BULK-04", "Pharmacy roll bag (Coastal Pharmacy)"),
        ),
    },
]

_TUESDAY_SPECS = [
    {
        "po_number": "PO-850-2001",
        "retailer": "Coastal Pharmacy",
        "issue": "price_mismatch",
        "po_date": date(2026, 9, 15),
        "styles": (
            ("RB-PHRM-07", "Everyday recycled PET tote (Coastal Pharmacy)"),
            ("RB-COOL-15", "Pharmacy insulated cooler (Coastal Pharmacy)"),
        ),
    },
    {
        "po_number": "PO-850-2002",
        "retailer": "Coastal Pharmacy",
        "issue": "clean",
        "po_date": date(2026, 9, 16),
        "styles": (
            ("RB-LUNCH-31", "Compact lunch tote (Coastal Pharmacy)"),
            ("RB-BULK-04", "Pharmacy roll bag (Coastal Pharmacy)"),
        ),
    },
    {
        "po_number": "PO-850-2003",
        "retailer": "Northfield Grocers",
        "issue": "missing_line",
        "po_date": date(2026, 9, 17),
        "styles": (
            ("RB-SACK-11", "Bulk pantry sack (Northfield program)"),
            ("RB-MESH-19", "Fine mesh produce bag (Northfield program)"),
        ),
    },
    {
        "po_number": "PO-850-2004",
        "retailer": "Northfield Grocers",
        "issue": "late_ship",
        "po_date": date(2026, 9, 14),
        "styles": (
            ("RB-TOTE-14", "Holiday 2026 insulated tote (Northfield program)"),
            ("RB-PROD-08", "Harvest mesh produce bag (Northfield program)"),
        ),
    },
    {
        "po_number": "PO-850-2005",
        "retailer": "BrightMart",
        "issue": "short_ship",
        "po_date": date(2026, 9, 18),
        "styles": (
            ("RB-GROC-22", "Store grocery sack (BrightMart)"),
            ("RB-WINE-16", "Earth Month bottle sleeve (BrightMart)"),
        ),
    },
    {
        "po_number": "PO-850-2006",
        "retailer": "BrightMart",
        "issue": "clean",
        "po_date": date(2026, 9, 19),
        "styles": (
            ("RB-SHOP-03", "Earth Month printed tote (BrightMart)"),
            ("RB-FLAT-27", "Earth Month kraft flat bag (BrightMart)"),
        ),
    },
]

_INBOUND = {
    "monday": (
        InboundShipment(
            container_id="MSKU-2204",
            origin_port="Ningbo",
            factory="Linden Cut-and-Sew, Ningbo",
            eta=date(2026, 10, 2),
            po_number="PO-850-1001",
            launch_date=date(2026, 10, 8),
        ),
        InboundShipment(
            container_id="MSKU-2208",
            origin_port="Yantian",
            factory="Linden Cut-and-Sew, Yantian",
            eta=date(2026, 10, 6),
            po_number="PO-850-1006",
            launch_date=date(2026, 10, 12),
        ),
    ),
    "tuesday": (
        InboundShipment(
            container_id="MSKU-4471",
            origin_port="Ningbo",
            factory="Linden Cut-and-Sew, Ningbo",
            eta=date(2026, 10, 14),
            po_number="PO-850-2006",
            launch_date=date(2026, 10, 10),
        ),
        InboundShipment(
            container_id="MSKU-4480",
            origin_port="Laem Chabang",
            factory="Linden Cut-and-Sew, Laem Chabang",
            eta=date(2026, 10, 3),
            po_number="PO-850-2002",
            launch_date=date(2026, 10, 9),
        ),
    ),
}

_DAY_SPECS = {
    "monday": _SPECS,
    "tuesday": _TUESDAY_SPECS,
}


def build_inbound(day: str = "monday") -> list[InboundShipment]:
    """Factory containers for the sample day. Tuesday's MSKU-4471 misses its launch."""
    containers = _INBOUND.get(day)
    if containers is None:
        raise ValueError(f"Unknown sample day {day}.")
    return list(containers)


def build_sample(seed: int = SEED, day: str = "monday") -> list[OrderPacket]:
    """Build six fictional orders. Four carry one planted problem; two are clean."""
    specs = _DAY_SPECS.get(day)
    if specs is None:
        raise ValueError(f"Unknown sample day {day}.")
    rng = random.Random(seed)
    packets: list[OrderPacket] = []
    for spec in specs:
        po_date: date = spec["po_date"]
        ship_by = po_date + timedelta(days=10)
        cancel_date = po_date + timedelta(days=16)
        ship_date = po_date + timedelta(days=8)
        po_lines = [
            POLine(
                style_code=code,
                description=description,
                qty=rng.choice(QTYS),
                unit_price=rng.choice(PRICES),
            )
            for code, description in spec["styles"]
        ]
        ship_lines = [ShipLine(style_code=line.style_code, qty_shipped=line.qty) for line in po_lines]
        invoice_lines = [
            InvoiceLine(style_code=line.style_code, qty_billed=line.qty, unit_price=line.unit_price)
            for line in po_lines
        ]
        issue = spec["issue"]
        if issue == "short_ship":
            gap = rng.choice(SHORT_GAPS)
            shipped = po_lines[0].qty - gap
            if shipped < 1:
                shipped = max(1, po_lines[0].qty // 2)
            ship_lines[0] = ShipLine(style_code=po_lines[0].style_code, qty_shipped=shipped)
            invoice_lines[0] = InvoiceLine(
                style_code=po_lines[0].style_code,
                qty_billed=shipped,
                unit_price=po_lines[0].unit_price,
            )
        elif issue == "price_mismatch":
            invoice_lines[0] = InvoiceLine(
                style_code=po_lines[0].style_code,
                qty_billed=po_lines[0].qty,
                unit_price=po_lines[0].unit_price + rng.choice(PRICE_DELTAS),
            )
        elif issue == "missing_line":
            ship_lines = ship_lines[:1]
            invoice_lines = invoice_lines[:1]
        elif issue == "late_ship":
            ship_date = cancel_date + timedelta(days=rng.randint(1, 4))

        suffix = spec["po_number"].rsplit("-", 1)[-1]
        packets.append(
            OrderPacket(
                purchase_order=PurchaseOrder(
                    po_number=spec["po_number"],
                    retailer=spec["retailer"],
                    po_date=po_date,
                    ship_by=ship_by,
                    cancel_date=cancel_date,
                    line_items=po_lines,
                ),
                shipment=ShipmentNotice(
                    po_number=spec["po_number"],
                    ship_date=ship_date,
                    line_items=ship_lines,
                ),
                invoice=Invoice(
                    invoice_number=f"INV-810-{suffix}",
                    po_number=spec["po_number"],
                    line_items=invoice_lines,
                ),
                injected_issue=issue,
            )
        )
    return packets


def as_edi(packet: OrderPacket) -> dict:
    """Three simplified EDI JSON records for one order: 850, 856, and 810."""
    return {
        "850": packet.purchase_order.model_dump(mode="json"),
        "856": packet.shipment.model_dump(mode="json"),
        "810": packet.invoice.model_dump(mode="json"),
    }
