"""Stripe billing integration: checkout sessions and webhook handling."""
from __future__ import annotations

import json
import sqlite3

import stripe

from .config import settings

stripe.api_key = settings.stripe_secret_key


def create_checkout_session(db: sqlite3.Connection, user: dict) -> str:
    """Create a Stripe Checkout Session for the user's subscription.

    Args:
        db: SQLite connection.
        user: User dict from DB (must have 'id' and 'stripe_customer_id' fields).

    Returns:
        Session URL for redirect.

    Raises:
        RuntimeError: If Stripe is not configured (stripe_enabled=False).
    """
    if not settings.stripe_enabled:
        raise RuntimeError("Stripe not configured")

    user_id = user["id"]

    # Get or create Stripe customer
    stripe_customer_id = user.get("stripe_customer_id")
    if not stripe_customer_id:
        customer = stripe.Customer.create(description=f"ogforge user {user_id}")
        stripe_customer_id = customer.id
        db.execute(
            "UPDATE users SET stripe_customer_id = ? WHERE id = ?",
            (stripe_customer_id, user_id),
        )
        db.commit()

    # Create Checkout Session
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=stripe_customer_id,
        client_reference_id=str(user_id),
        line_items=[
            {
                "price": settings.stripe_price_id,
                "quantity": 1,
            }
        ],
        success_url=f"{settings.base_url}/billing/success",
        cancel_url=f"{settings.base_url}/billing/cancel",
    )

    return session.url


def set_plan_by_customer(
    db: sqlite3.Connection, stripe_customer_id: str, plan: str
) -> None:
    """Set the plan for a user identified by stripe_customer_id.

    Args:
        db: SQLite connection.
        stripe_customer_id: Stripe customer ID.
        plan: Plan name ('free' or 'pro').
    """
    db.execute(
        "UPDATE users SET plan = ? WHERE stripe_customer_id = ?",
        (plan, stripe_customer_id),
    )
    db.commit()


def handle_webhook(
    db: sqlite3.Connection, payload: bytes, sig_header: str | None
) -> dict:
    """Handle Stripe webhook events.

    Args:
        db: SQLite connection.
        payload: Raw webhook body (bytes).
        sig_header: Stripe-Signature header value.

    Returns:
        {"status": "ok", "handled": <event_type or "ignored">}

    Raises:
        ValueError: On bad signature or malformed payload.
    """
    # Parse and verify event.
    # SECURITY: if a webhook secret is configured (i.e. production), a valid signature
    # is ALWAYS required. A missing/invalid signature must NOT fall through to unsigned
    # JSON — otherwise anyone could POST a forged "checkout.session.completed" and get a
    # free Pro upgrade. The unsigned path exists only for local dev where no secret is set.
    if settings.stripe_webhook_secret:
        if not sig_header:
            raise ValueError("Missing Stripe-Signature header")
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.stripe_webhook_secret
            )
        except Exception as e:  # SignatureVerificationError, ValueError, etc.
            raise ValueError(f"Invalid webhook signature: {e}")
    else:
        # Dev/test fallback: no secret configured -> accept unsigned JSON.
        try:
            event = json.loads(payload)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON payload: {e}")
        if not isinstance(event, dict):
            raise ValueError("Webhook payload must be a JSON object")

    event_type = event.get("type", "unknown")

    if event_type == "checkout.session.completed":
        data = event.get("data", {}).get("object", {})
        client_reference_id = data.get("client_reference_id")
        customer_id = data.get("customer")

        if client_reference_id:
            # Upgrade user to pro
            db.execute(
                "UPDATE users SET plan = ?, stripe_customer_id = ? WHERE id = ?",
                ("pro", customer_id, int(client_reference_id)),
            )
            db.commit()

        return {"status": "ok", "handled": "checkout.session.completed"}

    elif event_type == "customer.subscription.deleted":
        data = event.get("data", {}).get("object", {})
        customer_id = data.get("customer")

        if customer_id:
            set_plan_by_customer(db, customer_id, "free")

        return {"status": "ok", "handled": "customer.subscription.deleted"}

    else:
        return {"status": "ok", "handled": "ignored"}
