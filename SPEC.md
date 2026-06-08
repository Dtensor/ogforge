# ogforge — implementation contract (READ THIS FIRST, conform exactly)

ogforge is a **Dynamic Open-Graph / Social-Card Image API SaaS** built with FastAPI + SQLite + Pillow + Stripe.
Python 3.11. Project root: `/Users/King_1/claude_workspace/ogforge`. Port 8810.

## Foundation already on disk (DO NOT rewrite — import from these, match signatures exactly)

### `app/config.py`
- `settings` (module-level `Settings` instance). Fields: `db_path, secret_key, base_url,
  stripe_secret_key, stripe_publishable_key, stripe_price_id, stripe_webhook_secret`.
- `settings.stripe_enabled -> bool` (True iff secret_key and price_id set).

### `app/db.py`
- `connect() -> sqlite3.Connection` (Row factory set).
- `get_db()` — FastAPI dependency, `yield`s a connection.
- `init_db()` — creates tables.
- `utcnow() -> str` — ISO8601 UTC timestamp.
- Tables: `users(id, email UNIQUE, password_hash, plan, stripe_customer_id, created_at)`,
  `api_keys(id, user_id, key UNIQUE, revoked, created_at)`,
  `usage(id, user_id, endpoint, ts)`.

### `app/quota.py`
- `PLANS` dict: keys `"free"`, `"pro"`. Each has `label, monthly_limit, watermark (bool),
  custom_colors (bool), price_display`.
- `plan_of(plan) -> dict`
- `usage_this_month(db, user_id) -> int`
- `record_usage(db, user_id, endpoint) -> None`
- `check_quota(db, user_id, plan) -> (allowed: bool, used: int, limit: int)`

## Files to IMPLEMENT (exact signatures — other modules depend on these names)

### `app/auth.py`
```python
def hash_password(password: str) -> str          # pbkdf2_hmac sha256, store "salt$hexhash"
def verify_password(password: str, stored: str) -> bool
def create_user(db, email: str, password: str) -> int   # returns user_id; raises ValueError("email exists") on dup
def authenticate(db, email: str, password: str) -> dict | None   # returns user row as dict or None
def get_user(db, user_id: int) -> dict | None
def generate_api_key() -> str                     # "og_live_" + secrets.token_urlsafe(24)
def create_api_key(db, user_id: int) -> str       # revokes old keys for that user, inserts new, returns the key string
def user_by_api_key(db, key: str) -> dict | None  # joins api_keys (revoked=0) -> users; returns user dict or None
def active_api_key(db, user_id: int) -> str | None # current non-revoked key
```
Use only stdlib (`hashlib`, `secrets`, `os`). Return user rows as plain dicts (`dict(row)`).

### `app/imaging.py`
```python
TEMPLATES = ["default", "dark", "gradient", "minimal"]   # list of supported template names
def render_og_image(title: str, subtitle: str = "", template: str = "default",
                    bg: str | None = None, fg: str | None = None,
                    watermark: bool = True) -> bytes      # returns PNG bytes, 1200x630
```
- Use Pillow. Canvas 1200x630. Wrap `title` to fit (large bold), `subtitle` smaller/dimmer.
- Templates differ by palette: default=indigo bg/white text, dark=near-black/white,
  gradient=vertical indigo→violet, minimal=white bg/near-black text.
- `bg`/`fg` (hex like "#0ea5e9") override the template palette when provided.
- Load a TrueType font by trying, in order: `/System/Library/Fonts/Supplemental/Arial Bold.ttf`,
  `/System/Library/Fonts/Helvetica.ttc`, `/Library/Fonts/Arial.ttf`,
  `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`; fall back to `ImageFont.load_default()`.
  Provide a helper `_load_font(size)`.
- If `watermark` True, draw small dim text "ogforge.dev" bottom-right.
- Robust: invalid template falls back to "default"; invalid hex color is ignored (use palette).
- Return PNG via `BytesIO`.

### `app/billing.py`
```python
def create_checkout_session(db, user: dict) -> str
    # raises RuntimeError("Stripe not configured") if not settings.stripe_enabled
    # sets stripe customer if missing, creates a subscription Checkout Session for settings.stripe_price_id
    # success_url = f"{settings.base_url}/billing/success", cancel_url = f"{settings.base_url}/billing/cancel"
    # client_reference_id = str(user["id"]); returns session.url
def handle_webhook(db, payload: bytes, sig_header: str | None) -> dict
    # verify signature via stripe.Webhook.construct_event using settings.stripe_webhook_secret
    #   (if no webhook secret set, json.loads the payload directly — dev/test fallback)
    # on "checkout.session.completed": set users.plan='pro' and stripe_customer_id for the
    #   user identified by client_reference_id (fallback: customer id). commit.
    # on "customer.subscription.deleted": set users.plan='free' for that stripe_customer_id. commit.
    # returns {"status": "ok", "handled": <event_type or "ignored">}
    # raises ValueError on bad signature / malformed payload (routes_web maps to 400)
def set_plan_by_customer(db, stripe_customer_id: str, plan: str) -> None   # helper
```
Import `stripe` and set `stripe.api_key = settings.stripe_secret_key` at module load.

