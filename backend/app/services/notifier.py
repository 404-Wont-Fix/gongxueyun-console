"""Optional push notifications.

All channels are best-effort: a failed notification must never turn a successful
clock-in into a failure. Payloads contain no tokens, no registration numbers and
no request bodies.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from ..settings import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 8


def channels_for(account_notify: dict[str, Any] | None) -> dict[str, str]:
    settings = get_settings()
    merged = dict(settings.notify)
    for key, value in (account_notify or {}).items():
        if value:
            merged[key] = str(value)
    return merged


def enabled_events(channels: dict[str, str]) -> set[str]:
    raw = channels.get("events") or ""
    return {item.strip() for item in raw.split(",") if item.strip()}


def notify(
    title: str,
    body: str,
    *,
    event: str,
    account_notify: dict[str, Any] | None = None,
) -> list[str]:
    channels = channels_for(account_notify)
    if event not in enabled_events(channels):
        return []
    sent: list[str] = []
    text = f"{title}\n{body}"

    webhook = channels.get("webhook")
    if webhook:
        try:
            requests.post(webhook, json={"title": title, "content": body, "event": event}, timeout=_TIMEOUT)
            sent.append("webhook")
        except requests.RequestException as exc:
            logger.warning("webhook notification failed: %s", type(exc).__name__)

    pushplus = channels.get("pushplus")
    if pushplus:
        try:
            requests.post(
                "https://www.pushplus.plus/send",
                json={"token": pushplus, "title": title, "content": body, "template": "txt"},
                timeout=_TIMEOUT,
            )
            sent.append("pushplus")
        except requests.RequestException as exc:
            logger.warning("pushplus notification failed: %s", type(exc).__name__)

    serverchan = channels.get("serverchan")
    if serverchan:
        try:
            requests.post(
                f"https://sctapi.ftqq.com/{serverchan}.send",
                data={"title": title, "desp": body},
                timeout=_TIMEOUT,
            )
            sent.append("serverchan")
        except requests.RequestException as exc:
            logger.warning("serverchan notification failed: %s", type(exc).__name__)

    ntfy = channels.get("ntfy")
    if ntfy:
        try:
            requests.post(ntfy, data=text.encode("utf-8"), timeout=_TIMEOUT)
            sent.append("ntfy")
        except requests.RequestException as exc:
            logger.warning("ntfy notification failed: %s", type(exc).__name__)

    return sent
