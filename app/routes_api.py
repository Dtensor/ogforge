"""API routes: /v1/og (dynamic image generation) and /v1/usage (quota info)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from . import auth, imaging, quota
from .db import get_db

router = APIRouter(prefix="/v1", tags=["api"])


def _get_api_key(
    authorization: str | None = None,
    key: str | None = Query(None),
) -> str:
    """Resolve API key from Authorization Bearer header or ?key= query parameter.

    Raises HTTPException(401) if neither is provided.
    """
    # Try Authorization header first
    if authorization:
        if authorization.startswith("Bearer "):
            return authorization[7:]
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    # Fall back to ?key= query parameter
    if key:
        return key

    raise HTTPException(status_code=401, detail="Missing API key")


@router.get("/og")
def get_og_image(
    title: str,
    subtitle: str = "",
    template: str = "default",
    bg: str | None = None,
    fg: str | None = None,
    authorization: str | None = Header(None),
    key: str | None = Query(None),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    """Generate a dynamic Open-Graph image.

    Auth: Bearer token in Authorization header or ?key= query parameter.
    Returns: PNG image with X-OGForge-Plan header.
    On quota exceeded: 429 JSON response.
    """
    # Resolve and validate API key
    api_key = _get_api_key(authorization, key)
    user = auth.user_by_api_key(db, api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check quota (effective_plan honors the one-time Pro expiry)
    plan = quota.effective_plan(user)
    allowed, used, limit = quota.check_quota(db, user["id"], plan)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={
                "error": "monthly quota exceeded",
                "used": used,
                "limit": limit,
                "plan": plan,
            },
        )

    # Determine rendering options based on plan
    plan_config = quota.plan_of(plan)
    watermark = plan_config["watermark"]
    allow_custom_colors = plan_config["custom_colors"]

    # Pass custom colors only if allowed by plan
    render_bg = bg if allow_custom_colors else None
    render_fg = fg if allow_custom_colors else None

    # Render the image
    png_bytes = imaging.render_og_image(
        title=title,
        subtitle=subtitle,
        template=template,
        bg=render_bg,
        fg=render_fg,
        watermark=watermark,
    )

    # Record usage after successful render
    quota.record_usage(db, user["id"], "/v1/og")

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"X-OGForge-Plan": plan},
    )


@router.get("/usage")
def get_usage(
    authorization: str | None = Header(None),
    key: str | None = Query(None),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Return current quota usage and plan details.

    Auth: Same as /v1/og (Bearer or ?key=).
    Returns: JSON with plan, used, limit, watermark.
    """
    # Resolve and validate API key
    api_key = _get_api_key(authorization, key)
    user = auth.user_by_api_key(db, api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Get plan and usage (effective_plan honors the one-time Pro expiry)
    plan = quota.effective_plan(user)
    plan_config = quota.plan_of(plan)
    used = quota.usage_this_month(db, user["id"])
    limit = plan_config["monthly_limit"]
    watermark = plan_config["watermark"]

    return {
        "plan": plan,
        "used": used,
        "limit": limit,
        "watermark": watermark,
    }
