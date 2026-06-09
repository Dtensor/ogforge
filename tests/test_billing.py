"""Tests for Razorpay one-time billing (Payment Link = 30 days of Pro).

Dev path (no RAZORPAY_WEBHOOK_SECRET in the test env) skips signature verification,
so we feed synthetic payment_link.paid events and assert Pro is granted with an expiry.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.auth import create_user
from app.billing import handle_webhook
from app.db import connect, init_db
from app.quota import effective_plan


@pytest.fixture
def db():
    init_db()
    conn = connect()
    yield conn
    conn.close()


def _paid_event(user_id, link_id="plink_test") -> bytes:
    payload = {
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": link_id,
                    "status": "paid",
                    "notes": {"user_id": str(user_id)} if user_id is not None else {},
                }
            }
        },
    }
    return json.dumps(payload).encode("utf-8")


class TestPaymentGrantsPro:
    def test_paid_grants_pro_with_future_expiry(self, db):
        uid = create_user(db, "paid@example.com", "pw")
        result = handle_webhook(db, _paid_event(uid), sig_header=None)
        assert result["handled"] == "payment_link.paid"
        row = db.execute("SELECT plan, pro_until FROM users WHERE id = ?", (uid,)).fetchone()
        assert row["plan"] == "pro"
        assert row["pro_until"] is not None
        assert datetime.fromisoformat(row["pro_until"]) > datetime.now(timezone.utc)

    def test_paid_makes_effective_plan_pro(self, db):
        uid = create_user(db, "eff@example.com", "pw")
        handle_webhook(db, _paid_event(uid), sig_header=None)
        user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        assert effective_plan(dict(user)) == "pro"

    def test_second_payment_extends_window(self, db):
        uid = create_user(db, "extend@example.com", "pw")
        handle_webhook(db, _paid_event(uid), sig_header=None)
        first = db.execute("SELECT pro_until FROM users WHERE id = ?", (uid,)).fetchone()["pro_until"]
        handle_webhook(db, _paid_event(uid), sig_header=None)
        second = db.execute("SELECT pro_until FROM users WHERE id = ?", (uid,)).fetchone()["pro_until"]
        # paying again before expiry pushes the window further out (stacks, not resets)
        assert datetime.fromisoformat(second) > datetime.fromisoformat(first)


class TestEffectivePlanExpiry:
    def test_expired_pro_is_effectively_free(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        assert effective_plan({"plan": "pro", "pro_until": past}) == "free"

    def test_future_pro_is_pro(self):
        future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        assert effective_plan({"plan": "pro", "pro_until": future}) == "pro"

    def test_pro_with_no_until_is_free(self):
        assert effective_plan({"plan": "pro", "pro_until": None}) == "free"

    def test_free_is_free(self):
        assert effective_plan({"plan": "free", "pro_until": None}) == "free"


class TestWebhookEdgeCases:
    def test_ignored_event(self, db):
        assert handle_webhook(db, _paid_event(None, "x").replace(b"payment_link.paid", b"payment.failed"), sig_header=None)["handled"] == "ignored"

    def test_missing_user_id_does_not_crash(self, db):
        assert handle_webhook(db, _paid_event(None), sig_header=None)["status"] == "ok"

    def test_malformed_json_raises(self, db):
        with pytest.raises(ValueError):
            handle_webhook(db, b"not json {", sig_header=None)
