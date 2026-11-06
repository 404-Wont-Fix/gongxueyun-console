import os
import pathlib
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="gxy-test-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMP / 'test.db').as_posix()}")
os.environ.setdefault("APP_SECRET", "test-secret-key-with-enough-length-0123456789")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin12345")
os.environ.setdefault("CAPTCHA_MODEL_DIR", "")

import pytest


@pytest.fixture()
def db():
    from app.db import SessionLocal, init_db

    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def account(db):
    from app.models import Account, Execution, User, VerificationSession, ReportPlan

    user = User(username="u-test-clock", password_hash="x", role="user")
    db.add(user)
    db.commit()
    row = Account(
        owner_id=user.id,
        label="测试",
        phone="13800138000",
        password_enc="",
        plan={"planId": "p1", "planName": "实习计划"},
        device={"state": "mobile"},
        location={"address": "某地", "latitude": 1.0, "longitude": 2.0},
        profile={
            "position": "后端开发实习生",
            "company": "示例科技",
            "responsibilities": "维护接口；编写单元测试",
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    yield row
    db.query(Execution).filter(Execution.account_id == row.id).delete()
    db.query(VerificationSession).filter(VerificationSession.account_id == row.id).delete()
    db.query(ReportPlan).filter(ReportPlan.account_id == row.id).delete()
    db.delete(row)
    db.delete(user)
    db.commit()
