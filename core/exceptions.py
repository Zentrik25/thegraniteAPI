import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("core.exceptions")

_CODE_MAP: dict[type, str] = {
    NotAuthenticated:        "authentication_required",
    AuthenticationFailed:    "authentication_failed",
    PermissionDenied:        "permission_denied",
    DjangoPermissionDenied:  "permission_denied",
    NotFound:                "not_found",
    Http404:                 "not_found",
    Throttled:               "rate_limit_exceeded",
    ValidationError:         "validation_error",
}


def structured_exception_handler(exc, context) -> Response:
    response = exception_handler(exc, context)

    if response is None:
        logger.exception("Unhandled exception: %s", exc)
        return Response(
            {
                "status":  "error",
                "code":    "internal_server_error",
                "message": "An unexpected error occurred. Our engineers have been notified.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    request    = context.get("request")
    request_id = getattr(request, "request_id", None)
    code       = _CODE_MAP.get(type(exc), "error")

    errors  = None
    message = _get_message(exc)

    if isinstance(exc, ValidationError):
        errors  = _flatten_errors(exc.detail)
        message = "Validation failed. Please correct the errors below."

    body: dict = {
        "status":  "error",
        "code":    code,
        "message": message,
    }

    if errors:
        body["errors"] = errors
    if request_id:
        body["request_id"] = request_id
    if isinstance(exc, Throttled) and exc.wait is not None:
        body["retry_after_seconds"] = max(1, int(exc.wait))

    response.data = body
    return response


class ArticleNotPublished(APIException):
    status_code  = status.HTTP_403_FORBIDDEN
    default_code = "article_not_published"
    default_detail = "This article is not yet published."


class SlotOccupied(APIException):
    status_code  = status.HTTP_409_CONFLICT
    default_code = "slot_occupied"
    default_detail = "This top story slot is already occupied by another article."


class InsufficientRole(APIException):
    status_code  = status.HTTP_403_FORBIDDEN
    default_code = "insufficient_role"
    default_detail = "Your editorial role does not permit this action."


def _get_message(exc) -> str:
    detail = getattr(exc, "detail", None)
    if detail is None:
        return str(exc) or "An error occurred."
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:
        return str(detail[0])
    if isinstance(detail, dict):
        for errors in detail.values():
            if isinstance(errors, list) and errors:
                return str(errors[0])
            if isinstance(errors, str):
                return errors
    return str(detail)


def _flatten_errors(detail, prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}

    if isinstance(detail, dict):
        for field, errors in detail.items():
            key = f"{prefix}.{field}" if prefix else field
            if isinstance(errors, list):
                if errors:
                    flat[key] = str(errors[0])
            elif isinstance(errors, dict):
                flat.update(_flatten_errors(errors, prefix=key))
            else:
                flat[key] = str(errors)

    elif isinstance(detail, list):
        for i, item in enumerate(detail):
            key = f"{prefix}[{i}]" if prefix else f"[{i}]"
            if isinstance(item, dict):
                flat.update(_flatten_errors(item, prefix=key))
            elif item:
                flat[prefix or "non_field_errors"] = str(item)

    return flat
