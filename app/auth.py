"""Authentication: password hashing, user creation, API key management."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3

from .db import utcnow


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-SHA256 with random salt.

    Returns string formatted as "salt$hexhash".
    """
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations=100000,
    )
    return f"{salt}${hashed.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored hash.

    stored format: "salt$hexhash"
    """
    try:
        salt, hexhash = stored.split("$")
        hashed = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            iterations=100000,
        )
        return hashed.hex() == hexhash
    except (ValueError, AttributeError):
        return False


def create_user(db: sqlite3.Connection, email: str, password: str) -> int:
    """Create a new user. Returns user_id.

    Raises ValueError if email already exists.
    """
    try:
        password_hash = hash_password(password)
        cursor = db.execute(
            "INSERT INTO users (email, password_hash, plan, created_at) VALUES (?, ?, ?, ?)",
            (email, password_hash, "free", utcnow()),
        )
        db.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("email exists")


def authenticate(db: sqlite3.Connection, email: str, password: str) -> dict | None:
    """Authenticate user. Returns user row as dict or None."""
    row = db.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    if row and verify_password(password, row["password_hash"]):
        return dict(row)
    return None


def get_user(db: sqlite3.Connection, user_id: int) -> dict | None:
    """Get user by ID. Returns user row as dict or None."""
    row = db.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def generate_api_key() -> str:
    """Generate a new API key: 'og_live_' + token_urlsafe(24)."""
    return "og_live_" + secrets.token_urlsafe(24)


def create_api_key(db: sqlite3.Connection, user_id: int) -> str:
    """Create a new API key for user, revoking prior keys. Returns key string."""
    # Revoke all existing keys for this user
    db.execute(
        "UPDATE api_keys SET revoked = 1 WHERE user_id = ?",
        (user_id,),
    )

    # Generate and insert new key
    key = generate_api_key()
    db.execute(
        "INSERT INTO api_keys (user_id, key, revoked, created_at) VALUES (?, ?, ?, ?)",
        (user_id, key, 0, utcnow()),
    )
    db.commit()
    return key


def user_by_api_key(db: sqlite3.Connection, key: str) -> dict | None:
    """Resolve user from API key (non-revoked). Returns user row as dict or None."""
    row = db.execute(
        """
        SELECT u.* FROM users u
        INNER JOIN api_keys ak ON ak.user_id = u.id
        WHERE ak.key = ? AND ak.revoked = 0
        """,
        (key,),
    ).fetchone()
    return dict(row) if row else None


def active_api_key(db: sqlite3.Connection, user_id: int) -> str | None:
    """Get current non-revoked API key for user. Returns key string or None."""
    row = db.execute(
        "SELECT key FROM api_keys WHERE user_id = ? AND revoked = 0",
        (user_id,),
    ).fetchone()
    return row["key"] if row else None
