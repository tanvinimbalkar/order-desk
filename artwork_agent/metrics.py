"""Trial counts and a one-page PDF. Assumptions stay visible and editable."""

from __future__ import annotations

from artwork_agent.db import Database
from artwork_agent.records import project_rows, setting


def metrics(db: Database, as_of: str, nudge_days: int) -> dict:
    projects = project_rows(db, as_of, nudge_days)
    issues = 0
    waiting = {"customer": [], "designer": [], "factory": [], "us": []}
    for project in projects:
        if project["stale"]:
            issues += 1
        if project["conflicts"]:
            issues += 1
        if project["stage"] == "Approved" and any(item in project["gaps"] for item in ("Pantone colors", "quantity", "dieline")):
            issues += 1
        if project["days_waiting"] >= nudge_days and project.get("waiting_on"):
            issues += 1
        party = project.get("waiting_on") or ""
        if party in waiting:
            waiting[party].append(project["days_waiting"])
    vague = db.fetchone("SELECT COUNT(*) AS n FROM messages WHERE unclear = 1")
    issues += int(vague["n"])
    drafts = db.fetchone("SELECT COUNT(*) AS n FROM actions WHERE kind = 'draft'")
    used = db.fetchone("SELECT COUNT(*) AS n FROM actions WHERE status = 'draft_saved'")
    proofs = db.fetchone("SELECT COUNT(*) AS n FROM proof_links")
    approved = db.fetchone("SELECT COUNT(*) AS n FROM proof_reviewers WHERE decision = 'approved'")
    handoffs = db.fetchone("SELECT COUNT(*) AS n FROM factory_links")
    per_issue = int(setting(db, "minutes_per_issue", "12"))
    per_draft = int(setting(db, "minutes_per_draft", "8"))
    per_proof = int(setting(db, "minutes_per_proof", "20"))
    minutes = issues * per_issue + int(drafts["n"]) * per_draft + int(proofs["n"]) * per_proof
    averages = {}
    for party, days in waiting.items():
        averages[party] = round(sum(days) / len(days), 1) if days else 0
    return {
        "issues_caught": issues,
        "drafts_created": int(drafts["n"]),
        "drafts_used": int(used["n"]),
        "proofs_sent": int(proofs["n"]),
        "proofs_approved": int(approved["n"]),
        "factory_handoffs": int(handoffs["n"]),
        "avg_days_waiting": averages,
        "minutes_per_issue": per_issue,
        "minutes_per_draft": per_draft,
        "minutes_per_proof": per_proof,
        "hours_saved": round(minutes / 60, 1),
    }


def metrics_pdf(company: str, report: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=16)
    pdf.multi_cell(180, 10, f"{company} trial results")
    pdf.ln(2)
    pdf.set_font("Helvetica", size=11)
    lines = [
        f"Issues caught: {report['issues_caught']}",
        f"Drafts created: {report['drafts_created']}",
        f"Drafts saved for a person to send: {report['drafts_used']}",
        f"Proofs sent: {report['proofs_sent']}",
        f"Proofs approved: {report['proofs_approved']}",
        f"Factory handoffs: {report['factory_handoffs']}",
        "Average days waiting:",
    ]
    for party, days in report["avg_days_waiting"].items():
        lines.append(f"  {party}: {days}")
    lines.append(f"Estimated hours saved: {report['hours_saved']}")
    lines.append(
        "Assumptions: "
        f"{report['minutes_per_issue']} minutes per issue caught, "
        f"{report['minutes_per_draft']} minutes per draft, "
        f"{report['minutes_per_proof']} minutes per proof."
    )
    lines.append("The app stores drafts. It does not send customer email.")
    for line in lines:
        pdf.set_x(15)
        pdf.multi_cell(180, 8, line)
    return bytes(pdf.output())
