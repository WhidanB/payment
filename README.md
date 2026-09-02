# Payment Service

Payment microservice for the "parking fil rouge" project. It receives JSON payment
requests from the **booking** and **access** services, opens **transactions** to settle
them, and reports a status: `PENDING` / `ACCEPTED` / `REFUSED`.

The payment gateway is **simulated** for now (95% accepted, 5% refused). Stripe will be
plugged in later behind the same port, without touching the domain.

**Live:** https://payment-xp8n.onrender.com — [Swagger](https://payment-xp8n.onrender.com/docs)
· [health](https://payment-xp8n.onrender.com/health)
(Render free tier: first request after ~15 min idle takes 30-50 s to wake).

## Business model

- A **payment request** is identified by a caller-supplied **idempotency key**. Replaying the
  same key never creates a second charge — the existing request is returned as-is (HTTP 200).
- A payment request aggregates **1..N transactions** (attempts). Each transaction is unique
  (UUID v7). Several transactions can answer the same request.
- A transaction stays `PENDING` for **15 s** (asynchronous by nature), then resolves.
- On a refusal the service automatically opens **one** retry transaction (again `PENDING` 15 s).
  If it also fails, the payment request is `REFUSED`.
- Callers get the outcome by **polling** `GET /payments/{id}`.
- Every transaction / payment state change is written to the logs as a JSON line.

## Architecture (hexagonal)

The domain core has **no** framework import.

```
app/domain/model/     entities + rules  (PaymentRequest aggregate, Transaction, enums)
app/domain/ports/     interfaces        (PaymentRepository, PaymentGateway, ResolutionScheduler)
app/application/       use-cases         (PaymentService)
app/adapters/inbound/  FastAPI routes + DTOs
app/adapters/outbound/ InMemoryPaymentRepository, SimulatedPaymentGateway, AsyncioResolutionScheduler
app/container.py       composition root  <- swap adapters here (Stripe, SQL, ...)
app/main.py            application factory
```

To plug Stripe in later: add `app/adapters/outbound/stripe_payment_gateway.py` implementing
`PaymentGateway`, and wire it in `container.py`. Nothing else changes.

## API

Base URL: `https://payment-xp8n.onrender.com`. Interactive docs: **`/docs`** (Swagger UI),
`/redoc`, `/openapi.json`.

### `POST /payments` → `202 Accepted` (`200` on idempotent replay)

```json
{
  "idempotency_key": "booking-4567-1",
  "amount": 1250,
  "currency": "EUR",
  "reference": { "type": "BOOKING", "id": "resa_01J9Z..." },
  "source_service": "booking"
}
```

| field | notes |
|---|---|
| `idempotency_key` | required, unique per business operation |
| `amount` | integer, **minor units (cents)**, > 0 |
| `currency` | `EUR` |
| `reference.type` | `BOOKING` \| `PARKING_EXIT` |
| `reference.id` | booking id or parking-stay id |
| `source_service` | `booking` \| `access` |

Response:

```json
{
  "payment_id": "01a061e4-b37c-7881-8e47-743bcbc8cffb",
  "status": "PENDING",
  "amount": 1250,
  "currency": "EUR",
  "reference": { "type": "BOOKING", "id": "resa_01J9Z..." },
  "source_service": "booking",
  "transactions": [
    { "transaction_id": "01a061e4-...", "attempt": 1, "status": "PENDING",
      "created_at": "2026-09-02T11:32:53.244Z", "resolved_at": null }
  ],
  "created_at": "2026-09-02T11:32:53.244Z",
  "updated_at": "2026-09-02T11:32:53.244Z"
}
```

- `422` — invalid body.

### `GET /payments/{payment_id}` → `200 OK`

Same shape, kept up to date (aggregate status + every transaction). `404` if unknown.

### `GET /health` → `200 OK`

```json
{ "status": "ok", "version": "0.1.0", "uptime_seconds": 12.3 }
```

## Run locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload
```

```bash
# create
curl -si -XPOST localhost:8000/payments -H 'content-type: application/json' -d '{
  "idempotency_key":"demo-1","amount":1250,"currency":"EUR",
  "reference":{"type":"BOOKING","id":"resa_1"},"source_service":"booking"}'

# poll (repeat until status != PENDING; ~15s)
curl -s localhost:8000/payments/<payment_id>
```

Run tests:

```bash
pytest -q
```

## Configuration (env vars, prefix `PAYMENT_`)

| var | default | meaning |
|---|---|---|
| `PAYMENT_PENDING_DELAY_SECONDS` | `15` | how long a transaction stays PENDING |
| `PAYMENT_FAILURE_RATE` | `0.05` | share of simulated refusals |
| `PAYMENT_MAX_ATTEMPTS` | `2` | transactions per request (1 initial + 1 retry) |

## Deployment (Render)

`render.yaml` (blueprint) defines a free Python web service:

- build: `pip install -r requirements.txt`
- start: `uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT --workers 1`
- health check: `/health`

Push the repo to GitHub, then in Render: **New → Blueprint** and point it at the repo.

> **Single worker only** — the in-memory store and the async resolution tasks live in the
> process. Persistence (Postgres) is the next step and lifts this constraint.
