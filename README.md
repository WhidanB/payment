# Payment Service

Payment microservice for the "parking fil rouge" project. It receives JSON payment
requests from the **booking** and **access** services, opens **transactions** to settle
them, and reports a status: `PENDING` / `ACCEPTED` / `REFUSED`.

The payment gateway is **simulated** for now (95% accepted, 5% refused). Stripe will be
plugged in later behind the same port, without touching the domain.

**Live:** https://payment-xp8n.onrender.com — [Swagger](https://payment-xp8n.onrender.com/docs)
· [health](https://payment-xp8n.onrender.com/health)
(Render free tier: first request after ~15 min idle takes 30-50 s to wake).

**Calling this API from `booking` or `access`?** Start with
[docs/INTEGRATION_BOOKING_ACCESS.md](docs/INTEGRATION_BOOKING_ACCESS.md) — request
examples for both scenarios, the polling recipe, idempotency-key convention, and error
handling. Full internal state: [docs/ETAT_DU_SERVICE.md](docs/ETAT_DU_SERVICE.md).
Day-by-day progress: [JOURNAL.md](JOURNAL.md).

## Status

| | |
|---|---|
| Version | `0.1.0` (MVP, simulated gateway) |
| Deployed | yes, Render (Python 3.12.8, single worker) |
| Tests | 19 passing (`pytest -q`) |
| Auth | `X-API-Key` implemented; enforced only when `PAYMENT_API_KEY` is set on the server |
| Persistence | in-memory (lost on redeploy / sleep) |
| Next | agree the API contract with booking/access, Postgres + resume of `PENDING`, Stripe adapter |

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
app/adapters/inbound/  FastAPI routes, DTOs, X-API-Key security
app/adapters/outbound/ InMemoryPaymentRepository, SimulatedPaymentGateway, AsyncioResolutionScheduler
app/container.py       composition root  <- swap adapters here (Stripe, SQL, ...)
app/main.py            application factory
```

To plug Stripe in later: add `app/adapters/outbound/stripe_payment_gateway.py` implementing
`PaymentGateway`, and wire it in `container.py`. Nothing else changes.

## API

Base URL: `https://payment-xp8n.onrender.com`. Interactive docs: **`/docs`** (Swagger UI),
`/redoc`, `/openapi.json`.

### Authentication

Project-wide convention: every route except `/health` requires an **`X-API-Key`** header
(one key per service, shared privately, never committed). Missing or wrong key → `401`.
`/health`, `/docs`, `/redoc` and `/openapi.json` stay open; Swagger's **Authorize** button
lets you try the routes with the key. If `PAYMENT_API_KEY` is not set on the server, the
check is skipped (local dev, tests, and the transition period before a coordinated rollout).

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

- `401` — missing or invalid `X-API-Key` (when auth is enabled).
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
# create (add -H 'X-API-Key: <key>' if PAYMENT_API_KEY is set)
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

Explore the API end to end (create, replay, polling, 422/404, refusal hunt):

```bash
./scripts/requests.sh                                    # against Render
BASE_URL=http://localhost:8000 API_KEY=... ./scripts/requests.sh
```

## Configuration (env vars, prefix `PAYMENT_`)

| var | default | meaning |
|---|---|---|
| `PAYMENT_PENDING_DELAY_SECONDS` | `15` | how long a transaction stays PENDING |
| `PAYMENT_FAILURE_RATE` | `0.05` | share of simulated refusals |
| `PAYMENT_MAX_ATTEMPTS` | `2` | transactions per request (1 initial + 1 retry) |
| `PAYMENT_API_KEY` | _unset_ | shared secret expected in `X-API-Key`; unset = auth disabled. Set it in the Render dashboard (`sync: false`), never in git. |

## Deployment (Render)

`render.yaml` (blueprint) defines a free Python web service:

- Python version pinned by `.python-version` (`3.12.8`)
- build: `pip install -r requirements.txt`
- start: `uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT --workers 1`
- health check: `/health`

Push the repo to GitHub, then in Render: **New → Blueprint** and point it at the repo.
Every push to `master` redeploys automatically. To turn authentication on, add
`PAYMENT_API_KEY` in the service's **Environment** tab (coordinate with the callers first).

> **Single worker only** — the in-memory store and the async resolution tasks live in the
> process. Persistence (Postgres) is the next step and lifts this constraint.
