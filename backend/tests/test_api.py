import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def token(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_is_public(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_protected_route_requires_token(client):
    assert client.get("/api/accounts").status_code == 401


def test_login_rejects_bad_password(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-pass"})
    assert response.status_code == 401


def test_account_crud(client, auth):
    created = client.post(
        "/api/accounts",
        headers=auth,
        json={
            "label": "测试账号",
            "phone": "13800138000",
            "password": "gxy-password",
            "location": {"address": "某市某路 1 号", "latitude": 30.1, "longitude": 120.2},
            "morning_time": "8:05",
            "weekdays": "5,1,1",
            "report_types": "day,week",
        },
    )
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["morning_time"] == "08:05"
    assert account["weekdays"] == "1,5"
    assert account["report_types"] == "day,week"
    assert "password_enc" not in account and "session_enc" not in account

    listed = client.get("/api/accounts", headers=auth).json()
    assert [item["id"] for item in listed] == [account["id"]]

    patched = client.patch(
        f"/api/accounts/{account['id']}",
        headers=auth,
        json={"auto_clock_in": True, "evening_time": "18:45"},
    )
    assert patched.status_code == 200
    assert patched.json()["auto_clock_in"] is True
    assert patched.json()["evening_time"] == "18:45"

    duplicate = client.post(
        "/api/accounts",
        headers=auth,
        json={"phone": "13800138000", "password": "x"},
    )
    assert duplicate.status_code == 409

    assert client.get("/api/verifications", headers=auth).json() == []
    overview = client.get("/api/overview", headers=auth).json()
    assert overview["accounts"] >= 1
    assert "counts" in overview

    executions = client.get("/api/executions", headers=auth).json()
    assert "items" in executions

    capabilities = client.get("/api/capabilities", headers=auth).json()
    assert capabilities["package_version"] == "5.41.6"
    assert "slider_ready" in capabilities["captcha"]

    deleted = client.delete(f"/api/accounts/{account['id']}", headers=auth)
    assert deleted.status_code == 200
    assert client.get("/api/accounts", headers=auth).json() == []


def test_invalid_schedule_is_rejected(client, auth):
    response = client.post(
        "/api/accounts",
        headers=auth,
        json={"phone": "13900000000", "password": "x", "morning_time": "25:99"},
    )
    assert response.status_code == 422


def test_admin_settings_are_masked(client, auth):
    response = client.get("/api/settings", headers=auth)
    assert response.status_code == 200
    assert "scheduler_enabled" in response.json()


def test_change_password_roundtrip(client, auth):
    response = client.post(
        "/api/auth/change-password",
        headers=auth,
        json={"old_password": "admin12345", "new_password": "another-strong-pass"},
    )
    assert response.status_code == 200
    assert client.post(
        "/api/auth/login", json={"username": "admin", "password": "another-strong-pass"}
    ).status_code == 200
    # restore for other tests
    client.post(
        "/api/auth/change-password",
        headers=auth,
        json={"old_password": "another-strong-pass", "new_password": "admin12345"},
    )


def test_unknown_api_path_does_not_return_the_spa(client):
    response = client.get("/api/this-route-does-not-exist")
    assert response.status_code == 404


def test_invalid_schedule_update_is_rejected(client, auth):
    created = client.post(
        "/api/accounts",
        headers=auth,
        json={"phone": "13700000000", "password": "x", "location": {"address": "A"}},
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]
    assert client.patch(
        f"/api/accounts/{account_id}", headers=auth, json={"morning_time": "99:99"}
    ).status_code == 422
    assert client.patch(
        f"/api/accounts/{account_id}", headers=auth, json={"weekdays": "1,9"}
    ).status_code == 422
    assert client.patch(
        f"/api/accounts/{account_id}", headers=auth, json={"morning_time": "7:05"}
    ).json()["morning_time"] == "07:05"
    client.delete(f"/api/accounts/{account_id}", headers=auth)


def test_profile_and_writing_plan_flow(client, auth):
    created = client.post(
        "/api/accounts",
        headers=auth,
        json={
            "label": "写作测试",
            "phone": "13600000000",
            "password": "x",
            "location": {"address": "某市某路 2 号", "latitude": 30.2, "longitude": 120.2},
            "coord_type": "gcj02",
            "profile": {
                "position": "后端开发实习生",
                "responsibilities": "维护接口；编写单元测试",
            },
            "weekdays": "1,2,3,4,5",
        },
    )
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["profile"]["position"] == "后端开发实习生"
    assert account["coord_type"] == "gcj02"
    account_id = account["id"]

    plan = client.post(
        f"/api/accounts/{account_id}/plans",
        headers=auth,
        json={"kind": "week", "start_date": "2026-03-02", "use_ai": False},
    )
    assert plan.status_code == 201, plan.text
    body = plan.json()
    assert body["source"] == "template"
    assert len(body["items"]) == 5
    plan_id = body["id"]

    patched = client.patch(
        f"/api/plans/{plan_id}/items/0",
        headers=auth,
        json={"theme": "熟悉项目", "tasks": ["读文档", "跑测试"]},
    )
    assert patched.status_code == 200
    assert patched.json()["items"][0]["theme"] == "熟悉项目"

    listed = client.get(f"/api/accounts/{account_id}/plans", headers=auth).json()
    assert listed and listed[0]["id"] == plan_id

    assert client.delete(f"/api/plans/{plan_id}", headers=auth).status_code == 200
    client.delete(f"/api/accounts/{account_id}", headers=auth)


def test_ai_settings_roundtrip(client, auth):
    initial = client.get("/api/settings/ai", headers=auth).json()
    assert initial["configured"] is False

    saved = client.put(
        "/api/settings/ai",
        headers=auth,
        json={"base_url": "https://api.example.com/v1", "model": "demo-model", "api_key": "sk-test"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["configured"] is True
    assert saved.json()["has_key"] is True

    assert client.get("/api/capabilities", headers=auth).json()["ai_configured"] is True

    cleared = client.delete("/api/settings/ai", headers=auth)
    assert cleared.status_code == 200
    assert client.get("/api/settings/ai", headers=auth).json()["configured"] is False


def test_map_config_is_available(client, auth):
    config = client.get("/api/map-config", headers=auth).json()
    assert "tile_url" in config and "tile_coord" in config


def test_map_settings_roundtrip_and_masking(client, auth):
    initial = client.get("/api/settings/map", headers=auth).json()
    assert "amap_key" not in initial
    assert initial["provider"] in {"osm", "amap"}

    saved = client.put(
        "/api/settings/map",
        headers=auth,
        json={
            "provider": "amap",
            "amap_key": "amap-secret-key-123",
            "tile_url": "https://webrd0{s}.is.autonavi.com/appmaptile?x={x}&y={y}&z={z}",
            "tile_subdomains": "1234",
            "tile_coord": "gcj02",
            "attribution": "© 高德地图",
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["has_amap_key"] is True
    assert "amap-secret-key-123" not in str(body)

    config = client.get("/api/map-config", headers=auth).json()
    assert config["geocoder"] == "amap"
    assert config["has_amap_key"] is True
    assert config["tile_coord"] == "gcj02"

    bad = client.put(
        "/api/settings/map",
        headers=auth,
        json={"provider": "amap", "tile_url": "https://example.com/{z}"},
    )
    assert bad.status_code == 400

    assert client.delete("/api/settings/map", headers=auth).status_code == 200
    restored = client.get("/api/map-config", headers=auth).json()
    assert restored["geocoder"] == initial["provider"]
