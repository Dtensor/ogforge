"""Integration tests for API routes: signup, login, OG generation, usage, quota enforcement."""

from app.auth import active_api_key
from app.quota import PLANS


class TestAuthFlow:
    """Signup and login flow tests."""

    def test_signup_creates_user_and_key(self, client):
        """POST /signup creates user and returns dashboard."""
        response = client.post(
            "/signup",
            data={
                "email": "newuser@example.com",
                "password": "password123",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "newuser@example.com" in response.text or "dashboard" in response.text.lower()

    def test_signup_duplicate_email_error(self, client):
        """POST /signup with duplicate email shows error."""
        client.post(
            "/signup",
            data={
                "email": "dup@example.com",
                "password": "pass1",
            },
        )
        response = client.post(
            "/signup",
            data={
                "email": "dup@example.com",
                "password": "pass2",
            },
        )
        assert response.status_code == 200
        assert "error" in response.text.lower() or "exists" in response.text.lower()

    def test_login_success(self, client):
        """POST /login with valid credentials redirects to dashboard."""
        client.post(
            "/signup",
            data={
                "email": "login@example.com",
                "password": "correctpass",
            },
        )
        response = client.post(
            "/login",
            data={
                "email": "login@example.com",
                "password": "correctpass",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "login@example.com" in response.text or "dashboard" in response.text.lower()

    def test_login_wrong_password(self, client):
        """POST /login with wrong password shows error."""
        client.post(
            "/signup",
            data={
                "email": "wrongpass@example.com",
                "password": "correct",
            },
        )
        response = client.post(
            "/login",
            data={
                "email": "wrongpass@example.com",
                "password": "wrong",
            },
        )
        assert response.status_code == 200
        assert "error" in response.text.lower() or "invalid" in response.text.lower()


class TestAPIKeyRetrieval:
    """Retrieve API key from dashboard/database."""

    def test_get_api_key_from_dashboard(self, client, db):
        """Signup, then extract API key from dashboard HTML."""
        client.post(
            "/signup",
            data={
                "email": "keytest@example.com",
                "password": "pass123",
            },
            follow_redirects=True,
        )

        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "og_live_" in response.text  # API key displayed


class TestOGImageEndpoint:
    """GET /v1/og tests."""

    def test_og_endpoint_requires_auth(self, client):
        """GET /v1/og without key returns 401."""
        response = client.get("/v1/og?title=Test")
        assert response.status_code == 401

    def test_og_endpoint_with_valid_key(self, client, db):
        """GET /v1/og with valid key returns PNG."""
        # Signup
        client.post(
            "/signup",
            data={
                "email": "ogtest@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        # Get the user and key from DB
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("ogtest@example.com",)
        ).fetchone()
        user_id = user["id"]
        key = active_api_key(db, user_id)

        # Request OG image
        response = client.get(f"/v1/og?title=Test&key={key}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")

    def test_og_endpoint_with_bearer_token(self, client, db):
        """GET /v1/og with Authorization: Bearer header works."""
        client.post(
            "/signup",
            data={
                "email": "bearer@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("bearer@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        response = client.get(
            "/v1/og?title=Hello",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    def test_og_endpoint_invalid_key(self, client):
        """GET /v1/og with invalid key returns 401."""
        response = client.get("/v1/og?title=Test&key=og_live_invalid")
        assert response.status_code == 401

    def test_og_endpoint_required_title(self, client, db):
        """GET /v1/og without title parameter returns error."""
        client.post(
            "/signup",
            data={
                "email": "notitle@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("notitle@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        # Missing title should cause an error (422 or 400)
        response = client.get(f"/v1/og?key={key}")
        assert response.status_code in [400, 422]

    def test_og_endpoint_with_subtitle(self, client, db):
        """GET /v1/og with subtitle parameter."""
        client.post(
            "/signup",
            data={
                "email": "subtitle@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("subtitle@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        response = client.get(
            f"/v1/og?title=Main&subtitle=Sub&key={key}"
        )
        assert response.status_code == 200
        assert response.content.startswith(b"\x89PNG")

    def test_og_endpoint_plan_header(self, client, db):
        """GET /v1/og response includes X-OGForge-Plan header."""
        client.post(
            "/signup",
            data={
                "email": "planheader@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("planheader@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        response = client.get(f"/v1/og?title=Test&key={key}")
        assert "X-OGForge-Plan" in response.headers
        assert response.headers["X-OGForge-Plan"] == "free"

    def test_og_endpoint_custom_colors_disallowed_free(self, client, db):
        """GET /v1/og with custom colors on free plan ignores them."""
        client.post(
            "/signup",
            data={
                "email": "freecolor@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("freecolor@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        # Free plan should ignore custom colors
        response = client.get(
            f"/v1/og?title=Test&bg=%23ff0000&fg=%23ffffff&key={key}"
        )
        assert response.status_code == 200


class TestUsageEndpoint:
    """GET /v1/usage tests."""

    def test_usage_endpoint_requires_auth(self, client):
        """GET /v1/usage without key returns 401."""
        response = client.get("/v1/usage")
        assert response.status_code == 401

    def test_usage_endpoint_with_valid_key(self, client, db):
        """GET /v1/usage with valid key returns JSON."""
        client.post(
            "/signup",
            data={
                "email": "usage@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("usage@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        response = client.get(f"/v1/usage?key={key}")
        assert response.status_code == 200
        data = response.json()
        assert "plan" in data
        assert "used" in data
        assert "limit" in data
        assert data["plan"] == "free"
        assert data["used"] == 0
        assert data["limit"] == 50

    def test_usage_increments_after_image_request(self, client, db):
        """GET /v1/og increments usage counter."""
        client.post(
            "/signup",
            data={
                "email": "usageinc@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("usageinc@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        # Generate an image
        client.get(f"/v1/og?title=First&key={key}")

        # Check usage
        response = client.get(f"/v1/usage?key={key}")
        data = response.json()
        assert data["used"] == 1

    def test_usage_bearer_token(self, client, db):
        """GET /v1/usage with Authorization: Bearer header."""
        client.post(
            "/signup",
            data={
                "email": "usagebearer@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("usagebearer@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        response = client.get(
            "/v1/usage",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["plan"] == "free"


class TestQuotaEnforcement:
    """Quota limit enforcement tests."""

    def test_quota_exceeded_returns_429(self, client, db, monkeypatch):
        """GET /v1/og returns 429 when monthly quota exceeded."""
        # Monkeypatch free plan limit to 1 for testing
        monkeypatch.setitem(PLANS["free"], "monthly_limit", 1)

        client.post(
            "/signup",
            data={
                "email": "quota@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("quota@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        # First request should succeed
        response1 = client.get(f"/v1/og?title=First&key={key}")
        assert response1.status_code == 200

        # Second request should hit quota
        response2 = client.get(f"/v1/og?title=Second&key={key}")
        assert response2.status_code == 429
        data = response2.json()
        assert "error" in data
        assert "quota" in data["error"].lower()
        assert data["used"] == 1
        assert data["limit"] == 1

    def test_quota_error_includes_details(self, client, db, monkeypatch):
        """GET /v1/og 429 response includes used/limit/plan."""
        monkeypatch.setitem(PLANS["free"], "monthly_limit", 1)

        client.post(
            "/signup",
            data={
                "email": "quotadetail@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("quotadetail@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        client.get(f"/v1/og?title=First&key={key}")
        response = client.get(f"/v1/og?title=Second&key={key}")

        data = response.json()
        assert data["used"] == 1
        assert data["limit"] == 1
        assert "plan" in data


class TestFullFlowIntegration:
    """End-to-end workflow tests."""

    def test_signup_get_key_generate_image_check_usage(self, client, db):
        """Full flow: signup -> extract key -> generate image -> check usage."""
        # Signup
        client.post(
            "/signup",
            data={
                "email": "fullflow@example.com",
                "password": "testpass",
            },
            follow_redirects=True,
        )

        # Get key
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("fullflow@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])
        assert key is not None
        assert key.startswith("og_live_")

        # Generate image
        response = client.get(f"/v1/og?title=MyImage&key={key}")
        assert response.status_code == 200
        assert response.content.startswith(b"\x89PNG")

        # Check usage
        usage = client.get(f"/v1/usage?key={key}")
        data = usage.json()
        assert data["used"] == 1
        assert data["limit"] == 50
        assert data["plan"] == "free"
        assert data["watermark"] is True  # free plan has watermark

    def test_regenerate_api_key_invalidates_old(self, client, db):
        """POST /dashboard/regenerate-key invalidates old key."""
        # Signup
        client.post(
            "/signup",
            data={
                "email": "regenkey@example.com",
                "password": "pass",
            },
            follow_redirects=True,
        )

        # Get first key
        user1 = db.execute(
            "SELECT id FROM users WHERE email = ?", ("regenkey@example.com",)
        ).fetchone()
        key1 = active_api_key(db, user1["id"])

        # Regenerate via POST
        client.post(
            "/dashboard/regenerate-key",
            follow_redirects=True,
        )

        # Get second key
        user2 = db.execute(
            "SELECT id FROM users WHERE email = ?", ("regenkey@example.com",)
        ).fetchone()
        key2 = active_api_key(db, user2["id"])

        # old key should not work
        response1 = client.get(f"/v1/og?title=Test&key={key1}")
        assert response1.status_code == 401

        # new key should work
        response2 = client.get(f"/v1/og?title=Test&key={key2}")
        assert response2.status_code == 200


class TestWebhookHTTP:
    """Exercise the POST /billing/webhook HTTP route end-to-end (not just handle_webhook).

    Regression guard: an earlier Body(bytes) signature returned 422 on real Stripe POSTs.
    """

    def test_webhook_http_flips_user_to_pro(self, client, db):
        client.post(
            "/signup",
            data={"email": "hook@example.com", "password": "pw"},
            follow_redirects=False,
        )
        row = db.execute("SELECT id FROM users WHERE email = ?", ("hook@example.com",)).fetchone()
        uid = row["id"]
        payload = {
            "event": "subscription.activated",
            "payload": {"subscription": {"entity": {"id": "sub_http", "notes": {"user_id": str(uid)}}}},
        }
        # No RAZORPAY_WEBHOOK_SECRET in tests -> dev unsigned path. Must be 200, not 422.
        resp = client.post("/billing/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["handled"] == "subscription.activated"
        plan = db.execute("SELECT plan FROM users WHERE id = ?", (uid,)).fetchone()["plan"]
        assert plan == "pro"
