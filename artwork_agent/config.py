"""Demo defaults, with a tenant file and environment variables for a real trial."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEMO = {
    "mode": "demo",
    "company_name": "Linden Supply",
    "database_url": "",
    "as_of": "2026-09-28",
    "project_code_pattern": r"[A-Z]{2}-\d{2}",
    "confidence_threshold": 0.75,
    "nudge_days": 3,
    "brief_time": "08:00",
    "timezone": "America/Denver",
    "brief_delivery": "draft",
    "brief_sender": "mia@lindensupply.example",
    "llm_provider": "gemini",
    "llm_model": "",
    "llm_paid": False,
    "retention_days": 90,
    "minutes_per_issue": 12,
    "minutes_per_draft": 8,
    "minutes_per_proof": 20,
    "connectors": {
        "gmail": {"enabled": False},
        "drive": {"enabled": False},
        "whatsapp": {"enabled": False},
        "clickup": {"enabled": False},
        "hubspot": {"enabled": False},
    },
}


@dataclass
class Config:
    mode: str = "demo"
    company_name: str = "Linden Supply"
    database_url: str = ""
    as_of: str = "2026-09-28"
    project_code_pattern: str = r"[A-Z]{2}-\d{2}"
    confidence_threshold: float = 0.75
    nudge_days: int = 3
    brief_time: str = "08:00"
    timezone: str = "America/Denver"
    brief_delivery: str = "draft"
    brief_sender: str = "mia@lindensupply.example"
    llm_provider: str = "gemini"
    llm_model: str = ""
    llm_paid: bool = False
    retention_days: int = 90
    minutes_per_issue: int = 12
    minutes_per_draft: int = 8
    minutes_per_proof: int = 20
    connectors: dict = field(default_factory=dict)
    token_key: str = ""
    llm_api_key: str = ""
    admin_email: str = ""
    admin_password: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""

    @property
    def trial(self) -> bool:
        return self.mode == "trial"


class TrialSafetyError(RuntimeError):
    """Raised when trial mode would send customer data to a free-tier model."""


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _merge(base: dict, incoming: dict) -> dict:
    merged = dict(base)
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise TrialSafetyError("Install PyYAML to read a tenant file.") from exc
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise TrialSafetyError("The tenant file must be a mapping.")
    return loaded


def load_config() -> Config:
    data = dict(DEMO)
    path = os.environ.get("ORDER_DESK_TENANT", "")
    tenant = Path(path) if path else ROOT / "tenant.yaml"
    if tenant.is_file():
        data = _merge(data, _read_yaml(tenant))
    env_mode = os.environ.get("ORDER_DESK_MODE", "").strip().lower()
    if env_mode in {"demo", "trial"}:
        data["mode"] = env_mode
    if os.environ.get("DATABASE_URL"):
        data["database_url"] = os.environ["DATABASE_URL"]
    if os.environ.get("LLM_PROVIDER"):
        data["llm_provider"] = os.environ["LLM_PROVIDER"]
    if os.environ.get("LLM_MODEL"):
        data["llm_model"] = os.environ["LLM_MODEL"]
    if os.environ.get("LLM_PAID"):
        data["llm_paid"] = _as_bool(os.environ["LLM_PAID"])
    config = Config(
        mode=str(data.get("mode") or "demo"),
        company_name=str(data.get("company_name") or "Linden Supply"),
        database_url=str(data.get("database_url") or ""),
        as_of=str(data.get("as_of") or ""),
        project_code_pattern=str(data.get("project_code_pattern") or DEMO["project_code_pattern"]),
        confidence_threshold=float(data.get("confidence_threshold") or 0.75),
        nudge_days=int(data.get("nudge_days") or 3),
        brief_time=str(data.get("brief_time") or "08:00"),
        timezone=str(data.get("timezone") or "America/Denver"),
        brief_delivery=str(data.get("brief_delivery") or "draft"),
        brief_sender=str(data.get("brief_sender") or ""),
        llm_provider=str(data.get("llm_provider") or "gemini"),
        llm_model=str(data.get("llm_model") or ""),
        llm_paid=_as_bool(data.get("llm_paid")),
        retention_days=int(data.get("retention_days") or 90),
        minutes_per_issue=int(data.get("minutes_per_issue") or 12),
        minutes_per_draft=int(data.get("minutes_per_draft") or 8),
        minutes_per_proof=int(data.get("minutes_per_proof") or 20),
        connectors=data.get("connectors") or {},
        token_key=os.environ.get("TOKEN_KEY", ""),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        admin_email=os.environ.get("ADMIN_EMAIL", ""),
        admin_password=os.environ.get("ADMIN_PASSWORD", ""),
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=int(os.environ.get("SMTP_PORT") or 587),
        smtp_user=os.environ.get("SMTP_USER", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    )
    if config.mode not in {"demo", "trial"}:
        config.mode = "demo"
    if config.trial and not config.llm_paid:
        raise TrialSafetyError(
            "Trial mode requires a paid LLM. Set llm.paid to true and use a paid API key. "
            "Customer data is never sent to a free-tier model."
        )
    if config.trial and config.llm_paid and not config.llm_api_key:
        raise TrialSafetyError("Trial mode needs LLM_API_KEY for the paid model named in the tenant file.")
    return config
