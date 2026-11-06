"""Payload builders and parsers for the 工学云 protocol.

Field lists mirror the serializers recovered from the 5.41.6 APK
(`_$AttendanceModelToJson`, `_$ReportModelToJson`, `_$LoginUserFromJson`).

Rules borrowed from the analysis:

* time key is ``attendenceTime`` (typo is the server contract);
* ``type`` is ``START``/``END``/``HOLIDAY``; ``state`` is ``NORMAL``; replacement uses
  ``attendanceType="REPLACE"``;
* report ``formType`` is 7/8/9/10 for day/week/month/summary;
* a field existing in the model does **not** mean the caller must fill it.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from .constants import REPORT_FORM_TYPES, REPORT_KEYS

ATTENDANCE_KEYS = (
    "distance", "address", "lastAddress", "lastDetailAddress", "city", "area",
    "country", "latitude", "longitude", "province", "practiceAddress",
    "jobAddress", "jobAddrPoint",
    "attendanceId", "createBy", "createTime", "modifiedBy", "modifiedTime",
    "device", "isDeleted", "isReplace", "state", "type", "attendanceType",
    "attendenceTime", "isFirstSignInWeb", "isSYN", "applyState",
    "schoolId", "teacherId", "teacherNumber", "stuId", "planId", "username",
    "userId", "studentId", "studentNumber", "memberNumber", "headImg",
    "depName", "majorName", "className", "tpJobId",
    "content", "description", "images", "attachments", "logDtoList",
    "captcha", "appUuid", "isBeyondFence", "isBeyondFenceStu", "certifyId",
    "outRegisterNo",
)

LOCATION_KEYS = {
    "address", "distance", "lastAddress", "lastDetailAddress", "city", "area",
    "country", "latitude", "longitude", "province", "practiceAddress",
    "jobAddress", "jobAddrPoint", "isBeyondFence", "isBeyondFenceStu",
}

LOGIN_KEYS = (
    "userId", "moguNo", "nikeName", "gender", "userType", "token", "headImg",
    "plan", "orgJson", "roleName", "roleKey", "roleLevel", "dataList",
    "neteaseImId", "roleGroup", "user_type_data", "phone", "msgConfig",
    "isGraduate",
)


def empty_attendance() -> dict[str, Any]:
    return {key: None for key in ATTENDANCE_KEYS}


def empty_report() -> dict[str, Any]:
    return {key: None for key in REPORT_KEYS}


def format_local(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def build_attendance_payload(
    *,
    plan_id: str,
    user_id: str,
    kind: str,
    device: Any,
    location: Mapping[str, Any] | None,
    moment: dt.datetime,
    replace: bool = False,
    mirror_attendence_time: bool = True,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the 54-key save/replace body (without the network layer's ``t``)."""
    if kind not in {"START", "END", "HOLIDAY"}:
        raise ValueError("kind must be START, END or HOLIDAY")
    stamp = format_local(moment)
    data = empty_attendance()
    data.update(
        {
            "country": "中国",
            "createTime": stamp,
            "device": device,
            "state": "NORMAL",
            "type": kind,
            "planId": plan_id,
            "attendanceType": "REPLACE" if replace else None,
            "userId": user_id,
            "isFirstSignInWeb": None,
            "attendenceTime": None if replace or not mirror_attendence_time else stamp,
        }
    )
    for key, value in (location or {}).items():
        if key in LOCATION_KEYS and value is not None:
            data[key] = value
    for key, value in (overrides or {}).items():
        if key in ATTENDANCE_KEYS and value is not None:
            data[key] = value
    return data


