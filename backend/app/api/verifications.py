"""Verification center API: captcha hand-off and one-shot continuation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..services import clockin, verifications
from .deps import CurrentUser, DbSession, account_for_user, visible_account_ids
from .schemas import CaptchaPoints

router = APIRouter(prefix="/verifications", tags=["verifications"])


def _load(db, user, session_id: str):
    try:
        return verifications.get(db, session_id, account_ids=visible_account_ids(db, user))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("")
def list_verifications(
    user: CurrentUser,
    db: DbSession,
    include_closed: bool = Query(default=False),
) -> list[dict]:
    return verifications.list_sessions(
        db, account_ids=visible_account_ids(db, user), include_closed=include_closed
    )


@router.get("/{session_id}")
def get_verification(session_id: str, user: CurrentUser, db: DbSession) -> dict:
    return verifications.public_view(db, _load(db, user, session_id))


@router.post("/{session_id}/check")
def check_verification(session_id: str, user: CurrentUser, db: DbSession) -> dict:
    row = _load(db, user, session_id)
    try:
        return verifications.check(db, row)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{session_id}/confirm")
def confirm_verification(session_id: str, user: CurrentUser, db: DbSession) -> dict:
    """User states the official verification is done → verify, then resume once."""
    row = _load(db, user, session_id)
    try:
        return verifications.resume(db, row)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{session_id}/captcha/refresh")
def refresh_captcha(session_id: str, user: CurrentUser, db: DbSession) -> dict:
    row = _load(db, user, session_id)
    if row.verification_type != "captcha":
        raise HTTPException(400, "该任务不是验证码类型")
    account = account_for_user(db, user, row.account_id)
    try:
        return clockin.refresh_captcha(db, row, account)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"刷新验证码失败：{type(exc).__name__}") from exc


@router.post("/{session_id}/captcha")
def submit_captcha(session_id: str, payload: CaptchaPoints, user: CurrentUser, db: DbSession) -> dict:
    row = _load(db, user, session_id)
    if row.verification_type != "captcha":
        raise HTTPException(400, "该任务不是验证码类型")
    account = account_for_user(db, user, row.account_id)
    try:
        result = clockin.complete_captcha(db, account, row, payload.points)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"验证码处理失败：{type(exc).__name__}") from exc
    return {"result": result.to_dict(), "session": verifications.public_view(db, row)}


@router.post("/{session_id}/dismiss")
def dismiss_verification(session_id: str, user: CurrentUser, db: DbSession) -> dict:
    row = _load(db, user, session_id)
    try:
        return verifications.dismiss(db, row)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
