"""Order Desk — catch order, shipment, and invoice problems before retailers do."""

from __future__ import annotations

import html
import inspect
import json
import logging
import re
import time
from decimal import Decimal

import streamlit as st

from core.brief import morning_brief
from core.chat import CHIPS, LIMIT_MESSAGE, QUESTION_LIMIT, ask
from core.email import draft_email
from core.match import inbound_log_line, match_orders
from core.models import ExceptionRecord, OrderMatch, Tone, format_money, pretty_date
from core.summary import desk_numbers, ordered_exceptions
from data.sample import SAMPLE_DAYS, build_inbound, build_sample

logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="Order Desk",
    page_icon="👜",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,560;9..144,640&family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"], .stApp, .stMarkdown, .stCaption, button, input, textarea {
  font-family: Inter, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: #1E2A2A;
}
.stApp { background: #F7F4EE; }
header[data-testid="stHeader"], .stAppHeader { display: none !important; }
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], .stDeployButton, [data-testid="stAppDeployButton"],
[data-testid="stMainMenu"], header [data-testid="stToolbar"] { display: none !important; }
a.header-anchor, .stMarkdown h1 a, .stMarkdown h2 a, .stHeading a { display: none !important; }
.block-container {
  max-width: 1100px !important;
  padding-top: 1.6rem !important;
  padding-bottom: 2.5rem !important;
}
.mast { margin: 0 0 1.1rem; }
.kicker, .eyebrow {
  margin: 0 0 0.35rem;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #1F5F5B;
}
.mast h1 {
  margin: 0;
  font-family: Fraunces, Georgia, "Times New Roman", serif !important;
  font-weight: 560;
  font-size: 3.1rem;
  letter-spacing: -0.03em;
  line-height: 1.05;
  color: #1E2A2A;
}
.tagline {
  margin: 0.55rem 0 0;
  max-width: 38rem;
  font-size: 1.08rem;
  line-height: 1.45;
  color: #1E2A2A;
}
.card, .metric {
  background: #ffffff;
  border: 1px solid #E6DFD4;
  border-radius: 18px;
  box-shadow: 0 10px 30px rgba(30, 42, 42, 0.06);
}
.card { padding: 1.15rem 1.2rem 1.2rem; margin: 0 0 0.85rem; scroll-margin-top: 0.75rem; }
.brief p { margin: 0 0 0.65rem; line-height: 1.55; font-size: 1.02rem; }
.brief p:last-child { margin-bottom: 0; }
.metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0.75rem;
  margin-top: 0.9rem;
}
.since { margin: 0.15rem 0 0.85rem; color: #1E2A2A; }
.draft-line { margin: 0.15rem 0 0; line-height: 1.4; }
[class*="st-key-actions-"] .stButton > button,
[class*="st-key-draft-"] .stButton > button {
  width: auto !important;
}
.metric { padding: 0.9rem 1rem 1rem; }
.metric-label {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #1F5F5B;
  white-space: nowrap;
}
.metric-value {
  margin: 0.3rem 0 0;
  font-family: Fraunces, Georgia, serif !important;
  font-size: 1.85rem;
  letter-spacing: -0.03em;
  line-height: 1.1;
}
.lede { margin: 0.2rem 0 0.85rem; color: #1E2A2A; }
.card-head, .exc-top {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
}
.po-title {
  margin: 0;
  font-family: Fraunces, Georgia, serif !important;
  font-size: 1.55rem;
  letter-spacing: -0.02em;
  line-height: 1.15;
}
.meta, .exposure, .explain, .who, .follow {
  margin: 0.2rem 0 0;
  line-height: 1.45;
}
.meta.bad { color: #B23A3A; font-weight: 600; }
.exposure { color: #1F5F5B; font-weight: 600; margin-top: 0.45rem; }
.badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.28rem 0.7rem;
  font-size: 0.78rem;
  font-weight: 600;
  white-space: nowrap;
}
.badge.clean { background: #E5F1EF; color: #1F5F5B; }
.badge.attention { background: #F8EFE4; color: #C8742B; }
.badge.high { background: #F8E8E8; color: #B23A3A; }
.badge.medium { background: #F8EFE4; color: #C8742B; }
.badge.low { background: #EEEAE4; color: #5C5852; }
.badge.resolved { background: #E5F1EF; color: #1F5F5B; }
.card.highlight { box-shadow: 0 0 0 3px #1F5F5B, 0 10px 30px rgba(30, 42, 42, 0.06); }
.banner {
  background: #E5F1EF;
  border: 1px solid #1F5F5B;
  border-radius: 18px;
  padding: 0.9rem 1.1rem;
  margin: 0 0 0.85rem;
  font-weight: 600;
}
[class*="st-key-run-"] button {
  font-size: 1.08rem !important;
  padding: 0.85rem 1.5rem !important;
}
.line { margin-top: 0.95rem; padding-top: 0.9rem; border-top: 1px solid #EFE8DE; }
.style { display: flex; flex-direction: column; gap: 0.1rem; margin-bottom: 0.55rem; }
.style strong { font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace; font-size: 0.92rem; }
.style span { color: #1E2A2A; }
.cols { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.55rem; }
.cell {
  border-radius: 12px;
  padding: 0.65rem 0.75rem 0.7rem;
  background: #FBF9F5;
  min-height: 4.4rem;
}
.cell.amber { background: #FBF3EA; box-shadow: inset 0 0 0 1px #E7C19A; }
.cell.red { background: #F8ECEC; box-shadow: inset 0 0 0 1px #E4B4B4; }
.cell-k {
  display: block;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #1F5F5B;
}
.cell.amber .cell-k { color: #C8742B; }
.cell.red .cell-k { color: #B23A3A; }
.cell-v {
  display: block;
  margin-top: 0.2rem;
  font-family: Fraunces, Georgia, serif;
  font-size: 1.35rem;
  letter-spacing: -0.02em;
}
.cell-s { display: block; margin-top: 0.15rem; font-size: 0.88rem; }
.exc-side { text-align: right; }
.impact {
  margin: 0 0 0.35rem;
  font-family: Fraunces, Georgia, serif;
  font-size: 1.45rem;
  letter-spacing: -0.02em;
}
.who { font-weight: 600; margin: 0; }
.po-line { margin: 0.15rem 0 0; font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.88rem; }
.explain { margin-top: 0.75rem; }
.follow { margin-top: 0.45rem; color: #1F5F5B; font-weight: 600; font-size: 0.92rem; }
.legend { margin: 0 0 0.8rem; font-size: 0.92rem; }
.swatch {
  display: inline-block;
  width: 0.7rem;
  height: 0.7rem;
  border-radius: 3px;
  margin: 0 0.4rem 0 0.85rem;
  vertical-align: -1px;
}
.legend .swatch:first-child { margin-left: 0; }
.swatch.amber { background: #C8742B; }
.swatch.red { background: #B23A3A; }
.footer {
  margin: 1.4rem 0 0;
  text-align: center;
  font-size: 0.88rem;
  color: #1E2A2A;
}
div[data-testid="stVerticalBlockBorderWrapper"],
[class*="st-key-actioncard-"] {
  background: #ffffff !important;
  border: 1px solid #E6DFD4 !important;
  border-radius: 18px !important;
  box-shadow: 0 10px 30px rgba(30, 42, 42, 0.06) !important;
  padding: 0.9rem 1rem 1rem !important;
  margin: 0 0 0.85rem !important;
}
.stTabs [data-baseweb="tab-list"] { gap: 0.4rem; }
.stTabs [data-baseweb="tab"] {
  font-family: Inter, "Segoe UI", sans-serif;
  font-weight: 500;
  color: #1E2A2A;
  background: transparent;
}
.stTabs [aria-selected="true"] { color: #1F5F5B !important; }
.stTabs [data-baseweb="tab-highlight"] { background-color: #1F5F5B !important; }
.stButton > button {
  border-radius: 999px !important;
  font-family: Inter, "Segoe UI", sans-serif !important;
  font-weight: 600 !important;
  padding: 0.4rem 1rem !important;
  width: auto;
}
.stButton > button[data-testid="stBaseButton-primary"] {
  background-color: #1F5F5B !important;
  color: #ffffff !important;
  border: 1px solid #1F5F5B !important;
}
.stButton > button[data-testid="stBaseButton-primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:focus {
  background-color: #174A47 !important;
  color: #ffffff !important;
  border-color: #174A47 !important;
}
.stButton > button[data-testid="stBaseButton-secondary"] {
  background-color: #ffffff !important;
  color: #1F5F5B !important;
  border: 1px solid #1F5F5B !important;
}
.stButton > button[data-testid="stBaseButton-secondary"]:hover,
.stButton > button[data-testid="stBaseButton-secondary"]:focus {
  background-color: #E5F1EF !important;
  color: #1F5F5B !important;
  border-color: #1F5F5B !important;
}
div[data-testid="stCodeBlock"] { margin-top: 0.3rem; }
@media (max-width: 700px) {
  .block-container { padding-left: 0.85rem !important; padding-right: 0.85rem !important; }
  .mast h1 { font-size: 2.25rem; }
  .metrics { grid-template-columns: 1fr 1fr; }
  .metric-label { white-space: normal; }
  .cols { grid-template-columns: 1fr; }
  .card-head, .exc-top { flex-direction: column; }
  .exc-side { text-align: left; }
  .stButton > button { width: 100% !important; }
  [class*="st-key-actions-"] .stButton > button,
  [class*="st-key-draft-"] .stButton > button { width: auto !important; }
  div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
  div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
    min-width: 100% !important;
    width: 100% !important;
    flex: 1 1 100% !important;
  }
}
</style>
"""


def show_html(fragment: str) -> None:
    cleaned = "\n".join(line for line in fragment.splitlines() if line.strip())
    cleaned = cleaned.replace("$", "&#36;")
    st.markdown(cleaned, unsafe_allow_html=True)


def show_plain(content: str) -> None:
    """Show chat text as written. Dollar amounts stay numbers, not math."""
    body = html.escape(content).replace("$", "&#36;").replace("\n", "<br>")
    st.markdown(body, unsafe_allow_html=True)


def html_with_script(body: str, *, height: int = 0) -> None:
    """Run a small script. Newer Streamlit does this in the page; 1.50 needs a component."""
    if "unsafe_allow_javascript" in inspect.signature(st.html).parameters:
        st.html(body, unsafe_allow_javascript=True)
        return
    import streamlit.components.v1 as components

    components.html(body, height=height)


def load_desk(seed: int, day: str) -> list[OrderMatch]:
    packets = build_sample(seed, day=day)
    return match_orders(
        [packet.purchase_order for packet in packets],
        [packet.shipment for packet in packets],
        [packet.invoice for packet in packets],
        build_inbound(day),
    )


def day_state(day: str) -> dict:
    desk = st.session_state.setdefault("desk", {})
    if day not in desk:
        desk[day] = {
            "ran": False,
            "running": False,
            "confirm": False,
            "resolved": [],
            "skipped": [],
            "edits": {},
            "editing": None,
            "empty_save": False,
            "brief": "",
            "messages": [],
        }
    return desk[day]


def resolved_ids(state: dict) -> set[str]:
    return set(state["resolved"])


def message_for(state: dict, exception: ExceptionRecord) -> str:
    return state["edits"].get(exception.key) or draft_email(exception).rendered


def flash(message: str) -> None:
    st.session_state["toast"] = message


def show_flash() -> None:
    message = st.session_state.pop("toast", None)
    if message:
        st.toast(message)


def approve(state: dict, exception: ExceptionRecord) -> bool:
    if exception.key in state["resolved"]:
        return False
    state["resolved"].append(exception.key)
    state["skipped"] = [key for key in state["skipped"] if key != exception.key]
    if state["editing"] == exception.key:
        state["editing"] = None
    flash(f"Approved. {format_money(exception.dollar_impact)} removed from today's risk.")
    return True


def view_order(po_number: str) -> None:
    st.session_state["desk_tabs"] = "Orders"
    st.session_state["scroll_po"] = po_number
    st.session_state["highlight_po"] = po_number


def on_day_change() -> None:
    st.session_state["desk_tabs"] = "Agent"
    st.session_state.pop("scroll_po", None)
    st.session_state.pop("highlight_po", None)


def _qty(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}"


def _price(value: Decimal | None) -> str:
    if value is None:
        return "Missing"
    return format_money(value)


def _cell(label: str, value: str, sub: str, tone: Tone) -> str:
    detail = f"<span class='cell-s'>{html.escape(sub)}</span>" if sub else ""
    return (
        f"<div class='cell {tone.value}'>"
        f"<span class='cell-k'>{html.escape(label)}</span>"
        f"<span class='cell-v'>{html.escape(value)}</span>"
        f"{detail}</div>"
    )


def _badge(status: str) -> str:
    if status == "Clean":
        return "<span class='badge clean'>Clean</span>"
    if status == "Resolved":
        return "<span class='badge resolved'>Resolved</span>"
    return "<span class='badge attention'>Needs attention</span>"


def render_mast() -> None:
    show_html(
        """
        <header class="mast">
          <p class="kicker">Linden Supply</p>
          <h1>Order Desk</h1>
          <p class="tagline">An AI ops agent built for a reusable bag program supplier (fictional data). Click Run morning check and watch it work.</p>
        </header>
        """
    )


def render_metrics(results: list[OrderMatch], done: set[str]) -> None:
    numbers = desk_numbers(results, done)
    cards = [
        ("Orders", str(numbers["orders"])),
        ("Clean", str(numbers["clean"])),
        ("Need attention", str(numbers["need_attention"])),
        ("Resolved", str(numbers["resolved"])),
        ("$ at risk", format_money(numbers["at_risk"])),
    ]
    body = "".join(
        f"<article class='metric'><p class='metric-label'>{html.escape(label)}</p>"
        f"<p class='metric-value'>{html.escape(value)}</p></article>"
        for label, value in cards
    )
    show_html(f"<section class='metrics'>{body}</section>")
    return numbers


def grouped(results: list[OrderMatch], state: dict) -> tuple[list, list, list]:
    done = resolved_ids(state)
    skipped = set(state["skipped"])
    active, held, finished = [], [], []
    for item in ordered_exceptions(results):
        if item.key in done:
            finished.append(item)
        elif item.key in skipped:
            held.append(item)
        else:
            active.append(item)
    return active, held, finished


def run_morning_check(day: str, results: list[OrderMatch], state: dict) -> None:
    pause = 0.4
    ranked = ordered_exceptions(results)
    by_po: dict[str, list[ExceptionRecord]] = {}
    for item in ranked:
        by_po.setdefault(item.po_number, []).append(item)
    numbers = desk_numbers(results)
    with st.status("Morning check", expanded=True) as status:
        status.write(f"Pulling today's orders ({len(results)} found)")
        time.sleep(pause)
        for order in results:
            status.write(f"Reading {order.po_number} ({order.retailer})")
            time.sleep(pause)
            status.write("Comparing to shipment and invoice")
            time.sleep(pause)
            problems = by_po.get(order.po_number, [])
            if not problems:
                status.write("✓ Clean")
                time.sleep(pause)
            else:
                for item in problems:
                    status.write(
                        f"⚠️ {item.explanation}, {item.risk.value} chargeback risk, {format_money(item.dollar_impact)}"
                    )
                    time.sleep(pause)
        status.write(
            inbound_log_line(
                build_inbound(day),
                {order.po_number: order.retailer for order in results},
            )
        )
        time.sleep(pause)
        status.write("Ranking problems by chargeback risk and $ impact")
        time.sleep(pause)
        status.write("Writing morning brief")
        state["brief"] = morning_brief(results, day)
        time.sleep(pause)
        status.write("Drafting fixes for your approval")
        time.sleep(pause)
        status.write(f"Done: {len(ranked)} problems found, {format_money(numbers['at_risk'])} at risk")
        status.update(label="Morning check complete", state="complete")


def render_run_button(day: str, state: dict) -> None:
    if state["confirm"]:
        st.write("Run again? This resets today's actions.")
        yes, no = st.columns(2)
        if yes.button("Yes", key=f"yes-{day}", type="primary"):
            state["resolved"] = []
            state["skipped"] = []
            state["edits"] = {}
            state["editing"] = None
            state["empty_save"] = False
            state["confirm"] = False
            state["running"] = True
            st.rerun()
        if no.button("No", key=f"no-{day}"):
            state["confirm"] = False
            st.rerun()
        return
    if st.button("Run morning check", key=f"run-{day}", type="primary"):
        if state["ran"]:
            state["confirm"] = True
        else:
            state["running"] = True
        st.rerun()


def render_actions(day: str, results: list[OrderMatch], state: dict, *, show_resolved: bool) -> None:
    active, held, finished = grouped(results, state)
    done = resolved_ids(state)
    numbers = desk_numbers(results, done)
    if state["ran"] and not active and not held and finished:
        show_html("<p class='banner'>All clear. $0 at risk today.</p>")
    if active:
        for item in active:
            render_action_card(day, item, state, locked=False)
    elif state["ran"] and numbers["at_risk"] == 0:
        pass
    if held:
        show_html("<p class='lede'>Skipped</p>")
        for item in held:
            render_skipped(day, item, state)
    if show_resolved and finished:
        show_html("<p class='lede'>Resolved today</p>")
        for item in finished:
            render_action_card(day, item, state, locked=True)


def draft_lines(text: str) -> tuple[str, str]:
    to_line = next((line for line in text.splitlines() if line.startswith("To:")), "To:")
    subject = next((line for line in text.splitlines() if line.startswith("Subject:")), "Subject:")
    return to_line, subject


def copy_text(text: str) -> None:
    payload = json.dumps(text)
    html_with_script(
        f"""
        <script>
        (function () {{
          const text = {payload};
          const fallback = () => {{
            const area = document.createElement("textarea");
            area.value = text;
            area.setAttribute("readonly", "");
            area.style.position = "fixed";
            area.style.left = "-9999px";
            document.body.appendChild(area);
            area.select();
            document.execCommand("copy");
            area.remove();
          }};
          if (navigator.clipboard && navigator.clipboard.writeText) {{
            navigator.clipboard.writeText(text).catch(fallback);
          }} else {{
            fallback();
          }}
        }})();
        </script>
        """,
        height=0,
    )


def render_draft(day: str, exception: ExceptionRecord, state: dict) -> None:
    text = message_for(state, exception)
    to_line, subject = draft_lines(text)
    show_html(
        f"<p class='draft-line'>{html.escape(to_line)}</p>"
        f"<p class='draft-line'>{html.escape(subject)}</p>"
    )
    open_key = f"draft-open-{day}-{exception.key}"
    shown = bool(st.session_state.get(open_key))
    with st.container(
        horizontal=True,
        gap="small",
        horizontal_alignment="left",
        width="content",
        key=f"draft-{day}-{exception.key}",
    ):
        label = "Hide full draft" if shown else "Show full draft"
        if st.button(label, key=f"toggle-{day}-{exception.key}"):
            st.session_state[open_key] = not shown
            st.rerun()
        if st.button("Copy", key=f"copy-{day}-{exception.key}"):
            copy_text(text)
    if shown:
        st.code(text, language=None, wrap_lines=True)


def render_since_brief(results: list[OrderMatch], state: dict) -> None:
    if not state["resolved"] and not state["skipped"]:
        return
    done = resolved_ids(state)
    approved = [item for item in ordered_exceptions(results) if item.key in done]
    removed = sum((item.dollar_impact for item in approved), Decimal("0"))
    show_html(
        "<p class='since'>Since this brief: "
        f"{len(approved)} resolved, {html.escape(format_money(removed))} removed from risk.</p>"
    )


def render_action_card(day: str, exception: ExceptionRecord, state: dict, *, locked: bool) -> None:
    with st.container(border=True, key=f"actioncard-{day}-{exception.key}"):
        _render_action_card(day, exception, state, locked=locked)


def _render_action_card(day: str, exception: ExceptionRecord, state: dict, *, locked: bool) -> None:
    show_html(
        "<div class='exc'>"
        "<div class='exc-top'><div>"
        f"<p class='who'>{html.escape(exception.retailer)}</p>"
        f"<p class='po-line'>{html.escape(exception.po_number)}</p>"
        "</div><div class='exc-side'>"
        f"<p class='impact'>{html.escape(format_money(exception.dollar_impact))}</p>"
        f"<span class='badge {exception.risk.value.lower()}'>{html.escape(exception.risk.value)}</span>"
        "</div></div>"
        f"<p class='explain'>{html.escape(exception.explanation)}</p>"
        "</div>"
    )
    editing = state["editing"] == exception.key and not locked
    if locked:
        st.caption("Sent (demo)")
    elif not editing:
        render_draft(day, exception, state)
    if editing:
        with st.form(f"edit-form-{day}-{exception.key}"):
            text = st.text_area("Message", value=message_for(state, exception))
            if state["empty_save"]:
                st.write("Message can't be empty")
            save, cancel = st.columns(2)
            saved = save.form_submit_button("Save", type="primary")
            cancelled = cancel.form_submit_button("Cancel")
        if saved:
            if not text.strip():
                state["empty_save"] = True
            else:
                state["edits"][exception.key] = text.strip()
                state["editing"] = None
                state["empty_save"] = False
            st.rerun()
        if cancelled:
            state["editing"] = None
            state["empty_save"] = False
            st.rerun()
    with st.container(
        horizontal=True,
        gap="small",
        horizontal_alignment="left",
        width="content",
        key=f"actions-{day}-{exception.key}",
    ):
        if st.button("Approve", key=f"approve-{day}-{exception.key}", disabled=locked, type="primary"):
            if approve(state, exception):
                st.rerun()
        if st.button("Edit", key=f"edit-{day}-{exception.key}", disabled=locked):
            state["editing"] = exception.key
            state["empty_save"] = False
            st.rerun()
        if st.button("Skip", key=f"skip-{day}-{exception.key}", disabled=locked):
            if exception.key not in state["skipped"]:
                state["skipped"].append(exception.key)
            if state["editing"] == exception.key:
                state["editing"] = None
            st.rerun()
        st.button("View order", key=f"view-{day}-{exception.key}", on_click=view_order, args=(exception.po_number,))


def render_skipped(day: str, exception: ExceptionRecord, state: dict) -> None:
    show_html(
        "<div class='exc'>"
        f"<p class='who'>{html.escape(exception.retailer)}</p>"
        f"<p class='po-line'>{html.escape(exception.po_number)} · Skipped · {html.escape(format_money(exception.dollar_impact))}</p>"
        "</div>"
    )
    if st.button("Undo", key=f"undo-{day}-{exception.key}"):
        state["skipped"] = [key for key in state["skipped"] if key != exception.key]
        st.rerun()


def render_agent(day: str, results: list[OrderMatch], state: dict) -> None:
    if state["running"]:
        st.button("Run morning check", key=f"run-busy-{day}", type="primary", disabled=True)
        run_morning_check(day, results, state)
        state["running"] = False
        state["ran"] = True
        st.rerun()
    render_run_button(day, state)
    if not state["ran"]:
        show_html(
            "<article class='card'><p>The agent will pull today's orders, check every shipment and invoice, "
            "flag problems, and propose fixes for you to approve.</p></article>"
        )
        return
    done = resolved_ids(state)
    render_metrics(results, done)
    paragraphs = "".join(f"<p>{html.escape(line)}</p>" for line in state["brief"].splitlines() if line.strip())
    show_html(f"<section class='card brief'><p class='eyebrow'>Morning brief</p>{paragraphs}</section>")
    st.caption("Written by AI from this run.")
    st.caption("Risk = chance of a retailer chargeback, not dollar size.")
    render_since_brief(results, state)
    render_actions(day, results, state, show_resolved=False)
    render_chat(day, results, state)


def render_chat(day: str, results: list[OrderMatch], state: dict) -> None:
    show_html("<p class='lede'>Ask the agent</p>")
    for message in state["messages"]:
        with st.chat_message(message["role"]):
            for step in message.get("steps", []):
                with st.expander(f"🔧 {step}"):
                    st.write("Checked today's orders.")
            show_plain(message["content"])
    for index, chip in enumerate(CHIPS):
        if st.button(chip, key=f"chip-{day}-{index}"):
            take_question(day, results, state, chip, from_chip=True)
    count = st.session_state.get("question_count", 0)
    if count >= QUESTION_LIMIT:
        st.caption(LIMIT_MESSAGE)
    prompt = st.chat_input(
        "Ask about today's orders",
        key=f"chat-{day}",
        disabled=count >= QUESTION_LIMIT,
    )
    if prompt:
        take_question(day, results, state, prompt, from_chip=False)


def take_question(day: str, results: list[OrderMatch], state: dict, question: str, *, from_chip: bool) -> None:
    count = int(st.session_state.get("question_count", 0))
    state["messages"].append({"role": "user", "content": question, "steps": []})
    if count >= QUESTION_LIMIT and not from_chip:
        state["messages"].append({"role": "assistant", "content": LIMIT_MESSAGE, "steps": []})
        st.rerun()
    if count >= QUESTION_LIMIT and from_chip:
        reply = ask(question, results, day, resolved_ids(state), cache_only=True)
    else:
        st.session_state["question_count"] = count + 1
        reply = ask(question, results, day, resolved_ids(state))
    _apply_resolve(results, state, reply.get("resolve") or [])
    state["messages"].append(
        {"role": "assistant", "content": reply["answer"], "steps": reply.get("steps") or []}
    )
    st.rerun()


def _apply_resolve(results: list[OrderMatch], state: dict, keys: list[str]) -> None:
    by_key = {item.key: item for item in ordered_exceptions(results)}
    removed = Decimal("0")
    changed = False
    for key in keys:
        item = by_key.get(key)
        if item is None or key in state["resolved"]:
            continue
        state["resolved"].append(key)
        state["skipped"] = [kept for kept in state["skipped"] if kept != key]
        removed += item.dollar_impact
        changed = True
    if changed:
        flash(f"Approved. {format_money(removed)} removed from today's risk.")


def maybe_scroll() -> None:
    po_number = st.session_state.pop("scroll_po", None)
    if not po_number:
        return
    safe = re.sub(r"[^A-Za-z0-9_-]", "", po_number)
    html_with_script(
        f"""
        <script>
          const findOrder = () => {{
            const id = "order-{safe}";
            const local = document.getElementById(id);
            if (local) return local;
            try {{ return window.parent.document.getElementById(id); }} catch (err) {{ return null; }}
          }};
          const go = (tries) => {{
            const el = findOrder();
            if (el) {{
              el.scrollIntoView({{behavior: "smooth", block: "start"}});
              return;
            }}
            if (tries < 12) setTimeout(() => go(tries + 1), 100);
          }};
          go(0);
        </script>
        """,
        height=0,
    )


def render_orders(day: str, results: list[OrderMatch], state: dict) -> None:
    done = resolved_ids(state)
    highlight = st.session_state.get("highlight_po")
    show_html(
        "<p class='legend'><span class='swatch amber'></span>Mismatch"
        "<span class='swatch red'></span>High chargeback risk</p>"
    )
    for order in results:
        late = order.ship_date is not None and order.ship_date > order.cancel_date
        ship_text = pretty_date(order.ship_date) if order.ship_date else "No shipment notice"
        ship_class = "meta bad" if late else "meta"
        invoice = order.invoice_number or "No invoice"
        open_items = [item for item in order.exceptions if item.key not in done]
        if not order.exceptions:
            status = "Clean"
        elif not open_items:
            status = "Resolved"
        else:
            status = "Needs attention"
        lines_html = []
        for line in order.lines:
            if line.shipped_qty is None:
                shipped_sub = "Missing"
            elif late:
                shipped_sub = "After cancel date"
            elif line.shipped_tone == Tone.AMBER:
                shipped_sub = "Short"
            else:
                shipped_sub = ""
            lines_html.append(
                "<div class='line'>"
                "<div class='style'>"
                f"<strong>{html.escape(line.style_code)}</strong>"
                f"<span>{html.escape(line.description)}</span>"
                "</div><div class='cols'>"
                + _cell("Ordered", _qty(line.ordered_qty), _price(line.ordered_price), line.ordered_tone)
                + _cell("Shipped", _qty(line.shipped_qty), shipped_sub, line.shipped_tone)
                + _cell("Invoiced", _qty(line.billed_qty), _price(line.billed_price), line.invoiced_tone)
                + "</div></div>"
            )
        exposure = ""
        if open_items:
            amount = sum((item.dollar_impact for item in open_items), Decimal("0"))
            exposure = f"<p class='exposure'>Exposure {format_money(amount)}</p>"
        mark = " highlight" if highlight == order.po_number else ""
        show_html(
            f"<article class='card{mark}' id='order-{html.escape(order.po_number)}'>"
            "<div class='card-head'><div>"
            f"<p class='po-title'>{html.escape(order.po_number)}</p>"
            f"<p class='meta'>{html.escape(order.retailer)} · {html.escape(invoice)}</p>"
            f"<p class='{ship_class}'>Shipped {html.escape(ship_text)} · Cancel {html.escape(pretty_date(order.cancel_date))}</p>"
            f"{exposure}</div>{_badge(status)}</div>"
            + "".join(lines_html)
            + "</article>"
        )
    maybe_scroll()


def render_exceptions(day: str, results: list[OrderMatch], state: dict) -> None:
    if not state["ran"]:
        show_html(
            "<article class='card'><p>Run the morning check and the proposed fixes will show up here.</p></article>"
        )
        return
    render_actions(day, results, state, show_resolved=True)


def render_footer() -> None:
    show_html("<p class='footer'>Demo built by Tanvi Nimbalkar · All data fictional</p>")


def render_day_picker() -> str:
    labels = {day["id"]: f"{day['label']} · {day['when']}" for day in SAMPLE_DAYS}
    options = {
        "options": [day["id"] for day in SAMPLE_DAYS],
        "default": "monday",
        "format_func": lambda day_id: labels[day_id],
        "key": "sample_day",
        "on_change": on_day_change,
    }
    if "required" in inspect.signature(st.segmented_control).parameters:
        options["required"] = True
    choice = st.segmented_control("Sample day", **options)
    if choice in labels:
        return choice
    return "monday"


class _Pane:
    def __init__(self, active: bool) -> None:
        self.open = active

    def __enter__(self) -> "_Pane":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def section_panes():
    labels = ["Agent", "Orders", "Exceptions"]
    if "key" in inspect.signature(st.tabs).parameters:
        return st.tabs(labels, key="desk_tabs", on_change="rerun", default="Agent")
    if st.session_state.get("desk_tabs") not in labels:
        st.session_state["desk_tabs"] = "Agent"
    st.radio("Section", labels, horizontal=True, label_visibility="collapsed", key="desk_tabs")
    selected = st.session_state["desk_tabs"]
    return [_Pane(label == selected) for label in labels]


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    try:
        show_flash()
        render_mast()
        day_id = render_day_picker()
        meta = next(day for day in SAMPLE_DAYS if day["id"] == day_id)
        results = load_desk(meta["seed"], meta["id"])
        state = day_state(day_id)
        agent, orders, exceptions = section_panes()
        if agent.open is not False:
            with agent:
                render_agent(day_id, results, state)
        if orders.open is not False:
            with orders:
                render_orders(day_id, results, state)
        if exceptions.open is not False:
            with exceptions:
                render_exceptions(day_id, results, state)
        render_footer()
    except Exception:
        logging.exception("Order Desk could not render")
        st.error("Something went wrong. Try running the check again.")


main()
