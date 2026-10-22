#!/usr/bin/env bash
#
# Manual exploration of the payment API.
#
#   ./scripts/requests.sh                       # against the live Render service
#   BASE_URL=http://localhost:8000 ./scripts/requests.sh   # against a local server
#   API_KEY=... ./scripts/requests.sh           # once auth is enforced (X-API-Key)
#
# Needs: curl, python3 (for JSON pretty-print / field extraction).

set -euo pipefail

BASE_URL="${BASE_URL:-https://payment-xp8n.onrender.com}"

# Set API_KEY once auth is enforced server-side (X-API-Key header, agreed convention
# with booking/access). Leave unset while auth is disabled.
AUTH=()
[ -n "${API_KEY:-}" ] && AUTH=(-H "X-API-Key: $API_KEY")

jqf() { python3 -m json.tool; }
field() { python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }
hr() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

hr "1. Health"
curl -s "$BASE_URL/health" | jqf

hr "2. Swagger / OpenAPI (open in a browser)"
echo "$BASE_URL/docs"
echo "$BASE_URL/redoc"
curl -s -o /dev/null -w "openapi.json -> %{http_code}\n" "$BASE_URL/openapi.json"

# Unique key per run so replays are meaningful and runs don't collide.
KEY="demo-$(date +%s)"

hr "3. Create a payment request (booking) -> 202 PENDING"
CREATE=$(curl -s "${AUTH[@]}" "$BASE_URL/payments" \
  -H 'content-type: application/json' \
  -d "{\"idempotency_key\":\"$KEY\",\"amount\":1250,\"currency\":\"EUR\",\"reference\":{\"type\":\"BOOKING\",\"id\":\"resa_1\"},\"source_service\":\"booking\"}")
echo "$CREATE" | jqf
PID=$(echo "$CREATE" | field payment_id)
echo "payment_id = $PID"

hr "4. Idempotent replay (same key) -> 200, same payment_id, still 1 transaction"
curl -s "${AUTH[@]}" -w '\nHTTP %{http_code}\n' "$BASE_URL/payments" \
  -H 'content-type: application/json' \
  -d "{\"idempotency_key\":\"$KEY\",\"amount\":1250,\"currency\":\"EUR\",\"reference\":{\"type\":\"BOOKING\",\"id\":\"resa_1\"},\"source_service\":\"booking\"}"

hr "5. Poll until settled (transaction is PENDING for ~15s)"
for i in $(seq 1 40); do
  BODY=$(curl -s "${AUTH[@]}" "$BASE_URL/payments/$PID")
  STATUS=$(echo "$BODY" | field status)
  echo "  [$i] status=$STATUS"
  [ "$STATUS" != "PENDING" ] && break
  sleep 2
done
echo "$BODY" | jqf

hr "6. Second, distinct payment (access / parking exit)"
curl -s "${AUTH[@]}" "$BASE_URL/payments" \
  -H 'content-type: application/json' \
  -d "{\"idempotency_key\":\"exit-$(date +%s)\",\"amount\":460,\"currency\":\"EUR\",\"reference\":{\"type\":\"PARKING_EXIT\",\"id\":\"stay_42\"},\"source_service\":\"access\"}" | jqf

hr "7. Validation errors -> 422"
echo "- amount = 0"
curl -s "${AUTH[@]}" -o /dev/null -w '  HTTP %{http_code}\n' "$BASE_URL/payments" -H 'content-type: application/json' \
  -d '{"idempotency_key":"bad","amount":0,"currency":"EUR","reference":{"type":"BOOKING","id":"r"},"source_service":"booking"}'
echo "- missing idempotency_key"
curl -s "${AUTH[@]}" -o /dev/null -w '  HTTP %{http_code}\n' "$BASE_URL/payments" -H 'content-type: application/json' \
  -d '{"amount":100,"currency":"EUR","reference":{"type":"BOOKING","id":"r"},"source_service":"booking"}'
echo "- unknown reference.type"
curl -s "${AUTH[@]}" -o /dev/null -w '  HTTP %{http_code}\n' "$BASE_URL/payments" -H 'content-type: application/json' \
  -d '{"idempotency_key":"bad","amount":100,"currency":"EUR","reference":{"type":"PIZZA","id":"r"},"source_service":"booking"}'
echo "- unknown source_service"
curl -s "${AUTH[@]}" -o /dev/null -w '  HTTP %{http_code}\n' "$BASE_URL/payments" -H 'content-type: application/json' \
  -d '{"idempotency_key":"bad","amount":100,"currency":"EUR","reference":{"type":"BOOKING","id":"r"},"source_service":"parking"}'

hr "8. Unknown payment id -> 404"
curl -s "${AUTH[@]}" -o /dev/null -w '  HTTP %{http_code}\n' "$BASE_URL/payments/does-not-exist"

hr "9. Hunt for a refusal (~5% rate): fire 30 payments, settle, list statuses"
IDS=""
for i in $(seq 1 30); do
  ID=$(curl -s "${AUTH[@]}" "$BASE_URL/payments" -H 'content-type: application/json' \
    -d "{\"idempotency_key\":\"batch-$KEY-$i\",\"amount\":100,\"currency\":\"EUR\",\"reference\":{\"type\":\"BOOKING\",\"id\":\"r$i\"},\"source_service\":\"booking\"}" | field payment_id)
  IDS="$IDS $ID"
done
echo "  created 30, waiting for retries to finish (~35s)..."
sleep 35
for ID in $IDS; do
  echo "$ID -> $(curl -s "${AUTH[@]}" "$BASE_URL/payments/$ID" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['status'], '| attempts:', len(d['transactions']), '|', [t['status'] for t in d['transactions']])")"
done
echo "  (a REFUSED payment shows 2 transactions: attempt 1 + the automatic retry)"
