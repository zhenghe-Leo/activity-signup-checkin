"""registrations 表的参数化 SQL。事务边界由调用方决定。时间参数均为数据库格式（UTC 字符串）。"""
import sqlite3

_WITH_NAME = "SELECT r.*, u.name AS student_name FROM registrations r JOIN users u ON u.id = r.student_id"


def get(conn: sqlite3.Connection, activity_id: int, student_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM registrations WHERE activity_id = ? AND student_id = ?",
        (activity_id, student_id),
    ).fetchone()
    return dict(row) if row else None


def count_registered(conn: sqlite3.Connection, activity_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM registrations WHERE activity_id = ? AND status = 'REGISTERED'",
        (activity_id,),
    ).fetchone()[0]


def counts(conn: sqlite3.Connection, activity_id: int) -> dict:
    row = conn.execute(
        "SELECT"
        " COALESCE(SUM(status = 'REGISTERED'), 0) AS registered,"
        " COALESCE(SUM(status = 'WAITLISTED'), 0) AS waitlisted,"
        " COALESCE(SUM(checked_in_at IS NOT NULL), 0) AS checked_in,"
        " COALESCE(SUM(status = 'CANCELLED'), 0) AS cancelled"
        " FROM registrations WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    return dict(row)


def next_wait_seq(conn: sqlite3.Connection, activity_id: int) -> int:
    """入队取当前最大候补序号 + 1（03 §4.2）。"""
    return conn.execute(
        "SELECT COALESCE(MAX(wait_seq), 0) + 1 FROM registrations"
        " WHERE activity_id = ? AND status = 'WAITLISTED'",
        (activity_id,),
    ).fetchone()[0]


def waitlist_position(conn: sqlite3.Connection, activity_id: int, wait_seq: int) -> int:
    """候补位次 = 同一活动中候补序号 ≤ 本人序号的候补记录数（03 §4.5）。"""
    return conn.execute(
        "SELECT COUNT(*) FROM registrations"
        " WHERE activity_id = ? AND status = 'WAITLISTED' AND wait_seq <= ?",
        (activity_id, wait_seq),
    ).fetchone()[0]


def waitlist(conn: sqlite3.Connection, activity_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM registrations WHERE activity_id = ? AND status = 'WAITLISTED' ORDER BY wait_seq",
        (activity_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def active(conn: sqlite3.Connection, activity_id: int) -> list[dict]:
    """已报名和候补中的记录。"""
    rows = conn.execute(
        "SELECT * FROM registrations WHERE activity_id = ? AND status IN ('REGISTERED', 'WAITLISTED')"
        " ORDER BY id",
        (activity_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_for_activity(conn: sqlite3.Connection, activity_id: int) -> list[dict]:
    rows = conn.execute(
        f"{_WITH_NAME} WHERE r.activity_id = ?"
        " ORDER BY CASE r.status WHEN 'REGISTERED' THEN 0 WHEN 'WAITLISTED' THEN 1 ELSE 2 END,"
        " r.registered_at, r.wait_seq, r.id",
        (activity_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_for_student(conn: sqlite3.Connection, student_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM registrations WHERE student_id = ? ORDER BY updated_at DESC, id DESC", (student_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def insert(
    conn: sqlite3.Connection,
    activity_id: int,
    student_id: int,
    status: str,
    now: str,
    wait_seq: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO registrations"
        " (activity_id, student_id, status, registered_at, wait_seq, waitlisted_at, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            activity_id,
            student_id,
            status,
            now if status == "REGISTERED" else None,
            wait_seq,
            now if status == "WAITLISTED" else None,
            now,
            now,
        ),
    )
    return cur.lastrowid


def reactivate(conn: sqlite3.Connection, reg_id: int, status: str, now: str, wait_seq: int | None = None) -> None:
    """BR-02 再报名：复用已取消的记录，清空取消信息和旧通知。"""
    conn.execute(
        "UPDATE registrations SET status = ?, registered_at = ?, wait_seq = ?, waitlisted_at = ?,"
        " cancel_reason = NULL, cancelled_at = NULL, notify_status = 'NONE', notify_message = NULL,"
        " updated_at = ? WHERE id = ?",
        (
            status,
            now if status == "REGISTERED" else None,
            wait_seq,
            now if status == "WAITLISTED" else None,
            now,
            reg_id,
        ),
    )


def cancel(conn: sqlite3.Connection, reg_id: int, reason: str, now: str) -> None:
    conn.execute(
        "UPDATE registrations SET status = 'CANCELLED', cancel_reason = ?, cancelled_at = ?,"
        " wait_seq = NULL, updated_at = ? WHERE id = ?",
        (reason, now, now, reg_id),
    )


def promote(conn: sqlite3.Connection, reg_id: int, now: str) -> None:
    """候补中 → 已报名。"""
    conn.execute(
        "UPDATE registrations SET status = 'REGISTERED', registered_at = ?, wait_seq = NULL,"
        " updated_at = ? WHERE id = ?",
        (now, now, reg_id),
    )


def demote(conn: sqlite3.Connection, reg_id: int, wait_seq: int, now: str) -> None:
    """已报名 → 候补中（BR-13 缩减名额）。保留 registered_at 作为历史。"""
    conn.execute(
        "UPDATE registrations SET status = 'WAITLISTED', wait_seq = ?, waitlisted_at = ?, updated_at = ?"
        " WHERE id = ?",
        (wait_seq, now, now, reg_id),
    )


def notify(conn: sqlite3.Connection, reg_id: int, message: str, now: str) -> None:
    """BR-29：通知状态置为未读，保存最近一条通知内容。"""
    conn.execute(
        "UPDATE registrations SET notify_status = 'UNREAD', notify_message = ?, updated_at = ? WHERE id = ?",
        (message, now, reg_id),
    )


def set_checked_in(conn: sqlite3.Connection, reg_id: int, now: str) -> None:
    conn.execute(
        "UPDATE registrations SET checked_in_at = ?, updated_at = ? WHERE id = ?", (now, now, reg_id)
    )


def mark_all_read(conn: sqlite3.Connection, student_id: int) -> int:
    cur = conn.execute(
        "UPDATE registrations SET notify_status = 'READ' WHERE student_id = ? AND notify_status = 'UNREAD'",
        (student_id,),
    )
    return cur.rowcount
