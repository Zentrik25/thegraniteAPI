import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger("newsletter.tasks")


def _build_newsletter_confirm_url(token) -> str:
    """Build the absolute confirmation URL using environment-driven settings."""
    return f"{settings.SITE_URL}/api/v1/newsletter/confirm/?token={token}"


@shared_task(
    queue="slow",
    ignore_result=True,
    name="newsletter.tasks.send_confirmation_email",
)
def send_confirmation_email(subscriber_id: int) -> None:
    """
    Send a confirmation email to a new subscriber.

    Uses Django's configured email backend.
    """
    try:
        from .models import Subscriber
        subscriber = Subscriber.objects.get(pk=subscriber_id)

        confirmation_url = _build_newsletter_confirm_url(
            subscriber.confirmation_token
        )

        send_mail(
            subject="Confirm your Granite Post newsletter subscription",
            message=(
                "Please confirm your Granite Post newsletter subscription by "
                "opening the link below:\n"
                f"{confirmation_url}\n\n"
                "If you did not subscribe, you can ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[subscriber.email],
            fail_silently=False,
        )
        logger.info("Newsletter confirmation email sent: email=%s", subscriber.email)

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
    """
    try:
        from .models import Subscriber
        subscriber = Subscriber.objects.get(pk=subscriber_id)
        send_mail(
            subject="Welcome to The Granite Post newsletter",
            message=(
                "Your email address has been confirmed.\n\n"
                "You are now subscribed to The Granite Post newsletter."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[subscriber.email],
            fail_silently=False,
        )
        logger.info("Newsletter welcome email sent: email=%s", subscriber.email)
    except Exception as exc:
        logger.error(
            "Failed to send welcome email for subscriber_id=%s: %s",
            subscriber_id,
            exc,
        )
