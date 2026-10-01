"""Shared records for purchase orders, shipments, invoices, and exceptions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

CENT = Decimal("0.01")


def cents(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(value: Decimal) -> str:
    return f"${cents(value):,.2f}"


def pretty_date(value: date) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


class ChargebackRisk(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class IssueRule(str, Enum):
    SHORT_SHIP = "short_ship"
    QTY_BILLED = "qty_billed"
    PRICE = "price_mismatch"
    MISSING_LINE = "missing_line"
    LATE_SHIP = "late_ship"
    INBOUND_DELAY = "inbound_delay"


class Tone(str, Enum):
    OK = "ok"
    AMBER = "amber"
    RED = "red"


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _price(value: object) -> Decimal:
    return cents(Decimal(str(value)))


class POLine(_Record):
    style_code: str
    description: str
    qty: int
    unit_price: Decimal

    @field_validator("unit_price", mode="before")
    @classmethod
    def _round_price(cls, value: object) -> Decimal:
        return _price(value)


class PurchaseOrder(_Record):
    po_number: str
    retailer: str
    po_date: date
    ship_by: date
    cancel_date: date
    line_items: list[POLine]


class ShipLine(_Record):
    style_code: str
    qty_shipped: int


class ShipmentNotice(_Record):
    po_number: str
    ship_date: date
    line_items: list[ShipLine]


class InboundShipment(_Record):
    """A factory container headed for one purchase order."""

    container_id: str
    origin_port: str
    factory: str
    eta: date
    po_number: str
    launch_date: date


class InvoiceLine(_Record):
    style_code: str
    qty_billed: int
    unit_price: Decimal

    @field_validator("unit_price", mode="before")
    @classmethod
    def _round_price(cls, value: object) -> Decimal:
        return _price(value)


class Invoice(_Record):
    invoice_number: str
    po_number: str
    line_items: list[InvoiceLine]


class OrderPacket(_Record):
    """One PO plus its 856 and 810, and the issue planted in the sample."""

    purchase_order: PurchaseOrder
    shipment: ShipmentNotice
    invoice: Invoice
    injected_issue: Literal["clean", "short_ship", "price_mismatch", "missing_line", "late_ship"]


class LineView(_Record):
    style_code: str
    description: str
    ordered_qty: int | None
    ordered_price: Decimal | None
    shipped_qty: int | None
    billed_qty: int | None
    billed_price: Decimal | None
    ordered_tone: Tone
    shipped_tone: Tone
    invoiced_tone: Tone

    @field_validator("ordered_price", "billed_price", mode="before")
    @classmethod
    def _round_price(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _price(value)


class ExceptionRecord(_Record):
    po_number: str
    retailer: str
    invoice_number: str | None
    style_code: str | None
    description: str | None
    rule: IssueRule
    risk: ChargebackRisk
    dollar_impact: Decimal
    explanation: str
    audience: Literal["warehouse", "retailer"]
    ordered_qty: int | None = None
    shipped_qty: int | None = None
    billed_qty: int | None = None
    po_price: Decimal | None = None
    invoice_price: Decimal | None = None
    ship_date: date | None = None
    cancel_date: date | None = None

    @field_validator("dollar_impact", "po_price", "invoice_price", mode="before")
    @classmethod
    def _round_money(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _price(value)

    @property
    def key(self) -> str:
        return f"{self.po_number}-{self.rule.value}-{self.style_code or 'order'}"


class OrderMatch(_Record):
    po_number: str
    retailer: str
    po_date: date
    ship_by: date
    cancel_date: date
    ship_date: date | None
    invoice_number: str | None
    lines: list[LineView]
    exceptions: list[ExceptionRecord]
    status: Literal["Clean", "Needs attention"]

    @property
    def high_risk(self) -> bool:
        return any(item.risk == ChargebackRisk.HIGH for item in self.exceptions)

    @property
    def exposure(self) -> Decimal:
        return cents(sum((item.dollar_impact for item in self.exceptions), Decimal("0")))
