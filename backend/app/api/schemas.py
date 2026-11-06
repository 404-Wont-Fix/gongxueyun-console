"""Request/response shapes. Secrets never appear in these models."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Kind = Literal["START", "END", "HOLIDAY"]
ReportType = Literal["day", "week", "month", "summary"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool = True

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ChangePassword(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = ""
    role: Literal["admin", "user"] = "user"


class LocationIn(BaseModel):
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None
    province: str = ""
    city: str = ""
    area: str = ""
    country: str = "中国"
    distance: float | None = None

    def as_payload(self) -> dict[str, Any]:
        return {key: value for key, value in self.model_dump().items() if value not in (None, "")}


class DeviceIn(BaseModel):
    state: str = "mobile"
    brand: str = "Android"
    systemVersion: str = "13"


class ProfileIn(BaseModel):
    """What the AI needs to write reports. Only position + responsibilities matter."""

    position: str = ""
    company: str = ""
    department: str = ""
    mentor: str = ""
    responsibilities: str = ""
    tools: str = ""
    tone: str = "平实、简洁、第一人称"
    avoid: str = "不编造具体数据、客户名称和奖励"

    def as_payload(self) -> dict[str, str]:
        return {key: value.strip() for key, value in self.model_dump().items()}


class AccountCreate(BaseModel):
    label: str = Field(default="", max_length=64)
    phone: str = Field(min_length=6, max_length=20)
    password: str = Field(min_length=1, max_length=128)
    owner_id: int | None = None
    enabled: bool = True
    auto_clock_in: bool = False
    auto_reports: bool = False
    device: DeviceIn = DeviceIn()
    location: LocationIn = LocationIn()
    coord_type: Literal["gcj02", "wgs84"] = "gcj02"
    profile: ProfileIn = ProfileIn()
    morning_enabled: bool = True
    morning_time: str = "08:30"
    evening_enabled: bool = True
    evening_time: str = "18:00"
    weekdays: str = "1,2,3,4,5,6,7"
    calendar_enabled: bool = True
    report_time: str = "21:00"
    report_types: str = "day"
    mirror_attendence_time: bool = True
    notify: dict[str, Any] = Field(default_factory=dict)

    @field_validator("morning_time", "evening_time", "report_time")
    @classmethod
    def _check_time(cls, value: str) -> str:
        try:
            hour, minute = (int(part) for part in value.split(":", 1))
        except ValueError as exc:
            raise ValueError("时间格式应为 HH:MM") from exc
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError("时间超出范围")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("weekdays")
    @classmethod
    def _check_weekdays(cls, value: str) -> str:
        items = [item.strip() for item in value.split(",") if item.strip()]
        for item in items:
            if item not in {"1", "2", "3", "4", "5", "6", "7"}:
                raise ValueError("星期只能是 1-7")
        return ",".join(sorted(set(items), key=int))

    @field_validator("report_types")
    @classmethod
    def _check_report_types(cls, value: str) -> str:
        items = [item.strip() for item in value.split(",") if item.strip()]
        for item in items:
            if item not in {"day", "week", "month", "summary"}:
                raise ValueError("报告类型无效")
        return ",".join(dict.fromkeys(items))


class AccountUpdate(BaseModel):
    label: str | None = None
    password: str | None = None
    enabled: bool | None = None
    auto_clock_in: bool | None = None
    auto_reports: bool | None = None
    device: DeviceIn | None = None
    location: LocationIn | None = None
    coord_type: Literal["gcj02", "wgs84"] | None = None
    profile: ProfileIn | None = None
    morning_enabled: bool | None = None
    morning_time: str | None = None
    evening_enabled: bool | None = None
    evening_time: str | None = None
    weekdays: str | None = None
    calendar_enabled: bool | None = None
    report_time: str | None = None
    report_types: str | None = None
    mirror_attendence_time: bool | None = None
    notify: dict[str, Any] | None = None

    @field_validator("morning_time", "evening_time", "report_time")
    @classmethod
    def _check_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            hour, minute = (int(part) for part in value.split(":", 1))
        except ValueError as exc:
            raise ValueError("时间格式应为 HH:MM") from exc
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError("时间超出范围")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("weekdays")
    @classmethod
    def _check_weekdays(cls, value: str | None) -> str | None:
        if value is None:
            return None
        items = [item.strip() for item in value.split(",") if item.strip()]
        for item in items:
            if item not in {"1", "2", "3", "4", "5", "6", "7"}:
                raise ValueError("星期只能是 1-7")
        return ",".join(sorted(set(items), key=int))

    @field_validator("report_types")
    @classmethod
    def _check_report_types(cls, value: str | None) -> str | None:
        if value is None:
            return None
        items = [item.strip() for item in value.split(",") if item.strip()]
        for item in items:
            if item not in {"day", "week", "month", "summary"}:
                raise ValueError("报告类型无效")
        return ",".join(dict.fromkeys(items))


class AccountOut(BaseModel):
    id: int
    label: str
    phone: str
    enabled: bool
    auto_clock_in: bool
    auto_reports: bool
    device: dict[str, Any]
    location: dict[str, Any]
    coord_type: str
    profile: dict[str, Any]
    morning_enabled: bool
    morning_time: str
    evening_enabled: bool
    evening_time: str
    weekdays: str
    calendar_enabled: bool
    report_time: str
    report_types: str
    mirror_attendence_time: bool
    has_session: bool
    session_updated_at: str | None
    plan: dict[str, Any]
    plan_updated_at: str | None
    job: dict[str, Any]
    last_status: str
    last_message: str
    last_run_at: str | None
    owner_id: int
    notify: dict[str, Any]


class ClockInRequest(BaseModel):
    kind: Kind
    when: str | None = Field(default=None, description="ISO 时间，缺省为当前时间")
    replace: bool = False
    trigger: str = "manual"


class CaptchaPoints(BaseModel):
    points: list[dict[str, float]] = Field(min_length=1, max_length=6)


class ReportDraftRequest(BaseModel):
    report_type: ReportType = "day"
    day: str | None = Field(default=None, description="YYYY-MM-DD")
    notes: str = ""
    use_ai: bool = True


class PlanOutlineRequest(BaseModel):
    kind: Literal["week", "month"] = "week"
    start_date: str | None = Field(default=None, description="YYYY-MM-DD，缺省为今天")
    notes: str = ""
    use_ai: bool = True


class PlanItemUpdate(BaseModel):
    theme: str | None = None
    tasks: list[str] | None = None
    key_points: str | None = None


class PlanUpdate(BaseModel):
    title: str | None = None
    status: Literal["active", "archived"] | None = None


class AISettingsIn(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    temperature: float = Field(default=0.6, ge=0, le=2)
    timeout: float = Field(default=60, ge=5, le=300)
    enabled: bool = True
    clear_key: bool = False


class AIProbeIn(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key: str = ""


class MapSettingsIn(BaseModel):
    provider: Literal["osm", "amap"] = "osm"
    amap_key: str = ""
    geocode_base_url: str = ""
    tile_url: str = ""
    tile_subdomains: str = ""
    tile_coord: Literal["gcj02", "wgs84"] = "gcj02"
    attribution: str = ""
    clear_key: bool = False


class MapProbeIn(BaseModel):
    provider: Literal["osm", "amap"] | None = None
    amap_key: str = ""
    geocode_base_url: str = ""
    q: str = "杭州"


class ReportDraftUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    form_fields: list[dict[str, Any]] | None = None


class ExecutionOut(BaseModel):
    id: int
    account_id: int
    account_label: str = ""
    kind: str
    subtype: str
    trigger: str
    status: str
    message: str
    target_date: str
    detail: dict[str, Any]
    created_at: dt.datetime
    finished_at: dt.datetime | None
    duration_ms: int


class NotifyTest(BaseModel):
    title: str = "工学云助手测试通知"
    body: str = "如果你收到这条消息，说明通知通道配置成功。"
