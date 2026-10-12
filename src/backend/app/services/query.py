"""查询（T2.4）：学生列表与筛选、详情、我的报名、组织者汇总、名单、统计（BR-28）、操作记录。

只读，全部在 read_tx 内执行（WAL 下得到一致快照）。按时间变化的状态（阶段、候补失效）读取时实时计算。
接口中的时间统一转成配置时区、带偏移的 ISO 8601。
"""
import sqlite3
from datetime import date, datetime, timedelta

from app.clock import local_day_start_utc, to_api
from app.config import Settings
from app.db import read_tx
from app.errors import AppError
from app.repo import activities, logs, registrations
from app.services import policies


def list_activities(
    conn: sqlite3.Connection,
    now: datetime,
    cfg: Settings,
    *,
    keyword: str | None = None,
    tags: list[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    location: str | None = None,
    has_seats: bool = False,
) -> list[dict]:
    """学生活动列表（AC-27）：只含已发布且未取消的活动。日期按开始时间、配置时区的自然日计算。"""
    if date_from and date_to and date_from > date_to:
        raise AppError("VALIDATION_ERROR", "开始日期不能晚于结束日期")
    with read_tx(conn):
        rows = activities.search_visible(
            conn,
            keyword=(keyword or "").strip() or None,
            tags=tags or None,
            start_from=local_day_start_utc(date_from, cfg.tz) if date_from else None,
            start_before=local_day_start_utc(date_to + timedelta(days=1), cfg.tz) if date_to else None,
            location=(location or "").strip() or None,
            has_seats=has_seats,
        )
    return [_brief(a, now, cfg) for a in rows]


def activity_detail(conn: sqlite3.Connection, activity_id: int, student_id: int,
                    now: datetime, cfg: Settings) -> dict:
    """学生详情：草稿返回 404；已取消的活动可以看到，phase 为 CANCELLED。"""
    with read_tx(conn):
        act = activities.get(conn, activity_id)
        if act is None or act["status"] == "DRAFT":
            raise AppError("ACTIVITY_NOT_FOUND")
        reg = registrations.get(conn, activity_id, student_id)
        detail = {
            **_brief(act, now, cfg),
            "deadline_at": to_api(act["deadline_at"], cfg.tz),
            "summary": act["summary"],
            "notes": act["notes"],
            "waitlist_count": _stats(conn, act, now)["waitlisted"],
            "my_registration": _registration_view(conn, act, reg, now, cfg) if reg else None,
        }
    return detail


def my_registrations(conn: sqlite3.Connection, student_id: int, now: datetime, cfg: Settings) -> list[dict]:
    """我的报名：包含已取消的活动和已取消的记录（AC-13）。"""
    with read_tx(conn):
        result = []
        for reg in registrations.list_for_student(conn, student_id):
            act = activities.get(conn, reg["activity_id"])
            result.append({
                "activity": _brief(act, now, cfg),
                "registration": _registration_view(conn, act, reg, now, cfg),
            })
    return result


def organizer_activities(conn: sqlite3.Connection, now: datetime, cfg: Settings) -> list[dict]:
    """组织者汇总表（AC-28）：全部活动（含草稿、已取消）+ 每个活动的统计。"""
    with read_tx(conn):
        return [
            {**_brief(a, now, cfg), "status": a["status"], "stats": _stats(conn, a, now)}
            for a in activities.list_all(conn)
        ]


def organizer_activity(conn: sqlite3.Connection, activity_id: int, now: datetime, cfg: Settings) -> dict:
    """组织者视角的活动完整信息（含签到口令）。"""
    with read_tx(conn):
        act = activities.get(conn, activity_id)
        if act is None:
            raise AppError("ACTIVITY_NOT_FOUND")
        return {
            **_brief(act, now, cfg),
            "status": act["status"],
            "deadline_at": to_api(act["deadline_at"], cfg.tz),
            "summary": act["summary"],
            "notes": act["notes"],
            "checkin_code": act["checkin_code"],
            "ai_call_id": act["ai_call_id"],
            "created_at": to_api(act["created_at"], cfg.tz),
            "published_at": to_api(act["published_at"], cfg.tz),
            "cancelled_at": to_api(act["cancelled_at"], cfg.tz),
            "stats": _stats(conn, act, now),
        }


def roster(conn: sqlite3.Connection, activity_id: int, now: datetime, cfg: Settings) -> list[dict]:
    """组织者名单（AC-03、AC-10）：状态、签到、通知状态。"""
    with read_tx(conn):
        act = _get(conn, activity_id)
        return [
            {
                "student_id": r["student_id"],
                "student_name": r["student_name"],
                **_registration_view(conn, act, r, now, cfg),
            }
            for r in registrations.list_for_activity(conn, activity_id)
        ]


def activity_stats(conn: sqlite3.Connection, activity_id: int, now: datetime) -> dict:
    with read_tx(conn):
        return _stats(conn, _get(conn, activity_id), now)


def activity_logs(conn: sqlite3.Connection, activity_id: int, cfg: Settings) -> list[dict]:
    """活动的操作记录（AC-30），按时间倒序。"""
    with read_tx(conn):
        _get(conn, activity_id)
        items = logs.list_for_activity(conn, activity_id)
    for item in items:
        item["occurred_at"] = to_api(item["occurred_at"], cfg.tz)
        if item["actor_role"] == "system":
            item["actor_name"] = "系统"
    return items


# ---------- 组装 ----------

def _get(conn: sqlite3.Connection, activity_id: int) -> dict:
    act = activities.get(conn, activity_id)
    if act is None:
        raise AppError("ACTIVITY_NOT_FOUND")
    return act


def _brief(act: dict, now: datetime, cfg: Settings) -> dict:
    return {
        "id": act["id"],
        "title": act["title"],
        "location": act["location"],
        "start_at": to_api(act["start_at"], cfg.tz),
        "end_at": to_api(act["end_at"], cfg.tz),
        "tags": act["tags"],
        "capacity": act["capacity"],
        "registered_count": act["registered_count"],
        "remaining": max(act["capacity"] - act["registered_count"], 0),
        "phase": policies.activity_phase(act, now),
    }


def _stats(conn: sqlite3.Connection, act: dict, now: datetime) -> dict:
    """BR-28：候补中只计活动尚未开始的；签到率 = 已签到 / 已报名；递补人次来自操作日志。"""
    c = registrations.counts(conn, act["id"])
    waitlisted = 0 if policies.has_started(act, now) else c["waitlisted"]
    return {
        "registered": c["registered"],
        "waitlisted": waitlisted,
        "checked_in": c["checked_in"],
        "cancelled": c["cancelled"],
        "checkin_rate": round(c["checked_in"] / c["registered"], 4) if c["registered"] else 0.0,
        "promoted_count": logs.count_action(conn, act["id"], "PROMOTE"),
    }


def _display_status(act: dict, reg: dict, now: datetime) -> str:
    """展示状态：REGISTERED / CHECKED_IN / WAITLISTED / WAITLIST_EXPIRED / CANCELLED（03 §4.5）。"""
    if reg["status"] == "REGISTERED":
        return "CHECKED_IN" if reg["checked_in_at"] else "REGISTERED"
    if reg["status"] == "WAITLISTED":
        return "WAITLIST_EXPIRED" if policies.has_started(act, now) else "WAITLISTED"
    return "CANCELLED"


def _registration_view(conn: sqlite3.Connection, act: dict, reg: dict, now: datetime, cfg: Settings) -> dict:
    display = _display_status(act, reg, now)
    position = (
        registrations.waitlist_position(conn, act["id"], reg["wait_seq"]) if display == "WAITLISTED" else None
    )
    return {
        "status": reg["status"],
        "display_status": display,
        "cancel_reason": reg["cancel_reason"],
        "waitlist_position": position,
        "registered_at": to_api(reg["registered_at"], cfg.tz),
        "checked_in_at": to_api(reg["checked_in_at"], cfg.tz),
        "notify_status": reg["notify_status"],
        "notify_message": reg["notify_message"],
    }


