"""应用骨架测试：公共接口（03 §5.2）、身份与角色（AC-31）、统一错误结构（NFR-05、AC-31）。"""
import pytest
from fastapi import Body
from fastapi.testclient import TestClient

from app.deps import OrganizerDep, StudentDep
from app.errors import AppError
from app.seed import ACCOUNTS
from helpers import ORGANIZER_ID, STUDENT_IDS


@pytest.fixture
def probe_client(app):
    """在应用上挂几个测试专用路由，用来验证依赖和异常处理；业务路由从 M2 起补充。"""

    @app.get("/api/_probe/organizer")
    def organizer_only(user: OrganizerDep):
        return {"id": user["id"]}

    @app.get("/api/_probe/student")
    def student_only(user: StudentDep):
        return {"id": user["id"]}

    @app.post("/api/_probe/body")
    def needs_body(capacity: int = Body(..., embed=True)):
        return {"capacity": capacity}

    @app.get("/api/_probe/app-error")
    def app_error():
        raise AppError("ACTIVITY_NOT_FOUND")

    @app.get("/api/_probe/crash")
    def crash():
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------- 公共接口 ----------

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_users_lists_seed_accounts_without_identity(client):
    r = client.get("/api/users")
    assert r.status_code == 200
    assert [u["id"] for u in r.json()] == [a[0] for a in ACCOUNTS]
    assert set(r.json()[0]) == {"id", "name", "role"}


def test_meta_reports_config_and_ai_disabled_without_key(client):
    """无密钥时 ai_enabled=false（BR-26、NFR-09）；返回配置默认值（01-spec §7.2）。"""
    body = client.get("/api/meta").json()
    assert body["ai_enabled"] is False
    assert body["checkin_open_before_minutes"] == 30
    assert body["limits"]["capacity_max"] == 1000
    assert body["tag_library"][:2] == ["讲座", "竞赛"] and len(body["tag_library"]) == 10


def test_meta_ai_enabled_with_key_but_never_exposes_it(db_ready, clock):
    """NFR-08：配置了密钥时只返回布尔值，响应中不出现密钥。"""
    from pydantic import SecretStr

    from app.main import create_app

    fake_key = "sk-test-fake-key-not-real"
    settings = db_ready.model_copy(update={"deepseek_api_key": SecretStr(fake_key)})
    assert fake_key not in repr(settings)
    with TestClient(create_app(settings, clock)) as c:
        r = c.get("/api/meta")
    assert r.json()["ai_enabled"] is True
    assert fake_key not in r.text


def test_openapi_docs_available(client):
    """NFR-05：自动生成 OpenAPI 文档。"""
    assert client.get("/docs").status_code == 200
    assert "/api/health" in client.get("/openapi.json").json()["paths"]


# ---------- 身份与角色（AC-31） ----------

@pytest.mark.parametrize("headers", [{}, {"X-User-Id": "abc"}, {"X-User-Id": "9999"}])
def test_missing_or_unknown_identity_is_401(probe_client, headers):
    r = probe_client.get("/api/_probe/student", headers=headers)
    assert r.status_code == 401
    assert r.json() == {"code": "UNAUTHENTICATED", "message": "请先选择身份"}


def test_ac31_student_calling_organizer_api_is_403(probe_client):
    """AC-31：学生调用组织者接口 → 403「无权限」。"""
    r = probe_client.get("/api/_probe/organizer", headers={"X-User-Id": str(STUDENT_IDS["S1"])})
    assert r.status_code == 403
    assert r.json() == {"code": "FORBIDDEN", "message": "无权限"}


def test_roles_pass_for_matching_identity(probe_client):
    r1 = probe_client.get("/api/_probe/organizer", headers={"X-User-Id": str(ORGANIZER_ID)})
    r2 = probe_client.get("/api/_probe/student", headers={"X-User-Id": str(STUDENT_IDS["S2"])})
    assert r1.json() == {"id": ORGANIZER_ID} and r2.json() == {"id": STUDENT_IDS["S2"]}


# ---------- 统一错误结构（NFR-05、AC-31） ----------

@pytest.mark.parametrize("payload", [{}, {"capacity": "很多"}])
def test_ac31_invalid_request_returns_422_uniform_body(probe_client, payload):
    """AC-31：缺少必填字段或类型错误 → 422 + {code, message, details}。"""
    r = probe_client.post("/api/_probe/body", json=payload)
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR" and body["message"] == "请求参数不合法"
    assert body["details"][0]["field"].endswith("capacity")


def test_app_error_maps_to_status_and_body(probe_client):
    r = probe_client.get("/api/_probe/app-error")
    assert r.status_code == 404
    assert r.json() == {"code": "ACTIVITY_NOT_FOUND", "message": "活动不存在"}


def test_unknown_route_and_method_use_uniform_body(probe_client):
    r = probe_client.get("/api/no-such-route")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
    r = probe_client.delete("/api/health")
    assert r.status_code == 405 and r.json()["code"] == "METHOD_NOT_ALLOWED"


def test_unexpected_exception_is_500_without_leaking_details(probe_client):
    r = probe_client.get("/api/_probe/crash")
    assert r.status_code == 500
    assert r.json() == {"code": "INTERNAL_ERROR", "message": "服务器内部错误"}
    assert "boom" not in r.text


# ---------- 托管前端构建产物（T4.1） ----------

def test_frontend_dist_served_without_shadowing_api(db_ready, clock, fake_ai, tmp_path):
    """有 dist/index.html 时，根路径返回前端页面；/api 接口和统一错误结构不受影响。"""
    from app.main import create_app

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>前端</html>", encoding="utf-8")
    with TestClient(create_app(db_ready, clock, fake_ai, frontend_dist=dist)) as c:
        assert "前端" in c.get("/").text
        assert c.get("/api/health").json() == {"status": "ok"}
        r = c.get("/api/no-such-route")
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_no_dist_means_no_frontend_mount(db_ready, clock, fake_ai, tmp_path):
    from app.main import create_app

    with TestClient(create_app(db_ready, clock, fake_ai, frontend_dist=tmp_path / "missing")) as c:
        assert c.get("/").status_code == 404
