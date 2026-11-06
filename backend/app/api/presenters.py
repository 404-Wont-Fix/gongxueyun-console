"""Small functions that turn ORM rows into API dicts."""

from __future__ import annotations

from typing import Any

from ..models import Account, Execution


def iso(value) -> str | None:
    return value.isoformat() if value else None


def account_view(account: Account) -> dict[str, Any]:
    plan = account.plan or {}
    return {
        "id": account.id,
        "owner_id": account.owner_id,
        "label": account.label or account.phone,
        "phone": account.phone,
        "enabled": account.enabled,
        "auto_clock_in": account.auto_clock_in,
        "auto_reports": account.auto_reports,
        "device": account.device or {},
        "location": account.location or {},
        "coord_type": account.coord_type or "gcj02",
        "profile": account.profile or {},
        "morning_enabled": account.morning_enabled,
        "morning_time": account.morning_time,
        "evening_enabled": account.evening_enabled,
        "evening_time": account.evening_time,
        "weekdays": account.weekdays,
        "calendar_enabled": account.calendar_enabled,
        "report_time": account.report_time,
        "report_types": account.report_types,
        "mirror_attendence_time": account.mirror_attendence_time,
        "has_session": bool(account.session_enc),
        "session_updated_at": iso(account.session_updated_at),
        "plan": {
            "planId": plan.get("planId"),
            "planName": plan.get("planName"),
            "startTime": plan.get("startTime"),
            "endTime": plan.get("endTime"),
        }
        if plan
        else {},
        "plan_updated_at": iso(account.plan_updated_at),
        "job": account.job or {},
        "last_status": account.last_status,
        "last_message": account.last_message,
        "last_run_at": iso(account.last_run_at),
        "notify": account.notify or {},
    }


def execution_view(execution: Execution, label: str = "") -> dict[str, Any]:
    return {
        "id": execution.id,
        "account_id": execution.account_id,
        "account_label": label,
        "kind": execution.kind,
        "subtype": execution.subtype,
        "trigger": execution.trigger,
        "status": execution.status,
        "message": execution.message,
        "target_date": execution.target_date,
        "detail": execution.detail or {},
        "created_at": execution.created_at,
        "finished_at": execution.finished_at,
        "duration_ms": execution.duration_ms,
    }
