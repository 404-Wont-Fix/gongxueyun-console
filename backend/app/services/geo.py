"""Map helpers: coordinate conversion, map/geocoder settings and geocoding.

Configuration resolves in this order:

1. database ``app_settings['map']`` (editable in the web UI, AMap key encrypted);
2. environment variables ``MAP_TILE_*`` / ``GEOCODE_*`` / ``AMAP_KEY``.

The browser gets only tile metadata and a ``has_amap_key`` flag; keys never
leave the server. Geocoding is proxied here for the same reason.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, replace
from typing import Any

import requests
from sqlalchemy.orm import Session

from ..models import AppSetting
from ..security import decrypt_secret, encrypt_secret
from ..settings import get_settings

logger = logging.getLogger(__name__)

SETTING_KEY = "map"
_TIMEOUT = 8
_USER_AGENT = "gongxueyun-console/0.1 (self-hosted internship assistant)"
_A = 6378245.0
_EE = 0.00669342162296594323
_rate_lock = threading.Lock()
_last_call = 0.0

AMAP_TILE_URL = (
    "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}"
)
OSM_TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"


class GeoError(RuntimeError):
    """Geocoder unavailable or returned nothing usable."""


@dataclass
class MapSettings:
    provider: str = "osm"
    amap_key: str = ""
    geocode_base_url: str = "https://nominatim.openstreetmap.org"
    tile_url: str = AMAP_TILE_URL
    tile_subdomains: str = "1234"
    tile_coord: str = "gcj02"
    attribution: str = "© 高德地图"
    source: str = "env"

    def public(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "has_amap_key": bool(self.amap_key),
            "geocode_base_url": self.geocode_base_url,
            "tile_url": self.tile_url,
            "tile_subdomains": self.tile_subdomains,
            "tile_coord": self.tile_coord,
            "attribution": self.attribution,
            "source": self.source,
        }


def _env_settings() -> MapSettings:
    settings = get_settings()
    return MapSettings(
        provider=(settings.geocode_provider or "osm").lower(),
        amap_key=settings.amap_key,
        geocode_base_url=settings.geocode_base_url,
        tile_url=settings.map_tile_url,
        tile_subdomains=settings.map_tile_subdomains,
        tile_coord=settings.map_tile_coord,
        attribution=settings.map_tile_attribution,
        source="env",
    )


def resolve(db: Session | None) -> MapSettings:
    env = _env_settings()
    if db is None:
        return env
    row = db.get(AppSetting, SETTING_KEY)
    data = dict(row.value or {}) if row else {}
    if not data:
        return env
    key = ""
    if data.get("amap_key_enc"):
        try:
            key = decrypt_secret(str(data["amap_key_enc"]))
        except ValueError:
            key = ""
    return MapSettings(
        provider=str(data.get("provider") or env.provider).lower(),
        amap_key=key or env.amap_key,
        geocode_base_url=str(data.get("geocode_base_url") or env.geocode_base_url),
        tile_url=str(data.get("tile_url") or env.tile_url),
        tile_subdomains=str(data.get("tile_subdomains") or env.tile_subdomains),
        tile_coord=str(data.get("tile_coord") or env.tile_coord).lower(),
        attribution=str(data.get("attribution") or env.attribution),
        source="database",
    )


def public(db: Session) -> dict[str, Any]:
    return resolve(db).public()


def save(db: Session, payload: dict[str, Any]) -> MapSettings:
    row = db.get(AppSetting, SETTING_KEY)
    current = dict(row.value or {}) if row else {}
    base = resolve(db)

    key_enc = current.get("amap_key_enc", "")
    if payload.get("amap_key"):
        key_enc = encrypt_secret(str(payload["amap_key"]).strip())
    if payload.get("clear_key"):
        key_enc = ""

    data = {
        "provider": str(payload.get("provider") or current.get("provider") or base.provider).lower(),
        "geocode_base_url": str(
            payload.get("geocode_base_url") or current.get("geocode_base_url") or base.geocode_base_url
        ).rstrip("/"),
        "tile_url": str(payload.get("tile_url") or current.get("tile_url") or base.tile_url),
        "tile_subdomains": str(
            payload.get("tile_subdomains") or current.get("tile_subdomains") or base.tile_subdomains
        ),
        "tile_coord": str(payload.get("tile_coord") or current.get("tile_coord") or base.tile_coord).lower(),
        "attribution": str(payload.get("attribution") or current.get("attribution") or base.attribution),
        "amap_key_enc": key_enc,
    }
    if row is None:
        row = AppSetting(key=SETTING_KEY, value=data)
    else:
        row.value = data
    db.add(row)
    db.commit()
    return resolve(db)


def clear(db: Session) -> None:
    row = db.get(AppSetting, SETTING_KEY)
    if row is not None:
        db.delete(row)
        db.commit()


def validate(payload: dict[str, Any]) -> None:
    provider = str(payload.get("provider") or "osm").lower()
    if provider not in {"osm", "amap"}:
        raise GeoError("地址服务只能是 osm 或 amap")
    coord = str(payload.get("tile_coord") or "gcj02").lower()
    if coord not in {"wgs84", "gcj02"}:
        raise GeoError("底图坐标系只能是 wgs84 或 gcj02")
    tile_url = str(payload.get("tile_url") or "")
    if tile_url and not all(token in tile_url for token in ("{x}", "{y}", "{z}")):
        raise GeoError("底图 URL 必须包含 {x}{y}{z} 占位符")


# ----------------------------------------------------------- coordinates
def _out_of_china(lat: float, lng: float) -> bool:
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    if _out_of_china(lat, lng):
        return lat, lng
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lat + d_lat, lng + d_lng


def gcj02_to_wgs84(lat: float, lng: float) -> tuple[float, float]:
    if _out_of_china(lat, lng):
        return lat, lng
    w_lat, w_lng = lat, lng
    for _ in range(6):
        g_lat, g_lng = wgs84_to_gcj02(w_lat, w_lng)
        w_lat += lat - g_lat
        w_lng += lng - g_lng
    return round(w_lat, 7), round(w_lng, 7)


def convert(lat: float, lng: float, source: str, target: str) -> tuple[float, float]:
    source = (source or "").lower()
    target = (target or "").lower()
    if source == target or not source or not target:
        return lat, lng
    if source == "wgs84" and target == "gcj02":
        return wgs84_to_gcj02(lat, lng)
    if source == "gcj02" and target == "wgs84":
        return gcj02_to_wgs84(lat, lng)
    raise GeoError(f"不支持的坐标转换：{source} → {target}")


# ------------------------------------------------------------- map config
def map_config(db: Session) -> dict[str, Any]:
    settings = resolve(db)
    return {
        "tile_url": settings.tile_url,
        "attribution": settings.attribution,
        "subdomains": settings.tile_subdomains,
        "tile_coord": settings.tile_coord,
        "geocoder": settings.provider,
        "has_amap_key": bool(settings.amap_key),
    }


# -------------------------------------------------------------- geocoding
def _throttle() -> None:
    """Nominatim asks for at most 1 request/second."""
    global _last_call
    with _rate_lock:
        wait = 1.0 - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


def search(db: Session, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    settings = resolve(db)
    text = (query or "").strip()
    if not text:
        return []
    return _search_with(settings, text, limit)


def reverse(db: Session, lat: float, lng: float, *, coord: str = "wgs84") -> dict[str, Any]:
    settings = resolve(db)
    if settings.provider == "amap":
        g_lat, g_lng = convert(lat, lng, coord, "gcj02")
        return _amap_reverse(settings.amap_key, g_lat, g_lng)
    w_lat, w_lng = convert(lat, lng, coord, "wgs84")
    return _nominatim_reverse(settings.geocode_base_url, w_lat, w_lng)


def test(db: Session, override: dict[str, Any] | None = None, query: str = "杭州") -> dict[str, Any]:
    settings = resolve(db)
    if override and override.get("provider"):
        settings = replace(
            settings,
            provider=str(override.get("provider")).lower(),
            amap_key=str(override.get("amap_key") or settings.amap_key),
            geocode_base_url=str(override.get("geocode_base_url") or settings.geocode_base_url),
        )
    started = time.time()
    try:
        results = _search_with(settings, query, 3)
    except GeoError as exc:
        return {"ok": False, "message": str(exc), "latency_ms": int((time.time() - started) * 1000)}
    return {
        "ok": True,
        "provider": settings.provider,
        "count": len(results),
        "sample": results[:2],
        "latency_ms": int((time.time() - started) * 1000),
    }


def _search_with(settings: MapSettings, text: str, limit: int) -> list[dict[str, Any]]:
    if settings.provider == "amap":
        if not settings.amap_key:
            raise GeoError("地址服务设为高德，但还没有填写高德 Key")
        return _amap_search(settings.amap_key, text, limit)
    return _nominatim_search(settings.geocode_base_url, text, limit)


# ------------------------------------------------------------------ providers
def _nominatim_search(base: str, query: str, limit: int) -> list[dict[str, Any]]:
    _throttle()
    try:
        response = requests.get(
            f"{base}/search",
            params={"q": query, "format": "jsonv2", "limit": limit, "accept-language": "zh-CN"},
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GeoError("地址搜索服务不可用（网络）") from exc
    if response.status_code >= 400:
        raise GeoError(f"地址搜索失败：HTTP {response.status_code}")
    try:
        rows = response.json()
    except ValueError as exc:
        raise GeoError("地址搜索返回了非 JSON") from exc
    results = []
    for row in rows if isinstance(rows, list) else []:
        try:
            results.append(
                {
                    "label": str(row.get("display_name") or "")[:300],
                    "lat": float(row["lat"]),
                    "lng": float(row["lon"]),
                    "coord": "wgs84",
                    "type": str(row.get("type") or ""),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return results


def _nominatim_reverse(base: str, lat: float, lng: float) -> dict[str, Any]:
    _throttle()
    try:
        response = requests.get(
            f"{base}/reverse",
            params={"lat": lat, "lon": lng, "format": "jsonv2", "accept-language": "zh-CN"},
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GeoError("地址反查服务不可用（网络）") from exc
    if response.status_code >= 400:
        raise GeoError(f"地址反查失败：HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise GeoError("地址反查返回了非 JSON") from exc
    if not isinstance(payload, dict) or not payload.get("display_name"):
        raise GeoError("该坐标没有可用的地址")
    address = payload.get("address") or {}
    return {
        "address": str(payload.get("display_name") or "")[:300],
        "province": str(address.get("state") or address.get("province") or ""),
        "city": str(address.get("city") or address.get("town") or address.get("county") or ""),
        "area": str(address.get("suburb") or address.get("district") or address.get("county") or ""),
        "coord": "wgs84",
        "lat": lat,
        "lng": lng,
    }


def _amap_search(key: str, query: str, limit: int) -> list[dict[str, Any]]:
    try:
        response = requests.get(
            "https://restapi.amap.com/v3/geocode/geo",
            params={"key": key, "address": query, "output": "JSON"},
            timeout=_TIMEOUT,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise GeoError("高德地址搜索不可用") from exc
    if str(payload.get("status")) != "1":
        raise GeoError(f"高德返回错误：{payload.get('info') or 'unknown'}")
    results = []
    for row in (payload.get("geocodes") or [])[:limit]:
        location = str(row.get("location") or "")
        if "," not in location:
            continue
        lng_text, lat_text = location.split(",", 1)
        try:
            lat, lng = float(lat_text), float(lng_text)
        except ValueError:
            continue
        results.append(
            {
                "label": str(row.get("formatted_address") or row.get("formattedAddress") or query)[:300],
                "lat": lat,
                "lng": lng,
                "coord": "gcj02",
                "type": "amap",
                "province": str(row.get("province") or ""),
                "city": str(row.get("city") or ""),
                "area": str(row.get("district") or ""),
            }
        )
    return results


def _amap_reverse(key: str, lat: float, lng: float) -> dict[str, Any]:
    try:
        response = requests.get(
            "https://restapi.amap.com/v3/geocode/regeo",
            params={"key": key, "location": f"{lng},{lat}", "extensions": "base"},
            timeout=_TIMEOUT,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise GeoError("高德地址反查不可用") from exc
    if str(payload.get("status")) != "1":
        raise GeoError(f"高德返回错误：{payload.get('info') or 'unknown'}")
    regeocode = payload.get("regeocode") or {}
    component = regeocode.get("addressComponent") or {}
    address = str(regeocode.get("formatted_address") or "")
    if isinstance(address, list):  # amap returns [] when empty
        address = ""
    if not address:
        raise GeoError("该坐标没有可用的地址")
    return {
        "address": address[:300],
        "province": str(component.get("province") or ""),
        "city": str(component.get("city") or ""),
        "area": str(component.get("district") or ""),
        "coord": "gcj02",
        "lat": lat,
        "lng": lng,
    }
