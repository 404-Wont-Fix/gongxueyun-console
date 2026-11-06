"""Daily / weekly / monthly report assistance.

Flow: list existing reports → build a draft (template, optionally AI) → submit via
``practice/paper/v6/save`` → re-list to confirm. "Submitted" is only reported when
the report shows up in the list; the write itself is never retried.

Period semantics are taken from the newer repositories *and* the APK model:

* ``day``    — no start/end, only ``reportTime``;
* ``week``   — Monday 00:00:00 .. Sunday 23:59:59 plus ``weeks == "第N周"``,
               where N continues the submitted list (27xk / Huee1213 behaviour);
* ``month``  — only ``yearmonth == "YYYY-MM"``;
* ``summary``— same model, no period fields.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..gxy.client import GxyClient
from ..gxy.constants import REPORT_FORM_TYPES
from ..gxy.errors import GxyError
from ..models import Account, ReportDraft, utcnow
from ..settings import get_settings
from . import ai, plans, runtime
from .notifier import notify

logger = logging.getLogger(__name__)

TYPE_LABELS = {"day": "日报", "week": "周报", "month": "月报", "summary": "总结"}
PERIOD_FMT = "%Y-%m-%d"


def _client(db: Session, account: Account) -> GxyClient:
    client = runtime.build_client(account)
    runtime.ensure_login(db, account, client)
    return client


def _plan_id(db: Session, account: Account, client: GxyClient) -> str:
    plan = runtime.cached_plan(account) or runtime.refresh_plan(db, account, client)
    if plan is None or not plan.plan_id:
        raise ValueError("账号下没有可用的实习计划")
    return plan.plan_id


def remote_reports(db: Session, account: Account, report_type: str) -> list[dict[str, Any]]:
    client = _client(db, account)
    return client.list_reports(report_type=report_type, plan_id=_plan_id(db, account, client))


def week_options(db: Session, account: Account) -> list[dict[str, Any]]:
    client = _client(db, account)
    return client.report_weeks()


def week_bounds(day: dt.date) -> tuple[str, str]:
    start = day - dt.timedelta(days=day.weekday())
    end = start + dt.timedelta(days=6)
    return f"{start:%Y-%m-%d} 00:00:00", f"{end:%Y-%m-%d} 23:59:59"


def month_bounds(day: dt.date) -> tuple[str, str]:
    first = day.replace(day=1)
    nxt = dt.date(first.year + 1, 1, 1) if first.month == 12 else dt.date(first.year, first.month + 1, 1)
    last = nxt - dt.timedelta(days=1)
    return f"{first:%Y-%m-%d}", f"{last:%Y-%m-%d}"


def _draft_period(day: dt.date, report_type: str) -> tuple[str, str, str, str]:
    """(period_start, period_end, weeks, yearmonth) for the draft record."""
    if report_type == "day":
        stamp = f"{day:%Y-%m-%d}"
        return stamp, stamp, "", ""
    if report_type == "week":
        start, end = week_bounds(day)
        return start[:10], end[:10], "", ""
    if report_type == "month":
        start, end = month_bounds(day)
        return start, end, "", f"{day:%Y-%m}"
    return "", "", "", ""


def _request_period(day: dt.date, report_type: str, weeks_label: str) -> dict[str, Any]:
    if report_type == "week":
        start, end = week_bounds(day)
        period: dict[str, Any] = {"startTime": start, "endTime": end}
        if weeks_label:
            period["weeks"] = weeks_label
        return period
    if report_type == "month":
        return {"yearmonth": f"{day:%Y-%m}"}
    return {}


def _next_week_label(client: GxyClient, plan_id: str) -> str:
    """Continue the weekly numbering the account already uses."""
    try:
        items = client.list_reports(report_type="week", plan_id=plan_id) or []
    except GxyError:
        return ""
    last = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("weeks") or "")
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits:
            last = max(last, int(digits))
    return f"第{last + 1}周"


def report_title(report_type: str, day: dt.date, weeks_label: str = "") -> str:
    if report_type == "week":
        return f"{weeks_label or '本周'}周记"
    if report_type == "month":
        return f"{day:%Y年%m月}实习月报"
    if report_type == "summary":
        return f"{day:%Y-%m-%d} 实习总结"
    return f"{day:%Y-%m-%d} 实习日报"


def _template(
    account: Account,
    report_type: str,
    day: dt.date,
    notes: str,
    plan_item: dict[str, Any] | None = None,
) -> str:
    plan = account.plan or {}
    company = str(plan.get("createName") or plan.get("planName") or "")
    body_notes = notes.strip()
    if plan_item:
        tasks = "；".join(str(item) for item in (plan_item.get("tasks") or []))
        body_notes = body_notes or f"按计划完成：{tasks}。"
        if plan_item.get("theme"):
            body_notes = f"围绕「{plan_item['theme']}」，{body_notes}"
    body_notes = body_notes or "按计划完成岗位日常工作，遵守实习单位作息与安全规范。"
    label = TYPE_LABELS[report_type]
    sections = [
        f"一、实习概况\n本{label}在实习岗位继续开展实习工作，严格遵守单位考勤与安全管理要求。",
        f"二、主要工作内容\n{body_notes}",
        "三、学习与收获\n熟悉了岗位日常工作流程，提升了沟通协作与问题处理能力，"
        "对专业知识的实际应用有了更具体的理解。",
        "四、问题与改进\n遇到不熟悉的任务时先查阅资料并向指导老师请教，"
        "后续将提前梳理任务清单，提高工作效率。",
        "五、下一步计划\n按实习计划推进后续任务，及时记录工作过程，"
        "保持与学校和实习单位的沟通。",
    ]
    if company:
        sections.insert(0, f"实习单位：{company}")
    return "\n\n".join(sections)


def build_draft(
    db: Session,
    account: Account,
    *,
    report_type: str,
    day: dt.date,
    notes: str = "",
    use_ai: bool = True,
    client: GxyClient | None = None,
) -> ReportDraft:
    if report_type not in REPORT_FORM_TYPES:
        raise ValueError("报告类型只能是 day/week/month/summary")

    weeks_label = ""
    form_fields: list[dict[str, Any]] = []
    try:
        if client is None:
            # Never trigger a full login + captcha just to fetch optional form
            # fields. Accounts without a stored session can still generate a
            # draft from the plan/profile; the explicit "登录检测" creates the
            # session and the next draft will include the school form.
            if not account.session_enc:
                raise ValueError("尚未登录，跳过学校表单获取")
            client = _client(db, account)
        plan_id = _plan_id(db, account, client)
        if report_type == "week":
            weeks_label = _next_week_label(client, plan_id)
        # Fetch the school's dynamic form so the draft can be reviewed/filled.
        # We do not blindly fill values (27xk writes "b" into every field); an
        # unfilled required field is visible to the user before submission.
        data = client.report_form(REPORT_FORM_TYPES[report_type])
        raw_fields = data.get("formFieldDtoList") if isinstance(data, dict) else None
        if isinstance(raw_fields, list):
            form_fields = [dict(item) for item in raw_fields if isinstance(item, dict)]
    except (GxyError, ValueError):
        weeks_label = weeks_label or ""
        form_fields = []

    content: str | None = None
    start, end, _weeks, yearmonth = _draft_period(day, report_type)
    plan, plan_item, _index = plans.item_for(db, account.id, day.isoformat())
    period_items = (
        plans.period_items(db, account.id, start or day.isoformat(), end or day.isoformat())
        if report_type in {"week", "month"}
        else []
    )
    recent_rows = db.scalars(
        select(ReportDraft)
        .where(ReportDraft.account_id == account.id)
        .where(ReportDraft.report_type == report_type)
        .order_by(ReportDraft.created_at.desc())
        .limit(3)
    ).all()
    recent = [f"{row.title}：{(row.content or '')[:180]}" for row in recent_rows]

    if use_ai:
        try:
            content = ai.write_report(
                db,
                account,
                report_type=report_type,
                day=day.isoformat(),
                plan_item=plan_item,
                period_items=period_items,
                recent=recent,
                notes=notes,
            )
        except ai.AIError as exc:
            logger.info("AI report generation fell back to template: %s", str(exc)[:120])
    if not content:
        content = _template(account, report_type, day, notes, plan_item)

    draft = ReportDraft(
        account_id=account.id,
        report_type=report_type,
        title=report_title(report_type, day, weeks_label),
        content=content,
        period_start=start,
        period_end=end,
        weeks=weeks_label,
        yearmonth=yearmonth,
        form_fields=form_fields,
        plan_id=plan.id if plan else None,
        plan_date=day.isoformat() if plan_item else "",
        status="draft",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def draft_view(draft: ReportDraft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "account_id": draft.account_id,
        "report_type": draft.report_type,
        "title": draft.title,
        "content": draft.content,
        "period_start": draft.period_start,
        "period_end": draft.period_end,
        "yearmonth": draft.yearmonth,
        "weeks": draft.weeks,
        "status": draft.status,
        "remote_report_id": draft.remote_report_id,
        "error": draft.error,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "submitted_at": draft.submitted_at.isoformat() if draft.submitted_at else None,
        "form_fields": draft.form_fields or [],
        "plan_id": draft.plan_id,
        "plan_date": draft.plan_date,
    }


def list_drafts(db: Session, account_id: int, limit: int = 30) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ReportDraft)
        .where(ReportDraft.account_id == account_id)
        .order_by(ReportDraft.created_at.desc())
        .limit(limit)
    ).all()
    return [draft_view(row) for row in rows]


def _find_remote(reports: list[dict[str, Any]], draft: ReportDraft) -> dict[str, Any] | None:
    for item in reports:
        if not isinstance(item, dict):
            continue
        if str(item.get("title") or "") != draft.title:
            continue
        if str(item.get("reportType") or "") != draft.report_type:
            continue
        if draft.period_start and draft.report_type in {"week", "month"}:
            remote_start = str(item.get("startTime") or "")[:10]
            if remote_start and remote_start != draft.period_start[:10]:
                continue
        return item
    return None


def submit_draft(db: Session, draft: ReportDraft, *, trigger: str = "manual") -> dict[str, Any]:
    account = db.get(Account, draft.account_id)
    if account is None:
        raise ValueError("账号已被删除")
    if draft.status == "submitted":
        return {"status": "duplicate", "message": "该草稿已提交", "draft": draft_view(draft)}

    execution = runtime.start_execution(
        db,
        account,
        kind="REPORT",
        subtype=draft.report_type,
        trigger=trigger,
        target_date=draft.period_start or "",
        message=f"提交{TYPE_LABELS.get(draft.report_type, '报告')}",
    )
    try:
        client = _client(db, account)
        plan_id = _plan_id(db, account, client)

        day = dt.date.fromisoformat(draft.period_start) if draft.period_start else dt.date.today()
        weeks_label = draft.weeks
        if draft.report_type == "week" and not weeks_label:
            weeks_label = _next_week_label(client, plan_id)
        period = _request_period(day, draft.report_type, weeks_label)

        overrides: dict[str, Any] = {}
        job_id = str((account.job or {}).get("jobId") or "")
        if job_id:
            overrides["jobId"] = job_id

        payload = client.build_report(
            plan_id=plan_id,
            report_type=draft.report_type,
            title=draft.title,
            content=draft.content,
            form_fields=draft.form_fields or [],
            period=period,
            overrides=overrides,
        )
        response = client.save_report(payload)
        if not response.ok:
            draft.status = "failed"
            draft.error = f"code={response.code} msg={response.msg}"
            db.add(draft)
            db.commit()
            runtime.finish_execution(
                db, execution, status="rejected",
                message=f"报告提交被拒绝：{draft.error}", account=account,
            )
            return {"status": "rejected", "message": draft.error, "draft": draft_view(draft)}

        reports = client.list_reports(report_type=draft.report_type, plan_id=plan_id)
        remote = _find_remote(reports, draft)
        if remote:
            draft.status = "submitted"
            draft.remote_report_id = str(remote.get("reportId") or "")
            draft.submitted_at = utcnow()
            draft.error = ""
            db.add(draft)
            db.commit()
            runtime.finish_execution(
                db, execution, status="success",
                message=f"{draft.title} 已提交并回查确认", account=account,
            )
            notify(
                f"工学云 {account.label or account.phone} 报告已提交",
                f"{draft.title} 已提交并在列表中确认。",
                event="daily_summary",
                account_notify=account.notify,
            )
            return {"status": "success", "message": "报告已提交并确认", "draft": draft_view(draft)}

        runtime.finish_execution(
            db, execution, status="submitted_unconfirmed",
            message="接口返回成功，但报告列表中未查到", account=account,
        )
        return {
            "status": "submitted_unconfirmed",
            "message": "请求已被接受，但未在报告列表中确认，请手动核对",
            "draft": draft_view(draft),
        }
    except (GxyError, ValueError) as exc:
        draft.status = "failed"
        draft.error = runtime.safe_error_message(exc)
        db.add(draft)
        db.commit()
        runtime.finish_execution(db, execution, status="failed", message=draft.error, account=account)
        return {"status": "failed", "message": draft.error, "draft": draft_view(draft)}


def _report_exists_today(
    client: GxyClient, plan_id: str, report_type: str, day: dt.date
) -> bool:
    try:
        items = client.list_reports(report_type=report_type, plan_id=plan_id) or []
    except GxyError:
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        if report_type == "day":
            stamp = str(item.get("createTime") or item.get("reportTime") or "")[:10]
            if stamp == f"{day:%Y-%m-%d}":
                return True
        elif report_type == "week":
            start = str(item.get("startTime") or "")[:10]
            if start == week_bounds(day)[0][:10]:
                return True
        elif report_type == "month":
            if str(item.get("yearmonth") or "")[:7] == f"{day:%Y-%m}":
                return True
    return False


def auto_reports_due(db: Session, account: Account, day: dt.date) -> list[dict[str, Any]]:
    """Generate + submit the configured report types for today (scheduler use)."""
    results: list[dict[str, Any]] = []
    for report_type in [item.strip() for item in (account.report_types or "").split(",") if item.strip()]:
        if report_type not in REPORT_FORM_TYPES:
            continue
        try:
            client = _client(db, account)
            plan_id = _plan_id(db, account, client)
            if _report_exists_today(client, plan_id, report_type, day):
                results.append({"report_type": report_type, "status": "duplicate", "message": "本周期已提交"})
                continue
        except (GxyError, ValueError) as exc:
            results.append({"report_type": report_type, "status": "failed", "message": runtime.safe_error_message(exc)})
            continue
        draft = build_draft(db, account, report_type=report_type, day=day, client=client)
        results.append({"report_type": report_type, **submit_draft(db, draft, trigger="schedule")})
    return results
