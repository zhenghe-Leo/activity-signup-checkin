"""公共夹具：每个测试使用独立的临时数据库和固定时钟；不读取 .env，不依赖真实密钥。"""
import pytest
from fastapi.testclient import TestClient

from app import db
from app.clock import FixedClock
from app.config import Settings
from app.main import create_app
from app.seed import init_database
from fakes import FakeChatClient
from helpers import T0


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=str(tmp_path / "app.db"),
        deepseek_api_key="",
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def db_ready(settings, clock) -> Settings:
    """只导入账号，不导入演示活动；测试种子本身的用例显式调用 init/reset。"""
    init_database(settings, clock.now(), demo_activities=False)
    return settings


@pytest.fixture
def conn(db_ready):
    c = db.connect(db_ready.db_file, db_ready.db_busy_timeout_ms)
    yield c
    c.close()


@pytest.fixture
def fake_ai() -> FakeChatClient:
    return FakeChatClient()


@pytest.fixture
def app(db_ready, clock, fake_ai, tmp_path):
    """默认注入假 AI 客户端，任何测试都不会访问网络；不挂载前端，结果与本机是否构建过前端无关。"""
    return create_app(db_ready, clock, fake_ai, frontend_dist=tmp_path / "no-frontend")


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
