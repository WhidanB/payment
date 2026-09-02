"""Domain enumerations."""

from __future__ import annotations

from enum import Enum


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REFUSED = "REFUSED"


class PaymentStatus(str, Enum):
    """Aggregate status of a payment request (MVP keeps the three outcomes)."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REFUSED = "REFUSED"


class ReferenceType(str, Enum):
    """What the payment pays for."""

    BOOKING = "BOOKING"
    PARKING_EXIT = "PARKING_EXIT"


class SourceService(str, Enum):
    BOOKING = "booking"
    ACCESS = "access"
