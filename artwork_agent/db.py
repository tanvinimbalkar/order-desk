"""SQLite for the public demo and Postgres for a private trial. Same tables."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from artwork_agent.config import ROOT, Config

TABLES = [
    "audit_log",
    "actions",
    "comments",
    "proof_reviewers",
    "proof_links",
    "factory_events",
    "factory_links",
    "checklist_items",
    "approvals",
    "message_links",
    "unsorted",
    "messages",
    "related_files",
    "versions",
    "specs",
    "match_rules",
    "briefs",
    "connectors",
    "secrets",
    "team",
    "settings",
    "projects",
]

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        code TEXT NOT NULL,
        brand TEXT NOT NULL,
        stage TEXT NOT NULL,
        waiting_on TEXT,
        waiting_since TEXT,
        ship_date TEXT,
        customer_name TEXT,
        customer_email TEXT,
        customer_domain TEXT,
        customer_phone TEXT,
        drive_folder TEXT,
        clickup_task TEXT,
        hubspot_deal TEXT,
        order_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS versions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        version_label TEXT NOT NULL,
        uploaded_at TEXT,
        uploader TEXT,
        drive_file_id TEXT,
        file_name TEXT,
        preview_path TEXT,
        preview_available INTEGER NOT NULL DEFAULT 0,
        final_for_production INTEGER NOT NULL DEFAULT 0,
        byte_size INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        external_id TEXT,
        content_hash TEXT NOT NULL,
        source TEXT NOT NULL,
        sender TEXT,
        sent_at TEXT,
        subject TEXT,
        body TEXT,
        original_body TEXT,
        translation TEXT,
        unclear INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS message_links (
        message_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        reason TEXT,
        confidence REAL,
        PRIMARY KEY (message_id, project_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS unsorted (
        message_id TEXT PRIMARY KEY
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        version_label TEXT,
        approver TEXT,
        approved_at TEXT,
        quote TEXT,
        message_id TEXT,
        counts INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS checklist_items (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        request TEXT NOT NULL,
        status TEXT NOT NULL,
        done_in TEXT,
        message_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS specs (
        project_id TEXT NOT NULL,
        field TEXT NOT NULL,
        value TEXT,
        source TEXT,
        PRIMARY KEY (project_id, field)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS related_files (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        name TEXT,
        drive_file_id TEXT,
        note TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comments (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        version_label TEXT,
        author TEXT,
        body TEXT,
        pin_x REAL,
        pin_y REAL,
        created_at TEXT,
        parent_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS actions (
        id TEXT PRIMARY KEY,
        project_id TEXT,
        kind TEXT,
        status TEXT,
        to_addr TEXT,
        subject TEXT,
        body TEXT,
        issue TEXT,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id TEXT PRIMARY KEY,
        at TEXT,
        actor TEXT,
        action TEXT,
        detail TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS briefs (
        id TEXT PRIMARY KEY,
        created_at TEXT,
        summary TEXT,
        body TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS proof_links (
        token TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        version_label TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS proof_reviewers (
        id TEXT PRIMARY KEY,
        token TEXT NOT NULL,
        name TEXT,
        email TEXT,
        decision TEXT,
        decided_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS factory_links (
        token TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS factory_events (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        body TEXT,
        file_name TEXT,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS connectors (
        name TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        detail TEXT,
        last_synced TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS secrets (
        name TEXT PRIMARY KEY,
        ciphertext TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team (
        email TEXT PRIMARY KEY,
        name TEXT,
        password_hash TEXT,
        role TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS match_rules (
        id TEXT PRIMARY KEY,
        pattern TEXT NOT NULL,
        project_id TEXT NOT NULL,
        kind TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
]


class Database:
    def __init__(self, conn, dialect: str):
        self.conn = conn
        self.dialect = dialect

    def _sql(self, sql: str) -> str:
        if self.dialect == "postgres":
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params: tuple = ()):
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), params)
        return cur

    def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        rows = self.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        row = self.execute(sql, params).fetchone()
        return dict(row) if row else None

    def commit(self) -> None:
        self.conn.commit()


def new_id() -> str:
    return uuid.uuid4().hex


def migrate(db: Database) -> None:
    for statement in SCHEMA:
        db.execute(statement)
    db.commit()


def connect_sqlite(path: str | Path = ":memory:") -> Database:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    db = Database(conn, "sqlite")
    migrate(db)
    return db


def connect_postgres(url: str) -> Database:
    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(url, row_factory=dict_row)
    return Database(conn, "postgres")


def open_database(config: Config) -> Database:
    if config.trial and config.database_url:
        db = connect_postgres(config.database_url)
        migrate(db)
        return db
    if config.database_url.startswith("sqlite:"):
        return connect_sqlite(config.database_url.split("sqlite:", 1)[1])
    return connect_sqlite(ROOT / "data" / "artwork" / "demo.sqlite")


def wipe(db: Database) -> None:
    for table in TABLES:
        db.execute(f"DELETE FROM {table}")
    db.commit()
