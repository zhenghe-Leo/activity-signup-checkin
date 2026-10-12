"""Pydantic 请求与响应模型（03 §5）。时间：请求须带时区偏移；响应为配置时区、带偏移的 ISO 8601。"""
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ErrorOut(BaseModel):
    code: str
    message: str
    details: Any | None = None


# ---------- 公共 ----------

class HealthOut(BaseModel):
    status: str


class UserOut(BaseModel):
    id: int
    name: str
    role: str


class LimitsOut(BaseModel):
    capacity_max: int
    title_max_len: int
    summary_max_len: int
    notes_max_items: int
    note_max_len: int
    tags_min: int
    tags_max: int


class MetaOut(BaseModel):
    tag_library: list[str]
    checkin_open_before_minutes: int
    limits: LimitsOut
    ai_enabled: bool


# ---------- 活动与报名 ----------

class ActivityBriefOut(BaseModel):
    id: int
    title: str
    location: str
    start_at: str
    end_at: str
    tags: list[str]
    capacity: int
    registered_count: int
    remaining: int
    phase: str = Field(description="DRAFT / OPEN 报名中 / CLOSED 已截止 / ONGOING 进行中 / ENDED 已结束 / CANCELLED")


class RegistrationViewOut(BaseModel):
    status: str
    display_status: str = Field(description="REGISTERED / CHECKED_IN / WAITLISTED / WAITLIST_EXPIRED / CANCELLED")
    cancel_reason: str | None
    waitlist_position: int | None
    registered_at: str | None
    checked_in_at: str | None
    notify_status: str
    notify_message: str | None


class ActivityDetailOut(ActivityBriefOut):
    deadline_at: str
    summary: str
    notes: list[str]
    waitlist_count: int
    my_registration: RegistrationViewOut | None


class MyRegistrationItemOut(BaseModel):
    activity: ActivityBriefOut
    registration: RegistrationViewOut


class RegisterOut(BaseModel):
    status: str
    waitlist_position: int | None


class CancelRegistrationOut(BaseModel):
    status: str
    promoted_count: int


class CheckinIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)


class CheckinOut(BaseModel):
    checked_in_at: str


class NotificationsReadOut(BaseModel):
    updated: int


# ---------- 组织者 ----------

class StatsOut(BaseModel):
    registered: int
    waitlisted: int
    checked_in: int
    cancelled: int
    checkin_rate: float = Field(description="已签到 / 已报名，0–1；已报名为 0 时为 0")
    promoted_count: int


class ActivitySummaryOut(ActivityBriefOut):
    status: str
    stats: StatsOut


class OrganizerActivityOut(ActivitySummaryOut):
    deadline_at: str
    summary: str
    notes: list[str]
    checkin_code: str | None
    ai_call_id: int | None
    created_at: str
    published_at: str | None
    cancelled_at: str | None


class ActivityCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    location: str
    start_at: AwareDatetime
    end_at: AwareDatetime
    deadline_at: AwareDatetime
    capacity: int
    tags: list[str] = []
    summary: str = ""
    notes: list[str] = []
    ai_call_id: int | None = None


class ActivityUpdateIn(BaseModel):
    """只提交要修改的字段。已发布活动修改名额、时间、地点、截止时间会返回 USE_CHANGE_FLOW。"""
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    location: str | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    deadline_at: AwareDatetime | None = None
    capacity: int | None = None
    tags: list[str] | None = None
    summary: str | None = None
    notes: list[str] | None = None
    ai_call_id: int | None = None


class CancelActivityOut(BaseModel):
    cancelled_registrations: int


class CheckinCodeOut(BaseModel):
    code: str


class RosterItemOut(RegistrationViewOut):
    student_id: int
    student_name: str


class OperationLogOut(BaseModel):
    id: int
    occurred_at: str
    actor_id: int | None
    actor_name: str | None
    actor_role: str
    action: str
    target_student_id: int | None
    target_student_name: str | None
    detail: dict


# ---------- AI ----------

class AiSourceOut(BaseModel):
    mode: str = Field(description="MODEL 模型 / FALLBACK 降级")
    reason: str | None = Field(description="NO_KEY / TIMEOUT / CALL_FAILED / INVALID_OUTPUT")
    reason_text: str | None
    model: str | None


class GenerateIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    location: str = Field(min_length=1, max_length=100)
    start_at: AwareDatetime
    end_at: AwareDatetime
    capacity: int = Field(ge=1)


class ContentIssueOut(BaseModel):
    field: str
    rule: str
    text: str
    message: str


class GenerateOut(BaseModel):
    summary: str
    tags: list[str]
    notes: list[str]
    issues: list[ContentIssueOut]
    source: AiSourceOut
    ai_call_id: int


class NlFilterIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class NlConditionsOut(BaseModel):
    keyword: str | None
    tags: list[str]
    date_from: str | None
    date_to: str | None
    location: str | None
    has_seats: bool


class NlFilterOut(BaseModel):
    conditions: NlConditionsOut
    used_fields: list[str]
    items: list[ActivityBriefOut]
    source: AiSourceOut
    message: str


# ---------- 发布后变更（M5） ----------

class ChangeIn(BaseModel):
    """只提交要调整的字段；与当前值相同的字段不算调整。"""
    model_config = ConfigDict(extra="forbid")

    capacity: int | None = None
    deadline_at: AwareDatetime | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    location: str | None = None


class ChangeConfirmIn(ChangeIn):
    preview_token: str = Field(min_length=1)


class StudentRefOut(BaseModel):
    student_id: int
    student_name: str


class ChangePreviewOut(BaseModel):
    changes: dict[str, dict] = Field(description="{字段: {from, to}}")
    demoted: list[StudentRefOut] = Field(description="将退回候补（成为已报名最晚的在前）")
    promoted: list[StudentRefOut] = Field(description="将被递补")
    notified: list[StudentRefOut] = Field(description="修改时间或地点时将收到变更通知")
    waitlist_after: list[StudentRefOut] = Field(description="调整后的候补顺序")
    preview_token: str


class ChangeConfirmOut(BaseModel):
    changes: dict[str, dict]
    demoted: list[StudentRefOut]
    promoted: list[StudentRefOut]
    notified: list[StudentRefOut]
    waitlist_after: list[StudentRefOut]
    activity: OrganizerActivityOut
