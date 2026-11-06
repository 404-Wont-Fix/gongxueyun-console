from __future__ import annotations

from fastapi import APIRouter

from . import accounts, auth, calendar, geo, plans, reports, system, verifications

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(calendar.router)
api_router.include_router(reports.router)
api_router.include_router(plans.router)
api_router.include_router(verifications.router)
api_router.include_router(geo.router)
api_router.include_router(system.router)
