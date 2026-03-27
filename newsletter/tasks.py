import logging

from celery import shared_task

logger = logging.getLogger("newsletter.tasks")


@shared_task(
    queue="slow",
    ignore_result=True,
    name="newsletter.tasks.send_confirmation_email",
)
def send_confirmation_email(subscriber_id: int) -> None:
    """
    Send a confirmation email to a new subscriber.

    Placeholder — implement with your email provider when ready.
    Supported providers: SendGrid, Brevo, Django SMTP backend.

    The confirmation URL format:
        https://thegranite.co.zw/newsletter/confirm/?token=<uuid>
    or via API:
        GET /api/v1/newsletter/confirm/?token=<uuid>
    """
    try:
        from .models import Subscriber
        subscriber = Subscriber.objects.get(pk=subscriber_id)

        confirmation_url = (
            f"https://thegranite.co.zw/api/v1/newsletter/confirm/"
            f"?token={subscriber.confirmation_token}"
        )

        logger.info(
            "STUB — confirmation email for %s: %s",
            subscriber.email,
            confirmation_url,
        )

    except Exception as exc:
        logger.error(
            "Failed to send confirmation email for subscriber_id=%s: %s",
            subscriber_id,
            exc,
        )


@shared_task(
    queue="slow",
    ignore_result=True,
    name="newsletter.tasks.send_welcome_email",
)
def send_welcome_email(subscriber_id: int) -> None:
    """
    Send a welcome email after a subscriber confirms.
    Placeholder — implement with your email provider when ready.
    """
    try:
        from .models import Subscriber
        subscriber = Subscriber.objects.get(pk=subscriber_id)
        logger.info(
            "STUB — welcome email for %s",
            subscriber.email,
        )
    except Exception as exc:
        logger.error(
            "Failed to send welcome email for subscriber_id=%s: %s",
            subscriber_id,
            exc,
        )
