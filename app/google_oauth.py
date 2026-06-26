"""Google OAuth (OpenID Connect) sign-up / sign-in for end users.

Lets customers register/log in with Google instead of email+password. Uses httpx
(already required). Disabled gracefully when GOOGLE_CLIENT_ID/SECRET are unset.
"""
from __future__ import annotations

from urllib.parse import urlencode

import httpx

from .config import settings

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def redirect_uri() -> str:
    return settings.base_url + "/auth/google/callback"


def authorize_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def fetch_email(code: str) -> str | None:
    with httpx.Client(timeout=15) as client:
        tok = client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        tok.raise_for_status()
        access = tok.json().get("access_token")
        if not access:
            return None
        info = client.get(USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access}"})
        info.raise_for_status()
        data = info.json()
        if str(data.get("email_verified", "true")).lower() == "false":
            return None
        return data.get("email")
