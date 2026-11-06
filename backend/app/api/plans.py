"""Writing plans: generate outlines, edit items, list progress."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from ..models import Account, User
from ..services import plans
from ..settings import get_settings
from .deps import CurrentUser, DbSession, account_for_user
from .schemas import PlanItemUpdate, PlanOutlineRequest, PlanUpdate

router = APIRouter(tags=["plans"])


def _plan(db: Session, user: User, plan_id: int):
    try:
        plan = plans.get_plan(db, plan_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    account_for_user(db, user, plan.account_id)
    return plan


@router.get("/accounts/{account_id}/plans")
def list_plans(account_id: int, user: CurrentUser, db: DbSession) -> list[dict]:
    account_for_user(db, user, account_id)
    return plans.list_plans(db, account_id)


@router.post("/accounts/{account_id}/plans", status_code=201)
def create_outline(account_id: int, payload: PlanOutlineRequest, user: CurrentUser, db: DbSession) -> dict:
    account: Account = account_for_user(db, user, account_id)
    if payload.start_date:
        try:
            start = dt.date.fromisoformat(payload.start_date)
        except ValueError as exc:
            raise HTTPException(400, "日期格式应为 YYYY-MM-DD") from exc
    else:
        start = dt.datetime.now(get_settings().tz).date()
    try:
        plan = plans.create_outline(
            db,
            account,
            kind=payload.kind,
            start=start,
            notes=payload.notes,
            use_ai=payload.use_ai,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return plans.plan_view(db, plan)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, user: CurrentUser, db: DbSession) -> dict:
    return plans.plan_view(db, _plan(db, user, plan_id))


@router.patch("/plans/{plan_id}")
def update_plan(plan_id: int, payload: PlanUpdate, user: CurrentUser, db: DbSession) -> dict:
    plan = _plan(db, user, plan_id)
    if payload.title is not None:
        plan.title = payload.title.strip()[:200]
    if payload.status is not None:
        plan.status = payload.status
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plans.plan_view(db, plan)


@router.patch("/plans/{plan_id}/items/{index}")
def update_item(plan_id: int, index: int, payload: PlanItemUpdate, user: CurrentUser, db: DbSession) -> dict:
    plan = _plan(db, user, plan_id)
    try:
        plans.update_item(
            db,
            plan,
            index,
            theme=payload.theme,
            tasks=payload.tasks,
            key_points=payload.key_points,
        )
    except IndexError as exc:
        raise HTTPException(404, str(exc)) from exc
    db.refresh(plan)
    return plans.plan_view(db, plan)


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, user: CurrentUser, db: DbSession) -> dict:
    plan = _plan(db, user, plan_id)
    plans.delete_plan(db, plan)
    return {"message": "已删除"}
