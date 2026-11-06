"""HTTP client for the 工学云 mobile API.

Design notes (deliberately different from most public scripts):

* the network layer adds ``t`` **after** the signature is computed, exactly like
  ``CommonReqObj.reset`` + ``postSign``;
* mutating calls return the parsed response instead of raising, because
  ``msg`` 302/303/304 are *states* the caller must handle;
* no automatic retry of any write; a blind retry can double-submit attendance;
* no ``Authorization`` header is invented for endpoints that do not carry one
  (login captcha), and the click captcha carries it explicitly.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

import requests

from . import constants as C
from .captcha import CaptchaSolver
from .crypto import aes_decrypt, aes_encrypt, captcha_proof, challenge_hash, create_sign, point_json
from .errors import (
    CaptchaError,
    GxyAuthError,
    GxyBusinessError,
    GxyError,
    GxyHTTPError,
    GxyTransportError,
    ProtocolDrift,
)
from .models import (
    AttendanceRecord,
    LoginUser,
    PlanSummary,
    attendance_sign_parts,
    build_attendance_payload,
    build_report_payload,
    normalize_records,
    pick_plan,
    report_sign_parts,
)

logger = logging.getLogger(__name__)


class SupportsPost(Protocol):  # pragma: no cover - structural typing only
    def post(self, url: str, *, json: Any, headers: Mapping[str, str], timeout: float) -> Any: ...


@dataclass
class ClockCaptchaSolution:
    proof: str
    client_uid: str


@dataclass
class GxyResponse:
    path: str
    http_status: int
    code: int | None
    msg: str
    data: Any = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.code == C.CODE_OK

    @property
    def marker(self) -> str | None:
        """302/303/304 are business control flow, not failures to swallow."""
        text = str(self.msg or "")
        return text if text in {C.MSG_CLICK_CAPTCHA, C.MSG_ALIPAY_FACE, C.MSG_ACCOUNT_VERIFY} else None

    def brief(self) -> dict[str, Any]:
        return {"code": self.code, "msg": self.msg, "marker": self.marker}


@dataclass
class SessionState:
    token: str = ""
    user_id: str = ""
    role_key: str = ""
    user_type: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.token and self.user_id)

    def apply(self, user: LoginUser) -> "SessionState":
        self.token = user.token
        self.user_id = user.user_id
        self.role_key = user.role_key
        self.user_type = user.user_type
        return self

    def to_store(self) -> dict[str, str]:
        return {
            "token": self.token,
            "userId": self.user_id,
            "roleKey": self.role_key,
            "userType": self.user_type,
        }

    @classmethod
    def from_store(cls, value: Mapping[str, Any] | None) -> "SessionState":
        data = dict(value or {})
        return cls(
            token=str(data.get("token") or ""),
            user_id=str(data.get("userId") or ""),
            role_key=str(data.get("roleKey") or ""),
            user_type=str(data.get("userType") or ""),
        )


class GxyClient:
    def __init__(
        self,
        *,
        session: SessionState | None = None,
        captcha: CaptchaSolver | None = None,
        http: SupportsPost | None = None,
        timeout: float = 15.0,
        package_version: str = "5.41.6",
        build_number: str = "50291",
        code_version: str = "292",
        base_url: str = C.BASE_URL,
    ) -> None:
        self.session = session or SessionState()
        self.captcha = captcha or CaptchaSolver()
        self._http = http or requests.Session()
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.package_version = package_version
        self.build_number = build_number
        self.code_version = code_version

    # ------------------------------------------------------------------ headers
    def _headers(
        self,
        *,
        auth: bool = True,
        sign_parts: list[str] | None = None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        headers = {
            "user-agent": "Dart/3.7 (dart:io)",
            "content-type": "application/json; charset=utf-8",
            "accept-encoding": "gzip",
            "devices": "android",
            "packageVersion": self.package_version,
            "buildNumber": self.build_number,
            "codeVersion": self.code_version,
            "Client_Id": C.CLIENT_ID,
        }
        if auth:
            if not self.session.token:
                raise GxyAuthError(0, "尚未登录")
            headers["authorization"] = self.session.token
            headers["userid"] = self.session.user_id
            if self.session.role_key:
                headers["rolekey"] = self.session.role_key
        if sign_parts:
            headers["sign"] = create_sign(*sign_parts)
        if extra:
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    # -------------------------------------------------------------------- call
    def _post(
        self,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        auth: bool = True,
        sign_parts: list[str] | None = None,
        with_t: bool = True,
        extra_headers: Mapping[str, str] | None = None,
    ) -> GxyResponse:
        body: dict[str, Any] = dict(payload or {})
        headers = self._headers(auth=auth, sign_parts=sign_parts, extra=extra_headers)
        if with_t:
            body["t"] = aes_encrypt(str(int(time.time() * 1000)))
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self._http.post(url, json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise GxyTransportError(f"网络请求失败: {type(exc).__name__}") from exc

        status = int(getattr(response, "status_code", 0) or 0)
        text = getattr(response, "text", "") or ""
        if status >= 400:
            raise GxyHTTPError(status, text)
        try:
            raw = response.json()
        except Exception as exc:
            raise ProtocolDrift(f"响应不是 JSON（HTTP {status}）") from exc
        if not isinstance(raw, dict):
            raise ProtocolDrift("响应 JSON 不是对象")
        code = _coerce_int(raw.get("code"))
        msg = str(raw.get("msg") or "")
        return GxyResponse(
            path=path,
            http_status=status,
            code=code,
            msg=msg,
            data=raw.get("data"),
            raw=raw,
        )

    def _post_or_raise(self, *args: Any, **kwargs: Any) -> GxyResponse:
        response = self._post(*args, **kwargs)
        if response.ok:
            return response
        raise _to_error(response)

    # ------------------------------------------------------------------- login
    def solve_login_captcha(self, attempts: int = 3) -> str:
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._solve_login_captcha_once()
            except (CaptchaError, ProtocolDrift) as exc:
                last = exc
                logger.warning("登录验证码第 %s/%s 次失败: %s", attempt, attempts, type(exc).__name__)
                time.sleep(0.6)
        raise CaptchaError("登录滑块验证码未通过") from last

    def _solve_login_captcha_once(self) -> str:
        challenge = self._post(
            C.CAPTCHA_GET,
            {"clientUid": uuid.uuid1().hex, "captchaType": "blockPuzzle"},
            auth=False,
            with_t=False,
        )
        data = challenge.data if isinstance(challenge.data, dict) else {}
        secret = str(data.get("secretKey") or "")
        token = str(data.get("token") or "")
        original = str(data.get("originalImageBase64") or "")
        jigsaw = str(data.get("jigsawImageBase64") or "")
        if not (secret and token and original and jigsaw):
            raise ProtocolDrift("登录验证码响应字段不完整")

        interaction = self.captcha.solve_slider(jigsaw, original)
        check = self._post(
            C.CAPTCHA_CHECK,
            {
                "pointJson": challenge_hash(secret, interaction),
                "captchaType": "blockPuzzle",
                "token": token,
            },
            auth=False,
            with_t=False,
        )
        if not _captcha_passed(check):
            raise CaptchaError("登录验证码校验未通过")
        return captcha_proof(secret, token, interaction)

    def login(
        self,
        phone: str,
        password: str,
        *,
        system: str = "Android",
        system_version: str = "13",
        device: str = "android",
        captcha: str | None = None,
    ) -> tuple[LoginUser, GxyResponse]:
        proof = captcha if captcha is not None else self.solve_login_captcha()
        payload = {
            "phone": aes_encrypt(phone),
            "password": aes_encrypt(password),
            "captcha": proof,
            "loginType": device,
            "uuid": uuid.uuid1().hex,
            "device": device,
            "version": self.package_version,
            "t": aes_encrypt(str(int(time.time() * 1000))),
            "system": system,
            "systemVersion": system_version,
        }
        response = self._post(C.LOGIN, payload, auth=False, with_t=False)
        if not response.ok:
            raise _to_error(response)

        user_blob = response.data
        if isinstance(user_blob, str):
            try:
                user_blob = json.loads(aes_decrypt(user_blob))
            except Exception as exc:
                raise GxyAuthError(response.code, "登录成功但响应无法解密", response.data) from exc
        if not isinstance(user_blob, dict):
            raise ProtocolDrift("登录响应 data 结构未知")
        user = LoginUser.parse(user_blob)
        if not user.token or not user.user_id:
            raise GxyAuthError(response.code, "登录响应缺少 token/userId", None)
        self.session.apply(user)
        return user, response

    def restore(self, stored: Mapping[str, Any] | None) -> "SessionState":
        self.session = SessionState.from_store(stored)
        return self.session

    # ------------------------------------------------------------ read helpers
    def fetch_plans(self, *, use_v4: bool = False) -> list[dict[str, Any]]:
        path = C.PLAN_BY_STU_V4 if use_v4 else C.PLAN_BY_STU_V3
        payload = {} if use_v4 else {"pageSize": 999999}
        response = self._post_or_raise(path, payload, sign_parts=[self.session.user_id, self.session.role_key])
        return response.data if isinstance(response.data, list) else []

    def fetch_plan(self, *, use_v4: bool = False) -> PlanSummary | None:
        return pick_plan(self.fetch_plans(use_v4=use_v4))

    def fetch_job(self, plan_id: str) -> dict[str, Any]:
        response = self._post_or_raise(C.JOB_BY_STU_V4, {"planId": plan_id})
        return response.data if isinstance(response.data, dict) else {}

    def list_attendance(
        self,
        start: str,
        end: str,
        *,
        plan_id: str | None = None,
        teacher: bool = False,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"startTime": start, "endTime": end}
        if plan_id:
            payload["planId"] = plan_id
        path = C.ATTENDANCE_LIST_TEACHER if teacher else C.ATTENDANCE_LIST
        response = self._post_or_raise(path, payload)
        return response.data if isinstance(response.data, list) else []

    def attendance_records(
        self,
        start: str,
        end: str,
        *,
        plan_id: str | None = None,
        teacher: bool = False,
    ) -> list[AttendanceRecord]:
        return normalize_records(self.list_attendance(start, end, plan_id=plan_id, teacher=teacher))

    # ---------------------------------------------------------------- check-in
    def save_attendance(
        self,
        payload: Mapping[str, Any],
        *,
        replace: bool = False,
        teacher: bool = False,
        user_id: str | None = None,
    ) -> GxyResponse:
        path = (
            C.ATTENDANCE_SAVE_TEACHER
            if teacher
            else (C.ATTENDANCE_REPLACE if replace else C.ATTENDANCE_SAVE)
        )
        sign_parts = None if teacher else attendance_sign_parts(payload, user_id or self.session.user_id)
        return self._post(path, payload, sign_parts=sign_parts)

    def build_attendance(
        self,
        *,
        plan_id: str,
        kind: str,
        device: Any,
        location: Mapping[str, Any] | None,
        moment: dt.datetime | None = None,
        replace: bool = False,
        mirror_attendence_time: bool = True,
    ) -> dict[str, Any]:
        return build_attendance_payload(
            plan_id=plan_id,
            user_id=self.session.user_id,
            kind=kind,
            device=device,
            location=location,
            moment=moment or dt.datetime.now(),
            replace=replace,
            mirror_attendence_time=mirror_attendence_time,
        )

    # ------------------------------------------------------- attendance captcha
    def clock_captcha(self) -> dict[str, Any]:
        client_uid = uuid.uuid4().hex
        response = self._post_or_raise(
            C.CLOCK_CAPTCHA_GET,
            {"clientUid": client_uid, "captchaType": "clickWord"},
        )
        data = response.data if isinstance(response.data, dict) else {}
        if not data.get("originalImageBase64") or not data.get("token") or not data.get("secretKey"):
            raise ProtocolDrift("点选验证码响应字段不完整")
        # The page reuses this uid as `appUuid` when it retries the save.
        data["_clientUid"] = client_uid
        return data

    def solve_clock_captcha(self, attempts: int = 3) -> ClockCaptchaSolution:
        last: Exception | None = None
        for _ in range(attempts):
            try:
                data = self.clock_captcha()
                words = [str(w) for w in (data.get("wordList") or [])]
                interaction = self.captcha.solve_clickword(str(data["originalImageBase64"]), words)
                proof = self.submit_clock_captcha(
                    secret=str(data["secretKey"]),
                    token=str(data["token"]),
                    interaction=interaction,
                )
                return ClockCaptchaSolution(proof=proof, client_uid=str(data.get("_clientUid") or ""))
            except (CaptchaError, ProtocolDrift) as exc:
                last = exc
                time.sleep(0.6)
        raise CaptchaError("点选验证码自动识别未通过") from last

    def submit_clock_captcha(self, *, secret: str, token: str, interaction: str) -> str:
        check = self._post(
            C.CLOCK_CAPTCHA_CHECK,
            {
                "pointJson": challenge_hash(secret, interaction),
                "captchaType": "clickWord",
                "token": token,
            },
        )
        if not _captcha_passed(check):
            raise CaptchaError("点选验证码校验未通过")
        return captcha_proof(secret, token, interaction)

    # --------------------------------------------------------------- alipay
    def create_alipay_registration(self) -> dict[str, Any]:
        response = self._post_or_raise(C.ALIPAY_CREATE, {}, extra_headers={"client_id": C.CLIENT_ID})
        data = response.data if isinstance(response.data, dict) else {}
        return data

    def query_alipay_registration(self, out_register_no: str) -> GxyResponse:
        return self._post(
            C.ALIPAY_QUERY,
            {"outRegisterNo": out_register_no},
            extra_headers={"client_id": C.CLIENT_ID},
        )

    # ---------------------------------------------------------------- reports
    def list_reports(
        self,
        *,
        report_type: str,
        plan_id: str,
        page: int = 1,
        size: int = 100,
    ) -> list[dict[str, Any]]:
        response = self._post_or_raise(
            C.REPORT_LIST,
            {"currPage": page, "pageSize": size, "reportType": report_type, "planId": plan_id},
            sign_parts=[self.session.user_id, self.session.role_key, report_type],
        )
        return response.data if isinstance(response.data, list) else []

    def report_form(self, form_type: int, *, report_id: str | None = None, is_update: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {"formType": form_type}
        if report_id:
            payload["reportId"] = report_id
            if is_update:
                # APK: the edit branch sends the business value 1, not the Smi tag.
                payload["isUpdate"] = 1
        response = self._post_or_raise(C.REPORT_INFO, payload)
        return response.data if isinstance(response.data, dict) else {}

    def report_weeks(self) -> list[dict[str, Any]]:
        response = self._post_or_raise(C.REPORT_WEEKS, {})
        return response.data if isinstance(response.data, list) else []

    def build_report(
        self,
        *,
        plan_id: str,
        report_type: str,
        title: str,
        content: str,
        form_fields: list[dict[str, Any]] | None = None,
        period: Mapping[str, Any] | None = None,
        overrides: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return build_report_payload(
            plan_id=plan_id,
            report_type=report_type,
            title=title,
            content=content,
            form_fields=form_fields,
            period=period,
            overrides=overrides,
        )

    def save_report(self, payload: Mapping[str, Any], *, update: bool = False) -> GxyResponse:
        path = C.REPORT_UPDATE if update else C.REPORT_SAVE
        return self._post(path, payload, sign_parts=report_sign_parts(payload, self.session.user_id))

    def upload_token(self) -> str:
        response = self._post_or_raise(C.UPLOAD_TOKEN, {})
        return response.data if isinstance(response.data, str) else ""


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _captcha_passed(response: GxyResponse) -> bool:
    if response.code != C.CODE_OK:
        return False
    data = response.data
    if isinstance(data, dict) and "result" in data:
        return bool(data.get("result"))
    return True


def _to_error(response: GxyResponse) -> GxyError:
    if response.code == C.CODE_TOKEN_EXPIRED or response.msg in {
        "token失效", "Token失效", "token已失效", "Token已失效", "登录已失效", "请重新登录",
    }:
        return GxyAuthError(response.code, response.msg or "登录已失效", response.data)
    return GxyBusinessError(response.code, response.msg or "请求失败", response.data)
