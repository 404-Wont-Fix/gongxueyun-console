import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import app
from app.models import AttendanceMonth, CalendarOverride, User
from app.security import create_access_token


def test_calendar_routes_scoped_and_override_roundtrip(db, account):
    owner = db.get(User, account.owner_id)
    other = User(username="calendar-api-other", password_hash="x", role="user")
    db.add(other)
    db.commit()
    own = {"Authorization": "Bearer " + create_access_token(owner.id, "user")}
    foreign = {"Authorization": "Bearer " + create_access_token(other.id, "user")}
    path = f"/api/calendar/overrides/{account.id}/2026-10-01"
    try:
        with TestClient(app) as client:
            assert client.get("/api/calendar?month=2026-10").status_code == 401
            assert client.get(f"/api/calendar?month=2026-10&account_id={account.id}", headers=foreign).status_code == 404
            assert client.get("/api/calendar?month=2026-10", headers=foreign).json()["accounts"] == []
            assert client.post("/api/calendar/sync?year=2026", headers=own).status_code == 403
            assert client.put(path, headers=foreign, json={"mode": "holiday"}).status_code == 404
            assert client.put(path, headers=own, json={"mode": "holiday"}).status_code == 200
            view = client.get(f"/api/calendar?month=2026-10&account_id={account.id}", headers=own).json()
            assert view["days"][0]["plans"][0]["mode"] == "holiday"
            assert client.put(path, headers=own, json={"mode": "invalid"}).status_code == 422
            assert client.delete(path, headers=own).status_code == 200
            assert client.get("/api/calendar?month=2026-13", headers=own).status_code == 400
            assert client.put(path.replace("2026-10-01", "2026-02-30"), headers=own, json={"mode": "skip"}).status_code == 400
    finally:
        db.expire_all()
        db.query(CalendarOverride).filter_by(account_id=account.id).delete()
        db.delete(other)
        db.commit()


def test_legacy_calendar_migration_preserves_weekdays(tmp_path, monkeypatch):
    import app.db as database

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE accounts (id INTEGER PRIMARY KEY, weekdays VARCHAR(16))"))
        connection.execute(text("INSERT INTO accounts (id, weekdays) VALUES (1, '1,3,5')"))
    monkeypatch.setattr(database, "engine", engine)
    database._apply_column_migrations()
    database._apply_column_migrations()  # idempotent
    with engine.connect() as connection:
        assert connection.execute(text("SELECT weekdays, calendar_enabled FROM accounts")).one() == ("1,3,5", 1)
    engine.dispose()


def test_record_sync_updates_cache_without_clockin(db, account, monkeypatch):
    from app.gxy.models import AttendanceRecord
    from app.services import runtime, clockin

    class Client:
        session = type("Session", (), {"user_type": "student"})()
        def attendance_records(self, *args, **kwargs):
            return [AttendanceRecord("server-holiday", "2026-10-01", "HOLIDAY", "2026-10-01 08:30:00", "NORMAL", "某地")]

    monkeypatch.setattr(runtime, "build_client", lambda _: Client())
    monkeypatch.setattr(runtime, "ensure_login", lambda *args: None)
    monkeypatch.setattr(clockin, "submit_clock_in", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not clock in")))
    headers = {"Authorization": "Bearer " + create_access_token(account.owner_id, "user")}
    try:
        with TestClient(app) as client:
            response = client.post(f"/api/calendar/records/{account.id}/sync?month=2026-10", headers=headers)
            assert response.status_code == 200, response.text
            response = client.get(f"/api/calendar?month=2026-10&account_id={account.id}", headers=headers)
            assert response.json()["stats"]["confirmed"] == 1
            assert response.json()["days"][0]["records"][0]["kind"] == "HOLIDAY"
    finally:
        db.query(AttendanceMonth).filter_by(account_id=account.id).delete()
        db.commit()
