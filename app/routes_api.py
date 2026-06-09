"""API routes: /v1/og (dynamic image generation) and /v1/usage (quota info)."""
from __future__ import annotations

import base64
import sqlite3
from pydantic import BaseModel

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from . import auth, imaging, quota
from .db import get_db

router = APIRouter(prefix="/v1", tags=["api"])


@router.get("/sample")
def get_sample(
    title: str = "Your headline here",
    subtitle: str = "",
    template: str = "gradient",
    format: str = "og",
) -> Response:
    """Public, no-auth demo render for the landing page's live preview.

    Always watermarked, no custom colors, title/subtitle length-capped. Not metered —
    it's a marketing surface, not the product (real generation needs an API key on /v1/og).
    Supports formats: og (1200x630), story (1080x1920), square (1080x1080).
    """
    png = imaging.render_og_image(
        title=title[:70],
        subtitle=subtitle[:90],
        template=template,
        bg=None,
        fg=None,
        watermark=True,
        format=format,
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=60"},
    )



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
    format: str = "og",
    authorization: str | None = Header(None),
    key: str | None = Query(None),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    """Generate a dynamic Open-Graph image with optional format selection.

    Auth: Bearer token in Authorization header or ?key= query parameter.
    Format: og (1200x630, default), story (1080x1920, Pro only), square (1080x1080, Pro only)
    Returns: PNG image with X-OGForge-Plan and X-OGForge-Note headers.
    On quota exceeded or format denied: 429/403 JSON response.
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

    # Validate format and gate non-og formats to Pro
    if format not in ("og", "story", "square"):
        format = "og"

    if format != "og" and plan != "pro":
        # Free users: fall back to og format
        format = "og"
        note_header = "Format fallback: non-og formats require Pro"
    else:
        note_header = None

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
        format=format,
    )

    # Record usage after successful render
    quota.record_usage(db, user["id"], "/v1/og")

    headers = {"X-OGForge-Plan": plan}
    if note_header:
        headers["X-OGForge-Note"] = note_header

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers=headers,
    )


class BatchItem(BaseModel):
    """Single item in a batch request."""
    title: str
    subtitle: str = ""
    template: str = "default"
    format: str = "og"


class BatchRequest(BaseModel):
    """Batch generation request: up to 50 items."""
    items: list[BatchItem]


class BatchResult(BaseModel):
    """Single result in batch response."""
    title: str
    png_base64: str | None = None
    error: str | None = None


class BatchResponse(BaseModel):
    """Batch generation response."""
    count: int
    results: list[BatchResult]


@router.post("/batch")
def post_batch(
    request_data: BatchRequest,
    authorization: str | None = Header(None),
    key: str | None = Query(None),
    db: sqlite3.Connection = Depends(get_db),
) -> JSONResponse:
    """Generate multiple OG images in one request (Pro-only, max 25 items).

    Auth: Bearer token in Authorization header or ?key= query parameter.
    Input: JSON {items: [{title, subtitle?, template?, format?}, ...]}
    Output: JSON {count, results: [{title, png_base64?|error?}, ...]}

    Each image counts against monthly quota. Request is rejected atomically if it would
    exceed the quota.

    Free plan: 403 Forbidden
    Pro plan: Up to 25 items per batch, each uses 1 quota unit
    Exceeded quota: 429 Too Many Requests
    """
    # Resolve and validate API key
    api_key = None
    if authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]
        else:
            raise HTTPException(status_code=401, detail="Invalid Authorization header format")
    elif key:
        api_key = key
    else:
        raise HTTPException(status_code=401, detail="Missing API key")

    user = auth.user_by_api_key(db, api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check plan: batch is Pro-only
    plan = quota.effective_plan(user)
    if plan != "pro":
        return JSONResponse(
            status_code=403,
            content={"error": "Batch generation requires Pro plan"},
        )

    # Validate request size
    if len(request_data.items) == 0:
        return JSONResponse(
            status_code=400,
            content={"error": "items list cannot be empty"},
        )

    if len(request_data.items) > 25:
        return JSONResponse(
            status_code=400,
            content={"error": "Maximum 25 items per batch"},
        )

    # Check if batch would exceed quota (atomically)
    _, used, limit = quota.check_quota(db, user["id"], plan)
    if used + len(request_data.items) > limit:
        return JSONResponse(
            status_code=429,
            content={
                "error": "batch would exceed monthly quota",
                "used": used,
                "limit": limit,
                "batch_size": len(request_data.items),
            },
        )

    # Render each item
    results: list[BatchResult] = []
    for item in request_data.items:
        try:
            png_bytes = imaging.render_og_image(
                title=item.title,
                subtitle=item.subtitle,
                template=item.template,
                bg=None,
                fg=None,
                watermark=True,  # Pro watermark-less is only on /v1/og when directly called
                format=item.format,
            )
            png_base64 = base64.b64encode(png_bytes).decode("utf-8")
            results.append(BatchResult(title=item.title, png_base64=png_base64))
        except Exception as e:
            results.append(BatchResult(title=item.title, error=str(e)))

    # Record usage for each item (now that we know the batch succeeded)
    for _ in request_data.items:
        quota.record_usage(db, user["id"], "/v1/batch")

    return JSONResponse(
        status_code=200,
        content={
            "count": len(results),
            "results": [r.model_dump(exclude_none=True) for r in results],
        },
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
