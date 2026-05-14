"""
tasks.py — Celery tasks for reader account emails.

Sends transactional emails via Django's configured email backend
(SendGrid SMTP relay in production, console in dev).
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from core.logging_utils import _mask_email

logger = logging.getLogger("accounts.tasks")


def _build_frontend_url(path: str, token) -> str:
    return f"{settings.FRONTEND_URL}{path}?token={token}"


def _send_html_email(*, subject: str, to: str, text_body: str, html_body: str) -> None:
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


# ---------------------------------------------------------------------------
# Email HTML templates
# ---------------------------------------------------------------------------

def _verification_email_html(code: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Georgia,'Times New Roman',serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;max-width:600px;width:100%;">
        <tr>
          <td style="background:#981b1e;padding:28px 40px;">
            <p style="margin:0;color:#fff;font-size:22px;font-weight:700;letter-spacing:-0.5px;">The Granite Post</p>
          </td>
        </tr>
        <tr>
          <td style="padding:40px;">
            <h1 style="margin:0 0 16px;font-size:24px;color:#181411;">Verify your email address</h1>
            <p style="margin:0 0 24px;font-size:15px;line-height:1.7;color:#555;">
              Welcome to The Granite Post. Enter the code below on the verification page to activate your account.
              This code expires in <strong>1 hour</strong>.
            </p>
            <div style="background:#f8f5f0;border:2px solid #981b1e;border-radius:8px;padding:24px 40px;text-align:center;margin:0 0 32px;">
              <p style="margin:0 0 8px;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#888;">Your verification code</p>
              <p style="margin:0;font-size:40px;font-weight:700;letter-spacing:10px;color:#981b1e;font-family:monospace;">{code}</p>
            </div>
            <p style="margin:0;font-size:13px;color:#aaa;">
              If you did not create a Granite Post account you can safely ignore this email.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f5f5f5;padding:20px 40px;border-top:1px solid #e8e8e8;">
            <p style="margin:0;font-size:12px;color:#aaa;">
              &copy; The Granite Post &nbsp;·&nbsp; <a href="https://www.thegranite.co.zw" style="color:#981b1e;text-decoration:none;">thegranite.co.zw</a>
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _reset_email_html(reset_url: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Georgia,'Times New Roman',serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;max-width:600px;width:100%;">
        <tr>
          <td style="background:#981b1e;padding:28px 40px;">
            <p style="margin:0;color:#fff;font-size:22px;font-weight:700;letter-spacing:-0.5px;">The Granite Post</p>
          </td>
        </tr>
        <tr>
          <td style="padding:40px;">
            <h1 style="margin:0 0 16px;font-size:24px;color:#181411;">Reset your password</h1>
            <p style="margin:0 0 24px;font-size:15px;line-height:1.7;color:#555;">
              We received a request to reset your password. Click the button below to choose a new one.
              This link expires in <strong>1 hour</strong>.
            </p>
            <table cellpadding="0" cellspacing="0" style="margin:0 0 32px;">
              <tr>
                <td style="background:#981b1e;border-radius:6px;">
                  <a href="{reset_url}"
                     style="display:inline-block;padding:14px 32px;color:#fff;font-size:15px;font-weight:700;text-decoration:none;letter-spacing:-0.2px;">
                    Reset password
                  </a>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 8px;font-size:13px;color:#888;">Or copy and paste this link into your browser:</p>
            <p style="margin:0 0 32px;font-size:12px;color:#981b1e;word-break:break-all;">{reset_url}</p>
            <p style="margin:0;font-size:13px;color:#aaa;">
              If you did not request a password reset you can safely ignore this email.
              Your password will not change.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f5f5f5;padding:20px 40px;border-top:1px solid #e8e8e8;">
            <p style="margin:0;font-size:12px;color:#aaa;">
              &copy; The Granite Post &nbsp;·&nbsp; <a href="https://www.thegranite.co.zw" style="color:#981b1e;text-decoration:none;">thegranite.co.zw</a>
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_verification_email(self, reader_id: str) -> None:
    from accounts.models import ReaderAccount

    try:
        reader = ReaderAccount.objects.get(id=reader_id)
    except ReaderAccount.DoesNotExist:
        logger.warning("send_verification_email: reader_id=%s not found — skipping.", reader_id)
        return

    code = reader.email_verification_token

    try:
        _send_html_email(
            subject="Your Granite Post verification code",
            to=reader.email,
            text_body=(
                "Welcome to The Granite Post.\n\n"
                f"Your email verification code is: {code}\n\n"
                "Enter this code on the verification page to activate your account.\n"
                "This code expires in 1 hour.\n\n"
                "If you did not create this account, you can ignore this email."
            ),
            html_body=_verification_email_html(code),
        )
    except Exception as exc:
        logger.error(
            "Failed to send verification email: reader_id=%s email=%s error=%s",
            reader.id, _mask_email(reader.email), exc,
        )
        # In eager mode (CELERY_TASK_ALWAYS_EAGER=True) retries execute
        # synchronously with no delay, blocking the HTTP request for
        # max_retries * EMAIL_TIMEOUT seconds.  Log and return instead.
        if self.request.is_eager:
            return
        raise self.retry(exc=exc)

    logger.info("Verification email sent: reader_id=%s email=%s", reader.id, _mask_email(reader.email))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_email(self, reader_id: str) -> None:
    from accounts.models import ReaderAccount

    try:
        reader = ReaderAccount.objects.get(id=reader_id)
    except ReaderAccount.DoesNotExist:
        logger.warning("send_password_reset_email: reader_id=%s not found — skipping.", reader_id)
        return

    if not reader.password_reset_token:
        logger.warning("send_password_reset_email: reader_id=%s has no reset token — skipping.", reader_id)
        return

    reset_url = _build_frontend_url("/reset-password", reader.password_reset_token)

    try:
        _send_html_email(
            subject="Reset your Granite Post password",
            to=reader.email,
            text_body=(
                "We received a request to reset your Granite Post password.\n\n"
                "Use the link below to choose a new password:\n"
                f"{reset_url}\n\n"
                "This link expires in 1 hour. If you did not request a reset, "
                "you can ignore this email."
            ),
            html_body=_reset_email_html(reset_url),
        )
    except Exception as exc:
        logger.error(
            "Failed to send password reset email: reader_id=%s email=%s error=%s",
            reader.id, _mask_email(reader.email), exc,
        )
        if self.request.is_eager:
            return
        raise self.retry(exc=exc)

    logger.info("Password reset email sent: reader_id=%s email=%s", reader.id, _mask_email(reader.email))
