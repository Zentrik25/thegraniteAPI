"""
tasks.py — Celery tasks for reader account emails.

Uses Django's configured email backend so verification and password-reset
emails work in both local development (console/locmem) and production
SMTP-backed deployments.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from core.logging_utils import _mask_email

logger = logging.getLogger("accounts.tasks")


def _build_frontend_url(path: str, token) -> str:
    """Construct a tokenized frontend URL from environment-driven settings."""
    return f"{settings.FRONTEND_URL}{path}?token={token}"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_verification_email(self, reader_id: str) -> None:
    """
    Queue a verification email for a newly registered reader.

    Constructs the verification URL from the reader's
    email_verification_token and sends it through Django's email backend.

    Args:
        reader_id: UUID string of the ReaderAccount.
    """
    from accounts.models import ReaderAccount

    try:
        reader = ReaderAccount.objects.get(id=reader_id)
    except ReaderAccount.DoesNotExist:
        logger.warning(
            "send_verification_email: reader_id=%s not found — skipping.",
            reader_id,
        )
        return

    verify_url = _build_frontend_url(
        "/verify-email",
        reader.email_verification_token,
    )

    try:
        send_mail(
            subject="Verify your Granite Post account",
            message=(
                "Welcome to The Granite Post.\n\n"
                "Please verify your email address by opening the link below:\n"
                f"{verify_url}\n\n"
                "If you did not create this account, you can ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[reader.email],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to send verification email: reader_id=%s email=%s error=%s",
            reader.id,
            _mask_email(reader.email),
            exc,
        )
        raise self.retry(exc=exc)

    logger.info(
        "Verification email sent: reader_id=%s email=%s",
        reader.id,
        _mask_email(reader.email),
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_email(self, reader_id: str) -> None:
    """
    Queue a password reset email for a reader who requested one.

    Constructs the reset URL from the reader's password_reset_token and
    sends it through Django's email backend.

    Args:
        reader_id: UUID string of the ReaderAccount.
    """
    from accounts.models import ReaderAccount

    try:
        reader = ReaderAccount.objects.get(id=reader_id)
    except ReaderAccount.DoesNotExist:
        logger.warning(
            "send_password_reset_email: reader_id=%s not found — skipping.",
            reader_id,
        )
        return

    if not reader.password_reset_token:
        logger.warning(
            "send_password_reset_email: reader_id=%s has no reset token — skipping.",
            reader_id,
        )
        return

    reset_url = _build_frontend_url(
        "/reset-password",
        reader.password_reset_token,
    )

    try:
        send_mail(
            subject="Reset your Granite Post password",
            message=(
                "We received a request to reset your Granite Post password.\n\n"
                "Use the link below to choose a new password:\n"
                f"{reset_url}\n\n"
                "This link expires in 1 hour. If you did not request a reset, "
                "you can ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[reader.email],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to send password reset email: reader_id=%s email=%s error=%s",
            reader.id,
            _mask_email(reader.email),
            exc,
        )
        raise self.retry(exc=exc)

    logger.info(
        "Password reset email sent: reader_id=%s email=%s",
        reader.id,
        _mask_email(reader.email),
    )
