"""Account management + read-only queries + manual clock-in."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..gxy.errors import GxyError
from ..gxy.models import month_range
from ..models import Account, Execution, User, utcnow
from ..security import encrypt_secret
from ..services import clockin, runtime
from ..services.calendar import cache_records
from ..settings import get_settings
from .deps import CurrentUser, DbSession, account_for_user
from .presenters import account_view, execution_view
from .schemas import AccountCreate, AccountUpdate, ClockInRequest

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _owned_accounts(db, user: User) -> list[Account]:
    stmt = select(Account).order_by(Account.id)
    if not user.is_admin:
        stmt = stmt.where(Account.owner_id == user.id)
    return list(db.scalars(stmt))


@router.get("")
def list_accounts(user: CurrentUser, db: DbSession) -> list[dict]:
    return [account_view(account) for account in _owned_accounts(db, user)]


@router.post("", status_code=201)
def create_account(payload: AccountCreate, user: CurrentUser, db: DbSession) -> dict:
    owner_id = payload.owner_id if (payload.owner_id and user.is_admin) else user.id
    if db.get(User, owner_id) is None:
        raise HTTPException(400, "指定的用户不存在")
    if db.scalar(select(Account).where(Account.phone == payload.phone, Account.owner_id == owner_id)):
        raise HTTPException(409, "该手机号已存在")
    account = Account(
        owner_id=owner_id,
        label=payload.label.strip() or payload.phone,
        phone=payload.phone.strip(),
        password_enc=encrypt_secret(payload.password),
        enabled=payload.enabled,
        auto_clock_in=payload.auto_clock_in,
        auto_reports=payload.auto_reports,
        device=payload.device.model_dump(),
        location=payload.location.as_payload(),
        coord_type=payload.coord_type,
        profile=payload.profile.as_payload(),
        morning_enabled=payload.morning_enabled,
        morning_time=payload.morning_time,
        evening_enabled=payload.evening_enabled,
        evening_time=payload.evening_time,
        weekdays=payload.weekdays,
        calendar_enabled=payload.calendar_enabled,
        report_time=payload.report_time,
        report_types=payload.report_types,
        mirror_attendence_time=payload.mirror_attendence_time,
        notify=payload.notify,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account_view(account)


@router.patch("/{account_id}")
def update_account(account_id: int, payload: AccountUpdate, user: CurrentUser, db: DbSession) -> dict:
    account = account_for_user(db, user, account_id)
    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        password = data.pop("password")
        if password:
            account.password_enc = encrypt_secret(password)
            account.session_enc = ""
    if "device" in data and data["device"] is not None:
        account.device = data.pop("device")
    if "location" in data and data["location"] is not None:
        account.location = {
            key: value for key, value in data.pop("location").items() if value not in (None, "")
        }
    if "profile" in data and data["profile"] is not None:
        account.profile = {key: value for key, value in data.pop("profile").items() if value is not None}
    for key, value in data.items():
        if value is not None and hasattr(account, key):
            setattr(account, key, value)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account_view(account)


@router.delete("/{account_id}")
def delete_account(account_id: int, user: CurrentUser, db: DbSession) -> dict:
    account = account_for_user(db, user, account_id)
    db.delete(account)
    db.commit()
    return {"message": "已删除"}


@router.post("/{account_id}/login")
def login_and_probe(account_id: int, user: CurrentUser, db: DbSession) -> dict:
    """Log in and fetch plan + job. This is the safe "does it still work" probe."""
    account = account_for_user(db, user, account_id)
    today = dt.datetime.now(get_settings().tz).date().isoformat()
    execution = runtime.start_execution(
        db, account, kind="LOGIN", trigger="manual", target_date=today, message="登录检测"
    )
    try:
        client = runtime.build_client(account)
        logged_in = runtime.login_account(db, account, client)
        plan = runtime.refresh_plan(db, account, client)
        job: dict = {}
        if plan and plan.plan_id:
            job = client.fetch_job(plan.plan_id)
            account.job = job
            db.add(account)
            db.commit()
        runtime.finish_execution(
            db,
            execution,
            status="success",
            message="登录成功，计划与岗位已刷新",
            detail={"userType": logged_in.user_type, "planId": plan.plan_id if plan else ""},
            account=account,
        )
        return {
            "status": "success",
            "nickname": logged_in.nickname,
            "user_type": logged_in.user_type,
            "plan": account_view(db.get(Account, account.id))["plan"],
            "job": job,
            "execution_id": execution.id,
        }
    except Exception as exc:  # noqa: BLE001 - reported to the operator
        message = runtime.safe_error_message(exc)
        runtime.finish_execution(db, execution, status="failed", message=message, account=account)
        return {"status": "failed", "message": message, "execution_id": execution.id}


@router.post("/{account_id}/plan")
def refresh_plan(account_id: int, user: CurrentUser, db: DbSession) -> dict:
    account = account_for_user(db, user, account_id)
    client = runtime.build_client(account)
    try:
        runtime.ensure_login(db, account, client)
        plan = runtime.refresh_plan(db, account, client)
    except GxyError as exc:
        raise HTTPException(400, runtime.safe_error_message(exc)) from exc
    return {"plan": account_view(db.get(Account, account.id))["plan"], "found": plan is not None}


@router.get("/{account_id}/records")
def list_records(
    account_id: int,
    user: CurrentUser,
    db: DbSession,
    month: str | None = Query(default=None, description="YYYY-MM"),
) -> dict:
    account = account_for_user(db, user, account_id)
    today = dt.datetime.now(get_settings().tz).date()
    try:
        if month:
            year, mon = (int(part) for part in month.split("-", 1))
            base = dt.date(year, mon, 1)
        else:
            base = today
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "月份格式应为 YYYY-MM") from exc
    start, end = month_range(base)
    client = runtime.build_client(account)
    try:
        runtime.ensure_login(db, account, client)
        plan = runtime.cached_plan(account)
        records = client.attendance_records(
            start,
            end,
            plan_id=plan.plan_id if plan else None,
            teacher=(client.session.user_type or "").lower() == "teacher",
        )
    except GxyError as exc:
        raise HTTPException(400, runtime.safe_error_message(exc)) from exc
    cache_records(db, account.id, base.strftime("%Y-%m"), records)
    return {
        "month": base.strftime("%Y-%m"),
        "range": [start, end],
        "records": [
            {
                "attendance_id": record.attendance_id,
                "day": record.day,
                "kind": record.kind,
                "time": record.time,
                "state": record.state,
                "address": record.address,
            }
            for record in records
        ],
    }


@router.post("/{account_id}/clock-in")
def manual_clock_in(account_id: int, payload: ClockInRequest, user: CurrentUser, db: DbSession) -> dict:
    account = account_for_user(db, user, account_id)
    when: dt.datetime | None = None
    if payload.when:
        try:
            when = dt.datetime.fromisoformat(payload.when)
        except ValueError as exc:
            raise HTTPException(400, "时间格式应为 ISO 8601") from exc
    result = clockin.submit_clock_in(
        db,
        account,
        payload.kind,
        trigger=payload.trigger if payload.trigger in {"manual", "schedule", "retry"} else "manual",
        when=when,
        replace=payload.replace,
    )
    return result.to_dict()


@router.get("/{account_id}/executions")
def account_executions(
    account_id: int,
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    account = account_for_user(db, user, account_id)
    rows = db.scalars(
        select(Execution)
        .where(Execution.account_id == account.id)
        .order_by(Execution.created_at.desc())
        .limit(limit)
    ).all()
    return [execution_view(row, account.label or account.phone) for row in rows]


@router.get("/{account_id}/overview")
def account_overview(account_id: int, user: CurrentUser, db: DbSession) -> dict:
    account = account_for_user(db, user, account_id)
    today = utcnow().date().isoformat()
    rows = db.scalars(
        select(Execution)
        .where(Execution.account_id == account.id)
        .where(Execution.target_date == today)
        .order_by(Execution.created_at.desc())
    ).all()
    return {
        "account": account_view(account),
        "today": today,
        "executions": [execution_view(row, account.label) for row in rows],
    }
