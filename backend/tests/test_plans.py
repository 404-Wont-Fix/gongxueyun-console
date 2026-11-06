import datetime as dt

import pytest

from app.models import ReportDraft
from app.services import ai, geo, plans


def test_coordinate_conversion_known_vector_and_roundtrip():
    # Beijing Tiananmen area: the canonical WGS84 -> GCJ02 example.
    g_lat, g_lng = geo.wgs84_to_gcj02(39.915, 116.404)
    assert abs(g_lat - 39.91640428150164) < 1e-9
    assert abs(g_lng - 116.41024449916938) < 1e-9

    w_lat, w_lng = geo.gcj02_to_wgs84(g_lat, g_lng)
    assert abs(w_lat - 39.915) < 1e-6
    assert abs(w_lng - 116.404) < 1e-6

    # Outside China the offset must not be applied.
    assert geo.convert(48.8566, 2.3522, "wgs84", "gcj02") == (48.8566, 2.3522)


def test_working_days_respects_weekdays():
    dates = plans.working_days(dt.date(2026, 3, 2), dt.date(2026, 3, 8), "1,2,3,4,5")
    assert dates == ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"]


def test_fallback_outline_uses_profile(account):
    dates = plans.working_days(dt.date(2026, 3, 2), dt.date(2026, 3, 6), account.weekdays)
    title, items = plans.fallback_outline(account, "week", dates)
    assert len(items) == len(dates)
    assert all(item["tasks"] for item in items)
    assert any("接口" in " ".join(item["tasks"]) or "测试" in " ".join(item["tasks"]) for item in items)
    assert "计划" in title


def test_create_outline_without_ai_and_lookup(db, account):
    account.weekdays = "1,2,3,4,5"  # Explicit five-day report schedule, independent of account defaults.
    plan = plans.create_outline(
        db, account, kind="week", start=dt.date(2026, 3, 2), use_ai=False
    )
    assert plan.source == "template"
    assert plan.start_date == "2026-03-02"
    assert plan.end_date == "2026-03-08"
    assert len(plan.items) == 5  # Mon-Fri

    found_plan, item, index = plans.item_for(db, account.id, "2026-03-04")
    assert found_plan is not None and found_plan.id == plan.id
    assert item is not None and item["date"] == "2026-03-04"
    assert index == 2

    assert plans.item_for(db, account.id, "2026-03-07")[1] is None  # Saturday

    view = plans.plan_view(db, plan)
    assert view["progress"]["total"] == 5
    assert view["items"][0]["draft"] is None


def test_plan_view_reports_draft_progress(db, account):
    plan = plans.create_outline(db, account, kind="week", start=dt.date(2026, 3, 2), use_ai=False)
    day = plan.items[0]["date"]
    db.add(
        ReportDraft(
            account_id=account.id,
            report_type="day",
            title="x",
            content="y",
            period_start=day,
            period_end=day,
            plan_id=plan.id,
            plan_date=day,
            status="submitted",
        )
    )
    db.commit()
    view = plans.plan_view(db, plan)
    assert view["progress"]["drafted"] == 1
    assert view["progress"]["submitted"] == 1
    assert view["items"][0]["draft"]["status"] == "submitted"


def test_update_item_and_archive(db, account):
    plan = plans.create_outline(db, account, kind="week", start=dt.date(2026, 3, 2), use_ai=False)
    plans.update_item(db, plan, 0, theme="新的主题", tasks=["任务A", "任务B"], key_points="要点")
    assert plan.items[0]["theme"] == "新的主题"
    assert plan.items[0]["tasks"] == ["任务A", "任务B"]
    plans.archive_plan(db, plan)
    assert plan.status == "archived"
    assert plans.item_for(db, account.id, plan.items[0]["date"])[1] is None


def test_ai_json_extraction_and_normalisation():
    raw = '```json\n{"title":"T","items":[{"date":"2026-03-02","theme":"A","tasks":["x","y"],"key_points":"k"},{"date":"2026-03-09","theme":"bad"}]}\n```'
    payload = ai._extract_json(raw)
    items = ai._normalise_items(payload["items"], ["2026-03-02", "2026-03-03"])
    assert len(items) == 1  # the out-of-range date is dropped
    assert items[0]["tasks"] == ["x", "y"]
    assert items[0]["theme"] == "A"
    assert items[0]["key_points"] == "k"


def test_ai_rejects_non_json():
    with pytest.raises(ai.AIError):
        ai._extract_json("抱歉，我无法完成")


def test_ai_not_configured_raises_clear_error(db, account):
    # Tests run without AI_* env or DB config.
    with pytest.raises(ai.AIError):
        ai.write_report(db, account, report_type="day", day="2026-03-02")


def test_ai_config_roundtrip_encrypts_key(db):
    from app.services import ai as ai_service

    config = ai_service.save_config(
        db,
        {"base_url": "https://api.example.com/v1", "model": "demo", "api_key": "sk-secret-123"},
    )
    assert config.configured is True
    assert config.api_key == "sk-secret-123"
    resolved = ai_service.resolve_config(db)
    assert resolved.api_key == "sk-secret-123"
    assert "sk-secret" not in str(resolved.public())
    ai_service.clear_config(db)
    assert ai_service.resolve_config(db).configured is False


def test_create_outline_uses_ai_when_available(db, account, monkeypatch):
    account.weekdays = "1,2,3,4,5"
    payload = (
        '{"title":"AI 周计划","items":['
        '{"date":"2026-03-02","theme":"接口梳理","tasks":["梳理订单接口"],"key_points":"明确边界"},'
        '{"date":"2026-03-03","theme":"补测试","tasks":["补单元测试"],"key_points":"覆盖异常"}]}'
    )
    monkeypatch.setattr(ai, "chat", lambda *args, **kwargs: payload)
    plan = plans.create_outline(db, account, kind="week", start=dt.date(2026, 3, 2), use_ai=True)
    assert plan.source == "ai"
    assert plan.title == "AI 周计划"
    assert [item["date"] for item in plan.items] == ["2026-03-02", "2026-03-03"]


def test_build_draft_follows_plan_and_ai(db, account, monkeypatch):
    from app.services import reports

    plan = plans.create_outline(db, account, kind="week", start=dt.date(2026, 3, 2), use_ai=False)
    day = dt.date.fromisoformat(plan.items[0]["date"])

    monkeypatch.setattr(reports, "_client", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("offline")))
    monkeypatch.setattr(ai, "chat", lambda *args, **kwargs: "这是 AI 写的日报正文。")

    draft = reports.build_draft(db, account, report_type="day", day=day, use_ai=True)
    assert draft.content == "这是 AI 写的日报正文。"
    assert draft.plan_id == plan.id
    assert draft.plan_date == plan.items[0]["date"]
    view = reports.draft_view(draft)
    assert view["plan_id"] == plan.id


def test_build_draft_falls_back_to_template(db, account, monkeypatch):
    from app.services import reports

    monkeypatch.setattr(reports, "_client", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("offline")))
    monkeypatch.setattr(ai, "chat", lambda *args, **kwargs: (_ for _ in ()).throw(ai.AIError("no ai")))
    draft = reports.build_draft(db, account, report_type="day", day=dt.date(2026, 3, 2), use_ai=True)
    assert "实习概况" in draft.content
    assert draft.plan_id is None
