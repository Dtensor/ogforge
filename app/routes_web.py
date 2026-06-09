"""Web routes: landing, auth (signup/login/logout), dashboard, billing callbacks."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import sqlite3

from . import auth, billing, quota
from .config import settings
from .db import get_db

router = APIRouter(tags=["web"])

# Resolve template directory (works from any CWD)
app_dir = Path(__file__).parent
templates_dir = app_dir / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


def _current_user(request: Request, db: sqlite3.Connection) -> dict | None:
    """Helper: return user dict if logged in, else None."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return auth.get_user(db, user_id)


@router.get("/")
def landing(request: Request):
    """Landing page: hero + pricing."""
    return templates.TemplateResponse(
        "landing.html",
        {
            "request": request,
            "plans": quota.PLANS,
        },
    )


@router.get("/gallery")
def gallery(request: Request):
    """Gallery page: showcase all templates and formats with live samples.

    SEO-friendly public discovery page showing the 4 templates and 3 formats.
    """
    # Sample headlines for gallery items
    samples = [
        {"title": "The Art of API Design", "template": "gradient"},
        {"title": "Ship Faster with Snapcard", "template": "default"},
        {"title": "Social cards, powered by AI", "template": "dark"},
        {"title": "One line to gorgeous cards", "template": "minimal"},
    ]

    formats = [
        {"name": "og", "label": "Desktop (1200×630)", "width": 1200, "height": 630},
        {"name": "story", "label": "Stories (1080×1920)", "width": 1080, "height": 1920},
        {"name": "square", "label": "Square (1080×1080)", "width": 1080, "height": 1080},
    ]

    return templates.TemplateResponse(
        "gallery.html",
        {
            "request": request,
            "samples": samples,
            "formats": formats,
        },
    )


@router.get("/signup")
def signup_get(request: Request):
    """Signup form."""
    return templates.TemplateResponse("signup.html", {"request": request})


@router.post("/signup")
def signup_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """Create user, issue API key, log in, redirect to dashboard."""
    try:
        user_id = auth.create_user(db, email, password)
        auth.create_api_key(db, user_id)
        request.session["user_id"] = user_id
        return RedirectResponse(url="/dashboard", status_code=303)
    except ValueError:
        # Email already exists — re-render the form with an inline error (HTML form
        # validation convention: 200 + visible message, not a 4xx the browser may cache).
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": "Email already registered"},
        )


@router.get("/login")
def login_get(request: Request):
    """Login form."""
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """Authenticate and set session."""
    user = auth.authenticate(db, email, password)
    if not user:
        # Re-render the login form with an inline error (HTML form convention: 200).
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password"},
        )
    request.session["user_id"] = user["id"]
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/logout")
def logout(request: Request):
    """Clear session, redirect home."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@router.get("/dashboard")
def dashboard(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
):
    """User dashboard: email, plan, API key, usage, sample URL, curl snippet."""
    user = _current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Compute usage (effective_plan honors the one-time Pro expiry)
    plan = quota.effective_plan(user)
    allowed, used, limit = quota.check_quota(db, user["id"], plan)
    key = auth.active_api_key(db, user["id"])

    # Build sample URL and curl snippet
    sample_url = f"{settings.base_url}/v1/og?title=Hello&key={key}"
    curl_snippet = f'curl "{sample_url}" -o og-image.png'

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "email": user["email"],
            "plan": plan,
            "plan_label": quota.plan_of(plan)["label"],
            "api_key": key or "",
            "used": used,
            "limit": limit,
            "sample_url": sample_url,
            "curl_snippet": curl_snippet,
            "pro_until": user.get("pro_until") if plan == "pro" else None,
            "msg": request.query_params.get("msg"),
        },
    )


@router.post("/dashboard/regenerate-key")
def regenerate_key(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
):
    """Revoke old key and create new one."""
    user = _current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    auth.create_api_key(db, user["id"])
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/upgrade")
def upgrade(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
):
    """Redirect to Razorpay checkout or flash error if not configured."""
    user = _current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if not settings.razorpay_enabled:
        return RedirectResponse(
            url="/dashboard?msg=Razorpay%20not%20configured%20%E2%80%94%20set%20keys%20in%20.env",
            status_code=303,
        )

    try:
        session_url = billing.create_checkout_session(db, user)
        return RedirectResponse(url=session_url, status_code=303)
    except RuntimeError:
        return RedirectResponse(
            url="/dashboard?msg=Razorpay%20not%20configured%20%E2%80%94%20set%20keys%20in%20.env",
            status_code=303,
        )


@router.get("/billing/success")
def billing_success(request: Request):
    """Razorpay redirect after successful checkout."""
    return templates.TemplateResponse(
        "success.html",
        {
            "request": request,
        },
    )


@router.get("/billing/cancel")
def billing_cancel(request: Request):
    """Razorpay redirect after user cancels checkout."""
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/billing/webhook")
async def billing_webhook(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
):
    """Handle Razorpay webhook.

    Async so we can read the EXACT raw body bytes (await request.body()) that Razorpay's
    signature is computed over — FastAPI's Body() parsing mangles/validates the payload
    (returns 422 on real Razorpay POSTs). DB access here is SQLite, which tolerates the
    dependency/handler thread split (check_same_thread=False).
    """
    payload = await request.body()
    sig_header = request.headers.get("x-razorpay-signature")
    try:
        return billing.handle_webhook(db, payload, sig_header)
    except ValueError as e:
        # Must be a real 4xx so Razorpay records the failure and retries.
        return JSONResponse(status_code=400, content={"error": str(e)})
