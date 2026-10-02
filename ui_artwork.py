"""Artwork & Approvals workspace. Orders & Shipments stays in app.py."""

from __future__ import annotations

import html
import logging
import time
from datetime import date

import streamlit as st

from core.artwork import (
    SOURCE_LABELS,
    WAITING_LABELS,
    activity_line,
    approval_on_latest,
    as_of_date,
    checklist_rows,
    compare_versions,
    days_waiting,
    draft_for,
    factory_draft,
    get_artwork_projects,
    handoff_projects,
    latest_version,
    load_people,
    load_projects,
    preflight_gaps,
    project_summary,
    ready_for_factory,
    risk_for,
    rule_summary,
    sorted_messages,
    stale_approvals,
    stuck_projects,
    vague_messages,
    version_file,
)
from core.models import pretty_date

SOURCE_ICONS = {
    "email": "✉",
    "whatsapp": "💬",
    "text": "📱",
    "clickup": "☑",
    "wetransfer": "↗",
}


def _state() -> dict:
    if "artwork_desk" not in st.session_state:
        st.session_state["artwork_desk"] = {
            "ran": False,
            "running": False,
            "resolved": [],
            "skipped": [],
            "edits": {},
            "editing": None,
            "empty_save": False,
            "brief": "",
            "notice": "",
        }
    return st.session_state["artwork_desk"]


def _demo_banner() -> None:
    if st.session_state.get("artwork_demo"):
        st.markdown(
            "<p class='art-badge'>Demo mode (cached)</p>",
            unsafe_allow_html=True,
        )