def attendance_sign_parts(payload: Mapping[str, Any], user_id: str) -> list[str]:
    """Student save signature order: device, type, planId, userId, address."""
    parts: list[str] = []
    for key in ("device", "type", "planId", "userId", "address"):
        value = payload.get(key)
        if value is None or value == "":
            raise ValueError(f"打卡签名缺少字段: {key}")
        parts.append(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    if parts[3] != user_id:
        raise ValueError("打卡签名的 userId 与当前登录用户不一致")
    return parts


def build_report_payload(
    *,
    plan_id: str,
    report_type: str,
    title: str,
    content: str,
    form_fields: list[dict[str, Any]] | None = None,
    period: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if report_type not in REPORT_FORM_TYPES:
        raise ValueError(f"unsupported report type: {report_type}")
    data = empty_report()
    data.update(
        {
            "planId": plan_id,
            "reportType": report_type,
            "title": title,
            "content": content,
            "formFieldDtoList": form_fields or [],
            "fieldEntityList": form_fields or [],
            "isWarning": 0,
            "state": None,
            "reportTime": format_local(dt.datetime.now()),
        }
    )
    for key, value in (period or {}).items():
        if key in {"startTime", "endTime", "weeks", "yearmonth"} and value is not None:
            data[key] = value
    for key, value in (overrides or {}).items():
        if key in REPORT_KEYS and value is not None:
            data[key] = value
    return data


def report_sign_parts(payload: Mapping[str, Any], user_id: str) -> list[str]:
    """Report save/update signature: userId, reportType, planId, title."""
    parts: list[str] = []
    for key in ("reportType", "planId", "title"):
        value = payload.get(key)
        parts.append(value if isinstance(value, str) else ("" if value is None else str(value)))
    return [user_id, *parts]


@dataclass
class LoginUser:
    user_id: str = ""
    token: str = ""
    role_key: str = ""
    user_type: str = ""
    role_name: str = ""
    nickname: str = ""
    phone: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, payload: Mapping[str, Any] | None) -> "LoginUser":
        data = dict(payload or {})
        return cls(
            user_id=str(data.get("userId") or ""),
            token=str(data.get("token") or ""),
            role_key=str(data.get("roleKey") or ""),
            user_type=str(data.get("userType") or ""),
            role_name=str(data.get("roleName") or ""),
            nickname=str(data.get("nikeName") or data.get("nickName") or ""),
            phone=str(data.get("phone") or ""),
            raw=data,
        )

    def to_store(self) -> dict[str, Any]:
        """Only what the app needs later; the raw blob is not persisted."""
        return {
            "userId": self.user_id,
            "token": self.token,
            "roleKey": self.role_key,
            "userType": self.user_type,
            "roleName": self.role_name,
            "nikeName": self.nickname,
            "phone": self.phone,
        }


@dataclass
class AttendanceRecord:
    attendance_id: str
    day: str
    kind: str
    time: str
    state: str
    address: str
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, item: Mapping[str, Any]) -> "AttendanceRecord":
        raw = dict(item or {})
        stamp = str(raw.get("attendenceTime") or raw.get("createTime") or "")
        day = stamp[:10]
        return cls(
            attendance_id=str(raw.get("attendanceId") or ""),
            day=day,
            kind=str(raw.get("type") or ""),
            time=stamp,
            state=str(raw.get("state") or ""),
            address=str(raw.get("address") or ""),
            raw=raw,
        )


def normalize_records(items: Any) -> list[AttendanceRecord]:
    if not isinstance(items, list):
        return []
    records: list[AttendanceRecord] = []
    for item in items:
        if isinstance(item, Mapping):
            record = AttendanceRecord.parse(item)
            if record.day:
                records.append(record)
    return records


@dataclass
class PlanSummary:
    plan_id: str
    name: str
    start_time: str
    end_time: str
    state: Any
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, item: Mapping[str, Any]) -> "PlanSummary":
        raw = dict(item or {})
        return cls(
            plan_id=str(raw.get("planId") or ""),
            name=str(raw.get("planName") or ""),
            start_time=str(raw.get("startTime") or ""),
            end_time=str(raw.get("endTime") or ""),
            state=raw.get("state"),
            raw=raw,
        )


def pick_plan(items: Any) -> PlanSummary | None:
    """Pick the plan the client would use: first non-empty entry with a planId."""
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, Mapping) and item.get("planId"):
            return PlanSummary.parse(item)
    return None


def month_range(day: dt.date) -> tuple[str, str]:
    """First day 00:00:00 .. last day 00:00:00Z, matching the client helper.

    The APK formats the last day of the month (next month minus one day) at
    00:00:00 with a trailing ``Z``; 27xk's HelperFunctions does the same. The
    server compares dates, so this is the shape to reproduce.
    """
    first = day.replace(day=1)
    if first.month == 12:
        nxt = dt.date(first.year + 1, 1, 1)
    else:
        nxt = dt.date(first.year, first.month + 1, 1)
    last = nxt - dt.timedelta(days=1)
    return f"{first:%Y-%m-%d} 00:00:00", f"{last:%Y-%m-%d} 00:00:00Z"
