"""
tasks.py — Celery tasks for reader account emails.

These are stubs: no email is sent in this phase.  Each task logs the URL
that would be included in the email so the flow can be verified manually.
Replace the logger.info calls with your email provider's send call when
the email phase is implemented.
"""

import logging

from celery import shared_task

logger = logging.getLogger("accounts.tasks")

_FRONTEND_BASE_URL = "https://thegranite.co.zw"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_verification_email(self, reader_id: str) -> None:
    """
    Queue a verification email for a newly registered reader.

    Constructs the verification URL from the reader's
    email_verification_token and logs it.  In production, replace the
    log call with an email send via your chosen provider (e.g. Mailgun,
    SES, Resend).

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

    verify_url = (
        f"{_FRONTEND_BASE_URL}/verify-email"
        f"?token={reader.email_verification_token}"
    )

    logger.info(
        "[STUB] Verification email → %s  URL: %s",
        reader.email,
        verify_url,
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_email(self, reader_id: str) -> None:
    """
    Queue a password reset email for a reader who requested one.

    Constructs the reset URL from the reader's password_reset_token and
    logs it.  In production, replace the log call with a real email send.

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

    reset_url = (
        f"{_FRONTEND_BASE_URL}/reset-password"
        f"?token={reader.password_reset_token}"
    )

    logger.info(
        "[STUB] Password reset email → %s  URL: %s",
        reader.email,
        reset_url,
    )
