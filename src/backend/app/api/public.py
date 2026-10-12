"""公共接口（03 §5.2）：不需要身份。"""
from fastapi import APIRouter

from app.config import TAG_LIBRARY
from app.deps import ConnDep, SettingsDep
from app.repo import users
from app.schemas import HealthOut, LimitsOut, MetaOut, UserOut

router = APIRouter(tags=["公共"])


@router.get("/health", response_model=HealthOut)
def health() -> dict:
    return {"status": "ok"}


@router.get("/users", response_model=list[UserOut])
def list_users(conn: ConnDep) -> list[dict]:
    """预置账号列表，供前端身份切换使用。"""
    return users.list_users(conn)


@router.get("/meta", response_model=MetaOut)
def meta(settings: SettingsDep) -> dict:
    """前端需要的配置。ai_enabled 只是布尔值，不暴露密钥。"""
    return {
        "tag_library": TAG_LIBRARY,
        "checkin_open_before_minutes": settings.checkin_open_before_minutes,
        "limits": LimitsOut(
            capacity_max=settings.capacity_max,
            title_max_len=settings.title_max_len,
            summary_max_len=settings.summary_max_len,
            notes_max_items=settings.notes_max_items,
            note_max_len=settings.note_max_len,
            tags_min=settings.tags_min,
            tags_max=settings.tags_max,
        ),
        "ai_enabled": settings.ai_enabled,
    }
