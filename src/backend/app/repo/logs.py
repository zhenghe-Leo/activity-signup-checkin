"""operation_logs（只追加）的参数化 SQL。事务边界由调用方决定。"""
import json
import sqlite3


def add_operation(
    conn: sqlite3.Connection,
    *,
    now: str,
    actor_id: int | None,
    actor_role: str,
    action: str,
    activity_id: int | None,
    target_student_id: int | None = None,
    detail: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO operation_logs"
        " (occurred_at, actor_id, actor_role, action, activity_id, target_student_id, detail)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            now,
            actor_id,
            actor_role,
            action,
            activity_id,
            target_student_id,
            json.dumps(detail or {}, ensure_ascii=False),
        ),
    )


def list_for_activity(conn: sqlite3.Connection, activity_id: int) -> list[dict]:
    """活动的操作记录，按时间倒序（同一时刻按写入顺序倒序）。"""
    rows = conn.execute(
        "SELECT l.*, a.name AS actor_name, t.name AS target_student_name FROM operation_logs l"
        " LEFT JOIN users a ON a.id = l.actor_id LEFT JOIN users t ON t.id = l.target_student_id"
        " WHERE l.activity_id = ? ORDER BY l.occurred_at DESC, l.id DESC",
        (activity_id,),
    ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        item["detail"] = json.loads(item["detail"])
        result.append(item)
    return result


def count_action(conn: sqlite3.Connection, activity_id: int, action: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM operation_logs WHERE activity_id = ? AND action = ?", (activity_id, action)
    ).fetchone()[0]
