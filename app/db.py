"""SQLite access layer. Plain sqlite3 (no ORM) for zero version-surprise reliability.

Schema:
  users(id, email UNIQUE, password_hash, plan ['free'|'pro'], stripe_customer_id, created_at)
  api_keys(id, user_id, key UNIQUE, revoked, created_at)
  usage(id, user_id, endpoint, ts)   -- one row per generated image
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from .config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    email               TEXT UNIQUE NOT NULL,
    password_hash       TEXT NOT NULL,
    plan                TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id  TEXT,
    created_at          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    key         TEXT UNIQUE NOT NULL,
    revoked     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    endpoint    TEXT NOT NULL,
    ts          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_user_ts ON usage(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_api_keys_key ON api_keys(key);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> str:
    """Resolve the DB path at call time so per-test DB_PATH overrides take effect
    even after app.config was imported (settings is import-bound)."""
    return os.environ.get("DB_PATH", settings.db_path)


def connect() -> sqlite3.Connection:
    # check_same_thread=False: a per-request connection may be created by the sync
    # get_db() dependency in a threadpool worker, then used by an async route handler
    # running on the event-loop thread. The connection is never shared concurrently
    # (one request owns it for its lifetime), so disabling the thread guard is safe here.
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_db():
    """FastAPI dependency: yields a connection, always closes it."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
