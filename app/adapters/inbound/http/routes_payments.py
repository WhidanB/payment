"""Payment endpoints — the API consumed by the `booking` and `access` services."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.adapters.inbound.http.schemas import CreatePaymentRequest, PaymentResponse
from app.adapters.inbound.http.security import require_api_key
from app.application.errors import PaymentNotFound
from app.application.payment_service import PaymentService, RequestPaymentCommand
from app.container import Container
from app.domain.model.errors import IdempotencyConflict, InvalidPaymentRequest

router = APIRouter(
    prefix="/payments",
    tags=["payments"],
    dependencies=[Depends(require_api_key)],
    responses={401: {"description": "Missing or invalid X-API-Key"}},
)


def service_dep(request: Request) -> PaymentService:
    """Pull the wired PaymentService off the app (set at startup by the lifespan)."""

    container: Container = request.app.state.container
    return container.payment_service


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        200: {"description": "Idempotent replay: the existing request is returned unchanged"},
        409: {"description": "idempotency_key already used with a different payload"},
        422: {"description": "Invalid body (amount, currency, reference, source_service, key)"},
    },
    summary="Request a payment",
    description=(
        "Opens a payment request and its first transaction (PENDING). The transaction "
        "resolves asynchronously after ~15s. Poll `GET /payments/{id}` for the outcome. "
        "Replaying a known idempotency key returns the existing request with status 200."
    ),
)
async def create_payment(
    body: CreatePaymentRequest,
    response: Response,
    service: PaymentService = Depends(service_dep),
) -> PaymentResponse:
    command = RequestPaymentCommand(
        idempotency_key=body.idempotency_key,
        amount=body.amount,
        currency=body.currency,
        reference=body.reference.to_domain(),
        source_service=body.source_service,
    )
    try:
        result = await service.request_payment(command)
    except InvalidPaymentRequest as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if not result.created:
        response.status_code = status.HTTP_200_OK
    return PaymentResponse.from_domain(result.payment)


@router.get(
    "",
    response_model=list[PaymentResponse],
    summary="List recent payment requests",
    description="Most recent first. Used by the operations UI (/ui) to observe the service.",
)
async def list_payments(
    limit: int = Query(50, ge=1, le=200),
    service: PaymentService = Depends(service_dep),
) -> list[PaymentResponse]:
    return [PaymentResponse.from_domain(p) for p in await service.list_payments(limit)]


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    summary="Get a payment request",
    description="Returns the aggregate status and every transaction attached to the request.",
)
async def get_payment(
    payment_id: str,
    service: PaymentService = Depends(service_dep),
) -> PaymentResponse:
    try:
        payment = await service.get_payment(payment_id)
    except PaymentNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PaymentResponse.from_domain(payment)