### `app/routes_api.py`
```python
from fastapi import APIRouter
router = APIRouter(prefix="/v1", tags=["api"])
```
- `GET /v1/og` — params: `title` (required), `subtitle="", template="default", bg=None, fg=None`.
  Auth: `Authorization: Bearer <key>` header OR `?key=`. 401 if no/invalid key.
  Resolve user via `auth.user_by_api_key`. plan = user["plan"].
  `check_quota`; if not allowed -> 429 JSON `{"error":"monthly quota exceeded","used":..,"limit":..,"plan":..}`.
  Determine `wm = quota.plan_of(plan)["watermark"]`; `allow_custom = plan_of(plan)["custom_colors"]`.
  Pass bg/fg only if allow_custom (else None). render image, `quota.record_usage`, return
  `Response(content=png, media_type="image/png")` with header `X-OGForge-Plan: <plan>`.
- `GET /v1/usage` — same auth — returns JSON `{plan, used, limit, watermark}`.

### `app/routes_web.py`
```python
from fastapi import APIRouter
router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")
```
Session via `request.session` (SessionMiddleware added in main). Helper `_current_user(request, db)`.
- `GET /` -> landing.html (hero + pricing from quota.PLANS).
- `GET /signup`, `POST /signup` (form: email, password) -> create_user + create_api_key, log them in (session["user_id"]), redirect /dashboard. On dup email re-render with error.
- `GET /login`, `POST /login` -> authenticate, set session, redirect /dashboard; else error.
- `GET /logout` -> clear session, redirect /.
- `GET /dashboard` -> requires login (redirect /login if not). Show: email, plan, api key,
  usage used/limit, a sample image URL (`{base_url}/v1/og?title=Hello&key=<key>`), a curl snippet,
  and an Upgrade button (only if plan=='free'). Pass `stripe_enabled=settings.stripe_enabled`.
- `POST /dashboard/regenerate-key` -> create_api_key, redirect /dashboard.
- `POST /upgrade` -> if not logged in redirect /login; if not stripe_enabled flash a message on
  dashboard ("Stripe not configured — set keys in .env"); else create_checkout_session and redirect to its url.
- `GET /billing/success` -> success.html (info: webhook will confirm). `GET /billing/cancel` -> redirect /dashboard.
- `POST /billing/webhook` -> read raw body + `stripe-signature` header, call billing.handle_webhook,
  return JSON; on ValueError return 400.

Use `RedirectResponse(url, status_code=303)` for POST->GET redirects. Return `dict(row)` user objects.

### `app/templates/` (Jinja2) + `app/static/style.css`
- `base.html` (nav: ogforge logo, Dashboard/Login/Logout depending on `request.session`),
  `landing.html` (hero, live sample `<img>` pointing at a public demo? no — just describe;
   pricing cards from PLANS), `signup.html`, `login.html`, `dashboard.html`, `success.html`.
- Clean, modern, dark-ish indigo theme. One `style.css`. No external CDNs (self-contained).
- Forms POST to the routes above. Show `error` variable when present.

### `tests/` (pytest, no live Stripe, no network)
- `tests/conftest.py`: fixture that points DB_PATH at a temp file (set env BEFORE importing app),
  builds a `TestClient(app)`. Reset DB per test.
- `test_auth.py`: hash/verify roundtrip, create_user dup raises, authenticate good/bad, api key resolve.
- `test_quota.py`: record_usage increments, check_quota flips at limit (monkeypatch PLANS limit small).
- `test_imaging.py`: render returns non-empty PNG (starts with b"\x89PNG"), each template works,
  watermark on/off both render, custom colors render.
- `test_billing.py`: handle_webhook with no webhook secret + a synthetic
  `checkout.session.completed` payload (client_reference_id) flips user to 'pro';
  `customer.subscription.deleted` flips back to 'free'. (Build user via auth first.)
- `test_api.py`: full flow via TestClient — signup, grab key from dashboard/db, GET /v1/og returns
  image/png, /v1/usage increments, missing key -> 401, exceeding quota -> 429 (monkeypatch limit).

## main.py (glue — will be written by integrator, but conform):
```python
app = FastAPI(title="ogforge")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
init_db() at startup
app.include_router(routes_web.router); app.include_router(routes_api.router)
```

## Rules
- Python 3.11, type hints on signatures, f-strings, stdlib-first.
- Every network/Stripe call must be guarded; app must boot and serve free-tier with NO Stripe keys.
- No `print()` debug. Timeouts on any outbound HTTP (Stripe SDK handles its own).
- Return DB rows as dicts. Commit after writes.
