"""Crypto primitives used by the 工学云 mobile client.

Two independent things live here and must not be confused:

* field encryption  — AES-128-ECB + PKCS7, hex output (for account fields / `t`)
* request signature — MD5(parts.join("") + SIGN_SUFFIX)

Captcha material uses the *challenge* key from the server response and Base64
output, not the built-in key.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Iterable

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .constants import DEFAULT_AES_KEY, SIGN_SUFFIX


class CryptoError(ValueError):
    """Raised when encryption/decryption input is unusable."""


def _key_bytes(key: str) -> bytes:
    raw = (key or "").encode("utf-8")
    if len(raw) not in (16, 24, 32):
        raise CryptoError("AES key must be 16/24/32 UTF-8 bytes")
    return raw


def aes_encrypt(plaintext: str, key: str = DEFAULT_AES_KEY, out_format: str = "hex") -> str:
    """Encrypt a non-empty string; empty input stays empty (client short-circuits)."""
    if plaintext is None:
        return ""
    value = str(plaintext)
    if not value.strip():
        return ""
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    data = padder.update(value.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(_key_bytes(key)), modes.ECB()).encryptor()
    ciphertext = encryptor.update(data) + encryptor.finalize()
    if out_format == "hex":
        return ciphertext.hex()
    if out_format == "b64":
        return base64.b64encode(ciphertext).decode("ascii")
    raise CryptoError(f"unsupported output format: {out_format}")


def aes_decrypt(ciphertext: str, key: str = DEFAULT_AES_KEY, in_format: str = "hex") -> str:
    if not ciphertext:
        raise CryptoError("empty ciphertext")
    try:
        raw = bytes.fromhex(ciphertext) if in_format == "hex" else base64.b64decode(ciphertext)
    except (ValueError, TypeError) as exc:
        raise CryptoError("ciphertext is not valid hex/base64") from exc
    if not raw or len(raw) % 16:
        raise CryptoError("ciphertext length is not a multiple of the AES block size")
    decryptor = Cipher(algorithms.AES(_key_bytes(key)), modes.ECB()).decryptor()
    padded = decryptor.update(raw) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    try:
        return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
    except ValueError as exc:
        raise CryptoError("bad PKCS7 padding or non-UTF-8 plaintext") from exc


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def create_sign(*parts: Any) -> str:
    """``MD5(parts.join("") + SIGN_SUFFIX)``.

    Missing parts are a programming error: silently signing "None" would produce
    a signature the server rejects for an opaque reason.
    """
    chunks: list[str] = []
    for index, part in enumerate(parts):
        if part is None:
            raise CryptoError(f"signature part {index} is missing")
        chunks.append(part if isinstance(part, str) else str(part))
    return md5_hex("".join(chunks) + SIGN_SUFFIX)


def point_json(points: Iterable[dict[str, Any]] | dict[str, Any]) -> str:
    """Serialise captcha interaction data the way the client does (compact JSON)."""
    return json.dumps(points, separators=(",", ":"), ensure_ascii=False)


def captcha_proof(secret_key: str, token: str, interaction_json: str) -> str:
    """The value put into ``captcha`` after a challenge is solved.

    Client behaviour: ``AES_b64(secretKey, token + "---" + interaction)``.
    """
    return aes_encrypt(f"{token}---{interaction_json}", key=secret_key, out_format="b64")


def challenge_hash(secret_key: str, interaction_json: str) -> str:
    """The value put into ``pointJson`` when checking a challenge."""
    return aes_encrypt(interaction_json, key=secret_key, out_format="b64")


def safe_preview(value: Any, keep: int = 6) -> str:
    """Mask a secret for logs; never emit tokens or ciphertext in full."""
    text = str(value or "")
    if len(text) <= keep:
        return "*" * len(text)
    return f"{text[:keep]}…({len(text)} chars)"
