"""报名、候补、取消、递补（T2.2：BR-01~10、BR-29、BR-30）。

所有写操作都在 write_tx（BEGIN IMMEDIATE）内完成：检查与写入在同一把写锁里，并发时不超卖（DEC-02）。
检查顺序固定（03 §5.5），保证同一情形总是返回同一个错误码。
"""
import sqlite3
from datetime import datetime

from app.clock import to_db
from app.db import write_tx
from app.errors import AppError
from app.repo import activities, logs, registrations
from app.services import policies


def register(conn: sqlite3.Connection, activity_id: int, student_id: int, now: datetime) -> dict:
    """BR-01~03、BR-08~10：活动可见 → 未取消 → 未开始 → 未截止 → 不是有效记录 → 判断名额。"""
    ts = to_db(now)
    with write_tx(conn):
        act = _visible_activity(conn, activity_id)
        phase = policies.activity_phase(act, now)
        if phase == policies.CANCELLED:
            raise AppError("ACTIVITY_CANCELLED")
        if phase in (policies.ONGOING, policies.ENDED):
            raise AppError("ACTIVITY_STARTED")
        if phase == policies.CLOSED:
            raise AppError("REG_DEADLINE_PASSED")

        reg = registrations.get(conn, activity_id, student_id)
        if reg is not None:
            if reg["status"] == "REGISTERED":
                raise AppError("ALREADY_REGISTERED")
            if reg["status"] == "WAITLISTED":
                pos = registrations.waitlist_position(conn, activity_id, reg["wait_seq"])
                raise AppError("ALREADY_WAITLISTED", f"您已在候补队列中（第 {pos} 位）")

        # BR-03 / BR-04：锁内计数，有余量 → 已报名，否则 → 候补队尾
        if registrations.count_registered(conn, activity_id) < act["capacity"]:
            status, seq = "REGISTERED", None
        else:
            status, seq = "WAITLISTED", registrations.next_wait_seq(conn, activity_id)

        if reg is None:
            registrations.insert(conn, activity_id, student_id, status, ts, wait_seq=seq)
        else:  # BR-02：已取消的记录再报名，复用原记录
            registrations.reactivate(conn, reg["id"], status, ts, wait_seq=seq)

        pos = registrations.waitlist_position(conn, activity_id, seq) if seq is not None else None
        detail = {"position": pos} if pos is not None else {}
        if reg is not None:
            detail["reregister"] = True
        logs.add_operation(
            conn, now=ts, actor_id=student_id, actor_role="student",
            action="REGISTER" if status == "REGISTERED" else "WAITLIST",
            activity_id=activity_id, target_student_id=student_id, detail=detail,
        )
        return {"status": status, "waitlist_position": pos}


def cancel(conn: sqlite3.Connection, activity_id: int, student_id: int, now: datetime) -> dict:
    """BR-05：活动未取消 → 未开始 → 有已报名或候补记录 → 未签到。已报名者取消会触发递补（BR-06）。"""
    ts = to_db(now)
    with write_tx(conn):
        act = _visible_activity(conn, activity_id)
        if act["status"] == "CANCELLED":
            raise AppError("ACTIVITY_CANCELLED")
        if policies.has_started(act, now):
            raise AppError("ACTIVITY_STARTED", "活动已开始，无法取消")
        reg = registrations.get(conn, activity_id, student_id)
        if reg is None or reg["status"] == "CANCELLED":
            raise AppError("NOT_REGISTERED")
        if reg["checked_in_at"] is not None:
            raise AppError("CANCEL_AFTER_CHECKIN")

        registrations.cancel(conn, reg["id"], "BY_STUDENT", ts)
        logs.add_operation(
            conn, now=ts, actor_id=student_id, actor_role="student", action="CANCEL",
            activity_id=activity_id, target_student_id=student_id, detail={"from": reg["status"]},
        )
        promoted = promote_waitlist(conn, act, now) if reg["status"] == "REGISTERED" else []
        return {"status": "CANCELLED", "promoted_count": len(promoted)}


def promote_waitlist(conn: sqlite3.Connection, act: dict, now: datetime) -> list[int]:
    """BR-06、BR-07：有空位、有候补、活动已发布且未开始时，按 policies 依次递补，直到满员或候补为空。
    必须在调用方的写事务内执行，与触发它的操作一起提交。返回被递补的学生 ID。"""
    if act["status"] != "PUBLISHED" or policies.has_started(act, now):
        return []
    ts = to_db(now)
    promoted = []
    while registrations.count_registered(conn, act["id"]) < act["capacity"]:
        nxt = policies.pick_next_promotion(registrations.waitlist(conn, act["id"]))
        if nxt is None:
            break
        position = registrations.waitlist_position(conn, act["id"], nxt["wait_seq"])
        registrations.promote(conn, nxt["id"], ts)
        registrations.notify(conn, nxt["id"], f"您已从候补递补为正式报名：{act['title']}", ts)
        logs.add_operation(
            conn, now=ts, actor_id=None, actor_role="system", action="PROMOTE",
            activity_id=act["id"], target_student_id=nxt["student_id"], detail={"from_position": position},
        )
        promoted.append(nxt["student_id"])
    return promoted


def mark_notifications_read(conn: sqlite3.Connection, student_id: int) -> dict:
    """BR-29：学生打开「我的报名」后，本人所有未读通知置为已读。"""
    with write_tx(conn):
        return {"updated": registrations.mark_all_read(conn, student_id)}


def _visible_activity(conn: sqlite3.Connection, activity_id: int) -> dict:
    """草稿对学生不可见（§6.9），与不存在同样处理。"""
    act = activities.get(conn, activity_id)
    if act is None or act["status"] == "DRAFT":
        raise AppError("ACTIVITY_NOT_FOUND")
    return act
