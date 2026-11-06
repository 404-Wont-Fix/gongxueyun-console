"""In-process scheduler.

Single-process by design: two schedulers on the same database would race on the
same account. If you scale the backend, run the scheduler in exactly one replica
(``SCHEDULER_ENABLED=false`` elsewhere) — the per-account lock still protects
writes, but duplicate *attempts* would waste captcha quota.
"""

from __future__ import annotations

import datetime as dt
import logging
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Account, Execution, VerificationSession
from ..settings import get_settings
from . import clockin, reports, verifications
from .holidays import day_schedule
from .notifier import notify

logger = logging.getLogger(__name__)

OPEN_STATES = {
    clockin.SUCCESS,
    clockin.SUBMITTED,
    clockin.VERIFICATION,
    clockin.CAPTCHA,
    "running",
}
WINDOW_MINUTES = 45


def _due(now: dt.datetime, hhmm: str, window_minutes: int = WINDOW_MINUTES) -> bool:
    try:
        hour, minute = (int(part) for part in hhmm.split(":", 1))
    except (ValueError, AttributeError):
        return False
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return scheduled <= now < scheduled + dt.timedelta(minutes=window_minutes)


def _weekday_ok(account: Account, day: dt.date) -> bool:
    allowed = {item.strip() for item in (account.weekdays or "").split(",") if item.strip()}
    return not allowed or str(day.isoweekday()) in allowed


def _already_handled(db: Session, account_id: int, day: str, kind: str) -> bool:
    """True when today's kind already ran or is still running.

    A crashed process can leave a row in ``running`` forever; such a row stops
    counting after 15 minutes so the schedule can recover.
    """
    stale_before = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=15)
    stmt = (
        select(Execution.id)
        .where(Execution.account_id == account_id)
        .where(Execution.target_date == day)
        .where(Execution.subtype == kind)
        .where(Execution.status.in_(OPEN_STATES))
        .where(or_(Execution.status != "running", Execution.created_at >= stale_before))
        .limit(1)
    )
    return db.scalar(stmt) is not None


def _opposite_handled(db: Session, account_id: int, day: str, kind: str) -> bool:
    opposite = ("START", "END") if kind == "HOLIDAY" else ("HOLIDAY",)
    return any(_already_handled(db, account_id, day, other) for other in opposite)


def _open_verification(db: Session, account_id: int) -> bool:
    row = db.scalar(
        select(VerificationSession.id)
        .where(VerificationSession.account_id == account_id)
        .where(VerificationSession.state.not_in(list(verifications.TERMINAL)))
        .limit(1)
    )
    return row is not None


