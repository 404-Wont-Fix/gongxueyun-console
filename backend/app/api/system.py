"""Executions log, dashboard stats and system capabilities."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from ..gxy.captcha import CaptchaSolver
from ..models import Account, Execution, User, VerificationSession
from ..services import ai as ai_service
from ..services import scheduler
from ..services.verifications import TERMINAL
from ..settings import get_settings
from .deps import AdminUser, CurrentUser, DbSession
from .presenters import execution_view
from .schemas import AISettingsIn, AIProbeIn, NotifyTest

router = APIRouter(tags=["system"])


def _scoped_accounts(db, user: User) -> list[Account]:
    stmt = select(Account).order_by(Account.id)
    if not user.is_admin:
        stmt = stmt.where(Account.owner_id == user.id)
    return list(db.scalars(stmt))


@router.get("/executions")
def list_executions(
    user: CurrentUser,
    db: DbSession,
    account_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    accounts = {account.id: account for account in _scoped_accounts(db, user)}
    if account_id is not None and account_id not in accounts:
        return {"items": [], "total": 0}
    stmt = select(Execution).where(Execution.account_id.in_(list(accounts) or [-1]))
    if account_id is not None:
        stmt = stmt.where(Execution.account_id == account_id)
    if status:
        stmt = stmt.where(Execution.status == status)
    rows = db.scalars(
        stmt.order_by(Execution.created_at.desc()).offset(offset).limit(limit)
    ).all()
    count_stmt = select(func.count()).select_from(Execution).where(Execution.account_id.in_(list(accounts) or [-1]))
    if account_id is not None:
        count_stmt = count_stmt.where(Execution.account_id == account_id)
    if status:
        count_stmt = count_stmt.where(Execution.status == status)
    total = db.scalar(count_stmt) or 0
    return {
        "items": [
            execution_view(row, accounts[row.account_id].label or accounts[row.account_id].phone)
            for row in rows
            if row.account_id in accounts
        ],
        "total": total,
    }


@router.get("/overview")
def overview(user: CurrentUser, db: DbSession) -> dict:
    accounts = _scoped_accounts(db, user)
    today = dt.datetime.now(get_settings().tz).date().isoformat()
    ids = [account.id for account in accounts] or [-1]
    executions = db.scalars(
        select(Execution)
        .where(Execution.account_id.in_(ids))
        .where(Execution.target_date == today)
        .order_by(Execution.created_at.desc())
    ).all()
    pending = db.scalars(
        select(VerificationSession)
        .where(VerificationSession.account_id.in_(ids))
        .where(VerificationSession.state.not_in(list(TERMINAL)))
    ).all()

    counts: dict[str, int] = {}
    for row in executions:
        counts[row.status] = counts.get(row.status, 0) + 1

    per_account = []
    for account in accounts:
        rows = [row for row in executions if row.account_id == account.id]
        per_account.append(
            {
                "id": account.id,
                "label": account.label or account.phone,
                "enabled": account.enabled,
                "auto_clock_in": account.auto_clock_in,
                "last_status": account.last_status,
                "last_message": account.last_message,
                "today": [
                    {
                        "kind": row.subtype or row.kind,
                        "status": row.status,
                        "message": row.message,
                        "time": row.created_at.isoformat() if row.created_at else None,
                    }
                    for row in rows
                ],
            }
        )

    recent = db.scalars(
        select(Execution)
        .where(Execution.account_id.in_(ids))
        .order_by(Execution.created_at.desc())
        .limit(10)
    ).all()
    labels = {account.id: account.label or account.phone for account in accounts}
    return {
        "today": today,
        "accounts": len(accounts),
        "enabled_accounts": sum(1 for account in accounts if account.enabled),
        "auto_accounts": sum(1 for account in accounts if account.auto_clock_in),
        "counts": counts,
        "pending_verifications": len(pending),
        "per_account": per_account,
        "recent": [
            execution_view(row, labels.get(row.account_id, ""))
            for row in recent
            if row.account_id in labels
        ],
    }


@router.get("/capabilities")
def capabilities(_: CurrentUser, db: DbSession) -> dict:
    settings = get_settings()
    solver = CaptchaSolver.from_settings(settings.captcha_model_dir)
    ai_config = ai_service.resolve_config(db)
    return {
        "captcha": solver.describe(),
        "package_version": settings.gxy_package_version,
        "build_number": settings.gxy_build_number,
        "code_version": settings.gxy_code_version,
        "timezone": str(settings.tz),
        "scheduler_enabled": settings.scheduler_enabled,
        "ai_configured": ai_config.configured,
        "ai_model": ai_config.model if ai_config.configured else "",
        "notify_channels": [
            name
            for name, value in settings.notify.items()
            if name != "events" and value
        ],
    }


@router.get("/settings")
def read_settings(_: AdminUser) -> dict:
    settings = get_settings()

    def mask(value: str) -> str:
        return f"***{value[-4:]}" if len(value) > 4 else ("***" if value else "")

    return {
        "scheduler_enabled": settings.scheduler_enabled,
        "scheduler_tick_seconds": settings.scheduler_tick_seconds,
        "notify": {
            "webhook": mask(settings.notify.get("webhook", "")),
            "pushplus": mask(settings.notify.get("pushplus", "")),
            "serverchan": mask(settings.notify.get("serverchan", "")),
            "ntfy": mask(settings.notify.get("ntfy", "")),
            "events": settings.notify.get("events", ""),
        },
        "ai": {
            "base_url": settings.ai.get("base_url", ""),
            "model": settings.ai.get("model", ""),
            "configured": bool(settings.ai.get("api_key")),
        },
        "app_env": settings.app_env,
        "database": settings.database_url.split("///")[0],
    }


@router.post("/notify-test")
def notify_test(payload: NotifyTest, _: AdminUser) -> dict:
    from ..services.notifier import notify

    sent = notify(payload.title, payload.body, event="verification_required")
    return {"sent": sent, "message": "已发送" if sent else "没有启用的通道（检查 NOTIFY_* 配置）"}


@router.get("/settings/ai")
def get_ai_settings(_: AdminUser, db: DbSession) -> dict:
    return ai_service.resolve_config(db).public()


@router.put("/settings/ai")
def put_ai_settings(payload: AISettingsIn, _: AdminUser, db: DbSession) -> dict:
    config = ai_service.save_config(db, payload.model_dump())
    return config.public()


@router.post("/settings/ai/test")
def test_ai_settings(payload: AIProbeIn, _: AdminUser, db: DbSession) -> dict:
    override = payload.model_dump()
    if not override.get("api_key"):
        override["api_key"] = ai_service.resolve_config(db).api_key
    return ai_service.test_connection(db, override if override.get("base_url") else None)


@router.delete("/settings/ai")
def clear_ai_settings(_: AdminUser, db: DbSession) -> dict:
    ai_service.clear_config(db)
    return {"message": "已清除，回退到环境变量配置"}


@router.get("/summary")
def summary(user: CurrentUser, db: DbSession) -> dict:
    return scheduler.summary_counts(db)
