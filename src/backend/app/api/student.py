"""学生端接口（03 §5.3，角色：student）。只做入参出参与身份，业务判断在 services。"""
from datetime import date

from fastapi import APIRouter, status

from app.deps import ClockDep, ConnDep, SettingsDep, StudentDep
from app.schemas import (
    ActivityBriefOut, ActivityDetailOut, CancelRegistrationOut, CheckinIn, CheckinOut,
    MyRegistrationItemOut, NotificationsReadOut, RegisterOut,
)
from app.services import checkin, query, registration

router = APIRouter(tags=["学生"])


@router.get("/activities", response_model=list[ActivityBriefOut])
def list_activities(
    user: StudentDep, conn: ConnDep, clock: ClockDep, settings: SettingsDep,
    keyword: str | None = None,
    tags: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    has_seats: bool = False,
):
    """tags 为逗号分隔的多个标签，命中任意一个即可；其余条件之间为「且」。"""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    return query.list_activities(
        conn, clock.now(), settings,
        keyword=keyword, tags=tag_list, date_from=date_from, date_to=date_to, has_seats=has_seats,
    )


@router.get("/activities/{activity_id}", response_model=ActivityDetailOut)
def activity_detail(activity_id: int, user: StudentDep, conn: ConnDep, clock: ClockDep, settings: SettingsDep):
    return query.activity_detail(conn, activity_id, user["id"], clock.now(), settings)


@router.post("/activities/{activity_id}/registration", response_model=RegisterOut,
             status_code=status.HTTP_201_CREATED)
def register(activity_id: int, user: StudentDep, conn: ConnDep, clock: ClockDep):
    return registration.register(conn, activity_id, user["id"], clock.now())


@router.delete("/activities/{activity_id}/registration", response_model=CancelRegistrationOut)
def cancel_registration(activity_id: int, user: StudentDep, conn: ConnDep, clock: ClockDep):
    return registration.cancel(conn, activity_id, user["id"], clock.now())


@router.post("/activities/{activity_id}/checkin", response_model=CheckinOut)
def checkin_activity(activity_id: int, body: CheckinIn, user: StudentDep, conn: ConnDep,
                     clock: ClockDep, settings: SettingsDep):
    return checkin.checkin(conn, activity_id, user["id"], body.code, clock.now(), settings)


@router.get("/me/registrations", response_model=list[MyRegistrationItemOut])
def my_registrations(user: StudentDep, conn: ConnDep, clock: ClockDep, settings: SettingsDep):
    """只读，不改变通知状态；页面展示后再调用 POST /me/notifications/read。"""
    return query.my_registrations(conn, user["id"], clock.now(), settings)


@router.post("/me/notifications/read", response_model=NotificationsReadOut)
def mark_notifications_read(user: StudentDep, conn: ConnDep):
    return registration.mark_notifications_read(conn, user["id"])
