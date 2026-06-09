"""Tests for Razorpay billing webhook handling (no live API, no network).

The dev path (no RAZORPAY_WEBHOOK_SECRET set, as in the test env) skips signature
verification, so we can feed synthetic subscription events and assert the plan flips.
Mapping webhook -> user is via the subscription's notes.user_id.
"""
import json

import pytest

from app.auth import create_user
from app.billing import handle_webhook
from app.db import connect, init_db


@pytest.fixture
def db():
    init_db()
    conn = connect()
    yield conn
    conn.close()


def _event(event_type: str, user_id, sub_id="sub_test123") -> bytes:
    payload = {
        "event": event_type,
        "payload": {
            "subscription": {
                "entity": {
                    "id": sub_id,
                    "status": "active",
                    "notes": {"user_id": str(user_id)} if user_id is not None else {},
                }
            }
        },
    }
    return json.dumps(payload).encode("utf-8")


class TestSubscriptionActivation:
    def test_activated_flips_user_to_pro(self, db):
        uid = create_user(db, "activate@example.com", "pw")
        result = handle_webhook(db, _event("subscription.activated", uid), sig_header=None)
        assert result["handled"] == "subscription.activated"
        plan = db.execute("SELECT plan FROM users WHERE id = ?", (uid,)).fetchone()["plan"]
        assert plan == "pro"

    def test_charged_flips_user_to_pro(self, db):
        uid = create_user(db, "charged@example.com", "pw")
        handle_webhook(db, _event("subscription.charged", uid), sig_header=None)
        assert db.execute("SELECT plan FROM users WHERE id = ?", (uid,)).fetchone()["plan"] == "pro"


class TestSubscriptionCancellation:
    def test_cancelled_flips_user_to_free(self, db):
        uid = create_user(db, "cancel@example.com", "pw")
        handle_webhook(db, _event("subscription.activated", uid), sig_header=None)
        assert db.execute("SELECT plan FROM users WHERE id = ?", (uid,)).fetchone()["plan"] == "pro"
        handle_webhook(db, _event("subscription.cancelled", uid), sig_header=None)
        assert db.execute("SELECT plan FROM users WHERE id = ?", (uid,)).fetchone()["plan"] == "free"


class TestWebhookEdgeCases:
    def test_ignored_event(self, db):
        result = handle_webhook(db, _event("payment.captured", None), sig_header=None)
        assert result["handled"] == "ignored"

    def test_missing_user_id_does_not_crash(self, db):
        result = handle_webhook(db, _event("subscription.activated", None), sig_header=None)
        assert result["status"] == "ok"

    def test_nonexistent_user_id_does_not_crash(self, db):
        result = handle_webhook(db, _event("subscription.activated", 99999), sig_header=None)
        assert result["status"] == "ok"

    def test_malformed_json_raises(self, db):
        with pytest.raises(ValueError):
            handle_webhook(db, b"not valid json {", sig_header=None)
