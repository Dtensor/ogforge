"""Tests for auth module: password hashing, user creation, API key management."""
import pytest

from app.auth import (
    hash_password,
    verify_password,
    create_user,
    authenticate,
    get_user,
    generate_api_key,
    create_api_key,
    user_by_api_key,
    active_api_key,
)
from app.db import connect, init_db


@pytest.fixture
def db():
    """Fresh DB connection for each test."""
    init_db()
    conn = connect()
    yield conn
    conn.close()


class TestPasswordHashing:
    """hash_password and verify_password roundtrip tests."""

    def test_hash_password_returns_string(self):
        """hash_password returns a string with salt$hash format."""
        hashed = hash_password("testpass123")
        assert isinstance(hashed, str)
        assert "$" in hashed

    def test_verify_password_correct(self):
        """verify_password returns True for correct password."""
        password = "mypassword"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """verify_password returns False for incorrect password."""
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_verify_password_empty(self):
        """verify_password returns False for empty password."""
        hashed = hash_password("test")
        assert verify_password("", hashed) is False

    def test_hash_same_password_different_salts(self):
        """Hashing the same password twice produces different hashes (different salts)."""
        password = "test123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True


class TestUserCreation:
    """create_user and get_user tests."""

    def test_create_user_success(self, db):
        """create_user inserts and returns user_id."""
        user_id = create_user(db, "alice@example.com", "password123")
        assert isinstance(user_id, int)
        assert user_id > 0

    def test_create_user_duplicate_email_raises(self, db):
        """create_user raises ValueError on duplicate email."""
        create_user(db, "bob@example.com", "pass1")
        with pytest.raises(ValueError, match="email exists"):
            create_user(db, "bob@example.com", "pass2")

    def test_get_user_returns_dict(self, db):
        """get_user returns user dict with correct fields."""
        user_id = create_user(db, "charlie@example.com", "pass")
        user = get_user(db, user_id)
        assert isinstance(user, dict)
        assert user["id"] == user_id
        assert user["email"] == "charlie@example.com"
        assert user["plan"] == "free"

    def test_get_user_not_found(self, db):
        """get_user returns None for non-existent user."""
        user = get_user(db, 99999)
        assert user is None

    def test_create_user_plan_default_free(self, db):
        """create_user defaults plan to 'free'."""
        user_id = create_user(db, "dave@example.com", "pass")
        user = get_user(db, user_id)
        assert user["plan"] == "free"


class TestAuthentication:
    """authenticate tests."""

    def test_authenticate_valid_credentials(self, db):
        """authenticate returns user dict for valid email/password."""
        email = "eve@example.com"
        password = "correctpass"
        create_user(db, email, password)
        user = authenticate(db, email, password)
        assert user is not None
        assert user["email"] == email

    def test_authenticate_wrong_password(self, db):
        """authenticate returns None for wrong password."""
        create_user(db, "frank@example.com", "rightpass")
        user = authenticate(db, "frank@example.com", "wrongpass")
        assert user is None

    def test_authenticate_user_not_found(self, db):
        """authenticate returns None for non-existent email."""
        user = authenticate(db, "nonexistent@example.com", "anypass")
        assert user is None


class TestAPIKeyGeneration:
    """generate_api_key tests."""

    def test_generate_api_key_format(self):
        """generate_api_key returns a string starting with 'og_live_'."""
        key = generate_api_key()
        assert isinstance(key, str)
        assert key.startswith("og_live_")
        assert len(key) > len("og_live_")

    def test_generate_api_key_unique(self):
        """generate_api_key generates unique keys."""
        key1 = generate_api_key()
        key2 = generate_api_key()
        assert key1 != key2


class TestAPIKeyManagement:
    """create_api_key, user_by_api_key, active_api_key tests."""

    def test_create_api_key_returns_key(self, db):
        """create_api_key returns a key string."""
        user_id = create_user(db, "grace@example.com", "pass")
        key = create_api_key(db, user_id)
        assert isinstance(key, str)
        assert key.startswith("og_live_")

    def test_create_api_key_revokes_old(self, db):
        """create_api_key revokes previous keys for the same user."""
        user_id = create_user(db, "henry@example.com", "pass")
        key1 = create_api_key(db, user_id)
        key2 = create_api_key(db, user_id)
        # key1 should be revoked, key2 active
        user_from_key1 = user_by_api_key(db, key1)
        assert user_from_key1 is None
        user_from_key2 = user_by_api_key(db, key2)
        assert user_from_key2 is not None
        assert user_from_key2["id"] == user_id

    def test_user_by_api_key_valid(self, db):
        """user_by_api_key returns user dict for valid key."""
        user_id = create_user(db, "iris@example.com", "pass")
        key = create_api_key(db, user_id)
        user = user_by_api_key(db, key)
        assert user is not None
        assert user["id"] == user_id
        assert user["email"] == "iris@example.com"

    def test_user_by_api_key_invalid(self, db):
        """user_by_api_key returns None for invalid/revoked key."""
        user = user_by_api_key(db, "og_live_nonexistent")
        assert user is None

    def test_active_api_key_returns_key(self, db):
        """active_api_key returns the current non-revoked key."""
        user_id = create_user(db, "jack@example.com", "pass")
        key = create_api_key(db, user_id)
        active = active_api_key(db, user_id)
        assert active == key

    def test_active_api_key_no_key(self, db):
        """active_api_key returns None if user has no active key."""
        user_id = create_user(db, "kate@example.com", "pass")
        active = active_api_key(db, user_id)
        assert active is None

    def test_active_api_key_after_revocation(self, db):
        """active_api_key skips revoked keys and finds the current one."""
        user_id = create_user(db, "laura@example.com", "pass")
        key1 = create_api_key(db, user_id)
        key2 = create_api_key(db, user_id)  # revokes key1
        active = active_api_key(db, user_id)
        assert active == key2
        assert active != key1
