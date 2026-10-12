"""FastAPI 依赖：配置、时钟、数据库连接、当前身份与角色校验（03 §5.1）。"""
import sqlite3
from typing import Annotated, Iterator

from fastapi import Depends, Header, Request

from app import db
from app.ai.client import ChatClient
from app.clock import Clock
from app.config import Settings
from app.errors import AppError
from app.repo import users


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_ai_client(request: Request) -> ChatClient:
    return request.app.state.ai_client


def get_conn(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[sqlite3.Connection]:
    """每个请求一个连接，请求结束后关闭（03 §7.1）。"""
    conn = db.connect(settings.db_file, settings.db_busy_timeout_ms)
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(
    conn: Annotated[sqlite3.Connection, Depends(get_conn)],
    x_user_id: Annotated[str | None, Header()] = None,
) -> dict:
    """按请求头 X-User-Id 识别身份：缺失、非整数或用户不存在 → 401。"""
    if x_user_id is None or not x_user_id.strip().isdigit():
        raise AppError("UNAUTHENTICATED")
    user = users.get_user(conn, int(x_user_id))
    if user is None:
        raise AppError("UNAUTHENTICATED")
    return user


def _require_role(role: str):
    def dependency(user: Annotated[dict, Depends(get_current_user)]) -> dict:
        if user["role"] != role:
            raise AppError("FORBIDDEN")
        return user

    return dependency


require_student = _require_role("student")
require_organizer = _require_role("organizer")

ConnDep = Annotated[sqlite3.Connection, Depends(get_conn)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ClockDep = Annotated[Clock, Depends(get_clock)]
AiClientDep = Annotated[ChatClient, Depends(get_ai_client)]
StudentDep = Annotated[dict, Depends(require_student)]
OrganizerDep = Annotated[dict, Depends(require_organizer)]
