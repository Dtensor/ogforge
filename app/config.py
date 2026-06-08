"""Central configuration, read from environment (.env loaded by main at startup)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _load_dotenv() -> None:
    """Tiny .env loader (no python-dotenv dependency). Idempotent; never overrides existing env."""
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
    stripe_secret_key: str
    stripe_publishable_key: str
    stripe_price_id: str
    stripe_webhook_secret: str

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_price_id)


def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        db_path=os.environ.get("DB_PATH", "ogforge.db"),
        secret_key=os.environ.get("SESSION_SECRET", "dev-secret-change-me"),
        base_url=os.environ.get("BASE_URL", "http://localhost:8810").rstrip("/"),
        stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY", ""),
        stripe_publishable_key=os.environ.get("STRIPE_PUBLISHABLE_KEY", ""),
        stripe_price_id=os.environ.get("STRIPE_PRICE_ID", ""),
        stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
    )


settings = get_settings()
