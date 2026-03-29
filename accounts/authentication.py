"""
authentication.py — JWT token classes and authentication backend for readers.

Reader tokens are SEPARATE from staff tokens:
  - Reader access  tokens have ``token_type = "reader_access"``
  - Reader refresh tokens have ``token_type = "reader_refresh"``
  - Both carry a ``reader_id`` UUID claim instead of ``user_id``

Staff endpoints use the standard JWTAuthentication which validates
``token_type = "access"`` and reads ``user_id``.  It will reject reader
tokens because the token_type mismatch causes TokenError.

Reader endpoints use ReaderJWTAuthentication which validates
``token_type = "reader_access"`` and reads ``reader_id``.  It will reject
staff tokens for the same reason.

Usage in views:
    authentication_classes = [ReaderJWTAuthentication]
"""

import logging
from datetime import timedelta

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import Token

logger = logging.getLogger("accounts.authentication")

_ACCESS_LIFETIME  = timedelta(minutes=60)
_REFRESH_LIFETIME = timedelta(days=30)


class ReaderAccessToken(Token):
    """Short-lived access token for reader accounts. Valid for 60 minutes."""

    token_type = "reader_access"
    lifetime   = _ACCESS_LIFETIME


class ReaderRefreshToken(Token):
    """Long-lived refresh token for reader accounts. Valid for 30 days."""

    token_type = "reader_refresh"
    lifetime   = _REFRESH_LIFETIME


def get_tokens_for_reader(reader) -> dict:
    """
    Generate a JWT access + refresh token pair for *reader*.

    Both tokens carry a ``reader_id`` claim (UUID string).
    Returns a dict with ``access`` and ``refresh`` keys.
    """
    refresh = ReaderRefreshToken()
    refresh["reader_id"] = str(reader.id)

    access = ReaderAccessToken()
    access["reader_id"] = str(reader.id)

    return {
        "access":  str(access),
        "refresh": str(refresh),
    }


class ReaderJWTAuthentication(JWTAuthentication):
    """
    DRF authentication backend for reader accounts.

    Validates ``reader_access`` JWTs and resolves the ``reader_id`` claim
    to a ReaderAccount instance.  Staff access tokens are rejected because
    their token_type is ``"access"``, not ``"reader_access"``.
    """

    def get_validated_token(self, raw_token):
        """Parse and verify *raw_token* as a ReaderAccessToken."""
        try:
            return ReaderAccessToken(raw_token)
        except TokenError as exc:
            raise InvalidToken(
                {
                    "detail":   "Reader access token is invalid or expired.",
                    "messages": [str(exc)],
                }
            ) from exc

    def get_user(self, validated_token):
        """Resolve ``reader_id`` claim to an active ReaderAccount."""
        reader_id = validated_token.get("reader_id")
        if not reader_id:
            raise InvalidToken("Token does not contain a reader_id claim.")

        from .models import ReaderAccount

        try:
            return ReaderAccount.objects.get(id=reader_id, is_active=True)
        except ReaderAccount.DoesNotExist:
            raise InvalidToken("Reader account not found or has been deactivated.")
