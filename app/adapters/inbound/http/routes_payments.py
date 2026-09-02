"""Payment endpoints — the API consumed by the `booking` and `access` services."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.adapters.inbound.http.schemas import CreatePaymentRequest, PaymentResponse
from app.application.errors import PaymentNotFound
from app.application.payment_service import PaymentService, RequestPaymentCommand
from app.container import Container
from app.domain.model.errors import InvalidPaymentRequest

router = APIRouter(prefix="/payments", tags=["payments"])


def service_dep(request: Request) -> PaymentService:
    """Pull the wired PaymentService off the app (set at startup by the lifespan)."""

    container: Container = request.app.state.container
    return container.payment_service


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    if not result.created:
        response.status_code = status.HTTP_200_OK
    return PaymentResponse.from_domain(result.payment)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return PaymentResponse.from_domain(payment)
