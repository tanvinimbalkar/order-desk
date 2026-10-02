"""Artwork rules stay inside the JSON book and do not change the order book."""

from core.artwork import (
    activity_line,
    approval_on_latest,
    artwork_reply,
    compare_versions,
    days_waiting,
    draft_for,
    factory_draft,
    get_artwork_projects,
    get_checklist,
    get_messages,
    load_people,
    load_projects,
    normalize_workspace,
    preflight_gaps,
    project_by_id,
    stale_approvals,
    summary_for,
    vague_messages,
)
from core.chat import _tool_declarations, execute_tool
from data.sample import SEED, build_sample


def test_people_and_six_projects():
    people = load_people()
    assert people["account_manager"]["name"] == "Mia"
    assert people["designer"]["name"] == "Leo"
    assert people["production"]["name"] == "Priya"
    assert people["factory"]["name"] == "Mr. Chen"
    brands = [project["brand"] for project in load_projects()]
    assert brands == [
        "Ridgeline Coffee",
        "Copper Kettle Tea",
        "Bloom Bakery",
        "North Fork Roasters",
        "Sol Snacks",
        "Pine & Ash Candles",
    ]


def test_ridgeline_has_been_waiting_five_days_on_v3():
    project = project_by_id("RC-01")
    assert project["versions"][-1]["id"] == "v3"
    assert days_waiting(project) == 5
    assert approval_on_latest(project) is None
    assert vague_messages(project)[0]["text"] == "Looks good mostly."


def test_copper_kettle_approval_is_not_on_the_latest_version():
    project = project_by_id("Copper Kettle Tea")
    assert stale_approvals(project)[0]["version"] == "v2"
    assert approval_on_latest(project) is None
    assert "approval not on latest version" in preflight_gaps(project)
    draft = draft_for(project)
    assert "v2" in draft["body"]
    assert "v3" in draft["body"]


def test_bloom_revision_is_not_in_the_artwork():
    project = project_by_id("BB-01")
    rows = get_checklist("BB-01")["checklist"]
    assert rows[0]["status"] == "not done"
    assert "oat flour" in rows[0]["request"]
    assert get_messages("BB-01")["messages"][-1]["source"] == "whatsapp"


def test_north_fork_is_blocked_for_missing_pantone_and_quantity():
    project = project_by_id("NF-01")
    gaps = preflight_gaps(project)
    assert "Pantone colors" in gaps
    assert "quantity" in gaps
    pack = factory_draft(project)
    assert pack["ready"] is False
    assert "Pantone" in pack["question"]["body"]
    assert "quantity" in pack["question"]["body"]


def test_sol_snacks_keeps_both_quotes_for_a_person():
    project = project_by_id("SS-01")
    assert project["finish"] is None
    draft = draft_for(project)
    assert draft["flag"] == "Needs human decision"
    assert "Please print this run matte." in draft["body"]
    assert "We need gloss, not matte." in draft["body"]
    assert "Do not choose" in draft["body"]


def test_pine_and_ash_links_to_a_real_shipped_order():
    project = project_by_id("PA-01")
    assert project["order_id"] == "PO-850-1006"
    numbers = {packet.purchase_order.po_number for packet in build_sample(SEED)}
    assert project["order_id"] in numbers
    pack = factory_draft(project)
    assert pack["ready"] is True
    assert "PO-850-1006" in pack["english"]
    assert "PO-850-1006" in pack["chinese"]
    assert "3000" in pack["english"].replace(",", "") or "3,000" in pack["english"]


def test_empty_activity_and_a_clear_book():
    assert activity_line({"messages": []}) == "No activity yet."
    healthy = project_by_id("PA-01")
    assert summary_for([healthy]) == "Nothing needs attention today."


def test_workspace_query_defaults_to_orders():
    assert normalize_workspace(None) == "orders"
    assert normalize_workspace("nope") == "orders"
    assert normalize_workspace("artwork") == "artwork"
    assert normalize_workspace("orders") == "orders"


def test_compare_drops_unknown_items_and_low_confidence():
    result = compare_versions(
        "RC-01",
        "v1",
        "v3",
        [
            {"id": "not-a-real-item", "status": "done", "reason": "Invented."},
            {"id": "rc-logo", "status": "done", "reason": "Looks larger.", "confidence": "low"},
        ],
    )
    ids = [item["id"] for item in result["items"]]
    assert ids == ["rc-logo"]
    assert result["items"][0]["status"] == "unclear"
    assert result["items"][0]["reason"] == "unclear, check manually."


def test_chat_tools_answer_the_coffee_question_from_the_book():
    reply = artwork_reply("Which coffee orders are approved but not shipped?")
    assert "get_artwork_projects" in reply["steps"][0]
    assert "North Fork Roasters" in reply["answer"]
    assert "not shipped" in reply["answer"]
    assert "nf-2" in reply["answer"]
    assert "Ridgeline Coffee" in reply["answer"]
    assert "not approved" in reply["answer"]
    listed = execute_tool("get_artwork_projects", {}, [], set())
    assert len(listed["projects"]) == 6
    assert any(item["order_id"] == "PO-850-1006" for item in listed["projects"])


def test_order_tool_list_is_unchanged():
    names = [item.name for item in _tool_declarations()]
    assert names == ["list_exceptions", "get_order", "draft_email", "mark_resolved"]


def test_artwork_projects_are_in_the_tool_list():
    listed = get_artwork_projects()
    assert listed["as_of"] == "2026-09-28"
    ridgeline = next(item for item in listed["projects"] if item["id"] == "RC-01")
    assert ridgeline["version"] == "v3"
    assert ridgeline["waiting_on"] == "Customer"
    assert ridgeline["days_waiting"] == 5
