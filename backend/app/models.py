"""ORM models.

Only what the product actually needs. Secrets (passwords, tokens, verification
payloads) are stored encrypted and never exposed through the API.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .settings import get_settings


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def local_now() -> dt.datetime:
    return dt.datetime.now(get_settings().tz)


def new_id() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")  # admin | user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    accounts: Mapped[list["Account"]] = relationship(back_populates="owner", cascade="all, delete-orphan")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Account(Base):
    """A 工学云 account plus its automation settings."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str] = mapped_column(String(32), index=True)
    password_enc: Mapped[str] = mapped_column(Text, default="")

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_clock_in: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_reports: Mapped[bool] = mapped_column(Boolean, default=False)

    device: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    location: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    coord_type: Mapped[str] = mapped_column(String(8), default="gcj02")
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    mirror_attendence_time: Mapped[bool] = mapped_column(Boolean, default=True)

    morning_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    morning_time: Mapped[str] = mapped_column(String(5), default="08:30")
    evening_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    evening_time: Mapped[str] = mapped_column(String(5), default="18:00")
    weekdays: Mapped[str] = mapped_column(String(16), default="1,2,3,4,5,6,7")
    calendar_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    report_time: Mapped[str] = mapped_column(String(5), default="21:00")
    report_types: Mapped[str] = mapped_column(String(32), default="day")

    notify: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    session_enc: Mapped[str] = mapped_column(Text, default="")
    session_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    job: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    last_status: Mapped[str] = mapped_column(String(32), default="idle")
    last_message: Mapped[str] = mapped_column(String(255), default="")
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lock_owner: Mapped[str] = mapped_column(String(64), default="")
    locked_until: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="accounts")
    executions: Mapped[list["Execution"]] = relationship(back_populates="account", cascade="all, delete-orphan")


class Execution(Base):
    """One unit of work: login probe, clock-in, report submit, query…"""

    __tablename__ = "executions"
    __table_args__ = (
        UniqueConstraint("guard_key", name="uq_execution_guard"),
        Index("ix_execution_account_created", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="CLOCK_IN")
    subtype: Mapped[str] = mapped_column(String(12), default="")
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    target_date: Mapped[str] = mapped_column(String(10), default="")
    guard_key: Mapped[str | None] = mapped_column(String(96), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    account: Mapped[Account] = relationship(back_populates="executions")


class VerificationSession(Base):
    """A paused clock-in that needs a human verification / captcha step."""

    __tablename__ = "verification_sessions"
    __table_args__ = (Index("ix_verification_state", "state", "expires_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(8), default="START")
    target_date: Mapped[str] = mapped_column(String(10), default="")
    verification_type: Mapped[str] = mapped_column(String(16), default="account")  # account | face | captcha
    state: Mapped[str] = mapped_column(String(32), default="captcha_required")

    payload_enc: Mapped[str] = mapped_column(Text, default="")
    register_url_enc: Mapped[str] = mapped_column(Text, default="")
    out_register_no_enc: Mapped[str] = mapped_column(Text, default="")

    verification_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    record_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    resume_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    resume_state: Mapped[str] = mapped_column(String(32), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    server_time: Mapped[str] = mapped_column(String(32), default="")

    expires_at: Mapped[float] = mapped_column(Float, default=0.0)
    last_checked_at: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ReportDraft(Base):
    __tablename__ = "report_drafts"
    __table_args__ = (Index("ix_draft_account_type", "account_id", "report_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    report_type: Mapped[str] = mapped_column(String(12), default="day")
    title: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    period_start: Mapped[str] = mapped_column(String(32), default="")
    period_end: Mapped[str] = mapped_column(String(32), default="")
    yearmonth: Mapped[str] = mapped_column(String(16), default="")
    weeks: Mapped[str] = mapped_column(String(16), default="")
    form_fields: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_date: Mapped[str] = mapped_column(String(10), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | submitted | failed
    remote_report_id: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReportPlan(Base):
    """A generated writing outline: one item per working day."""

    __tablename__ = "report_plans"
    __table_args__ = (Index("ix_plan_account_range", "account_id", "start_date", "end_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8), default="week")  # week | month
    start_date: Mapped[str] = mapped_column(String(10), default="")
    end_date: Mapped[str] = mapped_column(String(10), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | archived
    source: Mapped[str] = mapped_column(String(12), default="ai")  # ai | template | manual
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CalendarYear(Base):
    __tablename__ = "calendar_years"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    days: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sources: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="missing")
    message: Mapped[str] = mapped_column(String(500), default="")
    checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CalendarOverride(Base):
    __tablename__ = "calendar_overrides"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    mode: Mapped[str] = mapped_column(String(12))  # work | holiday | skip
    note: Mapped[str] = mapped_column(String(200), default="")


class AttendanceMonth(Base):
    __tablename__ = "attendance_months"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    records: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    synced_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
