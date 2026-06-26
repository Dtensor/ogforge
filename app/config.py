"""Central configuration, read from environment (.env loaded by main at startup)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _load_dotenv() -> None:
    """Tiny .env loader (no python-dotenv dependency). Idempotent; never overrides existing env.

    Skipped entirely when OGFORGE_DISABLE_DOTENV is set, so the test suite stays
    hermetic even when a real .env (with live keys) exists on disk.
    """
    if os.environ.get("OGFORGE_DISABLE_DOTENV"):
        return
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    db_path: str
    secret_key: str
    base_url: str
    # Razorpay (India-friendly INR). One-time Payment Link = 1 month of Pro.
    # Test keys: rzp_test_…, live: rzp_live_… (Subscriptions API is gated separately.)
    razorpay_key_id: str
    razorpay_key_secret: str
    razorpay_webhook_secret: str
    google_client_id: str
    google_client_secret: str

    @property
    def razorpay_enabled(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)


def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        db_path=os.environ.get("DB_PATH", "ogforge.db"),
        secret_key=os.environ.get("SESSION_SECRET", "dev-secret-change-me"),
        base_url=os.environ.get("BASE_URL", "http://localhost:8810").rstrip("/"),
        razorpay_key_id=os.environ.get("RAZORPAY_KEY_ID", ""),
        razorpay_key_secret=os.environ.get("RAZORPAY_KEY_SECRET", ""),
        razorpay_webhook_secret=os.environ.get("RAZORPAY_WEBHOOK_SECRET", ""),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    )


settings = get_settings()
