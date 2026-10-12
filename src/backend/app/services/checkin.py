"""签到（T2.3：BR-19、BR-20）。

检查顺序（03 §5.5）：活动未取消 → 在签到窗口内 → 记录为已报名 → 尚未签到 → 口令正确。
在写锁内检查「尚未签到」，同一学生并发提交多次也只记录一次（AC-11）。
"""
import secrets
import sqlite3
from datetime import datetime

from app.clock import hhmm, to_api, to_db
from app.config import Settings
from app.db import write_tx
from app.errors import AppError
from app.repo import activities, logs, registrations
from app.services import policies


def checkin(conn: sqlite3.Connection, activity_id: int, student_id: int, code: str,
            now: datetime, cfg: Settings) -> dict:
    ts = to_db(now)
    with write_tx(conn):
        act = activities.get(conn, activity_id)
        if act is None or act["status"] == "DRAFT":
            raise AppError("ACTIVITY_NOT_FOUND")
        if act["status"] == "CANCELLED":
            raise AppError("ACTIVITY_CANCELLED")
        open_at, close_at = policies.checkin_window(act, cfg.checkin_open_before_minutes)
        if now < open_at:
            raise AppError("CHECKIN_NOT_OPEN")
        if now > close_at:
            raise AppError("CHECKIN_CLOSED")

        reg = registrations.get(conn, activity_id, student_id)
        if reg is None or reg["status"] == "CANCELLED":
            raise AppError("CHECKIN_NOT_REGISTERED")
        if reg["status"] == "WAITLISTED":
            raise AppError("CHECKIN_WAITLISTED")
        if reg["checked_in_at"] is not None:
            raise AppError(
                "ALREADY_CHECKED_IN",
                f"您已于 {hhmm(reg['checked_in_at'], cfg.tz)} 签到，请勿重复签到",
                details={"checked_in_at": to_api(reg["checked_in_at"], cfg.tz)},
            )
        # 按 bytes 比较：compare_digest 的 str 参数只接受 ASCII，输入中文会抛 TypeError
        if not act["checkin_code"] or not secrets.compare_digest(
            code.strip().encode(), act["checkin_code"].encode()
        ):
            raise AppError("CHECKIN_CODE_INVALID")

        registrations.set_checked_in(conn, reg["id"], ts)
        logs.add_operation(conn, now=ts, actor_id=student_id, actor_role="student", action="CHECKIN",
                           activity_id=activity_id, target_student_id=student_id)
    return {"checked_in_at": to_api(ts, cfg.tz)}