class AppScheduler:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.scheduler = BackgroundScheduler(timezone=self.settings.tz, daemon=True)
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="gxy-job")
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self._last_summary_day = ""

    # ------------------------------------------------------------------ public
    def start(self) -> None:
        if not self.settings.scheduler_enabled:
            logger.info("scheduler disabled by configuration")
            return
        self.scheduler.add_job(
            self.tick,
            "interval",
            seconds=self.settings.scheduler_tick_seconds,
            id="tick",
            max_instances=1,
            coalesce=True,
            next_run_time=dt.datetime.now(self.settings.tz) + dt.timedelta(seconds=10),
        )
        self.scheduler.add_job(
            self.daily_summary,
            CronTrigger(hour=22, minute=30, timezone=self.settings.tz),
            id="summary",
            max_instances=1,
        )
        self.scheduler.start()
        logger.info("scheduler started (tick=%ss)", self.settings.scheduler_tick_seconds)

    def shutdown(self) -> None:
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:  # pragma: no cover - already stopped
            pass
        self.pool.shutdown(wait=False)

    # -------------------------------------------------------------------- tick
    def tick(self) -> None:
        now = dt.datetime.now(self.settings.tz)
        day = now.date()
        try:
            with SessionLocal() as db:
                accounts = db.scalars(select(Account).where(Account.enabled.is_(True))).all()
                for account in accounts:
                    if account.auto_clock_in:
                        self._plan_clock_ins(db, account, now)
                    if account.auto_reports and _weekday_ok(account, day) and _due(now, account.report_time, 90):
                        self._submit(
                            f"report:{account.id}",
                            account.id,
                            lambda a=account: self._run_reports(a.id, day),
                        )
                try:
                    verifications.poll_active_sessions(db)
                    verifications.auto_resume_due(db)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("verification scan failed: %s", type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 - scheduler must never die
            logger.exception("scheduler tick failed: %s", type(exc).__name__)

    def _plan_clock_ins(self, db: Session, account: Account, now: dt.datetime) -> None:
        day = now.date().isoformat()
        plan = day_schedule(db, account, now.date())
        for slot in plan["slots"]:
            kind, hhmm = slot["kind"], slot["time"]
            if not _due(now, hhmm) or _opposite_handled(db, account.id, day, kind):
                continue
            if _already_handled(db, account.id, day, kind) or _open_verification(db, account.id):
                continue
            # Spread accounts inside the window instead of one burst at :00.
            delay = random.randint(0, 90)
            self._submit(f"{account.id}:{kind}", account.id, lambda a=account, k=kind, d=day: self._run_clock_in(a.id, k, d), delay)

    def _submit(self, key: str, account_id: int, fn, delay: int = 0) -> None:
        with self._lock:
            if key in self._inflight:
                return
            self._inflight.add(key)
        if self.settings.scheduler_enabled and self.scheduler.running:
            self.scheduler.add_job(
                self._wrap,
                "date",
                run_date=dt.datetime.now(self.settings.tz) + dt.timedelta(seconds=delay),
                args=[key, fn],
                id=f"job-{key}-{random.randint(0, 1 << 30)}",
                max_instances=1,
                misfire_grace_time=120,
            )
        else:  # pragma: no cover - used by tests / manual ticks
            self._wrap(key, fn)

    def _wrap(self, key: str, fn) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduled job %s failed: %s", key, type(exc).__name__)
        finally:
            with self._lock:
                self._inflight.discard(key)

    # ------------------------------------------------------------------- jobs
    def _run_clock_in(self, account_id: int, kind: str, target_day: str | None = None) -> None:
        with SessionLocal() as db:
            account = db.get(Account, account_id)
            if account is None or not account.enabled or not account.auto_clock_in:
                return
            now = dt.datetime.now(self.settings.tz)
            day = now.date().isoformat()
            if target_day and day != target_day:
                return
            # Re-evaluate after the delayed queue: settings / calendar may change.
            plan = day_schedule(db, account, now.date())
            if not any(s["kind"] == kind and _due(now, s["time"]) for s in plan["slots"]):
                return
            if _already_handled(db, account.id, day, kind) or _opposite_handled(db, account.id, day, kind) or _open_verification(db, account.id):
                return
            logger.info("scheduled clock-in %s %s", account_id, kind)
            clockin.submit_clock_in(db, account, kind, trigger="schedule")

    def _run_reports(self, account_id: int, day: dt.date) -> None:
        with SessionLocal() as db:
            account = db.get(Account, account_id)
            if account is None or not account.enabled:
                return
            counts: dict[str, int] = {}
            for result in reports.auto_reports_due(db, account, day):
                counts[result.get("status", "unknown")] = counts.get(result.get("status", "unknown"), 0) + 1
            if counts:
                logger.info("scheduled reports for %s: %s", account_id, counts)

    def daily_summary(self) -> None:
        today = dt.datetime.now(self.settings.tz).date().isoformat()
        if self._last_summary_day == today:
            return
        self._last_summary_day = today
        try:
            with SessionLocal() as db:
                rows = db.scalars(
                    select(Execution).where(Execution.target_date == today).where(Execution.kind != "QUERY")
                ).all()
                if not rows:
                    return
                counts: dict[str, int] = {}
                for row in rows:
                    counts[row.status] = counts.get(row.status, 0) + 1
                text = "；".join(f"{key}: {value}" for key, value in sorted(counts.items()))
                notify("工学云每日执行汇总", f"{today} 执行 {len(rows)} 次：{text}", event="daily_summary")
        except Exception as exc:  # noqa: BLE001
            logger.warning("daily summary failed: %s", type(exc).__name__)


_scheduler: AppScheduler | None = None
_guard = threading.Lock()


def get_scheduler() -> AppScheduler:
    global _scheduler
    with _guard:
        if _scheduler is None:
            _scheduler = AppScheduler()
        return _scheduler


def start_scheduler() -> None:
    get_scheduler().start()


def stop_scheduler() -> None:
    global _scheduler
    with _guard:
        if _scheduler is not None:
            _scheduler.shutdown()
            _scheduler = None


def summary_counts(db: Session) -> dict[str, Any]:
    """Small helper used by the dashboard endpoint and by tests."""
    today = dt.datetime.now(get_settings().tz).date().isoformat()
    rows = db.scalars(select(Execution).where(Execution.target_date == today)).all()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {"date": today, "total": len(rows), "status": counts}
