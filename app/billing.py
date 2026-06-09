"""Razorpay billing: one-time Payment Link = 1 month of Pro.

Razorpay's Subscriptions API is gated behind account activation, but one-time
Payments / Payment Links work immediately. So Pro is sold as a ₹750 one-time payment
that grants 30 days of Pro (extended if you pay again before it lapses). Access expires
via the users.pro_until timestamp (see quota.effective_plan).

  - create_checkout_session: create a Payment Link (notes.user_id) -> hosted short_url.
  - handle_webhook: verify X-Razorpay-Signature HMAC, then on payment_link.paid grant
    30 days of Pro to the user named in notes.user_id.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import razorpay

from .config import settings

PRO_DAYS = 30
PRICE_PAISE = 75000  # ₹750.00

_PAID_EVENTS = {"payment_link.paid"}


def _client() -> razorpay.Client:
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


def create_checkout_session(db: sqlite3.Connection, user: dict) -> str:
    """Create a Razorpay Payment Link for 1 month of Pro; return its hosted URL.

    Raises RuntimeError if Razorpay is not configured.
    """
    if not settings.razorpay_enabled:
        raise RuntimeError("Razorpay not configured")

    client = _client()
    link = client.payment_link.create(
        {
            "amount": PRICE_PAISE,
            "currency": "INR",
            "description": "ogforge Pro — 1 month (5000 images, no watermark, custom colors)",
            "notes": {"user_id": str(user["id"])},
            "callback_url": f"{settings.base_url}/billing/success",
            "callback_method": "get",
            "reminder_enable": False,
        }
    )
    return link["short_url"]


def _grant_pro(db: sqlite3.Connection, user_id: int, days: int = PRO_DAYS) -> None:
    """Set the user to Pro until now+days, extending an existing unexpired window."""
    now = datetime.now(timezone.utc)
    base = now
    row = db.execute("SELECT pro_until FROM users WHERE id = ?", (user_id,)).fetchone()
    if row and row["pro_until"]:
        try:
            current = datetime.fromisoformat(row["pro_until"])
            if current > now:
                base = current
        except ValueError:
            pass
    until = (base + timedelta(days=days)).isoformat()
    db.execute("UPDATE users SET plan = 'pro', pro_until = ? WHERE id = ?", (until, user_id))
    db.commit()


def handle_webhook(db: sqlite3.Connection, payload: bytes, sig_header: str | None) -> dict:
    """Verify and process a Razorpay webhook.

    Returns {"status": "ok", "handled": <event or "ignored">}.
    Raises ValueError on bad signature / malformed payload.
    """
    # A configured webhook secret ALWAYS requires a valid signature (production); the
    # unsigned path is only for local dev where no secret is set.
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

    if event_type in _PAID_EVENTS:
        entity = (
            event.get("payload", {}).get("payment_link", {}).get("entity", {})
            if isinstance(event.get("payload"), dict)
            else {}
        )
        user_id = (entity.get("notes") or {}).get("user_id")
        if user_id:
            _grant_pro(db, int(user_id))
        return {"status": "ok", "handled": event_type}

    return {"status": "ok", "handled": "ignored"}
