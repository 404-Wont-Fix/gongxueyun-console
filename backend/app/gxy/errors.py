"""Typed protocol errors.

Every failure mode that the caller must handle differently has its own type.
This is the main lesson from the older repositories: a single ``if code == 200``
turns "verification required" into a false success.
"""

from __future__ import annotations

from typing import Any


class GxyError(Exception):
    """Base error for the 工学云 client."""

    retryable = False


class GxyTransportError(GxyError):
    """Network problem / timeout. Safe for reads, never blind-retried for writes."""

    retryable = True


class GxyHTTPError(GxyError):
    def __init__(self, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        self.body = body[:500]
        super().__init__(f"HTTP {status_code}")

    retryable = True


class GxyBusinessError(GxyError):
    """Business ``code != 200`` (or a documented non-success marker)."""

    def __init__(self, code: Any, msg: str, data: Any = None) -> None:
        self.code = code
        self.msg = msg
        self.data = data
        super().__init__(f"code={code} msg={msg}")

    @property
    def auth_expired(self) -> bool:
        return self.code in (401, 7001, 7002) or self.msg in {
            "token失效", "Token失效", "token已失效", "Token已失效",
            "登录已失效", "请重新登录",
        }


class GxyAuthError(GxyBusinessError):
    """Login/authorisation truly failed."""


class CaptchaError(GxyError):
    """A captcha challenge was returned but could not be solved."""


class CaptchaUnavailable(CaptchaError):
    """No solver is configured for this captcha type."""


class ProtocolDrift(GxyError):
    """The response does not match any known shape; fail closed."""
