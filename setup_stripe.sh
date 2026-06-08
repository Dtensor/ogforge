#!/usr/bin/env bash
# One-shot Stripe wiring for ogforge. Run AFTER `stripe login`.
# Creates a $9/mo "ogforge Pro" product+price, grabs the webhook signing secret,
# and writes .env. Safe to re-run (idempotent on the product name).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STRIPE="${STRIPE_BIN:-$HOME/bin/stripe}"
ENV_FILE="$HERE/.env"

command -v "$STRIPE" >/dev/null 2>&1 || STRIPE="stripe"

echo "==> Checking Stripe login..."
if ! "$STRIPE" config --list >/dev/null 2>&1; then
  echo "   Not logged in. Run:  $STRIPE login   (opens a browser), then re-run this script." >&2
  exit 1
fi

# Test-mode API key the CLI stored at login (restricted key, valid for test-mode writes).
SK="$("$STRIPE" config --list 2>/dev/null | sed -n 's/.*test_mode_api_key *= *//p' | tr -d "'\" " | head -1)"
if [ -z "${SK:-}" ]; then
  echo "   Could not read test_mode_api_key from CLI config." >&2
  echo "   Paste your sk_test_... below (from https://dashboard.stripe.com/test/apikeys):" >&2
  read -r SK
fi

echo "==> Creating (or reusing) the 'ogforge Pro' product + \$9/mo price..."
# Reuse an existing price for an "ogforge Pro" product if one already exists.
PRICE_ID="$("$STRIPE" prices list --limit 100 2>/dev/null \
  | python3 -c "import sys,json
try:
    data=json.load(sys.stdin)
except Exception:
    print(''); sys.exit()
for p in data.get('data', []):
    prod=p.get('product')
    nick=p.get('nickname') or ''
    if p.get('unit_amount')==900 and (p.get('recurring') or {}).get('interval')=='month':
        print(p['id']); break
" 2>/dev/null || true)"

if [ -z "${PRICE_ID:-}" ]; then
  PROD_ID="$("$STRIPE" products create --name "ogforge Pro" \
      --description "ogforge Pro plan: 5000 images/mo, no watermark, custom colors" \
      2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")"
  PRICE_ID="$("$STRIPE" prices create --product "$PROD_ID" \
      --unit-amount 900 --currency usd -d "recurring[interval]=month" \
      2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")"
  echo "   created product=$PROD_ID price=$PRICE_ID"
else
  echo "   reusing existing price=$PRICE_ID"
fi

echo "==> Fetching webhook signing secret (stripe listen --print-secret)..."
WHSEC="$("$STRIPE" listen --print-secret 2>/dev/null | tr -d '[:space:]' || true)"
[ -z "${WHSEC:-}" ] && echo "   (could not auto-fetch; you can paste it later)" >&2

echo "==> Writing $ENV_FILE ..."
cat > "$ENV_FILE" <<EOF
SESSION_SECRET=$(python3 -c "import secrets;print(secrets.token_urlsafe(32))")
DB_PATH=ogforge.db
BASE_URL=http://localhost:8810
STRIPE_SECRET_KEY=$SK
STRIPE_PUBLISHABLE_KEY=
STRIPE_PRICE_ID=$PRICE_ID
STRIPE_WEBHOOK_SECRET=$WHSEC
EOF
chmod 600 "$ENV_FILE"

echo ""
echo "Done. .env written (chmod 600, gitignored). Summary (masked):"
echo "  STRIPE_SECRET_KEY = ${SK:0:11}…"
echo "  STRIPE_PRICE_ID   = $PRICE_ID"
echo "  STRIPE_WEBHOOK_SECRET = ${WHSEC:0:8}…"
echo ""
echo "Next, in TWO terminals:"
echo "  1) ./run.sh"
echo "  2) $STRIPE listen --forward-to localhost:8810/billing/webhook"
echo "Then click Upgrade on the dashboard — real Stripe Checkout (test mode) opens."
