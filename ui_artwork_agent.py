"""Artwork & Approvals workspace. Demo data and a private trial use the same screens."""

from __future__ import annotations

import html
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from artwork_agent.auth import hash_password, login
from artwork_agent.briefing import build_brief, factory_pack, latest_brief, save_as_draft
from artwork_agent.config import TrialSafetyError, load_config
from artwork_agent.connectors import import_whatsapp_file, mark_connector, save_token
from artwork_agent.db import open_database
from artwork_agent.ingest import assign_message
from artwork_agent.metrics import metrics, metrics_pdf
from artwork_agent.portals import create_factory_link, create_proof_link, move_factory_event, revoke
from artwork_agent.records import project_rows, setting, timeline
from artwork_agent.seed import seed_demo
from artwork_agent.tools import answer_question, compare

ICONS = {
    "email": "✉",
    "whatsapp": "💬",
    "text": "📱",
    "clickup": "☑",
    "wetransfer": "↗",
    "proof": "🖊",
    "factory": "🏭",
    "hubspot": "◆",
    "comment": "🖊",
}
WAITING = {"customer": "Customer", "designer": "Designer", "factory": "Factory", "us": "Us", "human": "Human", "": "—"}


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _open():
    config = load_config()
    db = open_database(config)
    if not config.trial:
        seed_demo(db, config)
    return config, db


