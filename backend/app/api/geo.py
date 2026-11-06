"""Map configuration, geocoding proxy and map/geocoder settings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..services import geo
from .deps import AdminUser, CurrentUser, DbSession
from .schemas import MapProbeIn, MapSettingsIn

router = APIRouter(tags=["geo"])


@router.get("/map-config")
def map_config(_: CurrentUser, db: DbSession) -> dict:
    return geo.map_config(db)


@router.get("/geo/search")
def search(
    _: CurrentUser,
    db: DbSession,
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=5, ge=1, le=10),
) -> dict:
    try:
        return {"results": geo.search(db, q, limit=limit)}
    except geo.GeoError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/geo/reverse")
def reverse(
    _: CurrentUser,
    db: DbSession,
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    coord: str = Query(default="wgs84", pattern="^(wgs84|gcj02)$"),
) -> dict:
    try:
        return geo.reverse(db, lat, lng, coord=coord)
    except geo.GeoError as exc:
        raise HTTPException(400, str(exc)) from exc


# ------------------------------------------------------------------ settings
@router.get("/settings/map")
def get_map_settings(_: AdminUser, db: DbSession) -> dict:
    return geo.public(db)


@router.put("/settings/map")
def put_map_settings(payload: MapSettingsIn, _: AdminUser, db: DbSession) -> dict:
    data = payload.model_dump()
    try:
        geo.validate(data)
    except geo.GeoError as exc:
        raise HTTPException(400, str(exc)) from exc
    geo.save(db, data)
    return geo.public(db)


@router.post("/settings/map/test")
def test_map_settings(payload: MapProbeIn, _: AdminUser, db: DbSession) -> dict:
    return geo.test(db, payload.model_dump(), query=payload.q or "杭州")


@router.delete("/settings/map")
def clear_map_settings(_: AdminUser, db: DbSession) -> dict:
    geo.clear(db)
    return {"message": "已清除，回退到环境变量配置"}
