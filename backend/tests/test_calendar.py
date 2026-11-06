import datetime as dt
import json

import pytest
from fastapi import HTTPException

from app.models import CalendarYear, CalendarOverride, Execution, AttendanceMonth, User
from app.services import holidays, calendar, scheduler
from app.api.calendar import get_calendar, set_override, OverrideIn

# Format fixture following the 2026 annual State Council notice. No live writes.
NOTICE = """国务院办公厅关于2026年部分节假日安排的通知
一、元旦：1月1日（周四）至3日（周六）放假调休，共3天。1月4日（周日）上班。
二、春节：2月15日（周日）至23日（周一）放假调休，共9天。2月14日（周六）、2月28日（周六）上班。
三、清明节：4月4日（周六）至6日（周一）放假，共3天。
四、劳动节：5月1日（周五）至5日（周二）放假调休，共5天。5月9日（周六）上班。
五、端午节：6月19日（周五）至21日（周日）放假，共3天。
六、中秋节：9月25日（周五）至27日（周日）放假，共3天。
七、国庆节：10月1日（周四）至7日（周三）放假调休，共7天。9月20日（周日）、10月10日（周六）上班。
"""


@pytest.fixture
def annual(db):
    row = db.get(CalendarYear, 2026) or CalendarYear(year=2026)
    row.days = holidays.parse_gov(NOTICE, 2026)
    row.accepted_at = dt.datetime.now(dt.timezone.utc)
    row.status = "ready"
    db.add(row)
    db.commit()
    yield row
    db.delete(row)
    db.commit()


def test_three_parsers_match():
    gov = holidays.parse_gov(NOTICE, 2026)
    cn = {"year": 2026, "papers": ["https://www.gov.cn/a", "http://localhost/private"],
          "days": [{"date": k, "name": v["name"], "isOffDay": v["off"]} for k, v in gov.items()]}
    timor = {"code": 0, "holiday": {k[5:]: {"date": k, "name": "不同节日名", "holiday": v["off"]} for k, v in gov.items()}}
    parsed, papers = holidays.parse_cn(cn, 2026)
    assert holidays.signature(gov) == holidays.signature(parsed) == holidays.signature(holidays.parse_timor(timor, 2026))
    assert papers == ["https://www.gov.cn/a"]
    assert len(gov) == 39
    assert gov["2026-09-20"]["off"] is False
    assert gov["2026-02-23"]["off"] is True


def test_government_footer_is_not_a_date_clause():
    footer = "国务院办公厅2025年11月4日国务院办公厅关于2026年部分节假日安排的通知经国务院批准，现将2026年节假日放假调休日期通知如下。"
    assert holidays.parse_gov(NOTICE + footer, 2026) == holidays.parse_gov(NOTICE, 2026)


def test_reject_partial_wrong_year_and_empty():
    with pytest.raises(holidays.CalendarError):
        holidays.parse_gov(NOTICE, 2027)
    with pytest.raises(holidays.CalendarError):
        holidays.parse_gov(NOTICE.split("四、")[0], 2026)
    with pytest.raises(holidays.CalendarError):
        holidays.parse_timor({"code": 0, "holiday": {}}, 2026)
    with pytest.raises(holidays.CalendarError):
        holidays.parse_cn({"year": 2025, "days": []}, 2026)


def test_conflict_preserves_accepted_snapshot(annual):
    original = dict(annual.days)
    changed = {**original, "2026-01-04": {"name": "冲突", "off": True}}
    old_time = annual.accepted_at
    holidays.accept_candidates(annual, {"gov": original, "timor": changed}, {})
    assert annual.status == "conflict"
    assert annual.days == original and annual.accepted_at == old_time
    holidays.accept_candidates(annual, {}, {})
    assert annual.status == "stale" and annual.days == original


def test_initial_trust_needs_official_or_two_agreeing():
    row = CalendarYear(year=2026)
    days = holidays.parse_gov(NOTICE, 2026)
    holidays.accept_candidates(row, {"timor": days}, {})
    assert row.status == "missing" and not row.accepted_at
    holidays.accept_candidates(row, {"timor": days, "holiday_cn": days}, {})
    assert row.status == "degraded" and row.accepted_at


