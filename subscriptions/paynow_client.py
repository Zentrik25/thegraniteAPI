"""
paynow_client.py — Paynow Zimbabwe payment gateway wrapper.

Wraps the ``paynow`` Python package to provide a clean interface for:
  - Mobile money payments (EcoCash, OneMoney) via initiate_mobile_payment()
  - Web / bank card payments via initiate_web_payment()
  - Payment status polling via check_payment_status()

All amounts are in USD. ZWL/ZIG are never used.

Environment variables required (set in settings.py):
  PAYNOW_INTEGRATION_ID  — Paynow merchant integration ID
  PAYNOW_INTEGRATION_KEY — Paynow merchant integration key
  PAYNOW_RETURN_URL      — URL reader is redirected to after web payment
  PAYNOW_RESULT_URL      — Paynow posts payment status to this URL (webhook)
"""

import hashlib
import hmac
import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger("subscriptions.paynow_client")

PAYMENT_INITIATION_ERROR = "Unable to initiate payment right now. Please try again."
PAYMENT_STATUS_ERROR = "Unable to verify payment status right now. Please refresh and try again."

# ---------------------------------------------------------------------------
# Callback hash verification
# ---------------------------------------------------------------------------

# Paynow's result-URL POST always includes these fields in this order,
# followed by the merchant integration key (lowercased).  The hash is
# SHA-512 of their concatenated string values (hash field excluded).
_CALLBACK_HASH_FIELDS = ("reference", "paynowreference", "amount", "status", "pollurl")


def verify_paynow_callback_hash(post_data: dict, integration_key: str) -> bool:
    """
    Verify the SHA-512 hash that Paynow includes in every result-URL POST.

    Algorithm (mirrors Paynow SDK's private __hash / __verify_hash methods):
      1. Concatenate the string value of each callback field in the documented
         order, skipping the ``hash`` field itself.
      2. Append the integration key in lowercase.
      3. SHA-512 the UTF-8-encoded result, uppercase hex.
      4. Constant-time compare with the provided hash value.

    Returns False (rather than raising) on any failure so callers always get
    a boolean they can act on immediately.
    """
    if not integration_key:
        logger.warning(
            "[Paynow] verify_callback_hash: PAYNOW_INTEGRATION_KEY is not configured"
        )
        return False

    provided = str(post_data.get("hash", "")).strip()
    if not provided:
        return False

    parts = "".join(
        str(post_data.get(field, "")) for field in _CALLBACK_HASH_FIELDS
    )
    parts += integration_key.lower()

    expected = hashlib.sha512(parts.encode("utf-8")).hexdigest().upper()
    return hmac.compare_digest(provided.upper(), expected)


