# ogforge 🖼️

## What we built

You know those nice preview pictures that show up when you paste a link into Twitter, Slack, or WhatsApp? The big banner with a title on it? Those are called **Open-Graph images**, and normally someone has to design one by hand for every page.

**ogforge is a robot that draws those banners for you.** You send it a web address like:

```
https://ogforge.fly.dev/v1/og?title=My+Cool+Post&key=YOUR_KEY
```

…and it hands back a finished 1200×630 picture with your words on it. Instantly. As many as you want (up to your monthly allowance).

It's a little **business**, not just a toy:
- Anyone can sign up and get a **free** plan (50 pictures a month, with a small `ogforge.dev` stamp in the corner).
- If they like it, they click **Upgrade**, pay **₹750/month** through **Razorpay** (a popular Indian payments company), and become **Pro**: 5,000 pictures a month, no stamp, and they can pick their own colors.
- When Razorpay says "this person's subscription is active," ogforge automatically flips them to Pro. When they cancel, it flips them back. Nobody does that by hand.

It's **live** at **https://ogforge.fly.dev**.

## How I use it manually

All commands run from the `ogforge/` folder.

```bash
# 1. One-time setup (make the Python sandbox and install the parts)
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
#    -> creates a private toolbox so ogforge's parts don't mess with anything else

# 2. (Optional) turn on real payments
cp env.sample .env        # then paste your Razorpay test keys into .env
./setup_razorpay.sh       # creates the ₹750/mo plan and writes its id into .env
#    -> without this, everything still works EXCEPT the "pay me" button

# 3. Start the website + API
./run.sh
#    -> opens the shop at http://localhost:8810  (Ctrl-C to stop)

# 4. Run the safety checks (98 tests)
.venv/bin/python -m pytest tests -q
#    -> proves signup, image-making, quotas, and the webhook all behave
```

Then open **http://localhost:8810** in a browser: sign up, copy your API key from the dashboard, and start making images.

## What runs automatically

You don't push these buttons — they happen on their own:

- **Payment reconciliation.** When someone's subscription activates or renews (or cancels) on Razorpay, Razorpay quietly POSTs a signed message to `/billing/webhook`. ogforge verifies the signature and upgrades/downgrades that person's plan with no human involved. This is the heart of the whole thing.
- **Quota counting.** Every time an image is made, ogforge writes a tiny tally mark. At the start of each calendar month the count effectively resets, so a free user gets a fresh 50.
- **Tier enforcement.** On every image request, ogforge looks up *from its own database* whether you're Free or Pro and decides the watermark and color rules from that — it never trusts what the request claims. So you can't sneak a Pro feature by adding `&plan=pro` to the URL.
- **The database tables are created on first boot** (`init_db()`), so there's no separate "set up the database" step.

## Commands

| Command | What It Does | When I Use It |
|---|---|---|
| `./run.sh` | Starts the website + API on port 8810 | Every time I want it running |
| `.venv/bin/python -m pytest tests -q` | Runs all 98 tests | Before trusting a change |
| `./setup_razorpay.sh` | Creates the ₹750/mo plan, writes its id to `.env` | Once, after adding Razorpay keys |
| `curl ".../v1/og?title=Hi&key=KEY" -o out.png` | Makes one image from the command line | Quick test without a browser |
| `flyctl deploy --app ogforge --ha=false` | Ships to production | After a change I want live |

## One real example (a typical first day)

1. I run `./run.sh` and open `http://localhost:8810`.
2. I click **Sign up**, enter an email + password. ogforge makes me an account and a key like `og_live_C0xz…`, and drops me on my **dashboard**.
3. The dashboard shows my key, my usage (`0 / 50`), a live sample image, and a ready-to-paste `curl` command.
4. I run that curl and get a real PNG banner — with the little `ogforge.dev` watermark, because I'm on Free.
5. I want my own colors and no watermark, so I click **Upgrade**. Razorpay's hosted page opens; I pay ₹750 (test card in test mode). Razorpay activates the subscription and pings the webhook. My dashboard now says **Pro**, `0 / 5000`.
6. I make another image with `&bg=%230b1021&fg=%2300e5ff` — now it uses *my* colors and has **no watermark**.
7. Later I cancel; the `subscription.cancelled` webhook fires and I'm gently moved back to Free.

That whole loop — signup → free image → pay → pro image → cancel → free — is covered by the test suite (the webhook half end-to-end over HTTP).

---

### Setting up Razorpay (test mode), the short version

1. Make a Razorpay account. (Test mode works immediately; live mode needs business KYC.)
2. **Settings → API Keys → Generate Test Key** → copy `rzp_test_…` (key id) and its secret into `.env` as `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`.
3. Run `./setup_razorpay.sh` → it creates the ₹750/mo "ogforge Pro" plan and writes `RAZORPAY_PLAN_ID` into `.env`.
4. **Settings → Webhooks → Add** a webhook at `<BASE_URL>/billing/webhook`, set a secret (put it in `.env` as `RAZORPAY_WEBHOOK_SECRET`), and subscribe to: `subscription.activated`, `subscription.charged`, `subscription.cancelled`, `subscription.completed`, `subscription.halted`.
5. Restart `./run.sh`. The **Upgrade** button now opens a real Razorpay subscription page.

In production (Fly), set the same four values as secrets: `flyctl secrets set RAZORPAY_KEY_ID=… RAZORPAY_KEY_SECRET=… RAZORPAY_PLAN_ID=… RAZORPAY_WEBHOOK_SECRET=… --app ogforge`.

### A note for grown-ups (architecture)

- **Stack:** FastAPI + plain `sqlite3` (no ORM) + Pillow (image drawing) + Razorpay + Jinja2 templates. Python 3.11. `db.py` also supports Postgres via `DATABASE_URL` (kept for a future async migration); production runs SQLite-WAL on a Fly volume.
- **Security boundary:** a user's plan is *always* read from the DB, never from request input; quota is counted per UTC calendar month; the API key resolves to a user via a non-revoked-key join. The Razorpay webhook **requires a valid HMAC signature whenever a webhook secret is configured** — it only accepts unsigned JSON in local dev where no secret is set (so a forged POST can't grant a free upgrade in production). The webhook maps back to a user via the subscription's `notes.user_id`.
- **Files:** `app/config.py` (env), `app/db.py` (schema + connections), `app/quota.py` (plans + limits), `app/auth.py` (passwords/keys), `app/imaging.py` (the drawing), `app/billing.py` (Razorpay), `app/routes_api.py` (the `/v1` API), `app/routes_web.py` (the website), `app/main.py` (glue).
- **Deploy:** `Dockerfile` (+ DejaVu fonts for Pillow) + `fly.toml` (single machine, persistent volume at `/data`, gunicorn + uvicorn workers).

_Originally built with Stripe; switched to Razorpay after Stripe rejected the India account for live payments. Postgres was trialed but reverted to SQLite — sync `psycopg` under FastAPI's async worker hangs under load (the correct Postgres path is a full async rewrite)._
