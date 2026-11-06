"""End-to-end-ish tests of the clock-in state machine with a fake transport.

These tests pin the behaviour that matters most:

* 304 pauses and creates a verification session — it is never reported as success;
* 303 does not fabricate an Alipay link from a notice string;
* 302 fetches a challenge, solves it, retries once and then reconciles the record;
* 200 without a matching attendance row is "unconfirmed", not "success".
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from app.gxy.captcha import CaptchaSolver
from app.gxy.client import GxyClient, GxyResponse, SessionState
from app.gxy.constants import REPORT_FORM_TYPES
from app.models import Execution, VerificationSession
from app.services import clockin, reports, runtime
from app.services.verifications import public_view

DAY = "2026-03-02"
WHEN = dt.datetime(2026, 3, 2, 8, 30, 0)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, *, json, headers, timeout):
        self.calls.append({"url": url, "body": json, "headers": dict(headers)})
        return FakeResponse(self.responses.pop(0))


class StubCaptcha(CaptchaSolver):
    def solve_slider(self, jigsaw_b64: str, background_b64: str) -> str:
        return '{"x":100.0,"y":5}'

    def solve_clickword(self, image_b64: str, words: list[str]) -> str:
        return json.dumps([{"x": 10 * i + 5, "y": 20} for i, _ in enumerate(words)])


def _client(responses):
    http = FakeHTTP(responses)
    client = GxyClient(
        session=SessionState(token="tok", user_id="u-1", role_key="student", user_type="student"),
        captcha=StubCaptcha(),
        http=http,
    )
    return client, http


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(runtime, "build_client", lambda account: client)


@pytest.mark.parametrize("replace", [False, True])
def test_holiday_submits_signs_confirms_and_guards(db, account, monkeypatch, replace):
    from app.gxy.crypto import create_sign

    client, http = _client([
        {"code": 200, "data": {}},
        {"code": 200, "data": [{"attendanceId": "holiday-1", "attendenceTime": f"{DAY} 08:30:00", "type": "HOLIDAY"}]},
    ])
    _patch_client(monkeypatch, client)
    result = clockin.submit_clock_in(db, account, "HOLIDAY", when=WHEN, replace=replace)
    assert result.status == clockin.SUCCESS
    sent = http.calls[0]
    body = sent["body"]
    assert body["type"] == "HOLIDAY"
    assert sent["headers"]["sign"] == create_sign(body["device"], "HOLIDAY", body["planId"], body["userId"], body["address"])
    assert sent["url"].endswith("/attendence/attendanceReplace/v6/save" if replace else "/attendence/clock/v6/save")
    execution = db.get(Execution, result.execution_id)
    assert execution.subtype == "HOLIDAY"
    if not replace:
        assert execution.guard_key == f"{account.id}:{DAY}:HOLIDAY"
        again = clockin.submit_clock_in(db, account, "HOLIDAY", when=WHEN)
        assert again.status == clockin.DUPLICATE
        assert len(http.calls) == 2


def test_holiday_not_confirmed_by_start_record(db, account, monkeypatch):
    client, _ = _client([
        {"code": 200, "data": {}},
        *[{"code": 200, "data": [{"attendanceId": "start-1", "attendenceTime": f"{DAY} 08:30:00", "type": "START"}]} for _ in range(3)],
    ])
    _patch_client(monkeypatch, client)
    monkeypatch.setattr(clockin.time, "sleep", lambda _: None)
    result = clockin.submit_clock_in(db, account, "HOLIDAY", when=WHEN)
    assert result.status == clockin.SUBMITTED


def test_304_pauses_and_creates_verification_session(db, account, monkeypatch):
    client, http = _client(
        [
            {"code": 200, "msg": "304", "data": {"attendanceId": "a1"}},
            {"code": 200, "data": {"registerUrl": "alipays://platformapi/x", "outRegisterNo": "REG-1"}},
        ]
    )
    _patch_client(monkeypatch, client)

    result = clockin.submit_clock_in(db, account, "START", when=WHEN)
    assert result.status == clockin.VERIFICATION
    assert result.session_id

    row = db.get(VerificationSession, result.session_id)
    view = public_view(db, row)
    assert view["verification_type"] == "account"
    assert view["state"] == "awaiting_verification"
    assert view["has_link"] is True
    assert view["can_resume"] is True
    assert view["target_date"] == DAY

    execution = db.get(Execution, result.execution_id)
    assert execution.status == clockin.VERIFICATION
    assert execution.guard_key is None
    assert len(http.calls) == 2  # save + createAxdjk, no record query
    assert http.calls[1]["url"].endswith("/usercenter/alipay/v1/createAxdjk")


def test_303_does_not_invent_an_alipay_link(db, account, monkeypatch):
    client, http = _client([{"code": 200, "msg": "303", "data": "请完成人脸检测识别打卡"}])
    _patch_client(monkeypatch, client)

    result = clockin.submit_clock_in(db, account, "START", when=WHEN)
    assert result.status == clockin.VERIFICATION
    row = db.get(VerificationSession, result.session_id)
    assert row.verification_type == "face"
    assert row.register_url_enc == ""
    assert len(http.calls) == 1  # no createAxdjk for 303


def test_303_token_builds_alipay_face_link(db, account, monkeypatch):
    token = "QWxhZGRpbjpvcGVuIHNlc2FtZQ"
    client, _ = _client([{"code": 200, "msg": "303", "data": token}])
    _patch_client(monkeypatch, client)

    result = clockin.submit_clock_in(db, account, "START", when=WHEN)
    row = db.get(VerificationSession, result.session_id)
    link = public_view(db, row)["link"]
    assert link.startswith("alipays://platformapi/startapp?appId=2021006127602453")
    assert "alipayToken%3D" in link


def test_face_link_rejects_a_notice_string():
    assert clockin.face_link("系统检测为风险学生,请完成人脸检测识别打卡") == ""
    assert clockin.face_link("") == ""
    assert clockin.face_link("a b") == ""
    assert clockin.face_link("abc123").startswith("alipays://")


def test_302_solves_captcha_then_confirms_record(db, account, monkeypatch):
    client, http = _client(
        [
            {"code": 200, "msg": "302"},
            {
                "code": 200,
                "data": {
                    "originalImageBase64": "aW1n",
                    "wordList": ["天", "地"],
                    "secretKey": "c2VjcmV0a2V5MTIzNDU2Nw==",
                    "token": "cap-1",
                },
            },
            {"code": 200, "data": {"result": True}},
            {"code": 200, "data": {}},
            {"code": 200, "data": [{"attendanceId": "a9", "attendenceTime": f"{DAY} 08:30:00", "type": "START"}]},
        ]
    )
    _patch_client(monkeypatch, client)

    result = clockin.submit_clock_in(db, account, "START", when=WHEN)
    assert result.status == clockin.SUCCESS, result.message
    assert len(http.calls) == 5
    retry = http.calls[3]
    assert retry["url"].endswith("/attendence/clock/v6/save")
    assert retry["body"]["captcha"]  # proof from the challenge
    assert retry["body"]["appUuid"]  # challenge uid reused, as kaka-niu does
    assert retry["body"]["createTime"] == "2026-03-02 08:30:00"

    execution = db.get(Execution, result.execution_id)
    assert execution.status == clockin.SUCCESS
    assert execution.guard_key == f"{account.id}:{DAY}:START"


def test_success_without_record_is_unconfirmed(db, account, monkeypatch):
    # confirm_record retries 3 times when the row is absent.
    client, _ = _client(
        [{"code": 200, "data": {}}, {"code": 200, "data": []}, {"code": 200, "data": []}, {"code": 200, "data": []}]
    )
    _patch_client(monkeypatch, client)

    result = clockin.submit_clock_in(db, account, "START", when=WHEN)
    assert result.status == clockin.SUBMITTED
    assert db.get(Execution, result.execution_id).guard_key is None


def test_business_error_is_rejected(db, account, monkeypatch):
    client, _ = _client([{"code": 500, "msg": "不允许打卡"}])
    _patch_client(monkeypatch, client)

    result = clockin.submit_clock_in(db, account, "START", when=WHEN)
    assert result.status == clockin.REJECTED
    assert "不允许打卡" in result.message


def test_signature_is_sent_for_student_save(db, account, monkeypatch):
    client, http = _client(
        [{"code": 200, "msg": "304", "data": {}}, {"code": 200, "data": {}}]
    )
    _patch_client(monkeypatch, client)
    clockin.submit_clock_in(db, account, "START", when=WHEN)

    from app.gxy.crypto import create_sign

    headers = http.calls[0]["headers"]
    assert headers["sign"] == create_sign("mobile", "START", "p1", "u-1", "某地")
    assert https_ok(headers["sign"])


def https_ok(value: str) -> bool:
    return len(value) == 32 and all(ch in "0123456789abcdef" for ch in value)


def test_duplicate_confirmed_run_is_skipped(db, account, monkeypatch):
    client, http = _client([])
    _patch_client(monkeypatch, client)
    db.add(
        Execution(
            account_id=account.id,
            kind="CLOCK_IN",
            subtype="START",
            trigger="manual",
            status=clockin.SUCCESS,
            target_date=DAY,
            guard_key=f"{account.id}:{DAY}:START",
        )
    )
    db.commit()

    result = clockin.submit_clock_in(db, account, "START", when=WHEN)
    assert result.status == clockin.DUPLICATE
    assert http.calls == []


def test_query_semantics_for_alipay():
    assert clockin.query_succeeded(GxyResponse("p", 200, 200, "success", None))
    assert clockin.query_succeeded(GxyResponse("p", 200, 200, "success", True))
    assert not clockin.query_succeeded(GxyResponse("p", 200, 200, "success", False))
    assert not clockin.query_succeeded(GxyResponse("p", 200, 500, "error", None))


def test_report_periods_match_reference_projects():
    day = dt.date(2026, 3, 4)  # Wednesday
    assert reports.week_bounds(day) == ("2026-03-02 00:00:00", "2026-03-08 23:59:59")
    assert reports._request_period(day, "week", "第3周") == {
        "startTime": "2026-03-02 00:00:00",
        "endTime": "2026-03-08 23:59:59",
        "weeks": "第3周",
    }
    assert reports._request_period(day, "month", "") == {"yearmonth": "2026-03"}
    assert reports._request_period(day, "day", "") == {}
    assert reports.report_title("week", day, "第3周") == "第3周周记"
    assert reports._draft_period(day, "week")[:2] == ("2026-03-02", "2026-03-08")
    assert REPORT_FORM_TYPES == {"day": 7, "week": 8, "month": 9, "summary": 10}


def test_stale_running_execution_does_not_block_forever(db, account):
    from app.services import scheduler as sched

    row = Execution(
        account_id=account.id,
        kind="CLOCK_IN",
        subtype="START",
        trigger="schedule",
        status="running",
        target_date=DAY,
        created_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=30),
    )
    db.add(row)
    db.commit()
    # A crashed job older than 15 minutes must not block the schedule.
    assert sched._already_handled(db, account.id, DAY, "START") is False

    row.created_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    db.add(row)
    db.commit()
    assert sched._already_handled(db, account.id, DAY, "START") is True

    row.status = "success"
    row.created_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(hours=6)
    db.add(row)
    db.commit()
    assert sched._already_handled(db, account.id, DAY, "START") is True
