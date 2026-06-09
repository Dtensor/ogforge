#!/usr/bin/env bash
# One-shot Razorpay plan setup for ogforge. Run AFTER putting RAZORPAY_KEY_ID and
# RAZORPAY_KEY_SECRET in .env. Creates a ₹750/mo "ogforge Pro" plan and writes its id
# back into .env as RAZORPAY_PLAN_ID. Idempotent-ish: reuses an existing ₹750/mo plan.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/.env"
PY="$HERE/.venv/bin/python"

[ -f "$ENV_FILE" ] || { echo "No .env — cp env.sample .env and add your Razorpay keys first." >&2; exit 1; }

KEY_ID=$(grep "^RAZORPAY_KEY_ID=" "$ENV_FILE" | cut -d= -f2-)
KEY_SECRET=$(grep "^RAZORPAY_KEY_SECRET=" "$ENV_FILE" | cut -d= -f2-)
[ -n "$KEY_ID" ] && [ -n "$KEY_SECRET" ] || { echo "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env first." >&2; exit 1; }

echo "==> Creating (or reusing) the ogforge Pro ₹750/mo plan..."
PLAN_ID="$(RAZORPAY_KEY_ID="$KEY_ID" RAZORPAY_KEY_SECRET="$KEY_SECRET" "$PY" - <<'PY'
import os, razorpay
c = razorpay.Client(auth=(os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"]))
# Reuse an existing monthly ₹750 plan if present.
plan_id = ""
try:
    for p in c.plan.all({"count": 100}).get("items", []):
        item = p.get("item", {})
        if p.get("period") == "monthly" and item.get("amount") == 75000 and item.get("currency") == "INR":
            plan_id = p["id"]; break
except Exception:
    pass
if not plan_id:
    plan = c.plan.create({
        "period": "monthly",
        "interval": 1,
        "item": {"name": "ogforge Pro", "amount": 75000, "currency": "INR",
                 "description": "ogforge Pro: 5000 images/mo, no watermark, custom colors"},
    })
    plan_id = plan["id"]
print(plan_id)
PY
)"
echo "   plan id: $PLAN_ID"

# Write/replace RAZORPAY_PLAN_ID in .env
if grep -q "^RAZORPAY_PLAN_ID=" "$ENV_FILE"; then
  sed -i '' "s|^RAZORPAY_PLAN_ID=.*|RAZORPAY_PLAN_ID=$PLAN_ID|" "$ENV_FILE"
else
  printf '\nRAZORPAY_PLAN_ID=%s\n' "$PLAN_ID" >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"
echo "Done. RAZORPAY_PLAN_ID written to .env."
echo "Next: add a webhook in the Razorpay dashboard -> Settings -> Webhooks:"
echo "  URL:    \$BASE_URL/billing/webhook"
echo "  events: subscription.activated, subscription.charged, subscription.cancelled,"
echo "          subscription.completed, subscription.halted"
echo "  secret: put the same value in .env as RAZORPAY_WEBHOOK_SECRET"
