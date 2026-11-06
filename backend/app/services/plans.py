"""Writing plans (outlines) for daily / weekly / monthly reports.

A plan is a list of dated items generated from the account's position and
responsibilities. Report generation consumes the item for that date, so the
AI writes a coherent series instead of inventing each day independently.

If AI is not configured (or fails), a deterministic template outline is created
and marked ``source="template"``; the UI shows which one was used.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Account, ReportDraft, ReportPlan
from . import ai

logger = logging.getLogger(__name__)

KIND_LABEL = {"week": "周", "month": "月"}


def _parse_day(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def working_days(start: dt.date, end: dt.date, weekdays: str) -> list[str]:
    allowed = {item.strip() for item in (weekdays or "").split(",") if item.strip()}
    days: list[str] = []
    cursor = start
    while cursor <= end:
        if not allowed or str(cursor.isoweekday()) in allowed:
            days.append(cursor.isoformat())
        cursor += dt.timedelta(days=1)
    return days


def _range(kind: str, start: dt.date) -> tuple[dt.date, dt.date]:
    if kind == "week":
        return start, start + dt.timedelta(days=6)
    if kind == "month":
        first = start.replace(day=1)
        nxt = dt.date(first.year + 1, 1, 1) if first.month == 12 else dt.date(first.year, first.month + 1, 1)
        return first, nxt - dt.timedelta(days=1)
    raise ValueError("kind 只能是 week 或 month")


def _responsibilities(account: Account) -> list[str]:
    raw = str((account.profile or {}).get("responsibilities") or "")
    parts = [item.strip() for item in re.split(r"[。；;\n、]+", raw) if item.strip()]
    return parts[:8] or ["完成岗位日常工作", "记录工作过程与问题"]


def _tools(account: Account) -> list[str]:
    raw = str((account.profile or {}).get("tools") or "")
    return [item.strip() for item in re.split(r"[,，、;；\n]+", raw) if item.strip()][:6]


def fallback_outline(account: Account, kind: str, dates: list[str]) -> tuple[str, list[dict[str, Any]]]:
    """Deterministic outline so the feature still works without AI."""
    duties = _responsibilities(account)
    tools = _tools(account)
    stages = [
        ("熟悉与准备", "梳理任务背景，确认交付标准"),
        ("执行与推进", "独立完成分配任务，记录过程"),
        ("检查与复盘", "复核结果，整理问题与改进点"),
    ]
    items: list[dict[str, Any]] = []
    for index, day in enumerate(dates):
        stage, stage_task = stages[min(index * len(stages) // max(1, len(dates)), len(stages) - 1)]
        duty = duties[index % len(duties)]
        tasks = [duty, stage_task]
        if tools:
            tool = tools[index % len(tools)]
            tasks.append(f"使用{tool}完成当天工作并留存记录")
        items.append(
            {
                "date": day,
                "theme": f"{stage}：{duty[:24]}",
                "tasks": tasks,
                "key_points": stage_task,
            }
        )
    title = f"{dates[0]} 起实习{KIND_LABEL.get(kind, '')}写作计划"
    return title, items


def create_outline(
    db: Session,
    account: Account,
    *,
    kind: str,
    start: dt.date,
    notes: str = "",
    use_ai: bool = True,
) -> ReportPlan:
    start_day, end_day = _range(kind, start)
    dates = working_days(start_day, end_day, account.weekdays)
    if not dates:
        raise ValueError("所选周期内没有匹配的工作日（检查账号的执行星期）")

    title = ""
    items: list[dict[str, Any]] = []
    source = "template"
    if use_ai:
        try:
            title, items, source = ai.generate_outline(
                db,
                account,
                kind=kind,
                start_date=start_day.isoformat(),
                end_date=end_day.isoformat(),
                dates=dates,
                notes=notes,
            )
        except ai.AIError as exc:
            logger.info("outline AI unavailable: %s", str(exc)[:120])
            source = "template"
    if not items:
        title, items = fallback_outline(account, kind, dates)
        source = "template"

    plan = ReportPlan(
        account_id=account.id,
        kind=kind,
        start_date=start_day.isoformat(),
        end_date=end_day.isoformat(),
        title=title[:200],
        items=items,
        source=source,
        status="active",
    )
    db.add(plan)
    # Older overlapping plans stay in the database but are archived so lookups
    # never pick two outlines for the same day.
    for old in db.scalars(
        select(ReportPlan)
        .where(ReportPlan.account_id == account.id)
        .where(ReportPlan.status == "active")
        .where(ReportPlan.start_date <= end_day.isoformat())
        .where(ReportPlan.end_date >= start_day.isoformat())
    ).all():
        old.status = "archived"
        db.add(old)
    db.commit()
    db.refresh(plan)
    return plan


def _draft_status(db: Session, plan: ReportPlan) -> dict[str, dict[str, Any]]:
    rows = db.scalars(
        select(ReportDraft)
        .where(ReportDraft.account_id == plan.account_id)
        .where(ReportDraft.plan_id == plan.id)
        .order_by(ReportDraft.created_at.desc())
    ).all()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.plan_date or ""
        if not key or key in result:
            continue
        result[key] = {"draft_id": row.id, "status": row.status, "title": row.title}
    return result


def plan_view(db: Session, plan: ReportPlan) -> dict[str, Any]:
    statuses = _draft_status(db, plan)
    items = []
    for index, item in enumerate(plan.items or []):
        day = str(item.get("date") or "")
        status = statuses.get(day, {})
        items.append({"index": index, **item, "draft": status or None})
    return {
        "id": plan.id,
        "account_id": plan.account_id,
        "kind": plan.kind,
        "start_date": plan.start_date,
        "end_date": plan.end_date,
        "title": plan.title,
        "source": plan.source,
        "status": plan.status,
        "items": items,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "progress": {
            "total": len(items),
            "drafted": sum(1 for item in items if item["draft"]),
            "submitted": sum(
                1 for item in items if item["draft"] and item["draft"].get("status") == "submitted"
            ),
        },
    }


def list_plans(db: Session, account_id: int, *, limit: int = 12) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ReportPlan)
        .where(ReportPlan.account_id == account_id)
        .order_by(ReportPlan.created_at.desc())
        .limit(limit)
    ).all()
    return [plan_view(db, row) for row in rows]


def get_plan(db: Session, plan_id: int, account_id: int | None = None) -> ReportPlan:
    plan = db.get(ReportPlan, plan_id)
    if plan is None or (account_id is not None and plan.account_id != account_id):
        raise LookupError("写作计划不存在")
    return plan


def update_item(
    db: Session,
    plan: ReportPlan,
    index: int,
    *,
    theme: str | None = None,
    tasks: list[str] | None = None,
    key_points: str | None = None,
) -> ReportPlan:
    items = list(plan.items or [])
    if index < 0 or index >= len(items):
        raise IndexError("计划条目不存在")
    item = dict(items[index])
    if theme is not None:
        item["theme"] = theme.strip()[:80]
    if tasks is not None:
        item["tasks"] = [str(task).strip()[:120] for task in tasks if str(task).strip()][:6]
    if key_points is not None:
        item["key_points"] = key_points.strip()[:160]
    items[index] = item
    plan.items = items
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def archive_plan(db: Session, plan: ReportPlan) -> ReportPlan:
    plan.status = "archived"
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def delete_plan(db: Session, plan: ReportPlan) -> None:
    db.delete(plan)
    db.commit()


def item_for(db: Session, account_id: int, day: str) -> tuple[ReportPlan | None, dict[str, Any] | None, int | None]:
    """Newest active plan covering ``day``; returns (plan, item, index)."""
    plans = db.scalars(
        select(ReportPlan)
        .where(ReportPlan.account_id == account_id)
        .where(ReportPlan.status == "active")
        .where(ReportPlan.start_date <= day)
        .where(ReportPlan.end_date >= day)
        .order_by(ReportPlan.created_at.desc())
    ).all()
    for plan in plans:
        for index, item in enumerate(plan.items or []):
            if str(item.get("date") or "") == day:
                return plan, dict(item), index
    return None, None, None


def period_items(db: Session, account_id: int, start: str, end: str) -> list[dict[str, Any]]:
    plans = db.scalars(
        select(ReportPlan)
        .where(ReportPlan.account_id == account_id)
        .where(ReportPlan.status == "active")
        .where(ReportPlan.end_date >= start)
        .where(ReportPlan.start_date <= end)
        .order_by(ReportPlan.created_at.desc())
    ).all()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for plan in plans:
        for item in plan.items or []:
            day = str(item.get("date") or "")
            if start <= day <= end and day not in seen:
                seen.add(day)
                items.append(dict(item))
    return sorted(items, key=lambda item: item.get("date") or "")
