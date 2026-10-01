"""Template emails filled with the figures already on an exception."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from core.models import ExceptionRecord, IssueRule, format_money


class EmailDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    audience: str
    to: str
    subject: str
    body: str

    @property
    def rendered(self) -> str:
        return f"To: {self.to}\nSubject: {self.subject}\n\n{self.body}"


def draft_email(exception: ExceptionRecord) -> EmailDraft:
    money = format_money(exception.dollar_impact)
    if exception.rule == IssueRule.INBOUND_DELAY:
        slug = re.sub(r"[^a-z0-9]+", "", exception.retailer.lower())
        return EmailDraft(
            audience="retailer",
            to=f"buyer@{slug}.example",
            subject=f"Inbound container delay: {exception.po_number}",
            body=(
                f"Hello {exception.retailer},\n\n"
                "Please choose a split shipment or a revised launch date.\n\n"
                f"{exception.explanation}\n\n"
                f"Chargeback risk: {exception.risk.value}\n"
                f"Exposure: {money}\n\n"
                "Thank you,\n"
                "Order Desk\n"
                "Linden Supply"
            ),
        )
    if exception.rule == IssueRule.LATE_SHIP:
        slug = re.sub(r"[^a-z0-9]+", "", exception.retailer.lower())
        return EmailDraft(
            audience="retailer",
            to=f"buyer@{slug}.example",
            subject=f"Request to accept late shipment: {exception.po_number}",
            body=(
                f"Hello {exception.retailer},\n\n"
                f"Please accept this shipment rather than refuse it.\n\n"
                f"{exception.explanation}\n\n"
                f"Chargeback risk: {exception.risk.value}\n"
                f"Exposure: {money}\n\n"
                "Thank you,\n"
                "Order Desk\n"
                "Linden Supply"
            ),
        )
    if exception.audience == "warehouse":
        return EmailDraft(
            audience="warehouse",
            to="shipping@lindensupply.example",
            subject=f"Action needed — {exception.po_number} for {exception.retailer}",
            body=(
                "Hello warehouse team,\n\n"
                f"Purchase order {exception.po_number} for {exception.retailer} needs a correction "
                "before it becomes a chargeback.\n\n"
                f"{exception.explanation}\n\n"
                f"Chargeback risk: {exception.risk.value}\n"
                f"Exposure: {money}\n\n"
                "Please confirm the fix and reply with the updated count or ship date today.\n\n"
                "Thank you,\n"
                "Order Desk\n"
                "Linden Supply"
            ),
        )
    slug = re.sub(r"[^a-z0-9]+", "-", exception.retailer.lower()).strip("-")
    invoice = exception.invoice_number or "the open invoice"
    return EmailDraft(
        audience="retailer",
        to=f"accounts@{slug}.example",
        subject=f"Please hold a deduction — {exception.po_number}",
        body=(
            f"Hello {exception.retailer} team,\n\n"
            f"We are correcting invoice {invoice} against purchase order {exception.po_number}.\n\n"
            f"{exception.explanation}\n\n"
            f"Chargeback risk: {exception.risk.value}\n"
            f"Exposure: {money}\n\n"
            f"Please hold any deduction while we send a corrected invoice for {money}.\n\n"
            "Thank you,\n"
            "Order Desk\n"
            "Linden Supply"
        ),
    )
