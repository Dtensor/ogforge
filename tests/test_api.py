"""Integration tests for API routes: signup, login, OG generation, usage, quota enforcement."""

from datetime import datetime, timedelta, timezone

from app.auth import active_api_key
from app.quota import PLANS


def _set_user_pro(db, user_id):
    """Helper: set a user to pro plan with 30-day future expiry."""
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    db.execute(
        "UPDATE users SET plan = ?, pro_until = ? WHERE id = ?",
        ("pro", future, user_id),
    )
    db.commit()


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
            "event": "payment_link.paid",
            "payload": {"payment_link": {"entity": {"id": "plink_http", "notes": {"user_id": str(uid)}}}},
        }
        # No RAZORPAY_WEBHOOK_SECRET in tests -> dev unsigned path. Must be 200, not 422.
        resp = client.post("/billing/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["handled"] == "payment_link.paid"
        plan = db.execute("SELECT plan FROM users WHERE id = ?", (uid,)).fetchone()["plan"]
        assert plan == "pro"


class TestMultiFormatSupport:
    """Tests for multi-format card generation (og, story, square)."""

    def test_sample_endpoint_format_og(self, client):
        """GET /v1/sample with format=og returns 1200x630 PNG."""
        response = client.get("/v1/sample?title=Test&format=og")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")

    def test_sample_endpoint_format_story(self, client):
        """GET /v1/sample with format=story returns 1080x1920 PNG."""
        response = client.get("/v1/sample?title=Test&format=story")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")

    def test_sample_endpoint_format_square(self, client):
        """GET /v1/sample with format=square returns 1080x1080 PNG."""
        response = client.get("/v1/sample?title=Test&format=square")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")

    def test_og_endpoint_format_og(self, client, db):
        """GET /v1/og with format=og (free user) returns PNG."""
        client.post(
            "/signup",
            data={"email": "format_og@example.com", "password": "pass"},
            follow_redirects=True,
        )
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("format_og@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        response = client.get(f"/v1/og?title=Test&format=og&key={key}")
        assert response.status_code == 200
        assert response.content.startswith(b"\x89PNG")
        assert response.headers.get("X-OGForge-Plan") == "free"

    def test_og_endpoint_format_story_free_fallback(self, client, db):
        """GET /v1/og with format=story (free user) falls back to og."""
        client.post(
            "/signup",
            data={"email": "format_story_free@example.com", "password": "pass"},
            follow_redirects=True,
        )
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("format_story_free@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        response = client.get(f"/v1/og?title=Test&format=story&key={key}")
        assert response.status_code == 200
        assert response.content.startswith(b"\x89PNG")
        # Should include fallback note header
        assert "fallback" in response.headers.get("X-OGForge-Note", "").lower()

    def test_og_endpoint_format_story_pro(self, client, db):
        """GET /v1/og with format=story (pro user) returns story format."""
        client.post(
            "/signup",
            data={"email": "format_story_pro@example.com", "password": "pass"},
            follow_redirects=True,
        )
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("format_story_pro@example.com",)
        ).fetchone()

        # Manually set to pro
        _set_user_pro(db, user["id"])

        key = active_api_key(db, user["id"])

        response = client.get(f"/v1/og?title=Test&format=story&key={key}")
        assert response.status_code == 200
        assert response.content.startswith(b"\x89PNG")
        assert response.headers.get("X-OGForge-Plan") == "pro"
        # Should NOT have fallback note
        assert response.headers.get("X-OGForge-Note") is None

    def test_og_endpoint_format_square_free_fallback(self, client, db):
        """GET /v1/og with format=square (free user) falls back to og."""
        client.post(
            "/signup",
            data={"email": "format_square_free@example.com", "password": "pass"},
            follow_redirects=True,
        )
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("format_square_free@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        response = client.get(f"/v1/og?title=Test&format=square&key={key}")
        assert response.status_code == 200
        assert response.content.startswith(b"\x89PNG")
        assert "fallback" in response.headers.get("X-OGForge-Note", "").lower()


class TestBatchGeneration:
    """Tests for POST /v1/batch (Pro-only batch image generation)."""

    def test_batch_free_user_403(self, client, db):
        """POST /v1/batch free user returns 403."""
        client.post(
            "/signup",
            data={"email": "batch_free@example.com", "password": "pass"},
            follow_redirects=True,
        )
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("batch_free@example.com",)
        ).fetchone()
        key = active_api_key(db, user["id"])

        response = client.post(
            "/v1/batch",
            json={"items": [{"title": "Test"}]},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 403
        data = response.json()
        assert "requires Pro" in data["error"]

    def test_batch_pro_user_single_item(self, client, db):
        """POST /v1/batch pro user with 1 item returns 1 base64 PNG."""
        client.post(
            "/signup",
            data={"email": "batch_pro@example.com", "password": "pass"},
            follow_redirects=True,
        )
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("batch_pro@example.com",)
        ).fetchone()
        _set_user_pro(db, user["id"])
        key = active_api_key(db, user["id"])

        response = client.post(
            "/v1/batch",
            json={"items": [{"title": "Card 1"}]},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Card 1"
        assert data["results"][0]["png_base64"] is not None
        # Verify it's valid base64 PNG
        import base64
        png_bytes = base64.b64decode(data["results"][0]["png_base64"])
        assert png_bytes.startswith(b"\x89PNG")

    def test_batch_pro_user_multiple_items(self, client, db):
        """POST /v1/batch pro user with 3 items returns 3 base64 PNGs."""
        client.post(
            "/signup",
            data={"email": "batch_multi@example.com", "password": "pass"},
            follow_redirects=True,
        )
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("batch_multi@example.com",)
        ).fetchone()
        _set_user_pro(db, user["id"])
        key = active_api_key(db, user["id"])

        response = client.post(
            "/v1/batch",
            json={
                "items": [
                    {"title": "Card 1"},
                    {"title": "Card 2", "template": "dark"},
                    {"title": "Card 3", "subtitle": "Subtitle"},
                ]
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert len(data["results"]) == 3

    def test_batch_quota_enforcement(self, client, db, monkeypatch):
        """POST /v1/batch rejects if batch would exceed quota."""
        monkeypatch.setitem(PLANS["pro"], "monthly_limit", 2)

        client.post(
            "/signup",
            data={"email": "batch_quota@example.com", "password": "pass"},
            follow_redirects=True,
        )
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("batch_quota@example.com",)
        ).fetchone()
        _set_user_pro(db, user["id"])
        key = active_api_key(db, user["id"])

        # First, use 1 quota
        client.get(f"/v1/og?title=First&key={key}")

        # Now try batch of 2 (would exceed 2-item limit)
        response = client.post(
            "/v1/batch",
            json={"items": [{"title": "B1"}, {"title": "B2"}]},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 429
        data = response.json()
        assert "exceed" in data["error"].lower()

    def test_batch_max_25_items(self, client, db):
        """POST /v1/batch with >25 items returns 400."""
        client.post(
            "/signup",
            data={"email": "batch_max@example.com", "password": "pass"},
            follow_redirects=True,
        )
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("batch_max@example.com",)
        ).fetchone()
        _set_user_pro(db, user["id"])
        key = active_api_key(db, user["id"])

        items = [{"title": f"Card {i}"} for i in range(26)]
        response = client.post(
            "/v1/batch",
            json={"items": items},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 400
        data = response.json()
        assert "25" in data["error"]

    def test_batch_empty_items_400(self, client, db):
        """POST /v1/batch with empty items list returns 400."""
        client.post(
            "/signup",
            data={"email": "batch_empty@example.com", "password": "pass"},
            follow_redirects=True,
        )
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("batch_empty@example.com",)
        ).fetchone()
        _set_user_pro(db, user["id"])
        key = active_api_key(db, user["id"])

        response = client.post(
            "/v1/batch",
            json={"items": []},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 400
        assert "empty" in response.json()["error"].lower()

    def test_batch_no_auth_401(self, client):
        """POST /v1/batch without auth returns 401."""
        response = client.post(
            "/v1/batch",
            json={"items": [{"title": "Test"}]},
        )
        assert response.status_code == 401

    def test_batch_with_formats(self, client, db):
        """POST /v1/batch items can specify different formats."""
        client.post(
            "/signup",
            data={"email": "batch_formats@example.com", "password": "pass"},
            follow_redirects=True,
        )
        user = db.execute(
            "SELECT id FROM users WHERE email = ?", ("batch_formats@example.com",)
        ).fetchone()
        _set_user_pro(db, user["id"])
        key = active_api_key(db, user["id"])

        response = client.post(
            "/v1/batch",
            json={
                "items": [
                    {"title": "OG", "format": "og"},
                    {"title": "Story", "format": "story"},
                    {"title": "Square", "format": "square"},
                ]
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        for result in data["results"]:
            assert result["png_base64"] is not None


class TestGalleryPage:
    """Tests for GET /gallery template page."""

    def test_gallery_page_loads(self, client):
        """GET /gallery returns 200 with HTML."""
        response = client.get("/gallery")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_gallery_page_contains_templates(self, client):
        """GET /gallery HTML includes all 4 templates."""
        response = client.get("/gallery")
        assert response.status_code == 200
        # Check for template names in the page
        text = response.text
        assert "gradient" in text.lower()
        assert "default" in text.lower()
        assert "dark" in text.lower()
        assert "minimal" in text.lower()

    def test_gallery_page_contains_formats(self, client):
        """GET /gallery HTML includes all 3 formats."""
        response = client.get("/gallery")
        text = response.text
        assert "1200" in text  # og dimensions
        assert "1920" in text  # story height
        assert "1080" in text  # story/square width

    def test_gallery_page_sample_images(self, client):
        """GET /gallery includes sample image URLs with /v1/sample."""
        response = client.get("/gallery")
        text = response.text
        assert "/v1/sample?" in text
        assert "template=" in text
