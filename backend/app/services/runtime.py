"""Per-account runtime: build a client, log in, refresh plan, record executions."""

from __future__ import annotations

import json
import logging
import datetime as dt
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from ..gxy.client import GxyClient, GxyResponse, SessionState
from ..gxy.captcha import CaptchaSolver
from ..gxy.errors import GxyAuthError, GxyError
from ..gxy.models import LoginUser, PlanSummary, pick_plan
from ..models import Account, Execution, utcnow
from ..security import decrypt_secret, encrypt_secret
from ..settings import get_settings

logger = logging.getLogger(__name__)


class LoginRequired(RuntimeError):
    """The stored session is unusable and the caller must log in first."""


@dataclass
class ExecutionResult:
    execution: Execution
    response: GxyResponse | None = None


def device_state(account: Account) -> str:
    return str((account.device or {}).get("state") or "mobile")


def device_brand(account: Account) -> str:
    return str((account.device or {}).get("brand") or "Android")


def device_system_version(account: Account) -> str:
    return str((account.device or {}).get("systemVersion") or "13")


def build_client(account: Account) -> GxyClient:
    settings = get_settings()
    stored = None
    if account.session_enc:
        try:
            stored = json.loads(decrypt_secret(account.session_enc))
        except ValueError:
            logger.warning("account %s session cannot be decrypted; will re-login", account.id)
            stored = None
    return GxyClient(
        session=SessionState.from_store(stored),
        captcha=CaptchaSolver.from_settings(settings.captcha_model_dir),
        timeout=settings.gxy_timeout_seconds,
        package_version=settings.gxy_package_version,
        build_number=settings.gxy_build_number,
        code_version=settings.gxy_code_version,
    )


def persist_session(db: Session, account: Account, client: GxyClient) -> None:
    account.session_enc = encrypt_secret(json.dumps(client.session.to_store(), ensure_ascii=False))
    account.session_updated_at = utcnow()
    db.add(account)


def login_account(db: Session, account: Account, client: GxyClient) -> LoginUser:
    password = decrypt_secret(account.password_enc)
    user, _ = client.login(
        account.phone,
        password,
        system=device_brand(account),
        system_version=device_system_version(account),
    )
    persist_session(db, account, client)
    account.last_status = "logged_in"
    account.last_message = "登录成功"
    db.add(account)
    db.commit()
    return user


def ensure_login(db: Session, account: Account, client: GxyClient) -> LoginUser:
    if client.session.ready:
        return LoginUser(
            user_id=client.session.user_id,
            token=client.session.token,
            role_key=client.session.role_key,
            user_type=client.session.user_type,
        )
    return login_account(db, account, client)


def refresh_plan(db: Session, account: Account, client: GxyClient) -> PlanSummary | None:
    plan = client.fetch_plan()
    if plan:
        account.plan = dict(plan.raw)
        account.plan_updated_at = utcnow()
        db.add(account)
        db.commit()
    return plan


def cached_plan(account: Account) -> PlanSummary | None:
    return pick_plan([account.plan]) if account.plan else None


# --------------------------------------------------------------------- locks
def acquire_lock(db: Session, account_id: int, owner: str, ttl_seconds: int) -> bool:
    """Compare-and-set lock so one account never runs two writes at once."""
    now = time.time()
    result = db.execute(
        update(Account)
        .where(Account.id == account_id)
        .where(or_(Account.locked_until < now, Account.lock_owner == owner, Account.lock_owner == ""))
        .values(lock_owner=owner, locked_until=now + ttl_seconds)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return bool(result.rowcount)


def release_lock(db: Session, account_id: int, owner: str) -> None:
    db.execute(
        update(Account)
        .where(Account.id == account_id, Account.lock_owner == owner)
        .values(lock_owner="", locked_until=0.0)
        .execution_options(synchronize_session=False)
    )
    db.commit()


# ---------------------------------------------------------------- executions
def start_execution(
    db: Session,
    account: Account,
    *,
    kind: str,
    trigger: str,
    target_date: str = "",
    message: str = "",
    subtype: str = "",
) -> Execution:
    execution = Execution(
        account_id=account.id,
        kind=kind,
        subtype=subtype,
        trigger=trigger,
        status="running",
        target_date=target_date,
        message=message,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def finish_execution(
    db: Session,
    execution: Execution,
    *,
    status: str,
    message: str,
    detail: dict[str, Any] | None = None,
    account: Account | None = None,
) -> Execution:
    execution.status = status
    execution.message = (message or "")[:500]
    if detail is not None:
        execution.detail = detail
    execution.finished_at = utcnow()
    started = execution.created_at
    if started is not None:
        # SQLite returns naive datetimes even for timezone=True columns.
        if started.tzinfo is None:
            started = started.replace(tzinfo=dt.timezone.utc)
        delta = (execution.finished_at - started).total_seconds()
        execution.duration_ms = max(0, int(delta * 1000))
    db.add(execution)
    if account is not None:
        account.last_status = status
        account.last_message = (message or "")[:255]
        account.last_run_at = execution.finished_at
        db.add(account)
    db.commit()
    return execution


def safe_error_message(exc: Exception) -> str:
    """Never leak tokens/ciphertext from an exception repr into logs or the UI."""
    if isinstance(exc, GxyAuthError):
        return "登录已失效，请重新登录"
    if isinstance(exc, GxyError):
        return str(exc)[:300]
    return f"{type(exc).__name__}: {str(exc)[:200]}"
