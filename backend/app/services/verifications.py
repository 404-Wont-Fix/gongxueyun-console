"""Verification sessions: paused clock-ins that need a human step.

Lifecycle::

    captcha_required ──(points)──> retry ──> success / verification_required
    awaiting_verification (304 account risk)
        ──(user confirms, queryAxdj ok)──> resume once ──> record_confirmed
    awaiting_verification (303 face)
        ──(user confirms, record still missing)──> resend original body once
                                                   ──> record_confirmed

Rules that protect the account:

* the original request body is stored encrypted and never returned by the API;
* the continuation write is claimed in the database **before** it is sent;
* ``queryAxdj`` returning 200 means "verification acknowledged", never "attendance
  exists" — the attendance row is queried separately;
* a record-query failure never triggers a resend.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any
from urllib.parse import quote

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..gxy.errors import GxyError
from ..models import Account, VerificationSession, utcnow
from ..security import decrypt_secret
from ..settings import get_settings
from . import clockin, runtime
from .notifier import notify

logger = logging.getLogger(__name__)

TERMINAL = {"record_confirmed", "cancelled", "expired", "failed", "superseded"}


def _account(db: Session, session_obj: VerificationSession) -> Account:
    account = db.get(Account, session_obj.account_id)
    if account is None:
        raise ValueError("账号已被删除")
    return account


def browser_link(register_url: str) -> str:
    return f"https://ds.alipay.com/?scheme={quote(register_url, safe='')}"


def public_view(db: Session, session_obj: VerificationSession) -> dict[str, Any]:
    account = db.get(Account, session_obj.account_id)
    expired = time.time() >= session_obj.expires_at and session_obj.state not in TERMINAL
    snapshot = clockin.load_payload(session_obj) if session_obj.payload_enc else {}
    link = ""
    if session_obj.register_url_enc:
        try:
            link = decrypt_secret(session_obj.register_url_enc)
        except ValueError:
            link = ""
    return {
        "id": session_obj.id,
        "account_id": session_obj.account_id,
        "account_label": (account.label if account else "") or (account.phone if account else ""),
        "kind": session_obj.kind,
        "target_date": session_obj.target_date,
        "verification_type": session_obj.verification_type,
        "state": "expired" if expired else session_obj.state,
        "verification_confirmed": session_obj.verification_confirmed,
        "record_confirmed": session_obj.record_confirmed,
        "resume_attempted": session_obj.resume_attempted,
        "resume_state": session_obj.resume_state,
        "attempts": session_obj.attempts,
        "server_time": session_obj.server_time,
        "created_at": session_obj.created_at.isoformat() if session_obj.created_at else None,
        "expires_at": session_obj.expires_at,
        "last_checked_at": session_obj.last_checked_at,
        "has_link": bool(link),
        "link": link,
        "browser_link": browser_link(link) if link else "",
        "captcha": clockin.public_captcha(snapshot) if session_obj.state == "captcha_required" else None,
        "note": snapshot.get("reason") or "",
        "can_resume": (
            session_obj.state == "awaiting_verification"
            and not session_obj.resume_attempted
            and time.time() < session_obj.expires_at
        ),
    }


def list_sessions(db: Session, *, account_ids: list[int], include_closed: bool = False) -> list[dict[str, Any]]:
    if not account_ids:
        return []
    stmt = select(VerificationSession).where(VerificationSession.account_id.in_(account_ids))
    if not include_closed:
        stmt = stmt.where(VerificationSession.state.not_in(list(TERMINAL)))
    stmt = stmt.order_by(VerificationSession.created_at.desc()).limit(100)
    return [public_view(db, row) for row in db.scalars(stmt)]


def get(db: Session, session_id: str, *, account_ids: list[int]) -> VerificationSession:
    row = db.get(VerificationSession, session_id)
    if row is None or row.account_id not in account_ids:
        raise LookupError("验证任务不存在")
    return row


def _expire_if_needed(db: Session, session_obj: VerificationSession) -> None:
    if time.time() >= session_obj.expires_at and session_obj.state not in TERMINAL:
        session_obj.state = "expired"
        session_obj.payload_enc = ""
        session_obj.register_url_enc = ""
        session_obj.out_register_no_enc = ""
        db.add(session_obj)
        db.commit()


def check(db: Session, session_obj: VerificationSession) -> dict[str, Any]:
    """Read-only poll: verification status + attendance record. Never writes attendance."""
    _expire_if_needed(db, session_obj)
    account = _account(db, session_obj)
    client = runtime.build_client(account)
    try:
        runtime.ensure_login(db, account, client)
    except Exception as exc:
        raise ValueError(f"登录已失效：{runtime.safe_error_message(exc)}") from exc

    if session_obj.verification_type == "account" and session_obj.out_register_no_enc:
        if not session_obj.verification_confirmed:
            try:
                registration = decrypt_secret(session_obj.out_register_no_enc)
                response = client.query_alipay_registration(registration)
                session_obj.verification_confirmed = clockin.query_succeeded(response)
            except (GxyError, ValueError) as exc:
                logger.info("queryAxdj failed: %s", type(exc).__name__)

    confirmed, server_time, state = clockin.confirm_record(
        db, account, client, session_obj.target_date, session_obj.kind, attempts=1
    )
    session_obj.last_checked_at = time.time()
    session_obj.updated_at = utcnow()
    if confirmed:
        return _mark_confirmed(db, session_obj, account, server_time)
    if state == "query_failed":
        session_obj.resume_state = "record_query_failed"
    db.add(session_obj)
    db.commit()
    return public_view(db, session_obj)


def resume(db: Session, session_obj: VerificationSession, *, trigger: str = "manual") -> dict[str, Any]:
    """Verify (or record-check) → claim → send once → re-query. Never loops."""
    _expire_if_needed(db, session_obj)
    if session_obj.state in TERMINAL:
        return {"status": "terminal", "view": public_view(db, session_obj)}
    if session_obj.verification_type == "captcha":
        raise ValueError("该任务需要先完成点选验证码")
    if session_obj.resume_attempted:
        return {"status": "already_attempted", "view": public_view(db, session_obj)}

    account = _account(db, session_obj)
    owner = uuid.uuid4().hex
    if not runtime.acquire_lock(db, account.id, owner, get_settings().task_lock_seconds):
        return {"status": "busy", "message": "该账号正在执行其他任务，请稍后再试",
                "view": public_view(db, session_obj)}
    try:
        client = runtime.build_client(account)
        try:
            runtime.ensure_login(db, account, client)
        except Exception as exc:
            raise ValueError(f"登录已失效：{runtime.safe_error_message(exc)}") from exc

        # 1) 304: only continue when the official side acknowledged the verification.
        if session_obj.verification_type == "account":
            if session_obj.out_register_no_enc:
                try:
                    registration = decrypt_secret(session_obj.out_register_no_enc)
                    response = client.query_alipay_registration(registration)
                except GxyError as exc:
                    raise ValueError(f"查询安全验证状态失败：{runtime.safe_error_message(exc)}") from exc
                except ValueError as exc:
                    raise ValueError(str(exc)) from exc
                if clockin.query_succeeded(response):
                    session_obj.verification_confirmed = True
            session_obj.last_checked_at = time.time()
            db.add(session_obj)
            db.commit()
            if not session_obj.verification_confirmed:
                return {"status": "verification_not_confirmed", "view": public_view(db, session_obj)}

        # 2) Maybe the first request already landed (verification completed late).
        confirmed, server_time, state = clockin.confirm_record(
            db, account, client, session_obj.target_date, session_obj.kind, attempts=2, delay=1.0
        )
        if confirmed:
            return {"status": "record_confirmed", "view": _mark_confirmed(db, session_obj, account, server_time)}
        if state == "query_failed" and session_obj.verification_type == "face":
            # For a face retry we will not send blind when we cannot read records.
            return {"status": "record_query_failed",
                    "message": "考勤记录查询失败，未重提；请稍后先检查记录",
                    "view": public_view(db, session_obj)}

        # 3) Claim the single continuation, then send it.
        claimed = db.execute(
            update(VerificationSession)
            .where(VerificationSession.id == session_obj.id, VerificationSession.resume_attempted.is_(False))
            .values(resume_attempted=True, resume_state="sending", updated_at=utcnow())
            .execution_options(synchronize_session=False)
        ).rowcount
        db.commit()
        db.refresh(session_obj)
        if not claimed:
            return {"status": "already_attempted", "view": public_view(db, session_obj)}

        snapshot = clockin.load_payload(session_obj)
        body = dict(snapshot.get("body") or {})
        if not body:
            session_obj.state = "failed"
            session_obj.resume_state = "context_missing"
            db.add(session_obj)
            db.commit()
            return {"status": "context_missing", "view": public_view(db, session_obj)}

        if session_obj.verification_type == "account":
            registration = ""
            if session_obj.out_register_no_enc:
                registration = decrypt_secret(session_obj.out_register_no_enc)
            if registration:
                body["outRegisterNo"] = registration
            if isinstance(snapshot.get("response_data"), dict) and snapshot["response_data"].get("attendanceId"):
                body["attendanceId"] = snapshot["response_data"]["attendanceId"]

        replace = bool(snapshot.get("replace"))
        try:
            response = client.save_attendance(
                body, replace=replace, teacher=(client.session.user_type or "").lower() == "teacher"
            )
        except GxyError as exc:
            session_obj.resume_state = "uncertain"
            db.add(session_obj)
            db.commit()
            return {
                "status": "uncertain",
                "message": f"续提结果未知（{runtime.safe_error_message(exc)}），请先检查考勤记录",
                "view": public_view(db, session_obj),
            }

        if response.marker in {"302", "303", "304"}:
            session_obj.resume_state = "verification_required_again"
            session_obj.state = "awaiting_verification"
            session_obj.updated_at = utcnow()
            db.add(session_obj)
            db.commit()
            return {"status": "verification_required_again", "view": public_view(db, session_obj)}

        confirmed, server_time, state = clockin.confirm_record(
            db, account, client, session_obj.target_date, session_obj.kind, attempts=3, delay=1.5
        )
        session_obj.last_checked_at = time.time()
        if confirmed:
            return {"status": "record_confirmed", "view": _mark_confirmed(db, session_obj, account, server_time)}
        session_obj.resume_state = "submitted_unconfirmed" if response.ok else "rejected"
        session_obj.state = "submitted_unconfirmed" if response.ok else "failed"
        db.add(session_obj)
        db.commit()
        return {
            "status": session_obj.resume_state,
            "message": "" if response.ok else f"续提被拒绝：code={response.code} msg={response.msg}",
            "view": public_view(db, session_obj),
        }
    finally:
        runtime.release_lock(db, account.id, owner)


def _mark_confirmed(
    db: Session, session_obj: VerificationSession, account: Account, server_time: str
) -> dict[str, Any]:
    session_obj.state = "record_confirmed"
    session_obj.record_confirmed = True
    session_obj.verification_confirmed = True
    session_obj.resume_state = "confirmed"
    session_obj.server_time = server_time
    session_obj.payload_enc = ""
    session_obj.register_url_enc = ""
    session_obj.out_register_no_enc = ""
    db.add(session_obj)
    account.last_status = clockin.SUCCESS
    account.last_message = f"{session_obj.target_date} {session_obj.kind} 已确认"
    db.add(account)
    db.commit()
    notify(
        f"工学云 {account.label or account.phone} 打卡已确认",
        f"{session_obj.target_date} {session_obj.kind} 已由服务端记录确认。",
        event="daily_summary",
        account_notify=account.notify,
    )
    return public_view(db, session_obj)


def dismiss(db: Session, session_obj: VerificationSession) -> dict[str, Any]:
    if session_obj.record_confirmed:
        raise ValueError("已确认的记录不能取消")
    session_obj.state = "cancelled"
    session_obj.payload_enc = ""
    session_obj.register_url_enc = ""
    session_obj.out_register_no_enc = ""
    db.add(session_obj)
    db.commit()
    return public_view(db, session_obj)


def auto_resume_due(db: Session, *, limit: int = 20) -> int:
    """Scheduler hook: continue account sessions whose verification is confirmed."""
    now = time.time()
    rows = db.scalars(
        select(VerificationSession)
        .where(VerificationSession.state == "awaiting_verification")
        .where(VerificationSession.expires_at > now)
        .where(VerificationSession.resume_attempted.is_(False))
        .where(VerificationSession.verification_type == "account")
        .where(VerificationSession.out_register_no_enc != "")
        .order_by(VerificationSession.created_at)
        .limit(limit)
    ).all()
    done = 0
    for row in rows:
        try:
            result = resume(db, row, trigger="auto")
            if result["status"] in {"record_confirmed", "submitted_unconfirmed", "verification_required_again"}:
                done += 1
        except Exception as exc:  # noqa: BLE001 - one broken session must not stop the scan
            logger.warning("auto resume failed for %s: %s", row.id, type(exc).__name__)
            db.rollback()
    return done


def poll_active_sessions(db: Session, *, limit: int = 20) -> int:
    """Refresh state for sessions still awaiting verification (read-only)."""
    now = time.time()
    rows = db.scalars(
        select(VerificationSession)
        .where(VerificationSession.state == "awaiting_verification")
        .where(VerificationSession.expires_at > now)
        .where(now - VerificationSession.last_checked_at > 8)
        .order_by(VerificationSession.created_at)
        .limit(limit)
    ).all()
    for row in rows:
        try:
            check(db, row)
        except Exception as exc:  # noqa: BLE001
            logger.info("session poll skipped for %s: %s", row.id, type(exc).__name__)
            db.rollback()
    return len(rows)
