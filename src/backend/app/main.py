"""应用入口：挂载路由、全局异常处理（统一错误结构 {code, message}，NFR-05）。

开发启动：uvicorn app.main:app --app-dir src/backend --reload
测试中用 create_app(settings, clock, ai_client) 注入临时数据库、固定时钟和假的 AI 客户端。
"""
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ai.client import ChatClient, DeepSeekClient
from app.api import ai, organizer, public, student
from app.clock import Clock, SystemClock
from app.config import PROJECT_ROOT, Settings, get_settings
from app.errors import ERROR_TABLE, AppError, error_body

logger = logging.getLogger("app")

FRONTEND_DIST = PROJECT_ROOT / "src" / "frontend" / "dist"

_HTTP_STATUS_CODES = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def create_app(settings: Settings | None = None, clock: Clock | None = None,
               ai_client: ChatClient | None = None, frontend_dist: Path | None = None) -> FastAPI:
    app = FastAPI(title="校园活动报名与签到系统", version="0.1.0")
    app.state.settings = settings or get_settings()
    app.state.clock = clock or SystemClock()
    app.state.ai_client = ai_client or DeepSeekClient(app.state.settings)

    _register_error_handlers(app)
    app.include_router(public.router, prefix="/api")
    app.include_router(student.router, prefix="/api")
    app.include_router(organizer.router, prefix="/api")
    app.include_router(ai.router, prefix="/api")

    # 托管前端构建产物（npm run build 生成）；挂在所有 /api 路由之后，前端使用 hash 路由，不需要回退规则
    dist = frontend_dist or FRONTEND_DIST
    if (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_body())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
            for err in exc.errors()
        ]
        status, message = ERROR_TABLE["VALIDATION_ERROR"]
        return JSONResponse(status_code=status, content=error_body("VALIDATION_ERROR", message, details))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 框架层错误（如路由不存在、方法不允许）也转成统一结构
        code = _HTTP_STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = ERROR_TABLE[code][1] if code in ERROR_TABLE else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content=error_body(code, message))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未预期的异常：%s %s", request.method, request.url.path)
        status, message = ERROR_TABLE["INTERNAL_ERROR"]
        return JSONResponse(status_code=status, content=error_body("INTERNAL_ERROR", message))


app = create_app()
