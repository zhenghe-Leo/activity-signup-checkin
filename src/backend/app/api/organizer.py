"""组织者端接口（03 §5.4，角色：organizer，前缀 /api/organizer）。"""
from fastapi import APIRouter, status

from app.deps import ClockDep, ConnDep, OrganizerDep, SettingsDep
from app.schemas import (
    ActivityCreateIn, ActivitySummaryOut, ActivityUpdateIn, CancelActivityOut, ChangeConfirmIn,
    ChangeConfirmOut, ChangeIn, ChangePreviewOut, CheckinCodeOut,
    OperationLogOut, OrganizerActivityOut, RosterItemOut, StatsOut,
)
from app.services import activity, change, query

router = APIRouter(prefix="/organizer", tags=["组织者"])


@router.get("/activities", response_model=list[ActivitySummaryOut])
def list_activities(user: OrganizerDep, conn: ConnDep, clock: ClockDep, settings: SettingsDep):
    """汇总表：全部活动（含草稿、已取消）及各自的统计。"""
    return query.organizer_activities(conn, clock.now(), settings)


@router.post("/activities", response_model=OrganizerActivityOut, status_code=status.HTTP_201_CREATED)
def create_activity(body: ActivityCreateIn, user: OrganizerDep, conn: ConnDep, clock: ClockDep,
                    settings: SettingsDep):
    return activity.create(conn, user["id"], body.model_dump(), clock.now(), settings)


@router.get("/activities/{activity_id}", response_model=OrganizerActivityOut)
def get_activity(activity_id: int, user: OrganizerDep, conn: ConnDep, clock: ClockDep, settings: SettingsDep):
    return query.organizer_activity(conn, activity_id, clock.now(), settings)


@router.put("/activities/{activity_id}", response_model=OrganizerActivityOut)
def update_activity(activity_id: int, body: ActivityUpdateIn, user: OrganizerDep, conn: ConnDep,
                    clock: ClockDep, settings: SettingsDep):
    return activity.update(conn, user["id"], activity_id, body.model_dump(exclude_unset=True),
                           clock.now(), settings)


@router.post("/activities/{activity_id}/publish", response_model=OrganizerActivityOut)
def publish_activity(activity_id: int, user: OrganizerDep, conn: ConnDep, clock: ClockDep,
                     settings: SettingsDep):
    return activity.publish(conn, user["id"], activity_id, clock.now(), settings)


@router.post("/activities/{activity_id}/cancel", response_model=CancelActivityOut)
def cancel_activity(activity_id: int, user: OrganizerDep, conn: ConnDep, clock: ClockDep,
                    settings: SettingsDep):
    return activity.cancel(conn, user["id"], activity_id, clock.now(), settings)


@router.post("/activities/{activity_id}/checkin-code", response_model=CheckinCodeOut)
def reset_checkin_code(activity_id: int, user: OrganizerDep, conn: ConnDep, clock: ClockDep):
    return activity.reset_checkin_code(conn, user["id"], activity_id, clock.now())


@router.get("/activities/{activity_id}/registrations", response_model=list[RosterItemOut])
def activity_roster(activity_id: int, user: OrganizerDep, conn: ConnDep, clock: ClockDep,
                    settings: SettingsDep):
    return query.roster(conn, activity_id, clock.now(), settings)


@router.get("/activities/{activity_id}/stats", response_model=StatsOut)
def activity_stats(activity_id: int, user: OrganizerDep, conn: ConnDep, clock: ClockDep):
    return query.activity_stats(conn, activity_id, clock.now())


@router.get("/activities/{activity_id}/logs", response_model=list[OperationLogOut])
def activity_logs(activity_id: int, user: OrganizerDep, conn: ConnDep, settings: SettingsDep):
    """操作记录，按时间倒序。"""
    return query.activity_logs(conn, activity_id, settings)


@router.post("/activities/{activity_id}/changes/preview", response_model=ChangePreviewOut)
def preview_change(activity_id: int, body: ChangeIn, user: OrganizerDep, conn: ConnDep, clock: ClockDep,
                   settings: SettingsDep):
    """发布后调整名额、截止时间、时间、地点：只计算影响，不修改数据（BR-12）。"""
    return change.preview(conn, activity_id, body.model_dump(exclude_unset=True), clock.now(), settings)


@router.post("/activities/{activity_id}/changes/confirm", response_model=ChangeConfirmOut)
def confirm_change(activity_id: int, body: ChangeConfirmIn, user: OrganizerDep, conn: ConnDep, clock: ClockDep,
                   settings: SettingsDep):
    """在一个事务内完成调整；预览之后数据有变化则拒绝，需要重新预览（BR-16）。"""
    data = body.model_dump(exclude_unset=True)
    token = data.pop("preview_token")
    return change.confirm(conn, user["id"], activity_id, data, token, clock.now(), settings)