def test_sync_diagnostics_and_three_sources(db, monkeypatch):
    days = holidays.parse_gov(NOTICE, 2026)
    cn = {"year": 2026, "papers": [], "days": [{"date": d, "name": x["name"], "isOffDay": x["off"]} for d, x in days.items()]}
    timor = {"code": 0, "holiday": {d: {"date": d, "name": x["name"], "holiday": x["off"]} for d, x in days.items()}}
    seen = []
    def fetch(url):
        seen.append(url)
        return NOTICE if "gov.cn" in url else json.dumps(cn if "githubusercontent" in url else timor)
    monkeypatch.setattr(holidays, "fetch_text", fetch)
    result = holidays.sync_year(2026)
    assert result["status"] == "ready" and len(seen) == 3
    assert all(v["status"] == "ok" for v in result["sources"].values())
    db.expire_all()
    db.delete(db.get(CalendarYear, 2026))
    db.commit()


def test_default_weekend_holiday_makeup_and_overrides(db, account, annual):
    assert account.weekdays == "1,2,3,4,5,6,7"
    plan = holidays.day_schedule(db, account, dt.date(2026, 3, 7))
    assert [s["kind"] for s in plan["slots"]] == ["START", "END"]
    account.weekdays = "1,2,3,4,5"
    assert holidays.day_schedule(db, account, dt.date(2026, 3, 7))["mode"] == "skip"
    assert holidays.day_schedule(db, account, dt.date(2026, 9, 20))["mode"] == "work"
    plan = holidays.day_schedule(db, account, dt.date(2026, 10, 1))
    assert plan["slots"] == [{"kind": "HOLIDAY", "time": account.morning_time}]
    account.morning_enabled = False
    assert holidays.day_schedule(db, account, dt.date(2026, 10, 1))["slots"] == plan["slots"]
    override = CalendarOverride(account_id=account.id, day="2026-10-01", mode="skip")
    db.add(override)
    db.commit()
    assert holidays.day_schedule(db, account, dt.date(2026, 10, 1))["mode"] == "skip"
    db.delete(override)
    db.commit()


def test_missing_year_pauses_but_explicit_override_works(db, account):
    assert holidays.day_schedule(db, account, dt.date(2027, 1, 1))["mode"] == "unknown"
    account.calendar_enabled = False
    assert holidays.day_schedule(db, account, dt.date(2027, 1, 1))["mode"] == "work"


def test_scheduler_holiday_once_not_evening(db, account, annual, monkeypatch):
    account.auto_clock_in = True
    runner = scheduler.AppScheduler()
    calls = []
    monkeypatch.setattr(runner, "_submit", lambda key, *args: calls.append(key))
    runner._plan_clock_ins(db, account, dt.datetime(2026, 10, 1, 8, 30))
    assert calls == [f"{account.id}:HOLIDAY"]
    calls.clear()
    runner._plan_clock_ins(db, account, dt.datetime(2026, 10, 1, 18, 0))
    assert calls == []
    runner.pool.shutdown(wait=False)


def test_scheduler_rechecks_disabled_before_queued_send(db, account, annual, monkeypatch):
    account.auto_clock_in = False
    db.commit()
    monkeypatch.setattr(scheduler.clockin, "submit_clock_in", lambda *a, **k: pytest.fail("must not submit"))
    runner = scheduler.AppScheduler()
    runner._run_clock_in(account.id, "HOLIDAY")
    runner.pool.shutdown(wait=False)


def test_stats_scope_dedup_and_unconfirmed(db, account, annual):
    rows = [Execution(account_id=account.id, kind="CLOCK_IN", subtype="START", target_date="2026-03-02", status=status)
            for status in ("failed", "submitted_unconfirmed", "success", "success")]
    rows.append(Execution(account_id=account.id, kind="CLOCK_IN", subtype="END", target_date="2026-03-02", status="submitted_unconfirmed"))
    rows.append(Execution(account_id=account.id, kind="LOGIN", target_date="2026-03-02", status="success"))
    db.add_all(rows)
    db.commit()
    result = calendar.month_view(db, [account], "2026-03")
    day = result["days"][1]
    assert day["stats"]["confirmed"] == 1 and day["stats"]["pending"] == 1
    assert day["stats"]["failed"] == 0 and day["stats"]["attempts"] == 5
    assert calendar.month_view(db, [], "2026-03")["stats"]["confirmed"] == 0
    outsider = User(username="calendar-outsider", password_hash="x", role="user")
    db.add(outsider)
    db.commit()
    assert get_calendar(user=outsider, db=db, month="2026-03")["accounts"] == []
    with pytest.raises(HTTPException):
        set_override(account.id, "2026-03-02", OverrideIn(mode="skip"), outsider, db)
    db.delete(outsider)
    db.commit()
