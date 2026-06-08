# ogforge 🖼️

## What we built

You know those nice preview pictures that show up when you paste a link into Twitter, Slack, or WhatsApp? The big banner with a title on it? Those are called **Open-Graph images**, and normally someone has to design one by hand for every page.

**ogforge is a robot that draws those banners for you.** You send it a web address like:

```
https://your-ogforge/v1/og?title=My+Cool+Post&key=YOUR_KEY
```

…and it hands back a finished 1200×630 picture with your words on it. Instantly. As many as you want (up to your monthly allowance).

It's a little **business**, not just a toy:
- Anyone can sign up and get a **free** plan (50 pictures a month, with a small `ogforge.dev` stamp in the corner).
- If they like it, they click **Upgrade**, pay through **Stripe** (the same company that handles payments for tons of websites), and become **Pro**: 5,000 pictures a month, no stamp, and they can pick their own colors.
- When Stripe says "this person paid," ogforge automatically flips them to Pro. When they cancel, it flips them back. Nobody has to do that by hand.

## How I use it manually

All commands run from the `ogforge/` folder.

```bash
# 1. One-time setup (make the Python sandbox and install the parts)
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
#    -> creates a private toolbox so ogforge's parts don't mess with anything else

# 2. (Optional) turn on real payments
cp env.sample .env        # then paste your Stripe test keys into .env
#    -> without this, everything still works EXCEPT the "pay me" button

# 3. Start the website + API
./run.sh
#    -> opens the shop at http://localhost:8810  (Ctrl-C to stop)

# 4. Run the safety checks (101 tests)
.venv/bin/python -m pytest tests -q
#    -> proves signup, image-making, quotas, and payments all behave
```

Then open **http://localhost:8810** in a browser: sign up, copy your API key from the dashboard, and start making images.

## What runs automatically

You don't push these buttons — they happen on their own:

- **Payment reconciliation.** When someone pays (or cancels) on Stripe, Stripe quietly POSTs a message to `/billing/webhook`. ogforge reads it and upgrades/downgrades that person's plan with no human involved. This is the heart of the whole thing.
- **Quota counting.** Every time an image is made, ogforge writes a tiny tally mark. At the start of each calendar month the count effectively resets, so a free user gets a fresh 50.
- **Tier enforcement.** On every image request, ogforge looks up *from its own database* whether you're Free or Pro and decides the watermark and color rules from that — it never trusts what the request claims. So you can't sneak a Pro feature by adding `&plan=pro` to the URL.
- **The website tables are created on first boot** (`init_db()`), so there's no separate "set up the database" step.

## Commands

| Command | What It Does | When I Use It |
|---|---|---|
| `./run.sh` | Starts the website + API on port 8810 | Every time I want it running |
| `.venv/bin/python -m pytest tests -q` | Runs all 101 tests | Before trusting a change |
| `cp env.sample .env` | Creates the secrets file | Once, when wiring up Stripe |
| `curl ".../v1/og?title=Hi&key=KEY" -o out.png` | Makes one image from the command line | Quick test without a browser |
| `curl -X POST .../billing/webhook -d '{...}'` | Simulates a Stripe payment event | Testing the upgrade flow locally |

## One real example (a typical first day)

1. I run `./run.sh` and open `http://localhost:8810`.
2. I click **Sign up**, enter an email + password. ogforge makes me an account and a key like `og_live_C0xz…`, and drops me on my **dashboard**.
3. The dashboard shows my key, my usage (`0 / 50`), a live sample image, and a ready-to-paste `curl` command.
4. I run that curl and get a real PNG banner — with the little `ogforge.dev` watermark, because I'm on Free.
5. I want my own colors and no watermark, so I click **Upgrade → $9/mo**. Stripe takes my (test) card. Stripe pings the webhook. My dashboard now says **Pro**, `0 / 5000`.
6. I make another image with `&bg=%230b1021&fg=%2300e5ff` — now it uses *my* colors and has **no watermark**.
7. Later I cancel in Stripe; the `customer.subscription.deleted` webhook fires and I'm gently moved back to Free.

That whole loop — signup → free image → pay → pro image → cancel → free — has been run end-to-end and is covered by the test suite.

---

### Setting up Stripe (test mode), the short version

1. Make a free Stripe account, switch to **Test mode**.
2. Create a recurring **Price** (e.g. $9/month). Copy its `price_…` id.
3. From *Developers → API keys*, copy the **Secret key** (`sk_test_…`) and **Publishable key** (`pk_test_…`).
4. Run `stripe listen --forward-to localhost:8810/billing/webhook` and copy the `whsec_…` it prints.
5. Paste all four into `.env` (see `env.sample`). Restart `./run.sh`.

Now the **Upgrade** button on the dashboard opens a real Stripe Checkout page.

### A note for grown-ups (architecture)

- **Stack:** FastAPI + plain `sqlite3` (no ORM) + Pillow (image drawing) + Stripe + Jinja2 templates. Python 3.11.
- **Security boundary:** a user's plan is *always* read from the DB, never from request input; quota is counted per UTC calendar month; the API key resolves to a user via a non-revoked-key join. The Stripe webhook **requires a valid signature whenever a webhook secret is configured** — it only accepts unsigned JSON in local dev where no secret is set (so a forged POST can't grant a free upgrade in production).
- **Files:** `app/config.py` (env), `app/db.py` (schema + connections), `app/quota.py` (plans + limits), `app/auth.py` (passwords/keys), `app/imaging.py` (the drawing), `app/billing.py` (Stripe), `app/routes_api.py` (the `/v1` API), `app/routes_web.py` (the website), `app/main.py` (glue).
- **Known cosmetics:** uses FastAPI's `@app.on_event("startup")` (deprecated in favor of lifespan handlers, still works on 0.115); gradient template draws row-by-row in Python (fine at this size).

_Built in one session: foundation + glue hand-written, leaf modules fanned out across parallel agents against a fixed contract (`SPEC.md`), then put through a 3-lens adversarial review (monetization / quota-security / integration) before fixing the real findings and verifying live._
