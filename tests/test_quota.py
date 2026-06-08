"""Tests for quota module: usage recording and monthly limit enforcement."""
import pytest

from app.quota import (
    PLANS,
    plan_of,
    usage_this_month,
    record_usage,
    check_quota,
)
from app.db import connect, init_db


@pytest.fixture
def db():
    """Fresh DB connection for each test."""
    init_db()
    conn = connect()
    yield conn
    conn.close()


class TestPlanOf:
    """plan_of retrieval tests."""

    def test_plan_of_free(self):
        """plan_of returns free plan config."""
        plan = plan_of("free")
        assert plan["label"] == "Free"
        assert plan["monthly_limit"] == 50

    def test_plan_of_pro(self):
        """plan_of returns pro plan config."""
        plan = plan_of("pro")
        assert plan["label"] == "Pro"
        assert plan["monthly_limit"] == 5000

    def test_plan_of_unknown_defaults_to_free(self):
        """plan_of defaults to free for unknown plan."""
        plan = plan_of("unknown")
        assert plan == PLANS["free"]

    def test_plan_of_none_defaults_to_free(self):
        """plan_of defaults to free for None."""
        plan = plan_of(None)
        assert plan == PLANS["free"]

    def test_plan_of_free_has_watermark(self):
        """free plan includes watermark."""
        plan = plan_of("free")
        assert plan["watermark"] is True

    def test_plan_of_pro_no_watermark(self):
        """pro plan has no watermark."""
        plan = plan_of("pro")
        assert plan["watermark"] is False

    def test_plan_of_custom_colors_free_disallowed(self):
        """free plan disallows custom colors."""
        plan = plan_of("free")
        assert plan["custom_colors"] is False

    def test_plan_of_custom_colors_pro_allowed(self):
        """pro plan allows custom colors."""
        plan = plan_of("pro")
        assert plan["custom_colors"] is True


class TestUsageRecording:
    """usage_this_month and record_usage tests."""

    def test_usage_this_month_zero_initially(self, db):
        """usage_this_month returns 0 for user with no usage."""
        # Insert a dummy user
        db.execute(
            "INSERT INTO users (email, password_hash, plan, created_at) VALUES (?, ?, ?, ?)",
            ("test@example.com", "hash", "free", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()
        user_id = db.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]
        count = usage_this_month(db, user_id)
        assert count == 0

    def test_record_usage_increments_count(self, db):
        """record_usage increments usage_this_month."""
        db.execute(
            "INSERT INTO users (email, password_hash, plan, created_at) VALUES (?, ?, ?, ?)",
            ("user@example.com", "hash", "free", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()
        user_id = db.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]

        record_usage(db, user_id, "/v1/og")
        count = usage_this_month(db, user_id)
        assert count == 1

    def test_record_usage_multiple_increments(self, db):
        """record_usage multiple times increments correctly."""
        db.execute(
            "INSERT INTO users (email, password_hash, plan, created_at) VALUES (?, ?, ?, ?)",
            ("multi@example.com", "hash", "free", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()
        user_id = db.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]

        record_usage(db, user_id, "/v1/og")
        record_usage(db, user_id, "/v1/og")
        record_usage(db, user_id, "/v1/og")
        count = usage_this_month(db, user_id)
        assert count == 3

    def test_usage_this_month_per_user_isolated(self, db):
        """usage_this_month only counts for the specified user."""
        # Create two users
        db.execute(
            "INSERT INTO users (email, password_hash, plan, created_at) VALUES (?, ?, ?, ?)",
            ("user1@example.com", "hash", "free", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()
        user1_id = db.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]

        db.execute(
            "INSERT INTO users (email, password_hash, plan, created_at) VALUES (?, ?, ?, ?)",
            ("user2@example.com", "hash", "free", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()
        user2_id = db.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]

        record_usage(db, user1_id, "/v1/og")
        record_usage(db, user1_id, "/v1/og")
        record_usage(db, user2_id, "/v1/og")

        assert usage_this_month(db, user1_id) == 2
        assert usage_this_month(db, user2_id) == 1


class TestCheckQuota:
    """check_quota enforcement tests."""

    def test_check_quota_allowed_under_limit(self, db):
        """check_quota allows usage under limit."""
        db.execute(
            "INSERT INTO users (email, password_hash, plan, created_at) VALUES (?, ?, ?, ?)",
            ("under@example.com", "hash", "free", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()
        user_id = db.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]

        allowed, used, limit = check_quota(db, user_id, "free")
        assert allowed is True
        assert used == 0
        assert limit == 50

    def test_check_quota_denied_at_limit(self, db, monkeypatch):
        """check_quota denies usage at or above limit."""
        db.execute(
            "INSERT INTO users (email, password_hash, plan, created_at) VALUES (?, ?, ?, ?)",
            ("at_limit@example.com", "hash", "free", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()
        user_id = db.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]

        # Monkeypatch free plan limit to 2 for testing
        monkeypatch.setitem(PLANS["free"], "monthly_limit", 2)

        record_usage(db, user_id, "/v1/og")
        record_usage(db, user_id, "/v1/og")

        allowed, used, limit = check_quota(db, user_id, "free")
        assert allowed is False
        assert used == 2
        assert limit == 2

    def test_check_quota_pro_higher_limit(self, db):
        """check_quota respects pro plan higher limit."""
        db.execute(
            "INSERT INTO users (email, password_hash, plan, created_at) VALUES (?, ?, ?, ?)",
            ("pro@example.com", "hash", "pro", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()
        user_id = db.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]

        allowed, used, limit = check_quota(db, user_id, "pro")
        assert allowed is True
        assert used == 0
        assert limit == 5000

    def test_check_quota_returns_tuple(self, db):
        """check_quota returns (bool, int, int) tuple."""
        db.execute(
            "INSERT INTO users (email, password_hash, plan, created_at) VALUES (?, ?, ?, ?)",
            ("tuple@example.com", "hash", "free", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()
        user_id = db.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]

        result = check_quota(db, user_id, "free")
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert isinstance(result[0], bool)
        assert isinstance(result[1], int)
        assert isinstance(result[2], int)

    def test_check_quota_boundary_just_over_limit(self, db, monkeypatch):
        """check_quota denies when usage exactly equals limit."""
        db.execute(
            "INSERT INTO users (email, password_hash, plan, created_at) VALUES (?, ?, ?, ?)",
            ("boundary@example.com", "hash", "free", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()
        user_id = db.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]

        monkeypatch.setitem(PLANS["free"], "monthly_limit", 1)
        record_usage(db, user_id, "/v1/og")

        allowed, used, limit = check_quota(db, user_id, "free")
        assert allowed is False  # used >= limit, not allowed
        assert used == 1
        assert limit == 1
