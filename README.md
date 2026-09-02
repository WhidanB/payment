# Payment Service

Payment microservice for the "parking fil rouge" project. It receives JSON payment
requests from the **booking** and **access** services, opens **transactions** to settle
them, and reports a status: `PENDING` / `ACCEPTED` / `REFUSED`.

The payment gateway is **simulated** for now (95% accepted, 5% refused). Stripe will be
plugged in later behind the same port.

## Business model

- A **payment request** is identified by a caller-supplied **idempotency key**. Replaying the
  same key never creates a second charge — the existing request is returned as-is.
- A payment request aggregates **1..N transactions** (attempts). Each transaction is unique
  (UUID v7).
- A transaction stays `PENDING` for **15 s** (asynchronous by nature), then resolves.
- On a refusal the service automatically opens **one** retry transaction (again `PENDING` 15 s).
  If it also fails, the payment request is `REFUSED`.
- Callers get the outcome by **polling** `GET /payments/{id}`.

## Architecture

Modern hexagonal architecture — the domain core has no framework imports:

```
app/domain/       business core (models + ports)
app/application/   use-cases
app/adapters/      inbound (FastAPI) + outbound (in-memory repo, simulated gateway, scheduler)
app/container.py   composition root (swap adapters here)
```

## Run locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload
```

- Swagger UI: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

> Run with a **single worker** — state is in-memory and resolution runs as in-process
> async tasks.

## Deployment (Render)

`render.yaml` defines the web service. Connect the repository in the Render dashboard.

## API contract

_Documented in `/docs` once the HTTP layer lands._
