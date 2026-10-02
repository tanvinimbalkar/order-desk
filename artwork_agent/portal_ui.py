"""Customer proof page and factory portal. Both open from a token, with no login."""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path

import streamlit as st

from artwork_agent.config import TrialSafetyError, load_config
from artwork_agent.db import open_database
from artwork_agent.portals import add_factory_event, factory_view, proof_view, submit_proof
from artwork_agent.records import project_detail, specs_map
from artwork_agent.seed import seed_demo

LABELS = {
    "title": ("Factory handoff", "工厂交接"),
    "specs": ("Specs", "规格"),
    "files": ("Final files", "最终文件"),
    "receipt": ("Confirm receipt", "确认收货"),
    "question": ("Ask a question", "提问"),
    "photo": ("Pre-production photo", "产前样照片"),
}


def _param(name: str):
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def _ready():
    config = load_config()
    db = open_database(config)
    if not config.trial:
        seed_demo(db, config)
    return config, db


def render_public_portal() -> bool:
    proof = _param("proof")
    factory = _param("factory")
    if not proof and not factory:
        return False
    try:
        config, db = _ready()
    except TrialSafetyError as exc:
        st.error(str(exc))
        return True
    if proof:
        _render_proof(db, config, proof)
    else:
        _render_factory(db, config, factory)
    db.commit()
    return True


def _render_proof(db, config, token: str) -> None:
    now = datetime.now().replace(microsecond=0)
    view = proof_view(db, token, now, config.company_name)
    if view["status"] != "open":
        st.markdown(f"<article class='card'><p>{view['message']}</p></article>", unsafe_allow_html=True)
        return
    link = view["link"]
    detail = project_detail(db, link["project_id"], config.as_of or now.date().isoformat(), config.nudge_days)
    st.markdown(f"<p class='kicker'>{config.company_name}</p>", unsafe_allow_html=True)
    st.markdown(f"<h1>Proof · {detail.get('brand', '')}</h1>", unsafe_allow_html=True)
    version = next((item for item in detail.get("versions", []) if item["version_label"] == link["version_label"]), None)
    if version and version.get("preview_available") and version.get("preview_path") and Path(version["preview_path"]).is_file():
        data = base64.b64encode(Path(version["preview_path"]).read_bytes()).decode("ascii")
        st.components.v1.html(
            f"""
            <img id="proof" src="data:image/png;base64,{data}" style="width:100%;max-width:420px;border-radius:16px" />
            <p style="font-family:sans-serif;color:#1E2A2A">Click the artwork to pin a comment.</p>
            <script>
            const img = document.getElementById("proof");
            img.onclick = function(event) {{
              const box = img.getBoundingClientRect();
              const x = ((event.clientX - box.left) / box.width).toFixed(3);
              const y = ((event.clientY - box.top) / box.height).toFixed(3);
              const url = new URL(window.top.location.href);
              url.searchParams.set("x", x);
              url.searchParams.set("y", y);
              window.top.location = url.toString();
            }};
            </script>
            """,
            height=520,
        )
    elif version:
        st.info(f"{version.get('file_name') or link['version_label']}: preview not available")
    pin_x = _param("x")
    pin_y = _param("y")
    if pin_x and pin_y:
        st.caption(f"Pin at {pin_x}, {pin_y}")
    for comment in view["comments"]:
        spot = ""
        if comment.get("pin_x") is not None:
            spot = f" · pin {comment['pin_x']}, {comment['pin_y']}"
        st.markdown(f"**{comment['author'] or 'Customer'}**{spot}")
        st.write(comment["body"])
    approved = [item["name"] for item in view["reviewers"] if item["decision"] == "approved" and item["name"]]
    pending = [item["email"] or item["name"] for item in view["reviewers"] if item["decision"] == "pending"]
    if approved:
        st.caption("Approved by " + ", ".join(approved))
    if pending:
        st.caption("Still waiting on " + ", ".join(pending))
    name = st.text_input("Your name", key=f"proof-name-{token}")
    note = st.text_area("Comment", key=f"proof-note-{token}")
    if st.button("Approve", key=f"proof-approve-{token}"):
        result = submit_proof(
            db, token, name=name, decision="approved", now=now, company=config.company_name, comment=note,
            pin_x=float(pin_x) if pin_x else None, pin_y=float(pin_y) if pin_y else None,
        )
        if result.get("error"):
            st.warning(result["error"])
        else:
            st.success("Approval recorded. It counts only if this is the latest version.")
    if st.button("Request changes", key=f"proof-changes-{token}"):
        submit_proof(
            db, token, name=name or "Customer", decision="changes", now=now, company=config.company_name,
            comment=note or "Changes requested.", pin_x=float(pin_x) if pin_x else None, pin_y=float(pin_y) if pin_y else None,
        )
        st.info("Change request recorded. Any approval on the latest version has been reset.")


def _render_factory(db, config, token: str) -> None:
    now = datetime.now().replace(microsecond=0)
    view = factory_view(db, token, now, config.company_name)
    if view["status"] != "open":
        st.markdown(f"<article class='card'><p>{view['message']}</p></article>", unsafe_allow_html=True)
        return
    link = view["link"]
    detail = project_detail(db, link["project_id"], config.as_of or now.date().isoformat(), config.nudge_days)
    specs = specs_map(db, link["project_id"])
    left, right = st.columns(2)
    left.markdown(f"### {LABELS['title'][0]}")
    right.markdown(f"### {LABELS['title'][1]}")
    left.write(detail.get("brand", ""))
    right.write(detail.get("brand", ""))
    for field in ("product_type", "size", "material", "finish", "pantone", "quantity", "ship_date"):
        value = (specs.get(field) or {}).get("value") or ""
        left.write(f"{field}: {value}")
        right.write(f"{field}: {value}")
    finals = [item for item in detail.get("versions", []) if item.get("final_for_production")]
    left.markdown(f"**{LABELS['files'][0]}**")
    right.markdown(f"**{LABELS['files'][1]}**")
    for item in finals:
        left.write(f"{item['version_label']} · {item['file_name']}")
        right.write(f"{item['version_label']} · {item['file_name']}")
    if st.button(f"{LABELS['receipt'][0]} / {LABELS['receipt'][1]}"):
        add_factory_event(db, link["project_id"], "receipt", "Factory confirmed receipt.", "", now.isoformat())
        st.success("Receipt confirmed.")
    question = st.text_area(f"{LABELS['question'][0]} / {LABELS['question'][1]}")
    if st.button("Send question", key="factory-question") and question.strip():
        add_factory_event(db, link["project_id"], "question", question.strip(), "", now.isoformat())
        st.success("Question added to the project timeline.")
    photo = st.file_uploader(f"{LABELS['photo'][0]} / {LABELS['photo'][1]}", type=["png", "jpg", "jpeg"])
    if photo is not None and st.button("Upload photo"):
        add_factory_event(db, link["project_id"], "photo", "Pre-production photo", photo.name, now.isoformat())
        st.success("Photo added to the project timeline.")
