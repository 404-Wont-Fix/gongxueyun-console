import datetime as dt

import pytest

from app.gxy.models import (
    ATTENDANCE_KEYS,
    REPORT_KEYS,
    attendance_sign_parts,
    build_attendance_payload,
    build_report_payload,
    empty_attendance,
    month_range,
    normalize_records,
    pick_plan,
    report_sign_parts,
)


def _payload(**overrides):
    base = dict(
        plan_id="plan-1",
        user_id="user-1",
        kind="START",
        device="mobile",
        location={"address": "某某路 1 号", "latitude": 30.1, "longitude": 120.2},
        moment=dt.datetime(2026, 3, 2, 8, 30, 0),
    )
    base.update(overrides)
    return build_attendance_payload(**base)


@pytest.mark.parametrize("kind", ["START", "END", "HOLIDAY"])
def test_attendance_kinds_in_schema_and_payload(kind):
    from app.api.schemas import ClockInRequest

    assert ClockInRequest(kind=kind).kind == kind
    data = _payload(kind=kind)
    assert data["type"] == kind
    assert attendance_sign_parts(data, "user-1")[1] == kind
    assert normalize_records([{**data, "attendanceId": "a1"}])[0].kind == kind


def test_invalid_attendance_kind_rejected():
    from app.api.schemas import ClockInRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ClockInRequest(kind="REST")
    with pytest.raises(ValueError):
        _payload(kind="REST")


def test_attendance_model_has_54_unique_keys() -> None:
    assert len(ATTENDANCE_KEYS) == 54
    assert len(set(ATTENDANCE_KEYS)) == 54
    assert set(empty_attendance()) == set(ATTENDANCE_KEYS)


def test_attendance_defaults_match_client() -> None:
    data = _payload()
    assert data["type"] == "START"
    assert data["state"] == "NORMAL"
    assert data["country"] == "中国"
    assert data["attendenceTime"] == "2026-03-02 08:30:00"  # mirrored by default
    assert data["attendanceType"] is None
    assert data["appUuid"] is None
    assert data["isFirstSignInWeb"] is None
    assert data["createTime"] == "2026-03-02 08:30:00"
    assert data["address"] == "某某路 1 号"


def test_replace_marks_attendance_type_and_clears_time() -> None:
    data = _payload(replace=True)
    assert data["attendanceType"] == "REPLACE"
    assert data["attendenceTime"] is None
    assert data["createTime"] == "2026-03-02 08:30:00"


def test_mirror_mode_can_be_disabled() -> None:
    assert _payload(mirror_attendence_time=False)["attendenceTime"] is None


def test_location_keys_do_not_leak_unknown_fields() -> None:
    data = _payload(location={"address": "A", "evil": "x", "latitude": 1.0})
    assert "evil" not in data
    assert data["latitude"] == 1.0


def test_attendance_signature_order() -> None:
    data = _payload()
    assert attendance_sign_parts(data, "user-1") == [
        "mobile",
        "START",
        "plan-1",
        "user-1",
        "某某路 1 号",
    ]


def test_attendance_signature_requires_address_and_user_match() -> None:
    data = _payload(location={})
    with pytest.raises(ValueError):
        attendance_sign_parts(data, "user-1")
    data = _payload()
    with pytest.raises(ValueError):
        attendance_sign_parts(data, "someone-else")


def test_report_model_has_60_keys_and_signature() -> None:
    data = build_report_payload(
        plan_id="plan-1",
        report_type="day",
        title="实习日报",
        content="正文",
        form_fields=[{"id": "f1", "value": "b"}],
        period={"startTime": "2026-03-02", "endTime": "2026-03-02"},
    )
    assert len(data) == len(REPORT_KEYS) == 60
    assert data["formFieldDtoList"] == data["fieldEntityList"]
    assert report_sign_parts(data, "user-1") == ["user-1", "day", "plan-1", "实习日报"]


def test_report_sign_parts_tolerate_missing_title() -> None:
    data = build_report_payload(plan_id="p", report_type="week", title="", content="c")
    assert report_sign_parts(data, "u") == ["u", "week", "p", ""]


def test_invalid_report_type_rejected() -> None:
    with pytest.raises(ValueError):
        build_report_payload(plan_id="p", report_type="yearly", title="t", content="c")


def test_month_range_uses_client_format() -> None:
    # APK getMonthLastDay: next month minus one day, formatted "%Y-%m-%d 00:00:00Z".
    start, end = month_range(dt.date(2026, 12, 15))
    assert start == "2026-12-01 00:00:00"
    assert end == "2026-12-31 00:00:00Z"


def test_normalize_and_pick_plan() -> None:
    records = normalize_records(
        [
            {"attendanceId": "a1", "attendenceTime": "2026-03-02 08:31:00", "type": "START"},
            {"attendanceId": "a2", "createTime": "2026-03-02 18:02:00", "type": "END"},
            {"nope": True},
        ]
    )
    assert [record.kind for record in records] == ["START", "END"]
    assert records[1].day == "2026-03-02"

    plan = pick_plan([{}, {"planId": "p1", "planName": "实习计划"}])
    assert plan is not None and plan.plan_id == "p1" and plan.name == "实习计划"
    assert pick_plan([]) is None
