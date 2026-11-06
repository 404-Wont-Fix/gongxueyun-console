"""Report listing, drafting and submission."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..gxy.errors import GxyError
from ..models import ReportDraft
from ..services import reports, runtime
from ..settings import get_settings
from .deps import CurrentUser, DbSession, account_for_user
from .schemas import ReportDraftRequest, ReportDraftUpdate

router = APIRouter(tags=["reports"])


def _draft_for_user(db, user, draft_id: int) -> ReportDraft:
    draft = db.get(ReportDraft, draft_id)
    if draft is None:
        raise HTTPException(404, "草稿不存在")
    account_for_user(db, user, draft.account_id)
    return draft


@router.get("/accounts/{account_id}/reports")
def list_remote_reports(
    account_id: int,
    user: CurrentUser,
    db: DbSession,
    type: str = Query(default="day"),
) -> dict:
    account = account_for_user(db, user, account_id)
    try:
        items = reports.remote_reports(db, account, type)
    except (GxyError, ValueError) as exc:
        raise HTTPException(400, runtime.safe_error_message(exc)) from exc
    return {
        "type": type,
        "items": [
            {
                "reportId": item.get("reportId"),
                "title": item.get("title"),
                "reportType": item.get("reportType"),
                "state": item.get("state"),
                "createTime": item.get("createTime"),
                "startTime": item.get("startTime"),
                "endTime": item.get("endTime"),
                "content": (item.get("content") or "")[:400],
            }
            for item in items
            if isinstance(item, dict)
        ],
    }


@router.get("/accounts/{account_id}/reports/weeks")
def list_weeks(account_id: int, user: CurrentUser, db: DbSession) -> dict:
    account = account_for_user(db, user, account_id)
    try:
        return {"weeks": reports.week_options(db, account)}
    except (GxyError, ValueError) as exc:
        raise HTTPException(400, runtime.safe_error_message(exc)) from exc


@router.get("/accounts/{account_id}/drafts")
def list_drafts(account_id: int, user: CurrentUser, db: DbSession) -> list[dict]:
    account = account_for_user(db, user, account_id)
    return reports.list_drafts(db, account.id)


@router.post("/accounts/{account_id}/drafts", status_code=201)
def create_draft(account_id: int, payload: ReportDraftRequest, user: CurrentUser, db: DbSession) -> dict:
    account = account_for_user(db, user, account_id)
    try:
        day = dt.date.fromisoformat(payload.day) if payload.day else dt.date.today()
    except ValueError as exc:
        raise HTTPException(400, "日期格式应为 YYYY-MM-DD") from exc
    draft = reports.build_draft(
        db, account, report_type=payload.report_type, day=day, notes=payload.notes, use_ai=payload.use_ai
    )
    return reports.draft_view(draft)


@router.patch("/drafts/{draft_id}")
def update_draft(draft_id: int, payload: ReportDraftUpdate, user: CurrentUser, db: DbSession) -> dict:
    draft = _draft_for_user(db, user, draft_id)
    if draft.status == "submitted":
        raise HTTPException(409, "已提交的草稿不能再修改")
    if payload.title is not None:
        draft.title = payload.title[:200]
    if payload.content is not None:
        draft.content = payload.content
    if payload.form_fields is not None:
        draft.form_fields = payload.form_fields
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return reports.draft_view(draft)


@router.post("/drafts/{draft_id}/submit")
def submit_draft(draft_id: int, user: CurrentUser, db: DbSession) -> dict:
    draft = _draft_for_user(db, user, draft_id)
    if not draft.content.strip():
        raise HTTPException(400, "正文不能为空")
    result = reports.submit_draft(db, draft)
    return result


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: int, user: CurrentUser, db: DbSession) -> dict:
    draft = _draft_for_user(db, user, draft_id)
    if draft.status == "submitted":
        raise HTTPException(409, "已提交的草稿不能删除")
    db.delete(draft)
    db.commit()
    return {"message": "已删除"}


@router.get("/accounts/{account_id}/reports/summary")
def report_summary(account_id: int, user: CurrentUser, db: DbSession) -> dict:
    """Counts by type from the local draft table (remote list is paginated)."""
    account = account_for_user(db, user, account_id)
    rows = db.scalars(select(ReportDraft).where(ReportDraft.account_id == account.id)).all()
    counts: dict[str, int] = {}
    for row in rows:
        if row.status == "submitted":
            counts[row.report_type] = counts.get(row.report_type, 0) + 1
    return {"submitted": counts, "timezone": str(get_settings().tz)}
