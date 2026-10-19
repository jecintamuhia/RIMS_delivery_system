"""Password hashing and session handling.

Sessions are server-signed, httpOnly cookies (the browser never holds a token in JS). CSRF is
handled with a double-submit token because the cookie is sent automatically by the browser:
without it, any origin could POST to the admin API using the customer's ambient session.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import get_settings

logger = logging.getLogger("app.security")

#: OWASP-recommended Argon2id parameters (19 MiB memory, 2 iterations, parallelism 1).
_hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1, hash_len=32, salt_len=16)


def hash_password(plaintext: str) -> str:
    if not plaintext:
        raise ValueError("password must not be empty")
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, password_hash: str) -> bool:
    """Constant-time-ish verification. A malformed stored hash is a failure, not an exception."""
    try:
        _hasher.verify(password_hash, plaintext)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:  # pragma: no cover - defensive: never leak a 500 on a login path
        logger.warning("password verification raised; treating as failed login")
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


# ── session payload ────────────────────────────────────────────────────────────────


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def sign_payload(payload: str) -> str:
    settings = get_settings()
    return _sign(payload, settings.effective_session_secret)


def unsign_payload(signed: str, max_age_seconds: int | None = None) -> str | None:
    settings = get_settings()
    age = settings.session_max_age_seconds if max_age_seconds is None else max_age_seconds
    try:
        return _unsign(signed, settings.effective_session_secret, age)
    except SignatureError:
        return None


class SignatureError(Exception):
    pass


def _sign(payload: str, secret: str) -> str:
    from itsdangerous import URLSafeSerializer

    return URLSafeSerializer(secret, salt="rims.session").dumps(payload)


def _unsign(signed: str, secret: str, max_age_seconds: int) -> str:
    from itsdangerous import BadSignature, SignatureExpired, URLSafeSerializer

    serializer = URLSafeSerializer(secret, salt="rims.session")
    try:
        result = serializer.loads(signed, max_age=max_age_seconds)
    except SignatureExpired as exc:
        raise SignatureError("expired") from exc
    except BadSignature as exc:
        raise SignatureError("invalid") from exc
    if not isinstance(result, str):
        raise SignatureError("unexpected payload")
    return result




def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(sent: str | None, expected: str | None) -> bool:
    if not sent or not expected:
        return False
    return hmac.compare_digest(sent, expected)




def opaque_token(length: int = 24) -> str:
    """URL-safe random token used for quote references and API correlation."""
    return secrets.token_urlsafe(length)[:length]


def stable_hash(value: str) -> str:
    """Deterministic hash for keys that must be looked up but not stored in the clear."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    return datetime.now(UTC)


def in_minutes(minutes: int) -> datetime:
    return utcnow() + timedelta(minutes=minutes)
