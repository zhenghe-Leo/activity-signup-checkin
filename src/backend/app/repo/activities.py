"""activities 表的参数化 SQL。事务边界由调用方决定。时间参数均为数据库格式（UTC 字符串）。"""
import json
import sqlite3

# 可以通过 insert / update 写入的列
EDITABLE = ("title", "location", "start_at", "end_at", "deadline_at", "capacity",
            "tags", "summary", "notes", "ai_call_id")
_JSON_COLUMNS = ("tags", "notes")

_REGISTERED_COUNT = (
    "(SELECT COUNT(*) FROM registrations r"
    " WHERE r.activity_id = a.id AND r.status = 'REGISTERED') AS registered_count"
)


def _to_dict(row: sqlite3.Row) -> dict:
    act = dict(row)
    for col in _JSON_COLUMNS:
        act[col] = json.loads(act[col])
    return act


def _encode(fields: dict) -> dict:
    return {k: (json.dumps(v, ensure_ascii=False) if k in _JSON_COLUMNS else v) for k, v in fields.items()}


def get(conn: sqlite3.Connection, activity_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT a.*, {_REGISTERED_COUNT} FROM activities a WHERE a.id = ?", (activity_id,)
    ).fetchone()
    return _to_dict(row) if row else None


def insert(conn: sqlite3.Connection, fields: dict, created_by: int, now: str) -> int:
    fields = _encode({k: v for k, v in fields.items() if k in EDITABLE})
    cols = [*fields, "status", "created_by", "created_at", "updated_at"]
    values = [*fields.values(), "DRAFT", created_by, now, now]
    cur = conn.execute(
        f"INSERT INTO activities ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", values
    )
    return cur.lastrowid


def update(conn: sqlite3.Connection, activity_id: int, fields: dict, now: str) -> None:
    fields = _encode({k: v for k, v in fields.items() if k in EDITABLE})
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE activities SET {assignments}, updated_at = ? WHERE id = ?",
        (*fields.values(), now, activity_id),
    )


def set_published(conn: sqlite3.Connection, activity_id: int, now: str) -> None:
    conn.execute(
        "UPDATE activities SET status = 'PUBLISHED', published_at = ?, updated_at = ? WHERE id = ?",
        (now, now, activity_id),
    )


def set_cancelled(conn: sqlite3.Connection, activity_id: int, now: str) -> None:
    conn.execute(
        "UPDATE activities SET status = 'CANCELLED', cancelled_at = ?, updated_at = ? WHERE id = ?",
        (now, now, activity_id),
    )


def set_checkin_code(conn: sqlite3.Connection, activity_id: int, code: str, now: str) -> None:
    conn.execute(
        "UPDATE activities SET checkin_code = ?, updated_at = ? WHERE id = ?", (code, now, activity_id)
    )


def list_all(conn: sqlite3.Connection) -> list[dict]:
    """组织者视角：全部活动（含草稿、已取消）。"""
    rows = conn.execute(
        f"SELECT a.*, {_REGISTERED_COUNT} FROM activities a ORDER BY a.start_at, a.id"
    ).fetchall()
    return [_to_dict(r) for r in rows]


def search_visible(
    conn: sqlite3.Connection,
    *,
    keyword: str | None = None,
    tags: list[str] | None = None,
    start_from: str | None = None,
    start_before: str | None = None,
    location: str | None = None,
    has_seats: bool = False,
) -> list[dict]:
    """学生可见的活动（已发布且未取消）+ 筛选条件。所有条件之间为「且」；多个标签之间为「或」。"""
    where = ["a.status = 'PUBLISHED'"]
    params: list = []
    if keyword:
        where.append("(a.title LIKE ? ESCAPE '\\' OR a.summary LIKE ? ESCAPE '\\')")
        params += [_like(keyword)] * 2
    if tags:
        where.append(
            f"EXISTS (SELECT 1 FROM json_each(a.tags) WHERE json_each.value IN ({', '.join('?' * len(tags))}))"
        )
        params += tags
    if start_from:
        where.append("a.start_at >= ?")
        params.append(start_from)
    if start_before:
        where.append("a.start_at < ?")
        params.append(start_before)
    if location:
        where.append("a.location LIKE ? ESCAPE '\\'")
        params.append(_like(location))
    sql = f"SELECT * FROM (SELECT a.*, {_REGISTERED_COUNT} FROM activities a WHERE {' AND '.join(where)})"
    if has_seats:
        sql += " WHERE capacity > registered_count"
    rows = conn.execute(sql + " ORDER BY start_at, id", params).fetchall()
    return [_to_dict(r) for r in rows]


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
