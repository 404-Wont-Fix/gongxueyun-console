"""Permission-scoped calendar; public holiday refresh is admin-only."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..models import Account, CalendarOverride
from ..services import calendar, holidays
from .accounts import list_records
from .deps import AdminUser, CurrentUser, DbSession, account_for_user

router = APIRouter(prefix="/calendar", tags=["calendar"])


class OverrideIn(BaseModel):
    mode: Literal["work", "holiday", "skip"]
    note: str = Field(default="", max_length=200)


def valid_day(day: str) -> dt.date:
    try:
        value = dt.date.fromisoformat(day)
        if value.isoformat() != day:
            raise ValueError()
        calendar.parse_month(day[:7])
        return value
    except ValueError as exc:
        raise HTTPException(400, "日期格式应为 YYYY-MM-DD，且年份须在支持范围内") from exc


@router.get("")
def get_calendar(user: CurrentUser, db: DbSession, month: str = Query(pattern=r"^\d{4}-\d{2}$"), account_id: int | None = None) -> dict:
    if account_id is not None:
        accounts = [account_for_user(db, user, account_id)]
    else:
        stmt = select(Account).order_by(Account.id)
        if not user.is_admin:
            stmt = stmt.where(Account.owner_id == user.id)
        accounts = list(db.scalars(stmt))
    try:
        return calendar.month_view(db, accounts, month)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/sync")
def sync_calendar(_: AdminUser, year: int = Query(ge=2020, le=2100)) -> dict:
    try:
        return holidays.sync_year(year)
    except holidays.CalendarError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/records/{account_id}/sync")
def sync_records(account_id: int, user: CurrentUser, db: DbSession, month: str = Query(pattern=r"^\d{4}-\d{2}$")) -> dict:
    # This performs only a query, never a clock-in. Successful queries are cached
    # by list_records; failures leave the previous snapshot intact.
    try:
        calendar.parse_month(month)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return list_records(account_id=account_id, user=user, db=db, month=month)


@router.put("/overrides/{account_id}/{day}")
def set_override(account_id: int, day: str, payload: OverrideIn, user: CurrentUser, db: DbSession) -> dict:
    account = account_for_user(db, user, account_id)
    date = valid_day(day)
    row = db.get(CalendarOverride, (account.id, day)) or CalendarOverride(account_id=account.id, day=day)
    row.mode, row.note = payload.mode, payload.note.strip()
    db.add(row)
    db.commit()
    return holidays.day_schedule(db, account, date)


@router.delete("/overrides/{account_id}/{day}")
def remove_override(account_id: int, day: str, user: CurrentUser, db: DbSession) -> dict:
    account = account_for_user(db, user, account_id)
    date = valid_day(day)
    row = db.get(CalendarOverride, (account.id, day))
    if row:
        db.delete(row)
        db.commit()
    return holidays.day_schedule(db, account, date)
