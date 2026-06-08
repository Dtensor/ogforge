"""Tests for billing module: Stripe webhook handling without live API."""
import json
import pytest

from app.billing import handle_webhook, set_plan_by_customer
from app.db import connect, init_db
from app.auth import create_user


@pytest.fixture
def db():
    """Fresh DB connection for each test."""
    init_db()
    conn = connect()
    yield conn
    conn.close()


class TestSetPlanByCustomer:
    """set_plan_by_customer helper tests."""

    def test_set_plan_by_customer_to_pro(self, db):
        """set_plan_by_customer updates user plan to 'pro'."""
        # Create a user with a stripe_customer_id
        db.execute(
            "INSERT INTO users (email, password_hash, plan, stripe_customer_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("user@example.com", "hash", "free", "cus_test123", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()

        set_plan_by_customer(db, "cus_test123", "pro")

        # Verify the plan was updated
        row = db.execute(
            "SELECT plan FROM users WHERE stripe_customer_id = ?", ("cus_test123",)
        ).fetchone()
        assert row["plan"] == "pro"

    def test_set_plan_by_customer_to_free(self, db):
        """set_plan_by_customer updates user plan to 'free'."""
        db.execute(
            "INSERT INTO users (email, password_hash, plan, stripe_customer_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("pro@example.com", "hash", "pro", "cus_pro456", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()

        set_plan_by_customer(db, "cus_pro456", "free")

        row = db.execute(
            "SELECT plan FROM users WHERE stripe_customer_id = ?", ("cus_pro456",)
        ).fetchone()
        assert row["plan"] == "free"


class TestHandleWebhookCheckoutSessionCompleted:
    """handle_webhook tests for checkout.session.completed event."""

    def test_handle_webhook_checkout_completed_with_client_reference_id(self, db):
        """handle_webhook processes checkout.session.completed with client_reference_id."""
        # Create a user
        user_id = create_user(db, "checkout@example.com", "pass")

        # Build a synthetic webhook payload
        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test123",
                    "client_reference_id": str(user_id),
                    "customer": "cus_test123",
                }
            },
        }

        payload_bytes = json.dumps(payload).encode("utf-8")

        result = handle_webhook(db, payload_bytes, sig_header=None)

        assert result["status"] == "ok"
        assert result["handled"] == "checkout.session.completed"

        # Verify user plan was updated to pro
        user_row = db.execute("SELECT plan FROM users WHERE id = ?", (user_id,)).fetchone()
        assert user_row["plan"] == "pro"

        # Verify stripe_customer_id was set
        stripe_row = db.execute(
            "SELECT stripe_customer_id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert stripe_row["stripe_customer_id"] == "cus_test123"

    def test_handle_webhook_checkout_completed_sets_customer_id(self, db):
        """handle_webhook sets stripe_customer_id on checkout completion."""
        user_id = create_user(db, "nocustomer@example.com", "pass")

        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_new",
                    "client_reference_id": str(user_id),
                    "customer": "cus_brand_new",
                }
            },
        }

        payload_bytes = json.dumps(payload).encode("utf-8")
        handle_webhook(db, payload_bytes, sig_header=None)

        user_row = db.execute("SELECT stripe_customer_id FROM users WHERE id = ?", (user_id,)).fetchone()
        assert user_row["stripe_customer_id"] == "cus_brand_new"


class TestHandleWebhookSubscriptionDeleted:
    """handle_webhook tests for customer.subscription.deleted event."""

    def test_handle_webhook_subscription_deleted(self, db):
        """handle_webhook processes customer.subscription.deleted."""
        # Create a pro user with a stripe_customer_id
        db.execute(
            "INSERT INTO users (email, password_hash, plan, stripe_customer_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("prosub@example.com", "hash", "pro", "cus_cancel123", "2026-06-01T00:00:00+00:00"),
        )
        db.commit()

        payload = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "customer": "cus_cancel123",
                }
            },
        }

        payload_bytes = json.dumps(payload).encode("utf-8")
        result = handle_webhook(db, payload_bytes, sig_header=None)

        assert result["status"] == "ok"
        assert result["handled"] == "customer.subscription.deleted"

        # Verify user plan was reverted to free
        user_row = db.execute(
            "SELECT plan FROM users WHERE stripe_customer_id = ?", ("cus_cancel123",)
        ).fetchone()
        assert user_row["plan"] == "free"


class TestHandleWebhookIgnoredEvents:
    """handle_webhook tests for ignored/unhandled events."""

    def test_handle_webhook_ignored_event(self, db):
        """handle_webhook returns 'ignored' for unhandled event types."""
        payload = {
            "type": "charge.succeeded",
            "data": {
                "object": {
                    "id": "ch_123",
                }
            },
        }

        payload_bytes = json.dumps(payload).encode("utf-8")
        result = handle_webhook(db, payload_bytes, sig_header=None)

        assert result["status"] == "ok"
        assert result["handled"] == "ignored"


class TestHandleWebhookMalformed:
    """handle_webhook tests for error handling."""

    def test_handle_webhook_malformed_json(self, db):
        """handle_webhook raises ValueError for malformed JSON."""
        payload_bytes = b"not valid json {"

        with pytest.raises(ValueError):
            handle_webhook(db, payload_bytes, sig_header=None)

    def test_handle_webhook_missing_type(self, db):
        """handle_webhook handles payload without 'type' field gracefully."""
        payload = {
            "data": {
                "object": {
                    "id": "test",
                }
            }
        }

        payload_bytes = json.dumps(payload).encode("utf-8")

        # Should return ignored status, not crash
        result = handle_webhook(db, payload_bytes, sig_header=None)
        assert result["status"] == "ok"


class TestHandleWebhookNoWebhookSecret:
    """handle_webhook tests with no webhook secret configured (dev mode)."""

    def test_handle_webhook_no_secret_trusts_payload(self, db):
        """handle_webhook with no webhook_secret trusts the payload (dev mode).

        The test env (conftest) leaves STRIPE_WEBHOOK_SECRET empty, so the dev
        unsigned-JSON path is exercised without needing to mutate the frozen Settings.
        """
        user_id = create_user(db, "nosecret@example.com", "pass")

        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test",
                    "client_reference_id": str(user_id),
                    "customer": "cus_dev123",
                }
            },
        }

        payload_bytes = json.dumps(payload).encode("utf-8")
        result = handle_webhook(db, payload_bytes, sig_header=None)

        assert result["status"] == "ok"
        user_row = db.execute("SELECT plan FROM users WHERE id = ?", (user_id,)).fetchone()
        assert user_row["plan"] == "pro"


class TestHandleWebhookEdgeCases:
    """Edge case tests for handle_webhook."""

    def test_handle_webhook_checkout_nonexistent_user(self, db):
        """handle_webhook with nonexistent client_reference_id (user lookup fails gracefully)."""
        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_ghost",
                    "client_reference_id": "99999",
                    "customer": "cus_ghost",
                }
            },
        }

        payload_bytes = json.dumps(payload).encode("utf-8")

        # Should not crash; likely returns ok/handled but doesn't update anything
        result = handle_webhook(db, payload_bytes, sig_header=None)
        assert result["status"] == "ok"

    def test_handle_webhook_subscription_nonexistent_customer(self, db):
        """handle_webhook subscription.deleted for nonexistent customer."""
        payload = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "customer": "cus_nonexistent",
                }
            },
        }

        payload_bytes = json.dumps(payload).encode("utf-8")

        # Should not crash
        result = handle_webhook(db, payload_bytes, sig_header=None)
        assert result["status"] == "ok"
