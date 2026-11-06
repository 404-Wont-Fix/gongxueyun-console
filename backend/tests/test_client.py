import json

import pytest

from app.gxy.captcha import CaptchaSolver
from app.gxy.client import GxyClient, SessionState
from app.gxy.crypto import aes_decrypt, aes_encrypt, create_sign
from app.gxy.errors import GxyBusinessError, GxyHTTPError


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, json, headers, timeout):
        self.calls.append({"url": url, "body": json, "headers": dict(headers)})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):
            payload, status = item
            return FakeResponse(payload, status)
        return FakeResponse(item)


class StubCaptcha(CaptchaSolver):
    def solve_slider(self, jigsaw_b64: str, background_b64: str) -> str:
        return '{"x":118.5,"y":5}'


USER = {
    "userId": "u-1",
    "token": "tok-1",
    "roleKey": "student",
    "userType": "student",
    "nikeName": "小明",
    "phone": "13800138000",
}


def _client(responses, *, captcha=None):
    http = FakeHTTP(responses)
    client = GxyClient(http=http, captcha=captcha or StubCaptcha(), timeout=5)
    return client, http


def _login_responses():
    return [
        {
            "code": 200,
            "data": {
                "originalImageBase64": "b3JpZ2luYWw=",
                "jigsawImageBase64": "amlnc2F3",
                "secretKey": "c2VjcmV0a2V5MTIzNDU2Nw==",
                "token": "cap-token",
            },
        },
        {"code": 200, "data": {"result": True}},
        {"code": 200, "data": aes_encrypt(json.dumps(USER))},
    ]


def test_login_builds_the_ten_field_body() -> None:
    client, http = _client(_login_responses())
    user, _ = client.login("13800138000", "secret-pass", system="Xiaomi", system_version="14")

    assert user.user_id == "u-1"
    assert client.session.token == "tok-1"
    assert len(http.calls) == 3

    captcha_call, check_call, login_call = http.calls
    assert captcha_call["url"].endswith("/session/captcha/v1/get")
    assert "authorization" not in captcha_call["headers"]
    assert "t" not in captcha_call["body"]

    assert check_call["body"]["captchaType"] == "blockPuzzle"
    assert check_call["body"]["token"] == "cap-token"

    body = login_call["body"]
    assert set(body) == {
        "phone", "password", "captcha", "loginType", "uuid",
        "device", "version", "t", "system", "systemVersion",
    }
    assert aes_decrypt(body["phone"]) == "13800138000"
    assert aes_decrypt(body["password"]) == "secret-pass"
    assert aes_decrypt(body["t"]).isdigit()
    assert len(body["uuid"]) == 32
    assert body["device"] == "android"
    assert body["system"] == "Xiaomi"
    assert "sign" not in login_call["headers"]
    # captcha proof is the token + "---" + interaction, encrypted with the challenge key
    assert aes_decrypt(body["captcha"], key="c2VjcmV0a2V5MTIzNDU2Nw==", in_format="b64") == (
        'cap-token---{"x":118.5,"y":5}'
    )


def test_login_failure_raises_business_error() -> None:
    responses = _login_responses()
    responses[-1] = {"code": 500, "msg": "账号或密码错误"}
    client, _ = _client(responses)
    with pytest.raises(GxyBusinessError) as info:
        client.login("1", "2")
    assert "账号或密码错误" in str(info.value)


def test_attendance_signature_and_marker() -> None:
    client, http = _client([{"code": 200, "msg": "304", "data": {"attendanceId": "a1"}}])
    client.session = SessionState(token="t", user_id="u-1", role_key="student", user_type="student")
    payload = {
        "device": "mobile",
        "type": "START",
        "planId": "p1",
        "userId": "u-1",
        "address": "某地",
    }
    response = client.save_attendance(payload)

    assert response.marker == "304"
    call = http.calls[0]
    assert call["headers"]["sign"] == create_sign("mobile", "START", "p1", "u-1", "某地")
    assert call["headers"]["authorization"] == "t"
    assert call["url"].endswith("/attendence/clock/v6/save")
    assert aes_decrypt(call["body"]["t"]).isdigit()


def test_list_attendance_uses_post_with_dates() -> None:
    client, http = _client([{"code": 200, "data": [{"attendanceId": "a1"}]}])
    client.session = SessionState(token="t", user_id="u-1", role_key="student")
    rows = client.list_attendance("2026-03-01 00:00:00", "2026-04-01 00:00:00Z")
    assert rows == [{"attendanceId": "a1"}]
    body = http.calls[0]["body"]
    assert body["startTime"].startswith("2026-03-01")
    assert body["endTime"].endswith("Z")
    assert "sign" not in http.calls[0]["headers"]


def test_http_error_is_typed() -> None:
    client, _ = _client([({"detail": "boom"}, 502)])
    client.session = SessionState(token="t", user_id="u-1")
    with pytest.raises(GxyHTTPError):
        client.fetch_plans()
