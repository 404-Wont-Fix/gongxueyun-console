"""Password hashing, JWT sessions and secret-at-rest encryption.

* passwords: scrypt (stdlib) — no bcrypt/passlib version dance;
* tokens: HS256 JWT with an explicit expiry;
* stored secrets: Fernet with a key derived from ``APP_SECRET``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from .settings import get_settings

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_ENC_PREFIX = "enc$"


# ----------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise ValueError("密码至少 8 位")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(digest_hex)),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


# --------------------------------------------------------------------- JWT
def create_access_token(user_id: int, role: str, *, hours: int = 24 * 7) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=hours)).timestamp()),
    }
    return jwt.encode(payload, settings.app_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.app_secret, algorithms=["HS256"])
    except JWTError:
        return None
    if not payload.get("sub"):
        return None
    return payload


# ---------------------------------------------------------- secret at rest
def _fernet() -> Fernet:
    settings = get_settings()
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.app_secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _ENC_PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(_ENC_PREFIX):
        raise ValueError("secret is not encrypted with the configured APP_SECRET")
    try:
        return _fernet().decrypt(value[len(_ENC_PREFIX) :].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("APP_SECRET changed; stored secret cannot be decrypted") from exc