class PaynowClient:
    """
    Thin wrapper around the ``paynow`` Python SDK.

    Reads PAYNOW_INTEGRATION_ID and PAYNOW_INTEGRATION_KEY from settings.
    All monetary values passed to Paynow are in USD.

    Methods never raise — exceptions are caught and returned as error dicts
    so callers can handle failures gracefully without try/except boilerplate.
    """

    def __init__(self) -> None:
        """Initialise Paynow client from Django settings."""
        from paynow import Paynow  # type: ignore[import]

        integration_id  = settings.PAYNOW_INTEGRATION_ID
        integration_key = settings.PAYNOW_INTEGRATION_KEY
        return_url      = settings.PAYNOW_RETURN_URL
        result_url      = settings.PAYNOW_RESULT_URL

        self._paynow = Paynow(integration_id, integration_key, return_url, result_url)

    # ------------------------------------------------------------------
    # Mobile money (EcoCash / OneMoney)
    # ------------------------------------------------------------------

    def initiate_mobile_payment(
        self,
        amount_usd: float,
        phone: str,
        email: str,
        reference: str,
        payment_method: str = "ecocash",
    ) -> dict[str, Any]:
        """
        Initiate a mobile money payment (EcoCash or OneMoney).

        Args:
            amount_usd:     Amount to charge in USD (e.g. 2.00).
            phone:          Reader's mobile number in Zimbabwean format (07xx or 263xx).
            email:          Reader's email address for the Paynow payment record.
            reference:      Unique merchant reference string (e.g. "sub-<uuid>").
            payment_method: "ECOCASH" or "ONEMONEY" — controls the Paynow provider
                            string sent to the gateway. Defaults to EcoCash.

        Returns:
            dict with keys:
              ok (bool)         — True if Paynow accepted the payment
              reference (str)   — Paynow transaction reference
              poll_url (str)    — URL to poll for payment status
              redirect_url (str)— empty for mobile payments
              error (str)       — populated only when ok=False
        """
        provider = "onemoney" if payment_method.upper() == "ONEMONEY" else "ecocash"
        logger.info(
            "[Paynow] Mobile payment initiated: provider=%s amount_usd=%.2f",
            provider,
            amount_usd,
        )
        try:
            payment = self._paynow.create_payment(reference, email)
            payment.add("Granite Post Subscription", float(amount_usd))

            response = self._paynow.send_mobile(payment, phone, provider)

            if response.success:
                logger.info(
                    "[Paynow] Mobile payment accepted: provider=%s",
                    provider,
                )
                return {
                    "ok":           True,
                    "reference":    response.paynow_reference or "",
                    "poll_url":     response.poll_url or "",
                    "redirect_url": "",
                    "error":        "",
                }

            logger.warning(
                "[Paynow] Mobile payment rejected: provider=%s",
                provider,
            )
            return {
                "ok":           False,
                "reference":    "",
                "poll_url":     "",
                "redirect_url": "",
                "error":        PAYMENT_INITIATION_ERROR,
            }

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[Paynow] Mobile payment exception: provider=%s exc_type=%s",
                provider,
                type(exc).__name__,
            )
            return {
                "ok":           False,
                "reference":    "",
                "poll_url":     "",
                "redirect_url": "",
                "error":        PAYMENT_INITIATION_ERROR,
            }

    # ------------------------------------------------------------------
    # Web / bank card
    # ------------------------------------------------------------------

    def initiate_web_payment(
        self,
        amount_usd: float,
        email: str,
        reference: str,
        return_url: str = "",
    ) -> dict[str, Any]:
        """
        Initiate a web (bank card) payment via Paynow's hosted checkout.

        Args:
            amount_usd:  Amount in USD.
            email:       Reader's email for the Paynow record.
            reference:   Unique merchant reference (e.g. "sub-<uuid>").
            return_url:  Override the global PAYNOW_RETURN_URL for this payment.

        Returns:
            dict with keys:
              ok (bool)         — True if Paynow accepted
              reference (str)   — Paynow transaction reference
              poll_url (str)    — URL to poll for status
              redirect_url (str)— URL to redirect the reader to
              error (str)       — populated only when ok=False
        """
        logger.info(
            "[Paynow] Web payment initiated: amount_usd=%.2f",
            amount_usd,
        )
        try:
            if return_url:
                self._paynow.return_url = return_url

            payment = self._paynow.create_payment(reference, email)
            payment.add("Granite Post Subscription", float(amount_usd))

            response = self._paynow.send(payment)

            if response.success:
                logger.info(
                    "[Paynow] Web payment accepted.",
                )
                return {
                    "ok":           True,
                    "reference":    response.paynow_reference or "",
                    "poll_url":     response.poll_url or "",
                    "redirect_url": response.redirect_url or "",
                    "error":        "",
                }

            logger.warning("[Paynow] Web payment rejected.")
            return {
                "ok":           False,
                "reference":    "",
                "poll_url":     "",
                "redirect_url": "",
                "error":        PAYMENT_INITIATION_ERROR,
            }

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[Paynow] Web payment exception: exc_type=%s",
                type(exc).__name__,
            )
            return {
                "ok":           False,
                "reference":    "",
                "poll_url":     "",
                "redirect_url": "",
                "error":        PAYMENT_INITIATION_ERROR,
            }

    # ------------------------------------------------------------------
    # Status polling
    # ------------------------------------------------------------------

    def check_payment_status(self, poll_url: str) -> dict[str, Any]:
        """
        Poll Paynow to check whether a payment has been confirmed.

        Args:
            poll_url: The poll URL returned during payment initiation.

        Returns:
            dict with keys:
              ok (bool)       — True if Paynow responded successfully
              paid (bool)     — True if the payment is confirmed complete
              reference (str) — Paynow transaction reference
              amount (float)  — Amount confirmed (USD)
              status (str)    — Raw Paynow status string
              error (str)     — populated only when ok=False
        """
        logger.info("[Paynow] Polling payment status.")
        try:
            status_response = self._paynow.check_transaction_status(poll_url)

            paid = getattr(status_response, "paid", False)
            reference = getattr(status_response, "paynow_reference", "") or ""
            amount = getattr(status_response, "amount", 0.0) or 0.0
            raw_status = getattr(status_response, "status", "") or ""

            logger.info(
                "[Paynow] Poll result: paid=%s status=%s",
                paid,
                raw_status,
            )
            return {
                "ok":        True,
                "paid":      bool(paid),
                "reference": str(reference),
                "amount":    float(amount),
                "status":    str(raw_status),
                "error":     "",
            }

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[Paynow] Poll exception: exc_type=%s",
                type(exc).__name__,
            )
            return {
                "ok":        False,
                "paid":      False,
                "reference": "",
                "amount":    0.0,
                "status":    "",
                "error":     PAYMENT_STATUS_ERROR,
            }
