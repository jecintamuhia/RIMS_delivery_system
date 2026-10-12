"""Domain error taxonomy and the public HTTP error envelope.

Every deliberate failure state in the system is an :class:`AppError`. The API layer turns
one into ``{"code", "message", "details"}``, which is the exact envelope ``rims-delivery-ui``
parses in ``src/services/api/client.ts``. Internal exceptions never reach a customer.
"""

from __future__ import annotations

from typing import Any


class ErrorCode:
    """Stable machine-readable codes. These are part of the public API contract."""

    INVALID_LOCATION = "INVALID_LOCATION"
    LOCATION_NOT_FOUND = "LOCATION_NOT_FOUND"
    AMBIGUOUS_LOCATION = "AMBIGUOUS_LOCATION"
    ROUTING_UNAVAILABLE = "ROUTING_UNAVAILABLE"
    DESTINATION_UNSUPPORTED = "DESTINATION_UNSUPPORTED"
    NO_PRICING_RULE = "NO_PRICING_RULE"
    ROAD_TYPE_REQUIRED = "ROAD_TYPE_REQUIRED"
    VEHICLE_REQUIRED = "VEHICLE_REQUIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    NETWORK = "NETWORK"
    SERVER = "SERVER"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION = "VALIDATION"
    UNKNOWN = "UNKNOWN"


#: Customer-facing default wording. Kept here (not in the database) because these describe
#: system behaviour, not RIMs business data. Admins can override per-error text via settings.
DEFAULT_MESSAGES: dict[str, str] = {
    ErrorCode.INVALID_LOCATION: (
        "We couldn't identify that location. Please search again or select a location on the map."
    ),
    ErrorCode.LOCATION_NOT_FOUND: (
        "We couldn't identify that location. Please search again or select a location on the map."
    ),
    ErrorCode.AMBIGUOUS_LOCATION: "More than one place matches that search. Please choose the right one.",
    ErrorCode.ROUTING_UNAVAILABLE: "We couldn't calculate the road distance right now. Please try again.",
    ErrorCode.DESTINATION_UNSUPPORTED: (
        "This delivery location is not currently covered by the configured RIMs delivery pricing."
    ),
    ErrorCode.NO_PRICING_RULE: (
        "We found the location, but no delivery price has been configured for this destination. "
        "Please contact RIMs for a quotation."
    ),
    ErrorCode.ROAD_TYPE_REQUIRED: "We need the road type for this route before we can price it. Please contact RIMs.",
    ErrorCode.VEHICLE_REQUIRED: "We need the vehicle for this delivery before we can price it. Please contact RIMs.",
    ErrorCode.MANUAL_REVIEW: "This delivery needs a quotation from RIMs. Please contact us and we'll price it for you.",
    ErrorCode.NETWORK: "We couldn't reach the server. Please check your connection and try again.",
    ErrorCode.SERVER: "Something went wrong on our side. Please try again in a moment.",
    ErrorCode.SESSION_EXPIRED: "Your session has expired. Please sign in again.",
    ErrorCode.INVALID_CREDENTIALS: "That email address and password don't match our records.",
    ErrorCode.FORBIDDEN: "You don't have permission to do that.",
    ErrorCode.NOT_FOUND: "We couldn't find what you were looking for.",
    ErrorCode.VALIDATION: "Please check the details you entered.",
    ErrorCode.UNKNOWN: "Something went wrong. Please try again.",
}

#: Canonical HTTP status per code. Anything absent is treated as an internal bug.
STATUS_BY_CODE: dict[str, int] = {
    ErrorCode.INVALID_LOCATION: 422,
    ErrorCode.LOCATION_NOT_FOUND: 422,
    ErrorCode.AMBIGUOUS_LOCATION: 422,
    ErrorCode.ROUTING_UNAVAILABLE: 503,
    ErrorCode.DESTINATION_UNSUPPORTED: 422,
    ErrorCode.NO_PRICING_RULE: 422,
    ErrorCode.ROAD_TYPE_REQUIRED: 422,
    ErrorCode.VEHICLE_REQUIRED: 422,
    ErrorCode.MANUAL_REVIEW: 422,
    ErrorCode.NETWORK: 503,
    ErrorCode.SERVER: 500,
    ErrorCode.SESSION_EXPIRED: 401,
    ErrorCode.INVALID_CREDENTIALS: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.VALIDATION: 422,
    ErrorCode.UNKNOWN: 500,
}


class AppError(Exception):
    """A failure the product knows how to explain to a human.

    Raising this instead of returning a guess is how the system refuses to fabricate a price.
    """

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.message = message or DEFAULT_MESSAGES.get(code, DEFAULT_MESSAGES[ErrorCode.UNKNOWN])
        self.details = details or {}
        self.status_code = status_code or STATUS_BY_CODE.get(code, 500)
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def not_found(entity: str, identifier: str | None = None) -> AppError:
    detail = f" {identifier}" if identifier else ""
    return AppError(ErrorCode.NOT_FOUND, f"{entity} not found{detail}.")


def validation(message: str, **details: Any) -> AppError:
    return AppError(ErrorCode.VALIDATION, message, details=details)


def forbidden(message: str | None = None) -> AppError:
    return AppError(ErrorCode.FORBIDDEN, message)