def _styles() -> None:
    st.markdown(
        """
        <style>
        .art-badge {
          display: inline-block;
          margin: 0 0 0.8rem;
          padding: 0.2rem 0.6rem;
          border-radius: 999px;
          background: #EEEAE4;
          color: #5C5852;
          font-size: 0.82rem;
          font-weight: 600;
        }
        .risk-green, .risk-yellow, .risk-red {
          display: inline-block;
          min-width: 0.7rem;
          padding: 0.12rem 0.45rem;
          border-radius: 999px;
          font-size: 0.75rem;
          font-weight: 600;
        }
        .risk-green { background: #E5F1EF; color: #1F5F5B; }
        .risk-yellow { background: #F8E8D8; color: #C8742B; }
        .risk-red { background: #F6E4E4; color: #B23A3A; }
        .art-table { width: 100%; border-collapse: collapse; }
        .art-table th { text-align: left; font-size: 0.75rem; letter-spacing: 0.04em; color: #1F5F5B; }
        .art-table td, .art-table th { padding: 0.45rem 0.35rem; border-bottom: 1px solid #E6DFD4; vertical-align: top; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _mark_demo(notice: str = "") -> None:
    st.session_state["artwork_demo"] = True
    if notice:
        _state()["notice"] = notice


def render_artwork_workspace(render_chat) -> None:
    _styles()
    try:
        from core.brief import gemini_settings

        gemini_settings()
    except Exception:
        _mark_demo()
    _demo_banner()
    if _state().get("notice"):
        st.info(_state()["notice"])
    projects_tab, handoff_tab, brief_tab = st.tabs(["Projects", "Factory Handoff", "Artwork Brief"])
    with projects_tab:
        render_projects()
    with handoff_tab:
        render_handoff()
    with brief_tab:
        render_brief(render_chat)


def render_projects() -> None:
    rows = []
    for project in load_projects():
        summary = project_summary(project)
        rows.append(summary)
    body = ["<table class='art-table'><tr><th>Brand</th><th>Stage</th><th>Version</th><th>Waiting on</th><th>Days</th><th>Ship date</th><th>Risk</th></tr>"]
    for row in rows:
        when = pretty_date(date.fromisoformat(row["ship_date"]))
        body.append(
            "<tr>"
            f"<td>{html.escape(row['brand'])}</td>"
            f"<td>{html.escape(row['stage'])}</td>"
            f"<td>{html.escape(row['version'])}</td>"
            f"<td>{html.escape(row['waiting_on'])}</td>"
            f"<td>{row['days_waiting']}</td>"
            f"<td>{html.escape(when)}</td>"
            f"<td><span class='risk-{row['risk']}'>{html.escape(row['risk'])}</span></td>"
            "</tr>"
        )
    body.append("</table>")
    st.markdown(f"<article class='card'>{''.join(body)}</article>", unsafe_allow_html=True)
    brands = [project["brand"] for project in load_projects()]
    brand = st.selectbox("Project", brands, key="artwork-project")
    project = next(item for item in load_projects() if item["brand"] == brand)
    render_detail(project)


def render_detail(project: dict) -> None:
    quiet = activity_line(project)
    if quiet:
        st.markdown(f"<article class='card'><p>{html.escape(quiet)}</p></article>", unsafe_allow_html=True)
        return
    st.markdown(f"<p class='lede'>{html.escape(project['brand'])}</p>", unsafe_allow_html=True)
    if project.get("order_id"):
        st.caption(f"Linked order {project['order_id']}")
    if project["conflicts"]:
        st.markdown("<p class='risk-red'>Needs human decision</p>", unsafe_allow_html=True)
        for item in project["conflicts"]:
            st.markdown(f"<p>{html.escape(item['contact'])}: “{html.escape(item['quote'])}”</p>", unsafe_allow_html=True)
    for message in vague_messages(project):
        st.caption(f"Not an approval: “{message['text']}” ({message['id']})")
    if stale_approvals(project):
        old = stale_approvals(project)[0]
        st.caption(f"Approval on {old['version']} does not cover {latest_version(project)['id']}.")
    timeline = []
    for message in sorted_messages(project):
        icon = SOURCE_ICONS.get(message["source"], "•")
        label = SOURCE_LABELS.get(message["source"], message["source"])
        timeline.append(
            f"<p>{icon} <strong>{html.escape(label)}</strong> · {html.escape(message['from'])} · {html.escape(message['at'][:10])}<br>"
            f"{html.escape(message['text'])} <span class='meta'>({html.escape(message['id'])})</span></p>"
        )
    checks = []
    for row in checklist_rows(project):
        checks.append(f"<li>{html.escape(row['request'])} — {html.escape(row['status'])} ({html.escape(row['message_id'])})</li>")
    check_html = "<p>No revision requests are on file.</p>" if not checks else "<ul>" + "".join(checks) + "</ul>"
    st.markdown(
        f"<article class='card'><p class='eyebrow'>Timeline</p>{''.join(timeline)}"
        f"<p class='eyebrow'>Revision checklist</p>{check_html}</article>",
        unsafe_allow_html=True,
    )
    versions = [item["id"] for item in project["versions"]]
    left, right = st.columns(2)
    with left:
        version_a = st.selectbox("Version A", versions, index=0, key=f"ver-a-{project['id']}")
    with right:
        version_b = st.selectbox("Version B", versions, index=len(versions) - 1, key=f"ver-b-{project['id']}")
    show_left, show_right = st.columns(2)
    file_a = version_file(project, version_a)
    file_b = version_file(project, version_b)
    if file_a and file_a.is_file():
        show_left.image(str(file_a), caption=version_a)
    if file_b and file_b.is_file():
        show_right.image(str(file_b), caption=version_b)
    if st.button("Check revisions", key=f"check-{project['id']}"):
        result = _checked_compare(project["id"], version_a, version_b)
        st.session_state[f"compare-{project['id']}"] = result
    result = st.session_state.get(f"compare-{project['id']}")
    if result:
        if result.get("error"):
            st.write(result["error"])
        elif not result.get("items"):
            st.write("No revision requests are on file.")
        else:
            for item in result["items"]:
                label = {"done": "done", "not_done": "not done", "unclear": "unclear"}.get(item["status"], item["status"])
                st.markdown(f"**{html.escape(label)}** — {html.escape(item['request'])} — {html.escape(item['reason'])}")


def _checked_compare(project_id: str, left: str, right: str) -> dict:
    cached = compare_versions(project_id, left, right)
    try:
        from core.brief import gemini_settings

        gemini_settings()
    except Exception:
        _mark_demo()
        return cached
    try:
        model_items = _vision_items(project_id, left, right)
    except Exception as exc:
        message = str(exc)
        if "429" in message or "RESOURCE_EXHAUSTED" in message:
            _mark_demo("The live model is at its limit for the moment. Showing the saved result.")
        else:
            _mark_demo()
            logging.warning("Artwork vision used the saved result: %s", exc.__class__.__name__)
        return cached
    if model_items is None:
        _mark_demo()
        return cached
    return compare_versions(project_id, left, right, model_items)


def _vision_items(project_id: str, left: str, right: str) -> list[dict] | None:
    from core.brief import gemini_settings

    project = next(item for item in load_projects() if item["id"] == project_id)
    key, model = gemini_settings()
    from google import genai
    from google.genai import types

    parts = [
        types.Part.from_text(
            text=(
                "Compare the two artwork files against this checklist. "
                "Return JSON only: a list of {id, status, reason, confidence}. "
                "status is done, not_done, or unclear. Use only these ids: "
                + ", ".join(row["id"] for row in checklist_rows(project))
            )
        )
    ]
    for version_id in (left, right):
        path = version_file(project, version_id)
        if path and path.is_file():
            parts.append(types.Part.from_bytes(data=path.read_bytes(), mime_type="image/png"))
    if len(parts) < 2:
        return None
    client = genai.Client(api_key=key)
    response = client.models.generate_content(model=model, contents=parts)
    text = getattr(response, "text", None) or ""
    return _parse_vision(text)


def _parse_vision(text: str) -> list[dict] | None:
    import json

    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return [item for item in parsed if isinstance(item, dict)]


def render_handoff() -> None:
    people = load_people()
    st.caption(f"Partner factory: {people['factory']['name']}, {people['factory']['role']}.")
    projects = handoff_projects()
    if not projects:
        st.markdown("<article class='card'><p>No approved artwork is ready to hand off.</p></article>", unsafe_allow_html=True)
        return
    for project in projects:
        pack = factory_draft(project)
        latest = latest_version(project)
        files = ", ".join(f"{item['id']} ({item['uploaded']})" for item in project["versions"])
        gaps = ", ".join(pack["gaps"]) if pack["gaps"] else "None"
        st.markdown(
            "<article class='card'>"
            f"<p class='who'>{html.escape(project['brand'])}</p>"
            f"<p>Spec: {html.escape(project['product_type'])}, {html.escape(project['size'])}, "
            f"{html.escape(str(project['material']))}, finish {html.escape(str(project['finish'] or 'undecided'))}, "
            f"quantity {html.escape(str(project['quantity'] if project['quantity'] is not None else 'missing'))}.</p>"
            f"<p>Files: {html.escape(files)}. Final on the brief: {html.escape(latest['id'])}.</p>"
            f"<p>Pre-flight: {html.escape(gaps)}.</p>"
            "</article>",
            unsafe_allow_html=True,
        )
        if not pack["ready"]:
            st.button("Ready for factory", key=f"ready-{project['id']}", disabled=True)
            question = pack["question"]
            st.markdown(
                f"<article class='card'><p class='eyebrow'>Question for the customer</p>"
                f"<p>To: {html.escape(question['to'])}</p>"
                f"<p>Subject: {html.escape(question['subject'])}</p>"
                f"<p>{html.escape(question['body']).replace(chr(10), '<br>')}</p></article>",
                unsafe_allow_html=True,
            )
            continue
        if st.button("Ready for factory", key=f"ready-{project['id']}"):
            st.session_state[f"factory-ready-{project['id']}"] = True
        if st.session_state.get(f"factory-ready-{project['id']}"):
            st.caption("Marked ready for the factory (demo).")
        english, chinese = st.columns(2)
        english.markdown(f"<article class='card'><p class='eyebrow'>English</p><p>{html.escape(pack['english']).replace(chr(10), '<br>')}</p></article>", unsafe_allow_html=True)
        chinese.markdown(f"<article class='card'><p class='eyebrow'>简体中文</p><p>{html.escape(pack['chinese']).replace(chr(10), '<br>')}</p></article>", unsafe_allow_html=True)


def render_brief(render_chat) -> None:
    state = _state()
    if state["running"]:
        st.button("Run morning check", key="art-run-busy", type="primary", disabled=True)
        _run_check(state)
        state["running"] = False
        state["ran"] = True
        st.rerun()
    if st.button("Run morning check", key="art-run", type="primary"):
        state["running"] = True
        st.rerun()
    if not state["ran"]:
        st.markdown(
            "<article class='card'><p>The agent will read every artwork project, see who it is waiting on, "
            "and draft the notes for you to approve.</p></article>",
            unsafe_allow_html=True,
        )
        render_chat()
        return
    if state.get("notice"):
        st.info(state["notice"])
    summary = state["brief"] or rule_summary()
    st.markdown(f"<article class='card brief'><p class='eyebrow'>Artwork brief</p><p>{html.escape(summary)}</p></article>", unsafe_allow_html=True)
    st.caption("Written by AI from this run.")
    cards = [draft_for(project) for project in stuck_projects()]
    if not cards:
        st.markdown("<article class='card'><p>Nothing needs attention today.</p></article>", unsafe_allow_html=True)
    active = [card for card in cards if card["key"] not in state["resolved"] and card["key"] not in state["skipped"]]
    skipped = [card for card in cards if card["key"] in state["skipped"]]
    sent = [card for card in cards if card["key"] in state["resolved"]]
    for card in active:
        _action_card(card, state, locked=False)
    if skipped:
        st.markdown("<p class='lede'>Skipped</p>", unsafe_allow_html=True)
        for card in skipped:
            st.markdown(f"<p>{html.escape(card['subject'])}</p>", unsafe_allow_html=True)
            if st.button("Undo", key=f"art-undo-{card['key']}"):
                state["skipped"] = [key for key in state["skipped"] if key != card["key"]]
                st.rerun()
    if sent:
        st.markdown("<p class='lede'>Outbox</p>", unsafe_allow_html=True)
        for card in sent:
            _action_card(card, state, locked=True)
    render_chat()


def _run_check(state: dict) -> None:
    pause = 0.4
    projects = get_artwork_projects()["projects"]
    with st.status("Artwork morning check", expanded=True) as status:
        status.write(f"Pulling artwork projects ({len(projects)} found)")
        time.sleep(pause)
        for row in projects:
            status.write(f"Reading {row['brand']} ({row['version']})")
            time.sleep(pause)
            if row["risk"] == "green":
                status.write("✓ Handed off")
            else:
                status.write(f"⚠️ {row['stage']}, waiting on {row['waiting_on']}, {row['days_waiting']} days")
            time.sleep(pause)
        status.write("Checking approvals against the latest version")
        time.sleep(pause)
        status.write("Checking factory pre-flight")
        time.sleep(pause)
        state["brief"] = _summary_sentence()
        status.write("Writing artwork brief")
        time.sleep(pause)
        status.write("Drafting notes for your approval")
        time.sleep(pause)
        stuck = stuck_projects()
        status.write(f"Done: {len(stuck)} projects need attention")
        status.update(label="Artwork morning check complete", state="complete")


def _summary_sentence() -> str:
    fallback = rule_summary()
    try:
        from core.brief import gemini_settings

        key, model = gemini_settings()
    except Exception:
        _mark_demo()
        return fallback
    try:
        from google import genai

        client = genai.Client(api_key=key)
        prompt = (
            "Write one sentence for an artwork desk. Use only these facts, and do not add brands, "
            f"versions, dates, or counts that are not here:\n{fallback}"
        )
        response = client.models.generate_content(model=model, contents=prompt)
        text = (getattr(response, "text", None) or "").strip().splitlines()[0].strip()
        if text and _summary_ok(text, fallback):
            return text
    except Exception as exc:
        message = str(exc)
        if "429" in message or "RESOURCE_EXHAUSTED" in message:
            _mark_demo("The live model is at its limit for the moment. Showing the saved result.")
        else:
            _mark_demo()
            logging.warning("Artwork brief used the saved sentence: %s", exc.__class__.__name__)
    return fallback


def _summary_ok(text: str, fallback: str) -> bool:
    allowed = set(fallback.replace(",", " ").split())
    for token in text.replace(",", " ").split():
        if any(character.isdigit() for character in token) and token not in allowed and token.strip(".") not in allowed:
            return False
    return True


def _message_text(state: dict, card: dict) -> str:
    return state["edits"].get(card["key"]) or f"To: {card['to']}\nSubject: {card['subject']}\n\n{card['body']}"


def _action_card(card: dict, state: dict, *, locked: bool) -> None:
    with st.container(border=True, key=f"artcard-{card['key']}-{int(locked)}"):
        st.markdown(
            f"<p class='who'>{html.escape(card['subject'])}</p><p>{html.escape(card.get('flag') or '')}</p>",
            unsafe_allow_html=True,
        )
        if locked:
            st.caption("Sent (demo)")
        elif state["editing"] == card["key"]:
            with st.form(f"art-edit-{card['key']}"):
                text = st.text_area("Message", value=_message_text(state, card))
                if state["empty_save"]:
                    st.write("Message can't be empty")
                save = st.form_submit_button("Save", type="primary")
                cancel = st.form_submit_button("Cancel")
            if save:
                if not text.strip():
                    state["empty_save"] = True
                else:
                    state["edits"][card["key"]] = text.strip()
                    state["editing"] = None
                    state["empty_save"] = False
                st.rerun()
            if cancel:
                state["editing"] = None
                state["empty_save"] = False
                st.rerun()
        else:
            st.markdown(f"<p class='draft-line'>To: {html.escape(card['to'])}</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='draft-line'>Subject: {html.escape(card['subject'])}</p>", unsafe_allow_html=True)
            with st.expander("Show full draft"):
                st.code(_message_text(state, card), language=None, wrap_lines=True)
        with st.container(horizontal=True, gap="small", horizontal_alignment="left", width="content", key=f"art-actions-{card['key']}-{int(locked)}"):
            if st.button("Approve", key=f"art-approve-{card['key']}-{int(locked)}", disabled=locked, type="primary"):
                if card["key"] not in state["resolved"]:
                    state["resolved"].append(card["key"])
                    state["skipped"] = [key for key in state["skipped"] if key != card["key"]]
                st.rerun()
            if st.button("Edit", key=f"art-edit-btn-{card['key']}-{int(locked)}", disabled=locked):
                state["editing"] = card["key"]
                state["empty_save"] = False
                st.rerun()
            if st.button("Skip", key=f"art-skip-{card['key']}-{int(locked)}", disabled=locked):
                if card["key"] not in state["skipped"]:
                    state["skipped"].append(card["key"])
                st.rerun()


def artwork_facts_line() -> str:
    """Small helper so the workspace can show the book date without a second clock."""
    return f"Artwork book dated {pretty_date(as_of_date())}. Waiting labels: {', '.join(WAITING_LABELS)}."
