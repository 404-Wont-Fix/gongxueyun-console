"""Clock-in orchestration.

The important part is not "send a POST" but deciding what the response *means*:

===============  ==========================================================
response         action
===============  ==========================================================
302              点选验证码 → auto-solve; if unsolvable, hand the challenge
                 to the UI and wait (never treat as success)
303              人脸检测/识别 → pause; the client shows a notice only, so we
                 do **not** invent an Alipay link here
304              账户风险 → create the official registration (createAxdjk),
                 show the Alipay link, resume once after queryAxdj confirms
200 + 记录存在    success (the only status reported as success)
200 + 无记录      submitted_unconfirmed
其他 code         rejected / failed
===============  ==========================================================

Grounding for the 303/304 split (see analysis/api-offline/工学云完整流程与协议总表.md):
the APK's save callback treats 303's `data` as a *notice string*, not as an
Alipay token, and the createAxdjk/queryAxdj pair is a registration/query flow
that the newer repositories use for the 304 account-risk branch.

Writes are never blindly retried: a duplicate attendance is worse than a clear
failure. The only permitted retry is after the server rejected the request for
an expired token, after a captcha it explicitly asked for, or after the user
completed the verification it explicitly asked for.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..gxy.client import GxyClient, GxyResponse
from ..gxy.errors import CaptchaError, CaptchaUnavailable, GxyAuthError, GxyError
from ..models import Account, Execution, VerificationSession, utcnow
from ..security import decrypt_secret, encrypt_secret
from ..settings import get_settings
from . import runtime
from .notifier import notify

logger = logging.getLogger(__name__)

# Public status vocabulary (single source of truth for API + UI)
SUCCESS = "success"
SUBMITTED = "submitted_unconfirmed"
VERIFICATION = "verification_required"
CAPTCHA = "captcha_required"
REJECTED = "rejected"
FAILED = "failed"
BUSY = "busy"
DUPLICATE = "duplicate"

CLOCK_IN_KINDS = {"START", "END", "HOLIDAY"}

# 303 branch: the APK's `AttendancePageState.alipayFace` (0xec8440) launches this
# mini-program with `key1=value1&alipayToken=<token>` in the query.
ALIPAY_FACE_DEEPLINK = (
    "alipays://platformapi/startapp?appId=2021006127602453&page=pages/index/index&query="
)


@dataclass
class ClockInResult:
    status: str
    message: str
    execution_id: int | None = None
    session_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "execution_id": self.execution_id,
            "session_id": self.session_id,
            "detail": self.detail,
        }


def face_link(data: Any) -> str:
    """Build the Alipay face deep link only for a plausible token.

    The APK shows `data` as a dialog message, and `alipayFace` reads the token
    elsewhere. A Chinese notice must never be turned into a link (this is the
    false-positive path in tangqingfeng7's 303 handling), so the token shape is
    checked explicitly.
    """
    token = str(data or "").strip()
    if not token or len(token) > 512:
        return ""
    if any(ch.isspace() for ch in token):
        return ""
    if any("\u4e00" <= ch <= "\u9fff" for ch in token):
        return ""
    return ALIPAY_FACE_DEEPLINK + quote(f"key1=value1&alipayToken={token}", safe="")


def guard_key(account_id: int, day: str, kind: str) -> str:
    return f"{account_id}:{day}:{kind}"


def already_confirmed(db: Session, account_id: int, day: str, kind: str) -> bool:
    row = db.scalar(select(Execution).where(Execution.guard_key == guard_key(account_id, day, kind)))
    return row is not None and row.status == SUCCESS


def confirm_record(
    db: Session,
    account: Account,
    client: GxyClient,
    day: str,
    kind: str,
    *,
    attempts: int = 3,
    delay: float = 1.5,
) -> tuple[bool, str, str]:
    """Look for the attendance row the server actually stored.

    Returns ``(confirmed, server_time, state)`` where state is
    ``confirmed`` / ``missing`` / ``query_failed``.
    """
    teacher = (client.session.user_type or "").lower() == "teacher"
    state = "missing"
    for attempt in range(attempts):
        if attempt:
            time.sleep(delay)
        try:
            records = client.attendance_records(
                f"{day} 00:00:00",
                f"{day} 23:59:59",
                teacher=teacher,
            )
        except GxyError as exc:
            state = "query_failed"
            logger.info("attendance re-query failed (%s)", type(exc).__name__)
            continue
        for record in records:
            if record.day == day and record.kind == kind:
                return True, record.time, "confirmed"
        state = "missing"
    return False, "", state


def query_succeeded(response: GxyResponse) -> bool:
    """``queryAxdj`` is a void operation: the client accepts 200 + null.

    A ``data == false`` is *not* success, so the check is explicit instead of
    just ``response.ok``.
    """
    if not response.ok:
        return False
    data = response.data
    return data is None or data is True


def _mark_guard(db: Session, execution: Execution, account: Account, day: str, kind: str) -> None:
    execution.guard_key = guard_key(account.id, day, kind)
    try:
        db.add(execution)
        db.commit()
    except IntegrityError:
        db.rollback()
        execution.guard_key = None
        db.add(execution)
        db.commit()


def _detail_from(response: GxyResponse | None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if response is None:
        return {}
    detail: dict[str, Any] = {
        "code": response.code,
        "msg": response.msg,
        "marker": response.marker,
        "http_status": response.http_status,
    }
    data = response.data
    if isinstance(data, dict):
        detail["data_keys"] = sorted(data.keys())[:20]
        if data.get("attendanceId"):
            detail["attendanceId"] = str(data["attendanceId"])
    elif isinstance(data, str):
        detail["data_preview"] = data[:120]
    if payload is not None:
        detail["type"] = payload.get("type")
        detail["planId"] = payload.get("planId")
        detail["createTime"] = payload.get("createTime")
    return detail


def submit_clock_in(
    db: Session,
    account: Account,
    kind: str,
    *,
    trigger: str = "manual",
    when: dt.datetime | None = None,
    replace: bool = False,
    execution: Execution | None = None,
    payload: dict[str, Any] | None = None,
) -> ClockInResult:
    if kind not in CLOCK_IN_KINDS:
        raise ValueError("kind must be START, END or HOLIDAY")
    moment = when or dt.datetime.now(get_settings().tz)
    day = moment.date().isoformat()
    target_kind = kind

    if not replace and already_confirmed(db, account.id, day, target_kind):
        return ClockInResult(DUPLICATE, f"{day} 的 {target_kind} 已有确认记录，已跳过")

    owner = uuid.uuid4().hex
    if not runtime.acquire_lock(db, account.id, owner, get_settings().task_lock_seconds):
        return ClockInResult(BUSY, "该账号正在执行其他任务，请稍后", execution_id=execution.id if execution else None)

    execution = execution or runtime.start_execution(
        db,
        account,
        kind="REPLACE" if replace else "CLOCK_IN",
        subtype=kind,
        trigger=trigger,
        target_date=day,
        message=f"{'补卡' if replace else '打卡'} {target_kind}",
    )
    try:
        return _submit_locked(
            db, account, kind, day, moment, replace, trigger, execution, payload
        )
    finally:
        runtime.release_lock(db, account.id, owner)


def _submit_locked(
    db: Session,
    account: Account,
    kind: str,
    day: str,
    moment: dt.datetime,
    replace: bool,
    trigger: str,
    execution: Execution,
    payload: dict[str, Any] | None,
) -> ClockInResult:
    client = runtime.build_client(account)
    try:
        runtime.ensure_login(db, account, client)
    except Exception as exc:
        return _fail(db, account, execution, f"登录失败：{runtime.safe_error_message(exc)}")

    plan = runtime.cached_plan(account)
    if plan is None:
        try:
            plan = runtime.refresh_plan(db, account, client)
        except GxyAuthError as exc:
            return _fail(db, account, execution, f"登录已失效：{runtime.safe_error_message(exc)}")
        except GxyError as exc:
            return _fail(db, account, execution, f"获取实习计划失败：{runtime.safe_error_message(exc)}")
    if plan is None or not plan.plan_id:
        return _fail(db, account, execution, "账号下没有可用的实习计划")

    if payload is None:
        try:
            body = client.build_attendance(
                plan_id=plan.plan_id,
                kind=kind,
                device=runtime.device_state(account),
                location=account.location or {},
                moment=moment,
                replace=replace,
                mirror_attendence_time=account.mirror_attendence_time,
            )
        except ValueError as exc:
            return _fail(db, account, execution, f"打卡参数不完整：{exc}")
    else:
        body = payload

    teacher = (client.session.user_type or "").lower() == "teacher"
    try:
        response = client.save_attendance(body, replace=replace, teacher=teacher)
    except ValueError as exc:
        # Missing signature field / userId mismatch: never send a half-signed write.
        return _fail(db, account, execution, f"打卡参数不完整：{exc}")
    except GxyError as exc:
        return _fail(db, account, execution, f"提交失败：{runtime.safe_error_message(exc)}")

    # Expired token: the write was rejected, so one re-login + resend is safe.
    if response.code == 401 or (response.code not in (200,) and _is_auth_text(response.msg)):
        try:
            runtime.login_account(db, account, client)
            response = client.save_attendance(body, replace=replace, teacher=teacher)
        except GxyError as exc:
            return _fail(db, account, execution, f"刷新登录后重试失败：{runtime.safe_error_message(exc)}")

    return _interpret(
        db,
        account,
        client,
        execution,
        body,
        response,
        kind=kind,
        day=day,
        replace=replace,
        trigger=trigger,
        depth=0,
    )


def _is_auth_text(msg: str) -> bool:
    return "token" in str(msg or "").lower() or "登录" in str(msg or "")


def _interpret(
    db: Session,
    account: Account,
    client: GxyClient,
    execution: Execution,
    body: dict[str, Any],
    response: GxyResponse,
    *,
    kind: str,
    day: str,
    replace: bool,
    trigger: str,
    depth: int,
) -> ClockInResult:
    # A non-200 response can carry any msg text; only business success may be
    # interpreted as a control-flow marker. This is exactly where several older
    # projects report a false success.
    if response.code != 200:
        return _fail(
            db,
            account,
            execution,
            f"打卡被拒绝：code={response.code} msg={response.msg or '未知'}",
            status=REJECTED,
            detail=_detail_from(response, body),
        )

    marker = response.marker

    if marker == "302":
        if depth >= 2:
            session = _create_captcha_session(
                db, account, client, execution, kind, day, body, response, "验证码连续两次未通过"
            )
            _notify_verification(account, kind, day, "点选验证码")
            return ClockInResult(CAPTCHA, "点选验证码未通过，请在页面完成", execution.id, session.id)

        try:
            solved = client.solve_clock_captcha()
        except CaptchaUnavailable as exc:
            session = _create_captcha_session(db, account, client, execution, kind, day, body, response, str(exc))
            _notify_verification(account, kind, day, "点选验证码")
            return ClockInResult(CAPTCHA, "需要完成点选验证码", execution.id, session.id)
        except CaptchaError as exc:
            session = _create_captcha_session(
                db, account, client, execution, kind, day, body, response, str(exc)
            )
            _notify_verification(account, kind, day, "点选验证码")
            return ClockInResult(CAPTCHA, "点选验证码自动识别失败，请在页面完成", execution.id, session.id)

        retry_body = {**body, "captcha": solved.proof}
        if solved.client_uid:
            # kaka-niu's 302 branch sends the challenge uid back as `appUuid`.
            retry_body["appUuid"] = solved.client_uid
        try:
            retry = client.save_attendance(
                retry_body,
                replace=replace,
                teacher=(client.session.user_type or "").lower() == "teacher",
            )
        except GxyError as exc:
            return _fail(db, account, execution, f"验证码后提交失败：{runtime.safe_error_message(exc)}")
        return _interpret(
            db, account, client, execution, retry_body, retry,
            kind=kind, day=day, replace=replace, trigger=trigger, depth=depth + 1,
        )

    if marker in {"303", "304"}:
        verification_type = "face" if marker == "303" else "account"
        session = _create_verification_session(
            db, account, client, execution, kind, day, body, response, verification_type=verification_type
        )
        _notify_verification(
            account, kind, day, "人脸验证" if marker == "303" else "账户本人安全验证"
        )
        return ClockInResult(
            VERIFICATION,
            "需要本人完成安全验证后才能继续本次打卡",
            execution.id,
            session.id,
            {"verification_type": verification_type, "marker": marker, "has_link": bool(session.register_url_enc)},
        )

    confirmed, server_time, state = confirm_record(db, account, client, day, kind)
    detail = _detail_from(response, body)
    detail["confirmation_state"] = state
    if confirmed:
        detail["server_time"] = server_time
        _mark_guard(db, execution, account, day, kind)
        runtime.finish_execution(
            db, execution, status=SUCCESS, message=f"{day} {kind} 已由服务端记录确认", detail=detail, account=account
        )
        return ClockInResult(SUCCESS, f"{day} {kind} 打卡成功（已回查确认）", execution.id, detail=detail)

    runtime.finish_execution(
        db,
        execution,
        status=SUBMITTED,
        message="接口返回成功，但未在考勤记录中查到本次打卡",
        detail=detail,
        account=account,
    )
    return ClockInResult(SUBMITTED, "请求已被接受，但考勤记录未确认，请稍后在记录页核对", execution.id, detail=detail)


def _fail(
    db: Session,
    account: Account,
    execution: Execution,
    message: str,
    *,
    status: str = FAILED,
    detail: dict[str, Any] | None = None,
) -> ClockInResult:
    runtime.finish_execution(db, execution, status=status, message=message, detail=detail or {}, account=account)
    notify(
        f"工学云 {account.label or account.phone} 执行失败",
        message,
        event="failed",
        account_notify=account.notify,
    )
    return ClockInResult(status, message, execution.id, detail=detail or {})


# --------------------------------------------------------------- verification
def _store_payload(payload: dict[str, Any]) -> str:
    return encrypt_secret(json.dumps(payload, ensure_ascii=False))


def load_payload(session: VerificationSession) -> dict[str, Any]:
    if not session.payload_enc:
        return {}
    return json.loads(decrypt_secret(session.payload_enc))


def create_alipay_link(db: Session, account: Account, session_obj: VerificationSession, client: GxyClient) -> None:
    """Create the official registration for the 304 branch (best effort).

    Only called for ``account`` type: the 303 branch's payload is a notice
    string in the APK, so deriving an ``alipays://`` link from it is unsupported.
    A failure here does not break the flow — the user can complete verification
    in the official app and then press "我已完成验证".
    """
    if session_obj.register_url_enc or session_obj.verification_type != "account":
        return
    try:
        data = client.create_alipay_registration()
    except Exception as exc:  # noqa: BLE001 - surfaced as "no link" in UI
        logger.info("createAxdjk unavailable for account %s: %s", account.id, type(exc).__name__)
        return
    register_url = str(data.get("registerUrl") or "")
    out_register_no = str(data.get("outRegisterNo") or "")
    if not register_url.startswith("alipays://") or not out_register_no:
        logger.info("createAxdjk response incomplete for account %s", account.id)
        return
    session_obj.register_url_enc = encrypt_secret(register_url)
    session_obj.out_register_no_enc = encrypt_secret(out_register_no)
    db.add(session_obj)
    db.commit()


def _create_verification_session(
    db: Session,
    account: Account,
    client: GxyClient,
    execution: Execution,
    kind: str,
    day: str,
    body: dict[str, Any],
    response: GxyResponse,
    *,
    verification_type: str,
) -> VerificationSession:
    snapshot = {
        "version": 1,
        "body": body,
        "response": {"code": response.code, "msg": response.msg},
        "response_data": response.data if isinstance(response.data, (str, int, float, bool, dict, list)) else None,
        "replace": execution.kind == "REPLACE",
    }
    session_obj = VerificationSession(
        account_id=account.id,
        execution_id=execution.id,
        kind=kind,
        target_date=day,
        verification_type=verification_type,
        state="awaiting_verification",
        payload_enc=_store_payload(snapshot),
        expires_at=time.time() + 1800,
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)

    if verification_type == "account":
        create_alipay_link(db, account, session_obj, client)
    else:
        link = face_link(response.data)
        if link:
            session_obj.register_url_enc = encrypt_secret(link)
            db.add(session_obj)
            db.commit()

    runtime.finish_execution(
        db,
        execution,
        status=VERIFICATION,
        message="等待本人完成安全验证",
        detail=_detail_from(response, body) | {"verification_type": verification_type},
        account=account,
    )
    return session_obj


def _create_captcha_session(
    db: Session,
    account: Account,
    client: GxyClient,
    execution: Execution,
    kind: str,
    day: str,
    body: dict[str, Any],
    response: GxyResponse,
    reason: str,
) -> VerificationSession:
    challenge: dict[str, Any] = {}
    try:
        data = client.clock_captcha()
        challenge = {
            "secret": str(data.get("secretKey") or ""),
            "token": str(data.get("token") or ""),
            "image": str(data.get("originalImageBase64") or ""),
            "words": [str(w) for w in (data.get("wordList") or [])],
            "client_uid": str(data.get("_clientUid") or ""),
        }
    except GxyError:
        challenge = {}
    snapshot = {
        "version": 1,
        "body": body,
        "replace": execution.kind == "REPLACE",
        "captcha": challenge,
        "reason": reason,
    }
    session_obj = VerificationSession(
        account_id=account.id,
        execution_id=execution.id,
        kind=kind,
        target_date=day,
        verification_type="captcha",
        state="captcha_required",
        payload_enc=_store_payload(snapshot),
        expires_at=time.time() + 1800,
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)
    runtime.finish_execution(
        db,
        execution,
        status=CAPTCHA,
        message=reason or "需要点选验证码",
        detail=_detail_from(response, body),
        account=account,
    )
    return session_obj


def refresh_captcha(db: Session, session_obj: VerificationSession, account: Account) -> dict[str, Any]:
    client = runtime.build_client(account)
    runtime.ensure_login(db, account, client)
    data = client.clock_captcha()
    snapshot = load_payload(session_obj)
    snapshot["captcha"] = {
        "secret": str(data.get("secretKey") or ""),
        "token": str(data.get("token") or ""),
        "image": str(data.get("originalImageBase64") or ""),
        "words": [str(w) for w in (data.get("wordList") or [])],
        "client_uid": str(data.get("_clientUid") or ""),
    }
    session_obj.payload_enc = _store_payload(snapshot)
    session_obj.state = "captcha_required"
    session_obj.updated_at = utcnow()
    db.add(session_obj)
    db.commit()
    return public_captcha(snapshot)


def public_captcha(snapshot: dict[str, Any]) -> dict[str, Any]:
    captcha = snapshot.get("captcha") or {}
    return {
        "image": captcha.get("image") or "",
        "words": captcha.get("words") or [],
        "ready": bool(captcha.get("image") and captcha.get("token")),
    }


def complete_captcha(
    db: Session,
    account: Account,
    session_obj: VerificationSession,
    points: list[dict[str, Any]],
    *,
    trigger: str = "manual",
) -> ClockInResult:
    snapshot = load_payload(session_obj)
    captcha = snapshot.get("captcha") or {}
    words = captcha.get("words") or []
    if not words:
        raise ValueError("验证码上下文已失效，请刷新验证码")
    if len(points) != len(words):
        raise ValueError(f"需要按顺序点击 {len(words)} 个字符")
    secret = str(captcha.get("secret") or "")
    token = str(captcha.get("token") or "")

    client = runtime.build_client(account)
    runtime.ensure_login(db, account, client)
    if account.session_enc:
        client.restore(json.loads(decrypt_secret(account.session_enc)))

    from ..gxy.crypto import point_json  # local import keeps the module surface small

    interaction = point_json([{"x": int(p["x"]), "y": int(p["y"])} for p in points])
    try:
        proof = client.submit_clock_captcha(secret=secret, token=token, interaction=interaction)
    except (CaptchaError, GxyError) as exc:
        raise ValueError(f"验证码校验未通过：{runtime.safe_error_message(exc)}") from exc

    body = dict(snapshot.get("body") or {})
    body["captcha"] = proof
    if captcha.get("client_uid"):
        body["appUuid"] = captcha["client_uid"]
    replace = bool(snapshot.get("replace"))
    response = client.save_attendance(
        body, replace=replace, teacher=(client.session.user_type or "").lower() == "teacher"
    )

    session_obj.attempts += 1
    session_obj.updated_at = utcnow()
    db.add(session_obj)
    db.commit()

    execution = db.get(Execution, session_obj.execution_id) if session_obj.execution_id else None
    if execution is None:
        execution = runtime.start_execution(
            db, account, kind="REPLACE" if replace else "CLOCK_IN", subtype=session_obj.kind,
            trigger=trigger, target_date=session_obj.target_date, message="验证码后续提",
        )
        session_obj.execution_id = execution.id
        db.add(session_obj)
        db.commit()

    result = _interpret(
        db, account, client, execution, body, response,
        kind=session_obj.kind, day=session_obj.target_date, replace=replace, trigger=trigger, depth=1,
    )
    if result.status in {SUCCESS, SUBMITTED}:
        session_obj.record_confirmed = result.status == SUCCESS
        session_obj.state = "record_confirmed" if result.status == SUCCESS else "submitted_unconfirmed"
        session_obj.resume_state = result.status
        session_obj.payload_enc = ""
        db.add(session_obj)
        db.commit()
    elif result.status in {VERIFICATION, CAPTCHA} and result.session_id and result.session_id != session_obj.id:
        session_obj.state = "superseded"
        session_obj.payload_enc = ""
        db.add(session_obj)
        db.commit()
    return result


def _notify_verification(account: Account, kind: str, day: str, label: str) -> None:
    notify(
        f"工学云 {account.label or account.phone} 需要验证",
        f"{day} {kind} 需要{label}，请打开管理台完成验证。",
        event="verification_required",
        account_notify=account.notify,
    )
