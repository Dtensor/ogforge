"""Pytest fixtures for ogforge tests. Isolate DB per test."""
import os
import tempfile
from pathlib import Path

# Module-level: runs at conftest import (BEFORE test modules import app.config),
# so the suite never picks up a real .env on disk and Stripe stays disabled.
os.environ["OGFORGE_DISABLE_DOTENV"] = "1"
for _k in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
    os.environ[_k] = ""
os.environ.setdefault("SESSION_SECRET", "test-secret-key")

import pytest  # noqa: E402  (must follow the env setup above)
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def temp_db():
    """Create a temporary DB file for each test, set env BEFORE importing app modules."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Set env vars BEFORE any app imports
    os.environ["DB_PATH"] = db_path
    os.environ.setdefault("SESSION_SECRET", "test-secret-key")
    os.environ.setdefault("BASE_URL", "http://localhost:8810")
    os.environ.setdefault("STRIPE_SECRET_KEY", "")
    os.environ.setdefault("STRIPE_PUBLISHABLE_KEY", "")
    os.environ.setdefault("STRIPE_PRICE_ID", "")
    os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "")

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def app():
    """Build and return the FastAPI app with fresh DB."""
    # Import AFTER temp_db sets env vars
    from app.db import init_db
    from app.main import create_app

    # Reload config to pick up test env vars
    import importlib
    import app.config
    importlib.reload(app.config)

    # Create and init app
    app_instance = create_app()
    init_db()

    return app_instance


@pytest.fixture
def client(app):
    """Return a TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def db():
    """Fresh DB connection bound to the per-test temp DB (set by autouse temp_db)."""
    from app.db import connect, init_db

    init_db()
    conn = connect()
    yield conn
    conn.close()
