"""AI 接口（03 §5.3、§5.4）。模型失败时不返回错误，而是 200 + 降级结果，source 中标明模式和原因。"""
from fastapi import APIRouter

from app.ai import generator, nl_filter
from app.deps import AiClientDep, ClockDep, ConnDep, OrganizerDep, SettingsDep, StudentDep
from app.schemas import GenerateIn, GenerateOut, NlFilterIn, NlFilterOut

router = APIRouter(tags=["AI"])


@router.post("/organizer/ai/generate", response_model=GenerateOut)
def generate_content(body: GenerateIn, user: OrganizerDep, conn: ConnDep, clock: ClockDep,
                     settings: SettingsDep, client: AiClientDep):
    """A1：生成简介、标签、注意事项，只返回给表单，不保存（BR-23）。"""
    return generator.generate_for_organizer(conn, client, user["id"], body.model_dump(), clock.now(), settings)


@router.post("/ai/nl-filter", response_model=NlFilterOut)
def natural_language_filter(body: NlFilterIn, user: StudentDep, conn: ConnDep, clock: ClockDep,
                            settings: SettingsDep, client: AiClientDep):
    """A2：一句话筛选活动，返回解析出的条件、使用字段和结果（BR-25）。"""
    return nl_filter.filter_for_student(conn, client, user["id"], body.query, clock.now(), settings)
