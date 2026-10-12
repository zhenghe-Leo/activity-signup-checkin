"""测试辅助：构造数据、检查不变量（03 §7.4）。"""
import sqlite3
from datetime import datetime, timedelta, timezone

from app.clock import to_db

# 默认测试时间：2026-10-13 10:00（北京时间）
T0 = datetime(2026, 10, 13, 2, 0, tzinfo=timezone.utc)

ORGANIZER_ID = 1
STUDENT_IDS = {"S1": 2, "S2": 3, "S3": 4, "S4": 5, "S5": 6, "S6": 7}
S1, S2, S3, S4, S5, S6 = (STUDENT_IDS[k] for k in ("S1", "S2", "S3", "S4", "S5", "S6"))
O1 = ORGANIZER_ID

# 默认活动时间：开始 = T0 + 3 天，结束 = 开始 + 2 小时，截止 = 开始 − 1 天；签到窗口 = 开始前 30 分钟
START = T0 + timedelta(days=3)
END = START + timedelta(hours=2)
DEADLINE = START - timedelta(days=1)


def hdr(user_id: int) -> dict:
    return {"X-User-Id": str(user_id)}


def api_create(client, *, capacity: int = 2, start: datetime = START, end: datetime | None = None,
               deadline: datetime | None = None, tags=("讲座",), title: str = "活动 A",
               publish: bool = True, **extra) -> int:
    """通过组织者接口创建（并发布）活动，返回活动 ID。"""
    body = {
        "title": title, "location": "图书馆报告厅", "capacity": capacity, "tags": list(tags),
        "start_at": start.isoformat(), "end_at": (end or start + timedelta(hours=2)).isoformat(),
        "deadline_at": (deadline or start - timedelta(days=1)).isoformat(), **extra,
    }
    r = client.post("/api/organizer/activities", json=body, headers=hdr(O1))
    assert r.status_code == 201, r.text
    activity_id = r.json()["id"]
    if publish:
        r = client.post(f"/api/organizer/activities/{activity_id}/publish", headers=hdr(O1))
        assert r.status_code == 200, r.text
    return activity_id


def register(client, activity_id: int, student_id: int):
    return client.post(f"/api/activities/{activity_id}/registration", headers=hdr(student_id))


def cancel(client, activity_id: int, student_id: int):
    return client.delete(f"/api/activities/{activity_id}/registration", headers=hdr(student_id))


def checkin(client, activity_id: int, student_id: int, code: str):
    return client.post(f"/api/activities/{activity_id}/checkin", json={"code": code}, headers=hdr(student_id))


def new_code(client, activity_id: int) -> str:
    r = client.post(f"/api/organizer/activities/{activity_id}/checkin-code", headers=hdr(O1))
    assert r.status_code == 200, r.text
    return r.json()["code"]


def my_reg(client, activity_id: int, student_id: int) -> dict | None:
    """学生视角：该活动详情中的 my_registration。"""
    r = client.get(f"/api/activities/{activity_id}", headers=hdr(student_id))
    assert r.status_code == 200, r.text
    return r.json()["my_registration"]


def roster(client, activity_id: int) -> dict:
    """组织者名单，按学生 ID 索引。"""
    r = client.get(f"/api/organizer/activities/{activity_id}/registrations", headers=hdr(O1))
    assert r.status_code == 200, r.text
    return {row["student_id"]: row for row in r.json()}


def stats(client, activity_id: int) -> dict:
    r = client.get(f"/api/organizer/activities/{activity_id}/stats", headers=hdr(O1))
    assert r.status_code == 200, r.text
    return r.json()


def assert_error(resp, status: int, code: str, message: str | None = None) -> None:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["code"] == code, body
    if message is not None:
        assert body["message"] == message, body


def make_activity(
    conn: sqlite3.Connection,
    now: datetime,
    *,
    capacity: int,
    status: str = "PUBLISHED",
    start_in: timedelta = timedelta(days=3),
    title: str = "测试活动",
) -> int:
    """直接写库构造一个活动（报名中阶段：截止时间在开始前 1 天）。"""
    start = now + start_in
    end = start + timedelta(hours=2)
    deadline = start - timedelta(days=1)
    ts = to_db(now)
    cur = conn.execute(
        "INSERT INTO activities (title, location, start_at, end_at, deadline_at, capacity,"
        " tags, status, created_by, created_at, updated_at, published_at, cancelled_at)"
        " VALUES (?, '图书馆报告厅', ?, ?, ?, ?, '[\"讲座\"]', ?, ?, ?, ?, ?, ?)",
        (
            title, to_db(start), to_db(end), to_db(deadline), capacity, status,
            ORGANIZER_ID, ts, ts,
            ts if status != "DRAFT" else None,
            ts if status == "CANCELLED" else None,
        ),
    )
    return cur.lastrowid


def add_students(conn: sqlite3.Connection, n: int, start_id: int = 100) -> list[int]:
    ids = list(range(start_id, start_id + n))
    conn.executemany(
        "INSERT INTO users (id, name, role) VALUES (?, ?, 'student')",
        [(i, f"测试学生{i}") for i in ids],
    )
    return ids


def assert_invariants(conn: sqlite3.Connection) -> None:
    """03 §7.4 不变量 I1–I4，每个并发测试结束后都要检查。"""
    i1 = conn.execute(
        "SELECT a.id FROM activities a WHERE a.capacity <"
        " (SELECT COUNT(*) FROM registrations r WHERE r.activity_id = a.id AND r.status = 'REGISTERED')"
    ).fetchall()
    assert i1 == [], f"I1 已报名人数超过名额：{[tuple(r) for r in i1]}"

    i2 = conn.execute(
        "SELECT activity_id, student_id FROM registrations"
        " GROUP BY activity_id, student_id HAVING COUNT(*) > 1"
    ).fetchall()
    assert i2 == [], f"I2 同一活动 + 学生有多条记录：{[tuple(r) for r in i2]}"

    i3 = conn.execute(
        "SELECT activity_id, wait_seq FROM registrations WHERE status = 'WAITLISTED'"
        " GROUP BY activity_id, wait_seq HAVING COUNT(*) > 1"
    ).fetchall()
    assert i3 == [], f"I3 候补序号重复：{[tuple(r) for r in i3]}"

    i4 = conn.execute(
        "SELECT id FROM registrations WHERE checked_in_at IS NOT NULL AND status <> 'REGISTERED'"
    ).fetchall()
    assert i4 == [], f"I4 非已报名记录有签到时间：{[tuple(r) for r in i4]}"
