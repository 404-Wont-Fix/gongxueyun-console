import base64
import hashlib

import pytest

from app.gxy.crypto import (
    CryptoError,
    aes_decrypt,
    aes_encrypt,
    captcha_proof,
    challenge_hash,
    create_sign,
    md5_hex,
    point_json,
    safe_preview,
)
from app.gxy.constants import DEFAULT_AES_KEY, SIGN_SUFFIX


# Cross-checked with Node's crypto (aes-128-ecb + PKCS7) — independent of our code.
VECTORS = {
    "13800138000": "a2a491a06bd27eea811ad5a55879b64a",
    "1700000000000": "7ad45922de892c34d7bbed8e8b0d8afd",
    "123456": "cacddb2b833f98eebe8f90bcf7d960ec",
}


@pytest.mark.parametrize("plaintext,ciphertext", VECTORS.items())
def test_encrypt_matches_reference(plaintext: str, ciphertext: str) -> None:
    assert aes_encrypt(plaintext) == ciphertext
    assert aes_decrypt(ciphertext) == plaintext


def test_empty_input_is_not_encrypted() -> None:
    assert aes_encrypt("") == ""
    assert aes_encrypt("   ") == ""


def test_ciphertext_is_block_aligned_hex() -> None:
    value = aes_encrypt("a" * 40)
    assert len(value) % 32 == 0
    assert int(value, 16) >= 0


def test_decrypt_rejects_garbage() -> None:
    with pytest.raises(CryptoError):
        aes_decrypt("not-hex")
    with pytest.raises(CryptoError):
        aes_decrypt("00" * 16)


def test_wrong_key_fails_padding_or_utf8() -> None:
    value = aes_encrypt("13800138000")
    with pytest.raises(CryptoError):
        aes_decrypt(value, key="0000000000000000")


def test_sign_is_md5_of_joined_parts_plus_suffix() -> None:
    parts = ("user-1", "student", "day")
    expected = hashlib.md5(("".join(parts) + SIGN_SUFFIX).encode("utf-8")).hexdigest()
    assert create_sign(*parts) == expected
    assert create_sign(*parts) == md5_hex("".join(parts) + SIGN_SUFFIX)


def test_sign_requires_every_part() -> None:
    with pytest.raises(CryptoError):
        create_sign("user-1", None, "day")


def test_captcha_proof_roundtrip() -> None:
    secret = "c2VjcmV0a2V5MTIzNDU2Nw=="  # any 16-byte key after urlsafe decode
    token = "token-abc"
    interaction = point_json({"x": 123.4, "y": 5})
    proof = captcha_proof(secret, token, interaction)
    raw = base64.b64decode(proof)
    assert len(raw) % 16 == 0
    assert aes_decrypt(proof, key=secret, in_format="b64") == f"{token}---{interaction}"
    assert aes_decrypt(challenge_hash(secret, interaction), key=secret, in_format="b64") == interaction


def test_point_json_is_compact() -> None:
    assert point_json([{"x": 1, "y": 2}]) == '[{"x":1,"y":2}]'


def test_safe_preview_masks_long_values() -> None:
    assert safe_preview("abcdef") == "******"
    assert safe_preview("abcdefghij").startswith("abcdef…")
    assert DEFAULT_AES_KEY not in safe_preview(DEFAULT_AES_KEY)
