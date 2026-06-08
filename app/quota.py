"""Plan definitions and monthly quota enforcement.

The PLAN of a user is ALWAYS read from the DB, never from request input — this is a
security boundary, not a feature. Usage is counted per calendar month (UTC).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .db import utcnow

PLANS: dict[str, dict] = {
    "free": {
        "label": "Free",
        "monthly_limit": 50,
        "watermark": True,
        "custom_colors": False,
        "price_display": "$0",
    },
    "pro": {
        "label": "Pro",
        "monthly_limit": 5000,
        "watermark": False,
        "custom_colors": True,
        "price_display": "$9/mo",
    },
}


def plan_of(plan: str | None) -> dict:
    """Return the plan config dict, defaulting to free for unknown/missing plans."""
    return PLANS.get(plan or "free", PLANS["free"])


def _month_prefix() -> str:
    """e.g. '2026-06' — UTC calendar month, matches ISO timestamps stored in usage.ts."""
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def usage_this_month(db: sqlite3.Connection, user_id: int) -> int:
    row = db.execute(
        "SELECT COUNT(*) AS n FROM usage WHERE user_id = ? AND ts LIKE ?",
        (user_id, f"{_month_prefix()}%"),
    ).fetchone()
    return int(row["n"]) if row else 0


def record_usage(db: sqlite3.Connection, user_id: int, endpoint: str) -> None:
    db.execute(
        "INSERT INTO usage (user_id, endpoint, ts) VALUES (?, ?, ?)",
        (user_id, endpoint, utcnow()),
    )
    db.commit()


def check_quota(db: sqlite3.Connection, user_id: int, plan: str) -> tuple[bool, int, int]:
    """Return (allowed, used, limit). allowed=False when used >= limit."""
    limit = plan_of(plan)["monthly_limit"]
    used = usage_this_month(db, user_id)
    return (used < limit, used, limit)