def render_artwork_agent() -> None:
    st.markdown(
        """
        <style>
        .risk-green, .risk-yellow, .risk-red {
          display: inline-block; padding: 0.12rem 0.45rem; border-radius: 999px;
          font-size: 0.75rem; font-weight: 600;
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
    try:
        config, db = _open()
    except TrialSafetyError as exc:
        st.error(str(exc))
        return
    if config.trial and not _logged_in(db):
        return
    if not config.trial:
        st.caption("Demo mode (cached). Fictional data. No live connectors.")
    labels = ["Today", "Projects", "Assets", "Proofing", "Factory", "Ask the Agent", "Trial Results", "Settings"]
    tabs = st.tabs(labels)
    with tabs[0]:
        _today(db, config)
    with tabs[1]:
        _projects(db, config)
    with tabs[2]:
        _assets(db, config)
    with tabs[3]:
        _proofing(db, config)
    with tabs[4]:
        _factory(db, config)
    with tabs[5]:
        _ask(db, config)
    with tabs[6]:
        _results(db, config)
    with tabs[7]:
        _settings(db, config)
    db.commit()


def _logged_in(db) -> bool:
    if st.session_state.get("team_email"):
        return True
    st.markdown("<article class='card'><p>Sign in with your team email.</p></article>", unsafe_allow_html=True)
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Sign in"):
        person = login(db, email, password)
        if person:
            st.session_state["team_email"] = person["email"]
            st.rerun()
        st.error("That email or password does not match a team member.")
    return False


def _today(db, config) -> None:
    if st.button("Run check now", type="primary", key="agent-run"):
        as_of = config.as_of or _now()[:10]
        nudge = int(setting(db, "nudge_days", str(config.nudge_days)))
        projects = project_rows(db, as_of, nudge)
        with st.status("Reading projects...", expanded=True) as box:
            box.write(f"Reading projects ({len(projects)} found)")
            for project in projects:
                time.sleep(0.15)
                who = WAITING.get(project.get("waiting_on") or "", "—")
                if project["risk"] == "green":
                    box.write(f"✓ {project['brand']} is clear")
                else:
                    box.write(f"⚠ {project['brand']} · {project['stage']} · waiting on {who} · {project['days_waiting']} days")
            brief = build_brief(db, config, _now())
            db.commit()
            box.write("Done.")
            box.update(label="Check complete", state="complete")
        st.session_state["agent_brief_id"] = brief["id"]
    brief = latest_brief(db)
    if brief is None:
        st.markdown("<article class='card'><p>No brief yet. Run check now, or wait for the morning job.</p></article>", unsafe_allow_html=True)
        return
    st.markdown(
        f"<article class='card brief'><p class='eyebrow'>Morning brief</p><p>{html.escape(brief['summary'])}</p>"
        f"<p>{html.escape(brief['body']).replace(chr(10), '<br>')}</p></article>",
        unsafe_allow_html=True,
    )
    st.caption("Written from stored records. Nothing is sent.")
    proposed = db.fetchall("SELECT * FROM actions WHERE kind = 'draft' AND status = 'proposed' ORDER BY created_at")
    if not proposed and brief["summary"] == "Nothing needs attention today.":
        st.markdown("<article class='card'><p>Nothing needs attention today.</p></article>", unsafe_allow_html=True)
    for card in proposed:
        _action_card(db, card)
    saved = db.fetchall("SELECT * FROM actions WHERE kind = 'draft' AND status = 'draft_saved'")
    if saved:
        st.markdown("<p class='eyebrow'>Outbox</p>", unsafe_allow_html=True)
        for card in saved:
            st.markdown(
                f"<article class='card'><p>{html.escape(card['subject'] or '')}</p><p>Saved as a Gmail draft. Not sent.</p></article>",
                unsafe_allow_html=True,
            )


def _action_card(db, card: dict) -> None:
    st.markdown(
        f"<article class='card'><p class='who'>{html.escape(card['subject'] or '')}</p>"
        f"<p>{html.escape(card['issue'] or '')}</p><p>To: {html.escape(card['to_addr'] or '')}</p></article>",
        unsafe_allow_html=True,
    )
    with st.expander("Show full draft"):
        st.text(card["body"] or "")
    approve, edit, skip = st.columns(3)
    if approve.button("Approve", key=f"approve-{card['id']}"):
        save_as_draft(db, card["id"], _now())
        db.commit()
        st.toast("Saved as a Gmail draft. Not sent.")
        st.rerun()
    if edit.button("Edit", key=f"edit-{card['id']}"):
        st.session_state[f"editing-{card['id']}"] = True
    if st.session_state.get(f"editing-{card['id']}"):
        with st.form(f"form-{card['id']}"):
            body = st.text_area("Draft", value=card["body"] or "")
            if st.form_submit_button("Save"):
                if not body.strip():
                    st.warning("Message can't be empty.")
                else:
                    db.execute("UPDATE actions SET body = ? WHERE id = ?", (body, card["id"]))
                    db.commit()
                    st.session_state[f"editing-{card['id']}"] = False
                    st.rerun()
    if skip.button("Skip", key=f"skip-{card['id']}"):
        db.execute("UPDATE actions SET status = 'skipped' WHERE id = ?", (card["id"],))
        db.commit()
        st.rerun()


def _projects(db, config) -> None:
    as_of = config.as_of or _now()[:10]
    nudge = int(setting(db, "nudge_days", str(config.nudge_days)))
    rows = project_rows(db, as_of, nudge)
    if not rows:
        st.markdown("<article class='card'><p>No projects yet.</p></article>", unsafe_allow_html=True)
        return
    body = ["<table class='art-table'><tr><th>Brand</th><th>Stage</th><th>Version</th><th>Waiting on</th><th>Days</th><th>Ship date</th><th>Risk</th></tr>"]
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(row['brand'])}</td>"
            f"<td>{html.escape(row['stage'])}</td>"
            f"<td>{html.escape(row['version'])}</td>"
            f"<td>{html.escape(WAITING.get(row.get('waiting_on') or '', '—'))}</td>"
            f"<td>{row['days_waiting']}</td>"
            f"<td>{html.escape(row.get('ship_date') or '')}</td>"
            f"<td><span class='risk-{row['risk']}'>{html.escape(row['risk'])}</span></td>"
            "</tr>"
        )
    body.append("</table>")
    st.markdown(f"<article class='card'>{''.join(body)}</article>", unsafe_allow_html=True)
    brand = st.selectbox("Project", [row["brand"] for row in rows], key="agent-project")
    project = next(row for row in rows if row["brand"] == brand)
    _project_page(db, config, project)


def _project_page(db, config, project: dict) -> None:
    st.markdown(f"<p class='lede'>{html.escape(project['brand'])}</p>", unsafe_allow_html=True)
    if project.get("order_id"):
        st.caption(f"Linked order {project['order_id']}")
    events = timeline(db, project["id"])
    if not events:
        st.markdown("<article class='card'><p>No activity yet.</p></article>", unsafe_allow_html=True)
    else:
        lines = []
        for item in events:
            icon = ICONS.get(item["source"], "•")
            text = item["text"]
            if item.get("translation") and item.get("original") and item["translation"] != item["original"]:
                text = f"{item['original']} — {item['translation']}"
            unclear = " · unclear, not an approval" if item.get("unclear") else ""
            lines.append(f"<p>{icon} {html.escape(item['source'])} · {html.escape(item['who'])} · {html.escape(item['at'])} {html.escape(text)} ({html.escape(item['id'])}){unclear}</p>")
        st.markdown(f"<article class='card'><p class='eyebrow'>Timeline</p>{''.join(lines)}</article>", unsafe_allow_html=True)
    checks = []
    for item in project["checklist"]:
        state = {"done": f"done in {item.get('done_in') or ''}", "not_done": "not done", "needs_human": "Needs human decision"}.get(item["status"], item["status"])
        checks.append(f"<li>{html.escape(item['request'])} — {html.escape(state)} ({html.escape(item.get('message_id') or '')})</li>")
    check_html = "<p>No revision requests are on file.</p>" if not checks else "<ul>" + "".join(checks) + "</ul>"
    st.markdown(f"<article class='card'><p class='eyebrow'>Revision checklist</p>{check_html}</article>", unsafe_allow_html=True)
    st.markdown("<p class='eyebrow'>Specs</p>", unsafe_allow_html=True)
    for field, row in project["specs"].items():
        st.caption(f"{field}: {row['value'] or 'missing'} · source {row['source']}")
    with st.form(f"specs-{project['id']}"):
        field = st.selectbox("Field", list(project["specs"]))
        value = st.text_input("Value", value=project["specs"][field]["value"] or "")
        if st.form_submit_button("Save spec"):
            db.execute(
                "UPDATE specs SET value = ?, source = ? WHERE project_id = ? AND field = ?",
                (value, f"edited by a person {_now()[:10]}", project["id"], field),
            )
            db.commit()
            st.rerun()
    photos = db.fetchall("SELECT * FROM factory_events WHERE project_id = ? AND kind = 'photo'", (project["id"],))
    if photos:
        choices = [row["brand"] for row in project_rows(db, config.as_of or _now()[:10], config.nudge_days)]
        target = st.selectbox("Move a factory photo to", choices, key=f"move-{project['id']}")
        if st.button("Move photo", key=f"move-btn-{project['id']}"):
            other = db.fetchone("SELECT id FROM projects WHERE brand = ?", (target,))
            move_factory_event(db, photos[0]["id"], other["id"], _now())
            db.commit()
            st.rerun()
    unsorted = db.fetchall(
        """
        SELECT messages.* FROM messages
        JOIN unsorted ON unsorted.message_id = messages.id
        """
    )
    if unsorted:
        st.markdown("<p class='eyebrow'>Unsorted</p>", unsafe_allow_html=True)
        for item in unsorted:
            st.write(f"{item['sender']}: {item['body']}")
            if st.button("Assign to this project", key=f"assign-{item['id']}-{project['id']}"):
                pattern = ""
                if "@" in (item["sender"] or ""):
                    pattern = item["sender"].split("@", 1)[1].lower()
                assign_message(db, item["id"], project["id"], pattern, "domain", _now())
                db.commit()
                st.rerun()


def _assets(db, config) -> None:
    project = _pick(db, config, "assets")
    if not project:
        return
    for version in project["versions"]:
        mark = " · Final for production" if version["final_for_production"] else ""
        st.markdown(f"**{version['version_label']}** · {version['uploaded_at']} · {version['uploader']}{mark}")
        path = version.get("preview_path") or ""
        if version["preview_available"] and path and Path(path).is_file():
            st.image(path, width=220)
        else:
            st.caption(f"{version.get('file_name') or version['version_label']}: preview not available")
        if st.button("Mark final for production", key=f"final-{version['id']}"):
            db.execute("UPDATE versions SET final_for_production = 0 WHERE project_id = ?", (project["id"],))
            db.execute("UPDATE versions SET final_for_production = 1 WHERE id = ?", (version["id"],))
            db.commit()
            st.rerun()
    if project["files"]:
        st.markdown("<p class='eyebrow'>Related files</p>", unsafe_allow_html=True)
        for item in project["files"]:
            st.write(f"{item['kind']}: {item['name']} — {item['note']}")
    labels = [item["version_label"] for item in project["versions"]]
    if len(labels) >= 1:
        left, right = st.columns(2)
        version_a = left.selectbox("Version A", labels, index=0, key=f"a-{project['id']}")
        version_b = right.selectbox("Version B", labels, index=len(labels) - 1, key=f"b-{project['id']}")
        if st.button("Check revisions", key=f"check-{project['id']}"):
            result = compare(db, config, project["id"], version_a, version_b)
            if result.get("error"):
                st.write(result["error"])
            elif not result.get("items"):
                st.write("No revision requests are on file.")
            for item in result.get("items") or []:
                st.write(f"{item['status']} — {item['request']} — {item['reason']} ({item['message_id']})")


def _proofing(db, config) -> None:
    project = _pick(db, config, "proof")
    if not project:
        return
    labels = [item["version_label"] for item in project["versions"]]
    version = st.selectbox("Version to send", labels, index=len(labels) - 1)
    reviewers = st.text_input("Reviewer emails, comma separated")
    if st.button("Send proof"):
        emails = [item.strip() for item in reviewers.split(",") if item.strip()]
        token = create_proof_link(db, project["id"], version, datetime.now(), emails)
        db.commit()
        st.session_state["last_proof"] = token
    if st.session_state.get("last_proof"):
        token = st.session_state["last_proof"]
        st.markdown(f"[Open the customer proof](?proof={token})")
        st.caption("The link expires in 30 days.")
        if st.button("Revoke proof link"):
            revoke(db, token, "proof", _now())
            db.commit()
            st.session_state["last_proof"] = ""
            st.rerun()


def _factory(db, config) -> None:
    as_of = config.as_of or _now()[:10]
    nudge = int(setting(db, "nudge_days", str(config.nudge_days)))
    approved = [
        row
        for row in project_rows(db, as_of, nudge)
        if any(item.get("counts") for item in row["approvals"])
        or row["stage"] in {"Approved", "Sent to factory", "In production", "Shipped"}
    ]
    if not approved:
        st.markdown("<article class='card'><p>No approved artwork is ready to hand off.</p></article>", unsafe_allow_html=True)
        return
    for project in approved:
        pack = factory_pack(project, config.company_name)
        st.markdown(f"<article class='card'><p class='who'>{html.escape(project['brand'])}</p><p>Pre-flight: {html.escape(', '.join(pack['gaps']) or 'None')}</p></article>", unsafe_allow_html=True)
        if not pack["ready"]:
            st.button("Ready for factory", key=f"ready-{project['id']}", disabled=True)
            question = pack.get("question") or {}
            st.markdown(
                f"<article class='card'><p class='eyebrow'>Question for the customer</p><p>{html.escape(question.get('subject') or '')}</p>"
                f"<p>{html.escape(question.get('body') or '').replace(chr(10), '<br>')}</p></article>",
                unsafe_allow_html=True,
            )
            continue
        left, right = st.columns(2)
        left.markdown(f"<article class='card'><p class='eyebrow'>English</p><p>{html.escape(pack['english']).replace(chr(10), '<br>')}</p></article>", unsafe_allow_html=True)
        right.markdown(f"<article class='card'><p class='eyebrow'>简体中文</p><p>{html.escape(pack['chinese']).replace(chr(10), '<br>')}</p></article>", unsafe_allow_html=True)
        if st.button("Ready for factory", key=f"ready-{project['id']}"):
            token = create_factory_link(db, project["id"], datetime.now())
            db.execute("UPDATE projects SET stage = 'Sent to factory' WHERE id = ? AND stage = 'Approved'", (project["id"],))
            db.commit()
            st.session_state[f"factory-token-{project['id']}"] = token
        token = st.session_state.get(f"factory-token-{project['id']}")
        if token:
            st.markdown(f"[Open the factory portal](?factory={token})")
            if st.button("Revoke factory link", key=f"revoke-factory-{project['id']}"):
                revoke(db, token, "factory", _now())
                db.commit()


def _ask(db, config) -> None:
    history = st.session_state.setdefault("agent_chat", [])
    for item in history:
        st.markdown(f"**You**  \n{html.escape(item['question'])}")
        for step in item["steps"]:
            st.caption(f"🔧 {step}")
        st.write(item["answer"])
    question = st.chat_input("Ask about a project, version, or message")
    if question:
        result = answer_question(db, config, question, _now())
        db.commit()
        history.append({"question": question, **result})
        st.rerun()


def _results(db, config) -> None:
    as_of = config.as_of or _now()[:10]
    nudge = int(setting(db, "nudge_days", str(config.nudge_days)))
    report = metrics(db, as_of, nudge)
    st.markdown(
        f"<article class='card'><p>Issues caught: {report['issues_caught']}</p>"
        f"<p>Drafts created: {report['drafts_created']} · saved by a person: {report['drafts_used']}</p>"
        f"<p>Proofs sent: {report['proofs_sent']} · approved: {report['proofs_approved']}</p>"
        f"<p>Factory handoffs: {report['factory_handoffs']}</p>"
        f"<p>Estimated hours saved: {report['hours_saved']}</p></article>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Assumptions: {report['minutes_per_issue']} minutes per issue, "
        f"{report['minutes_per_draft']} per draft, {report['minutes_per_proof']} per proof. "
        "Change these on Settings."
    )
    for party, days in report["avg_days_waiting"].items():
        st.write(f"Average days waiting on {party}: {days}")
    if st.button("Prepare one-page PDF"):
        st.session_state["trial_pdf"] = metrics_pdf(config.company_name, report)
    if st.session_state.get("trial_pdf"):
        st.download_button(
            "Download one-page PDF",
            data=st.session_state["trial_pdf"],
            file_name="trial-results.pdf",
            mime="application/pdf",
        )


def _settings(db, config) -> None:
    rows = db.fetchall("SELECT * FROM connectors ORDER BY name")
    for row in rows:
        color = "#B23A3A" if row["status"] == "error" else "#1F5F5B"
        st.markdown(
            f"<p style='color:{color}'><strong>{html.escape(row['name'])}</strong> · {html.escape(row['status'])}"
            f" · {html.escape(row['detail'] or '')} · last sync {html.escape(row['last_synced'] or 'never')}</p>",
            unsafe_allow_html=True,
        )
    upload = st.file_uploader("WhatsApp chat export", type=["txt", "zip"])
    if upload is not None and st.button("Import WhatsApp export"):
        result = import_whatsapp_file(db, config, upload.getvalue(), upload.name, _now())
        db.commit()
        st.success(f"Imported {result['imported']}. Skipped {result['duplicates']} already stored.")
    with st.form("agent-settings"):
        threshold = st.text_input("Matching threshold", value=setting(db, "confidence_threshold", "0.75"))
        nudge = st.text_input("Nudge a customer after this many days", value=setting(db, "nudge_days", "3"))
        brief_time = st.text_input("Brief time", value=setting(db, "brief_time", config.brief_time))
        timezone = st.text_input("Time zone", value=setting(db, "timezone", config.timezone))
        retention = st.text_input("Keep data for this many days", value=setting(db, "retention_days", "90"))
        pattern = st.text_input("Project code format", value=setting(db, "code_pattern", config.project_code_pattern))
        per_issue = st.text_input("Minutes per issue", value=setting(db, "minutes_per_issue", "12"))
        per_draft = st.text_input("Minutes per draft", value=setting(db, "minutes_per_draft", "8"))
        per_proof = st.text_input("Minutes per proof", value=setting(db, "minutes_per_proof", "20"))
        if st.form_submit_button("Save settings"):
            pairs = {
                "confidence_threshold": threshold,
                "nudge_days": nudge,
                "brief_time": brief_time,
                "timezone": timezone,
                "retention_days": retention,
                "code_pattern": pattern,
                "minutes_per_issue": per_issue,
                "minutes_per_draft": per_draft,
                "minutes_per_proof": per_proof,
            }
            for key, value in pairs.items():
                db.execute("DELETE FROM settings WHERE key = ?", (key,))
                db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))
            db.commit()
            st.success("Saved.")
    st.markdown("<p class='eyebrow'>Team</p>", unsafe_allow_html=True)
    for person in db.fetchall("SELECT name, email, role FROM team ORDER BY name"):
        st.write(f"{person['name']} · {person['email']} · {person['role']}")
    with st.form("add-team"):
        name = st.text_input("Name")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        role = st.text_input("Role", value="Team")
        if st.form_submit_button("Add team member") and email and password:
            db.execute("DELETE FROM team WHERE email = ?", (email.strip().lower(),))
            db.execute(
                "INSERT INTO team (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
                (email.strip().lower(), name, hash_password(password), role),
            )
            db.commit()
            st.success("Team member added. The password is stored as a hash.")
    secret = st.text_input("Connector token", type="password")
    which = st.selectbox("Save token for", ["gmail", "drive", "clickup", "hubspot"])
    if st.button("Save token") and secret:
        try:
            save_token(db, config, which, secret)
            mark_connector(db, which, True, "connected", "Token stored.", _now())
            db.commit()
            st.success("Token encrypted and stored.")
        except RuntimeError as exc:
            st.error(str(exc))


def _pick(db, config, key: str):
    as_of = config.as_of or _now()[:10]
    rows = project_rows(db, as_of, int(setting(db, "nudge_days", str(config.nudge_days))))
    if not rows:
        st.markdown("<article class='card'><p>No projects yet.</p></article>", unsafe_allow_html=True)
        return None
    brand = st.selectbox("Project", [row["brand"] for row in rows], key=f"pick-{key}")
    return next(row for row in rows if row["brand"] == brand)
