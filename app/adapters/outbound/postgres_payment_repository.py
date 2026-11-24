"""PostgreSQL implementation of :class:`PaymentRepository` (Neon in production).

Two tables: one row per payment request, one row per transaction (attempt). The
aggregate is always written in a single database transaction.

Neon specifics: compute scales to zero when idle and may sit behind a pooler, so the
pool keeps no idle connection for long (a suspended compute drops them) and the
prepared-statement cache is disabled.
"""

from __future__ import annotations

import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

from app.domain.model.enums import PaymentStatus, ReferenceType, SourceService, TransactionStatus
from app.domain.model.errors import IdempotencyKeyTaken
from app.domain.model.payment import PaymentReference, PaymentRequest
from app.domain.model.transaction import Transaction
from app.domain.ports.payment_repository import PaymentRepository

_SCHEMA_LOCK_ID = 718_201_604  # arbitrary, serialises schema creation across instances

SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_requests (
    id               uuid        PRIMARY KEY,
    idempotency_key  text        NOT NULL UNIQUE,
    amount           bigint      NOT NULL CHECK (amount > 0),
    currency         text        NOT NULL,
    reference_type   text        NOT NULL,
    reference_id     text        NOT NULL,
    source_service   text        NOT NULL,
    status           text        NOT NULL,
    max_attempts     integer     NOT NULL CHECK (max_attempts >= 1),
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS payment_requests_created_at_idx
    ON payment_requests (created_at DESC);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id           uuid        PRIMARY KEY,
    payment_id   uuid        NOT NULL REFERENCES payment_requests (id) ON DELETE CASCADE,
    attempt      integer     NOT NULL CHECK (attempt >= 1),
    status       text        NOT NULL,
    created_at   timestamptz NOT NULL,
    resolved_at  timestamptz,
    UNIQUE (payment_id, attempt)
);
CREATE INDEX IF NOT EXISTS payment_transactions_pending_idx
    ON payment_transactions (payment_id) WHERE status = 'PENDING';
"""

_UPSERT_PAYMENT = """
INSERT INTO payment_requests (id, idempotency_key, amount, currency, reference_type,
    reference_id, source_service, status, max_attempts, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, updated_at = EXCLUDED.updated_at
"""

_UPSERT_TRANSACTION = """
INSERT INTO payment_transactions (id, payment_id, attempt, status, created_at, resolved_at)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, resolved_at = EXCLUDED.resolved_at
"""


# libpq-only options that asyncpg would otherwise forward to the server as settings
# (and fail on). Neon's copy-paste connection string includes channel_binding=require.
_LIBPQ_ONLY_PARAMS = {"channel_binding"}


def asyncpg_dsn(dsn: str) -> str:
    parts = urlsplit(dsn)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in _LIBPQ_ONLY_PARAMS]
    return urlunsplit(parts._replace(query=urlencode(query)))


class PostgresPaymentRepository(PaymentRepository):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresPaymentRepository:
        pool = await asyncpg.create_pool(
            asyncpg_dsn(dsn),
            min_size=0,
            max_size=5,
            max_inactive_connection_lifetime=60,
            statement_cache_size=0,
            command_timeout=10,
        )
        repository = cls(pool)
        await repository.migrate()
        return repository

    async def migrate(self) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _SCHEMA_LOCK_ID)
            await conn.execute(SCHEMA)

    async def ping(self) -> bool:
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT 1") == 1

    async def close(self) -> None:
        await self._pool.close()

    # -- PaymentRepository -------------------------------------------------------

    async def save(self, payment: PaymentRequest) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            try:
                await conn.execute(
                    _UPSERT_PAYMENT,
                    uuid.UUID(payment.id),
                    payment.idempotency_key,
                    payment.amount,
                    payment.currency,
                    payment.reference.type.value,
                    payment.reference.id,
                    payment.source_service.value,
                    payment.status.value,
                    payment.max_attempts,
                    payment.created_at,
                    payment.updated_at,
                )
            except asyncpg.UniqueViolationError as exc:
                raise IdempotencyKeyTaken(payment.idempotency_key) from exc
            await conn.executemany(
                _UPSERT_TRANSACTION,
                [
                    (
                        uuid.UUID(t.id),
                        uuid.UUID(payment.id),
                        t.attempt,
                        t.status.value,
                        t.created_at,
                        t.resolved_at,
                    )
                    for t in payment.transactions
                ],
            )

    async def get(self, payment_id: str) -> PaymentRequest | None:
        try:
            key = uuid.UUID(payment_id)
        except ValueError:
            return None
        found = await self._load("WHERE id = $1", key)
        return found[0] if found else None

    async def find_by_idempotency_key(self, idempotency_key: str) -> PaymentRequest | None:
        found = await self._load("WHERE idempotency_key = $1", idempotency_key)
        return found[0] if found else None

    async def list_recent(self, limit: int) -> list[PaymentRequest]:
        return await self._load("ORDER BY created_at DESC, id DESC LIMIT $1", limit)

    async def find_with_pending_transactions(self) -> list[PaymentRequest]:
        return await self._load(
            "WHERE id IN (SELECT payment_id FROM payment_transactions WHERE status = 'PENDING')"
            " ORDER BY created_at"
        )

    # -- mapping -------------------------------------------------------------------

    async def _load(self, clause: str, *args) -> list[PaymentRequest]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(f"SELECT * FROM payment_requests {clause}", *args)
            if not rows:
                return []
            tx_rows = await conn.fetch(
                "SELECT * FROM payment_transactions WHERE payment_id = ANY($1::uuid[])"
                " ORDER BY payment_id, attempt",
                [r["id"] for r in rows],
            )
        by_payment: dict[uuid.UUID, list[Transaction]] = {}
        for t in tx_rows:
            by_payment.setdefault(t["payment_id"], []).append(
                Transaction(
                    id=str(t["id"]),
                    payment_id=str(t["payment_id"]),
                    attempt=t["attempt"],
                    status=TransactionStatus(t["status"]),
                    created_at=t["created_at"],
                    resolved_at=t["resolved_at"],
                )
            )
        return [
            PaymentRequest(
                id=str(r["id"]),
                idempotency_key=r["idempotency_key"],
                amount=r["amount"],
                currency=r["currency"],
                reference=PaymentReference(ReferenceType(r["reference_type"]), r["reference_id"]),
                source_service=SourceService(r["source_service"]),
                max_attempts=r["max_attempts"],
                status=PaymentStatus(r["status"]),
                transactions=by_payment.get(r["id"], []),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]
