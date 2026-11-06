"""Calendar projections over scoped accounts, confirmed records and executions."""
from __future__ import annotations

import calendar as monthlib
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..gxy.models import AttendanceRecord
from ..models import Account, AttendanceMonth, CalendarYear, Execution, utcnow
from ..settings import get_settings
from .holidays import day_schedule, year_view

KINDS = {"START", "END", "HOLIDAY"}
PENDING = {"running", "submitted_unconfirmed", "verification_required", "captcha_required"}


def cache_records(db: Session, account_id: int, month: str, records: list[AttendanceRecord]) -> None:
    row = db.get(AttendanceMonth, (account_id, month)) or AttendanceMonth(account_id=account_id, month=month)
    row.records = [{"attendance_id": r.attendance_id, "day": r.day, "kind": r.kind,
                    "time": r.time, "state": r.state, "address": r.address} for r in records if r.day.startswith(month + "-")]
    row.synced_at = utcnow()
    db.add(row)
    db.commit()


def parse_month(month: str) -> dt.date:
    if len(month) != 7:
        raise ValueError("月份格式应为 YYYY-MM")
    day = dt.date.fromisoformat(month + "-01")
    if not 2020 <= day.year <= dt.datetime.now(get_settings().tz).year + 1:
        raise ValueError("日历年份超出支持范围")
    return day


def month_view(db: Session, accounts: list[Account], month: str) -> dict:
    first = parse_month(month)
    last = first.replace(day=monthlib.monthrange(first.year, first.month)[1])
    ids = [a.id for a in accounts]
    labels = {a.id: a.label or a.phone for a in accounts}
    executions = list(db.scalars(select(Execution).where(
        Execution.account_id.in_(ids), Execution.kind.in_(["CLOCK_IN", "REPLACE"]),
        Execution.target_date >= first.isoformat(), Execution.target_date <= last.isoformat()
    ).order_by(Execution.id)))
    snapshots = list(db.scalars(select(AttendanceMonth).where(AttendanceMonth.account_id.in_(ids), AttendanceMonth.month == month)))
    records_by_day: dict[str, list] = {}
    for snapshot in snapshots:
        for record in snapshot.records or []:
            if record.get("kind") in KINDS:
                records_by_day.setdefault(record["day"], []).append({**record, "account_id": snapshot.account_id, "account_label": labels[snapshot.account_id]})
    events_by_day: dict[str, list] = {}
    for row in executions:
        if row.subtype in KINDS:
            events_by_day.setdefault(row.target_date, []).append(row)
    annual = db.get(CalendarYear, first.year)
    today = dt.datetime.now(get_settings().tz).date().isoformat()
    days = []
    for number in range(1, last.day + 1):
        day = first.replace(day=number)
        date = day.isoformat()
        special = (annual.days or {}).get(date) if annual and annual.accepted_at else None
        events = events_by_day.get(date, [])
        remote = records_by_day.get(date, [])
        # Count unique account/day/type slots, not HTTP attempts/retries.
        confirmed = {(r["account_id"], r["kind"]) for r in remote}
        confirmed.update((e.account_id, e.subtype) for e in events if e.status == "success")
        latest = {(e.account_id, e.subtype): e for e in events}
        pending = sum(e.status in PENDING for key, e in latest.items() if key not in confirmed)
        failed = sum(e.status in {"failed", "rejected"} for key, e in latest.items() if key not in confirmed)
        plans = [{"account_id": a.id, "account_label": labels[a.id], **day_schedule(db, a, day)} for a in accounts]
        expected = {(p["account_id"], s["kind"]) for p in plans if p["automatic"] for s in p["slots"]}
        days.append({
            "date": date, "weekday": day.isoweekday(),
            "day_type": ("holiday" if special["off"] else "makeup") if special else ("normal" if annual and annual.accepted_at else "unknown"),
            "name": special["name"] if special else "", "is_today": date == today,
            "stats": {"expected": len(expected), "confirmed": len(confirmed), "pending": pending, "failed": failed,
                      "remaining": len(expected - confirmed), "attempts": len(events)},
            "plans": plans, "records": remote,
            "executions": [{"id": e.id, "account_id": e.account_id, "account_label": labels[e.account_id],
                            "kind": e.subtype, "status": e.status, "message": e.message,
                            "time": e.created_at.isoformat() + ("Z" if e.created_at.tzinfo is None else "") if e.created_at else None} for e in reversed(events)],
        })
    stats = {key: sum(d["stats"][key] for d in days) for key in ("expected", "confirmed", "pending", "failed", "attempts")}
    return {"month": month, "today": today, "calendar": year_view(annual, first.year), "days": days, "stats": stats,
            "accounts": [{"id": a.id, "label": labels[a.id]} for a in accounts],
            "record_sync": [{"account_id": r.account_id, "synced_at": r.synced_at.isoformat() + ("Z" if r.synced_at.tzinfo is None else "")} for r in snapshots]}
