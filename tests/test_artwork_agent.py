"""Rules for the artwork agent. The order book is not involved."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from artwork_agent.checks import compare_checklist, expired_message, grounded, is_vague, link_status
from artwork_agent.config import Config, TrialSafetyError, load_config
from artwork_agent.connectors import apply_gmail_messages, gmail_can_send, import_whatsapp, record_drive_file
from artwork_agent.crypto import decrypt_token, encrypt_token
from artwork_agent.db import connect_sqlite, wipe
from artwork_agent.ingest import assign_message
from artwork_agent.llm import generate
from artwork_agent.matching import match_message
from artwork_agent.portals import create_proof_link, proof_view, submit_proof
from artwork_agent.records import project_detail
from artwork_agent.seed import seed_demo
from delete_tenant_data import main as delete_main


def _config():
    return Config(mode="demo", as_of="2026-09-28", company_name="Linden Supply", llm_paid=False)


def _seeded():
    db = connect_sqlite(":memory:")
    seed_demo(db, _config())
    return db


def _projects():
    return [
        {"id": "RC-01", "code": "RC-01", "customer_domain": "ridgeline.example", "customer_phone": "", "drive_folder": "Ridgeline Coffee", "clickup_task": "", "hubspot_deal": ""},
        {"id": "CK-01", "code": "CK-01", "customer_domain": "copperkettle.example", "customer_phone": "", "drive_folder": "Copper Kettle Tea", "clickup_task": "task-9", "hubspot_deal": "deal-9"},
    ]


def test_project_code_can_link_two_projects():
    result = match_message("Please update RC-01 and CK-01 today", pattern=r"[A-Z]{2}-\d{2}", projects=_projects())
    assert [item["project_id"] for item in result["links"]] == ["RC-01", "CK-01"]
    assert result["unsorted"] is False


def test_domain_phone_folder_and_low_confidence():
    domain = match_message("hello", pattern=r"[A-Z]{2}-\d{2}", projects=_projects(), sender_email="ava@ridgeline.example")
    assert domain["links"][0]["reason"] == "customer domain"
    phone = match_message("hello", pattern=r"[A-Z]{2}-\d{2}", projects=[{"id": "SS-01", "code": "SS-01", "customer_domain": "", "customer_phone": "+15555550198", "drive_folder": "", "clickup_task": "", "hubspot_deal": ""}], sender_phone="555-555-0198")
    assert phone["links"][0]["project_id"] == "SS-01"
    folder = match_message("new file", pattern=r"[A-Z]{2}-\d{2}", projects=_projects(), drive_folder="Ridgeline Coffee")
    assert folder["links"][0]["reason"] == "drive folder"
    low = match_message("the pouch", pattern=r"[A-Z]{2}-\d{2}", projects=_projects(), ai_guesses=[{"project_id": "RC-01", "confidence": 0.4}], threshold=0.75)
    assert low["unsorted"] is True


def test_saved_rule_matches_next_time():
    db = connect_sqlite(":memory:")
    db.execute(
        "INSERT INTO projects (id, code, brand, stage) VALUES ('RC-01', 'RC-01', 'Ridgeline Coffee', 'Proof sent')"
    )
    from artwork_agent.ingest import add_message

    added = add_message(db, source="email", sender="pat@newbrand.example", sent_at="2026-09-01T00:00:00", body="Where is the proof?")
    assign_message(db, added["id"], "RC-01", "newbrand.example", "domain", "2026-09-28T00:00:00")
    result = match_message(
        "following up",
        pattern=r"[A-Z]{2}-\d{2}",
        projects=[{"id": "RC-01", "code": "RC-01", "customer_domain": "", "customer_phone": "", "drive_folder": "", "clickup_task": "", "hubspot_deal": ""}],
        sender_email="pat@newbrand.example",
        rules=db.fetchall("SELECT * FROM match_rules"),
    )
    assert result["links"][0]["reason"] == "saved rule"


def test_seed_flags_old_approval_missing_spec_and_conflict():
    db = _seeded()
    copper = project_detail(db, "CK-01", "2026-09-28", 3)
    assert copper["stale"][0]["version_label"] == "v2"
    assert copper["approval_on_latest"] == []
    assert "approval not on latest version" in copper["gaps"]
    north = project_detail(db, "NF-01", "2026-09-28", 3)
    assert "Pantone colors" in north["gaps"]
    assert "quantity" in north["gaps"]
    assert north["risk"] == "red"
    sol = project_detail(db, "SS-01", "2026-09-28", 3)
    quotes = " ".join(item["request"] for item in sol["conflicts"])
    assert "Please print this run matte." in quotes
    assert "We need gloss, not matte." in quotes
    ridge = project_detail(db, "RC-01", "2026-09-28", 3)
    assert ridge["days_waiting"] == 5
    assert ridge["version"] == "v3"
    vague = db.fetchone("SELECT unclear FROM messages WHERE id = 'rc-4'")
    assert vague["unclear"] == 1
    assert is_vague("Looks good mostly.")
    pine = project_detail(db, "PA-01", "2026-09-28", 3)
    assert pine["risk"] == "green"
    assert pine["order_id"] == "PO-850-1006"
    assert pine["gaps"] == []


def test_whatsapp_reupload_is_deduped():
    db = connect_sqlite(":memory:")
    text = "[9/20/26, 11:20:00 AM] Lila Berg: Please move the bakery script below the logo\n"
    config = _config()
    first = import_whatsapp(db, config, text, "2026-09-28T00:00:00")
    second = import_whatsapp(db, config, text, "2026-09-28T00:00:00")
    assert first["imported"] == 1
    assert second["duplicates"] == 1
    assert second["imported"] == 0


def test_gmail_messages_dedupe_by_external_id_and_never_send():
    db = connect_sqlite(":memory:")
    config = _config()
    row = {"external_id": "abc", "from_email": "ava@ridgeline.example", "sender": "Ava", "sent_at": "2026-09-08T00:00:00", "subject": "RC-01", "body": "Please make the logo larger."}
    db.execute("INSERT INTO projects (id, code, brand, stage, customer_domain) VALUES ('RC-01', 'RC-01', 'Ridgeline', 'Proof sent', 'ridgeline.example')")
    apply_gmail_messages(db, config, [row], "2026-09-28T00:00:00")
    again = apply_gmail_messages(db, config, [row], "2026-09-28T00:00:00")
    assert again["duplicates"] == 1
    assert gmail_can_send() is False
    source = Path("artwork_agent/connectors.py").read_text(encoding="utf-8")
    assert "messages().send" not in source
    assert "users.messages.send" not in source


def test_large_and_ai_files_keep_metadata_without_a_preview():
    db = connect_sqlite(":memory:")
    db.execute("INSERT INTO projects (id, code, brand, stage) VALUES ('RC-01', 'RC-01', 'Ridgeline', 'New')")
    huge = record_drive_file(db, project_id="RC-01", name="art.pdf", drive_file_id="big", uploaded_at="2026-09-01", uploader="Leo", byte_size=30_000_000)
    native = record_drive_file(db, project_id="RC-01", name="art.ai", drive_file_id="ai", uploaded_at="2026-09-02", uploader="Leo", byte_size=1000)
    assert huge["preview_available"] == 0
    assert native["note"] == "preview not available"


def test_proof_expiry_and_change_request_resets_approval():
    db = _seeded()
    now = datetime(2026, 9, 28, 12, 0, 0)
    token = create_proof_link(db, "PA-01", "v2", now)
    open_view = proof_view(db, token, now, "Linden Supply")
    assert open_view["status"] == "open"
    saved = submit_proof(db, token, name="Chris Hale", decision="approved", now=now, company="Linden Supply")
    assert saved["status"] == "saved"
    submit_proof(db, token, name="Chris Hale", decision="changes", now=now, company="Linden Supply", comment="Please move the wordmark.")
    latest = db.fetchall("SELECT counts FROM approvals WHERE project_id = 'PA-01' AND version_label = 'v2'")
    assert all(row["counts"] == 0 for row in latest)
    expired = {"expires_at": (now - timedelta(days=1)).isoformat(), "revoked": 0}
    assert link_status(expired, now) == "expired"
    assert expired_message("Linden Supply") == "This link has expired, please contact Linden Supply."
    db.execute("UPDATE proof_links SET expires_at = ? WHERE token = ?", ((now - timedelta(days=1)).isoformat(), token))
    closed = proof_view(db, token, now, "Linden Supply")
    assert closed["status"] == "expired"


def test_vague_text_is_not_approval_and_vision_low_confidence_is_unclear():
    assert is_vague("👍")
    items = [{"id": "rc-logo", "request": "Make the mountain logo larger", "status": "done", "done_in": "v2", "message_id": "rc-2"}]
    versions = [{"version_label": "v1"}, {"version_label": "v3"}]
    result = compare_checklist(items, versions, "v3", [{"id": "rc-logo", "status": "done", "reason": "Looks larger.", "confidence": "low"}, {"id": "made-up", "status": "done", "reason": "no"}])
    assert result[0]["status"] == "unclear"
    assert result[0]["reason"] == "unclear, check manually."
    assert len(result) == 1
    assert grounded("Approved on v9", {"v1", "v3"}) is False


def test_tokens_are_encrypted_and_wipe_removes_rows():
    key = "test-token-key"
    hidden = encrypt_token("super-secret", key)
    assert "super-secret" not in hidden
    assert decrypt_token(hidden, key) == "super-secret"
    db = _seeded()
    wipe(db)
    assert db.fetchone("SELECT id FROM projects LIMIT 1") is None


def test_trial_mode_refuses_a_free_model(monkeypatch):
    monkeypatch.setenv("ORDER_DESK_MODE", "trial")
    monkeypatch.delenv("LLM_PAID", raising=False)
    with pytest.raises(TrialSafetyError):
        load_config()


def test_demo_mode_does_not_call_the_model():
    calls = []

    def _call(prompt):
        calls.append(prompt)
        return "invented v99"

    assert generate(Config(mode="demo"), "hello", call=_call) == (None, None)
    assert calls == []


def test_llm_error_is_retried_then_skipped():
    attempts = {"n": 0}

    def _call(_prompt):
        attempts["n"] += 1
        raise RuntimeError("429")

    config = Config(mode="trial", llm_paid=True, llm_api_key="paid-key", llm_model="claude-sonnet")
    text, error = generate(config, "hello", call=_call, sleep=lambda _seconds: None)
    assert text is None
    assert error == "could not process, will retry next sync."
    assert attempts["n"] == 3


def test_delete_script_requires_confirmation():
    with pytest.raises(SystemExit):
        delete_main([])
