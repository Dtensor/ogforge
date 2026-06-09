"""Razorpay billing integration: subscription checkout + webhook handling.

Flow (mirrors the old Stripe one, India-native):
  - create_checkout_session: create a Razorpay Subscription against RAZORPAY_PLAN_ID,
    tagging it with notes.user_id, and return its hosted `short_url` for redirect.
  - handle_webhook: verify the X-Razorpay-Signature HMAC, then on subscription
    activation/charge flip the user to 'pro', on cancellation/halt flip back to 'free'.
    The user is resolved from the subscription's notes.user_id (no schema change needed).
"""
from __future__ import annotations

import json
import sqlite3

import razorpay

from .config import settings

# Events that mean "subscription is paying" -> Pro, and "subscription ended" -> Free.
_ACTIVATE_EVENTS = {
    "subscription.activated",
    "subscription.charged",
    "subscription.authenticated",
    "subscription.resumed",
}
_DEACTIVATE_EVENTS = {
    "subscription.cancelled",
    "subscription.completed",
    "subscription.halted",
    "subscription.expired",
}


def _client() -> razorpay.Client:
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


def create_checkout_session(db: sqlite3.Connection, user: dict) -> str:
    """Create a Razorpay subscription and return its hosted checkout URL (short_url).

    Raises RuntimeError if Razorpay is not configured.
    """
    if not settings.razorpay_enabled:
        raise RuntimeError("Razorpay not configured")

    client = _client()
    sub = client.subscription.create(
        {
            "plan_id": settings.razorpay_plan_id,
            "total_count": 120,  # up to 120 monthly cycles (~10y); user can cancel anytime
            "customer_notify": 1,
            "notes": {"user_id": str(user["id"])},
        }
    )
    return sub["short_url"]


def _set_plan(db: sqlite3.Connection, user_id: int, plan: str) -> None:
    db.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))
    db.commit()


def handle_webhook(db: sqlite3.Connection, payload: bytes, sig_header: str | None) -> dict:
    """Verify and process a Razorpay webhook.

    Returns {"status": "ok", "handled": <event or "ignored">}.
    Raises ValueError on bad signature / malformed payload.
    """
    # Verify signature when a secret is configured (production). The unsigned path is
    # only for local dev where no secret is set — a configured secret ALWAYS requires a
    # valid signature, so a forged POST can't grant a free upgrade.
    if settings.razorpay_webhook_secret:
        if not sig_header:
            raise ValueError("Missing X-Razorpay-Signature header")
        try:
            body = payload.decode("utf-8") if isinstance(payload, bytes) else payload
            _client().utility.verify_webhook_signature(
                body, sig_header, settings.razorpay_webhook_secret
            )
        except Exception as e:  # SignatureVerificationError, etc.
            raise ValueError(f"Invalid webhook signature: {e}")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON payload: {e}")
    if not isinstance(event, dict):
        raise ValueError("Webhook payload must be a JSON object")

    event_type = event.get("event", "unknown")
    entity = (
        event.get("payload", {}).get("subscription", {}).get("entity", {})
        if isinstance(event.get("payload"), dict)
        else {}
    )
    notes = entity.get("notes") or {}
    user_id = notes.get("user_id")

    if event_type in _ACTIVATE_EVENTS:
        if user_id:
            _set_plan(db, int(user_id), "pro")
        return {"status": "ok", "handled": event_type}

    if event_type in _DEACTIVATE_EVENTS:
        if user_id:
            _set_plan(db, int(user_id), "free")
        return {"status": "ok", "handled": event_type}

    return {"status": "ok", "handled": "ignored"}
