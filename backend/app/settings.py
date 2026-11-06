"""Runtime configuration from environment variables.

Deliberately dependency-free: a small dataclass instead of pydantic-settings,
so the protocol package stays importable with almost no third-party packages.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or "").strip() or default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name, "1" if default else "0").lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_list(name: str) -> list[str]:
    raw = _env(name)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_secret: str
    admin_username: str
    admin_password: str
    database_url: str
    cors_origins: list[str]
    tz: timezone
    scheduler_enabled: bool
    scheduler_tick_seconds: int
    task_lock_seconds: int
    gxy_package_version: str
    gxy_build_number: str
    gxy_code_version: str
    gxy_timeout_seconds: float
    captcha_model_dir: Path | None
    captcha_model_auto_download: bool
    geocode_provider: str
    geocode_base_url: str
    amap_key: str
    map_tile_url: str
    map_tile_attribution: str
    map_tile_subdomains: str
    map_tile_coord: str
    notify: dict[str, str] = field(default_factory=dict)
    ai: dict[str, str] = field(default_factory=dict)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def dev_secret(self) -> bool:
        return self.app_secret.startswith("please-change") or len(self.app_secret) < 16


def _load() -> Settings:
    secret = _env("APP_SECRET")
    if not secret:
        # Dev convenience only: a random secret invalidates sessions on restart.
        secret = secrets.token_urlsafe(48)
    offset = _env_int("APP_TIMEZONE_OFFSET", 8)
    model_dir = _env("CAPTCHA_MODEL_DIR")
    return Settings(
        app_env=_env("APP_ENV", "development"),
        app_secret=secret,
        admin_username=_env("ADMIN_USERNAME", "admin"),
        admin_password=_env("ADMIN_PASSWORD", "admin12345"),
        database_url=_env("DATABASE_URL", "sqlite:///./data/gxy.db"),
        cors_origins=_env_list("CORS_ORIGINS"),
        tz=timezone(timedelta(hours=offset)),
        scheduler_enabled=_env_bool("SCHEDULER_ENABLED", True),
        scheduler_tick_seconds=max(10, _env_int("SCHEDULER_TICK_SECONDS", 30)),
        task_lock_seconds=max(60, _env_int("TASK_LOCK_SECONDS", 300)),
        gxy_package_version=_env("GXY_PACKAGE_VERSION", "5.41.6"),
        gxy_build_number=_env("GXY_BUILD_NUMBER", "50291"),
        gxy_code_version=_env("GXY_CODE_VERSION", "292"),
        gxy_timeout_seconds=_env_float("GXY_TIMEOUT_SECONDS", 15.0),
        captcha_model_dir=Path(model_dir).expanduser() if model_dir else None,
        captcha_model_auto_download=_env_bool("CAPTCHA_MODEL_AUTO_DOWNLOAD", False),
        geocode_provider=_env("GEOCODE_PROVIDER", "amap").lower(),
        geocode_base_url=_env("GEOCODE_BASE_URL", "https://nominatim.openstreetmap.org").rstrip("/"),
        amap_key=_env("AMAP_KEY"),
        map_tile_url=_env(
            "MAP_TILE_URL",
            "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
        ),
        map_tile_attribution=_env("MAP_TILE_ATTRIBUTION", "© 高德地图"),
        map_tile_subdomains=_env("MAP_TILE_SUBDOMAINS", "1234"),
        map_tile_coord=_env("MAP_TILE_COORD", "gcj02").lower(),
        notify={
            "webhook": _env("NOTIFY_WEBHOOK_URL"),
            "pushplus": _env("NOTIFY_PUSHPLUS_TOKEN"),
            "serverchan": _env("NOTIFY_SERVERCHAN_KEY"),
            "ntfy": _env("NOTIFY_NTFY_URL"),
            "events": _env("NOTIFY_EVENTS", "verification_required,failed"),
        },
        ai={
            "base_url": _env("AI_BASE_URL"),
            "api_key": _env("AI_API_KEY"),
            "model": _env("AI_MODEL"),
            "timeout": _env("AI_TIMEOUT_SECONDS", "60"),
        },
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _load()


def reset_settings_cache() -> None:
    """Used by tests after monkeypatching the environment."""
    get_settings.cache_clear()


def _load_dotenv() -> None:
    """Read a local ``.env`` without overriding real environment variables.

    No third-party dependency: only ``KEY=VALUE`` lines, ``#`` comments and
    optional surrounding quotes are supported. Looked up in the current working
    directory and in the project root next to ``backend/``.
    """
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            item = line.strip()
            if not item or item.startswith("#") or "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)
        return


_load_dotenv()
