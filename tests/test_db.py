"""数据库层测试：初始化与重置（AC-29、NFR-02）、事务（BR-04、03 §7.1）、约束（R1、03 §4.2）、时钟（NFR-04）。"""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.clock import FixedClock, from_db, to_db
from app.errors import AppError
from app.seed import ACCOUNTS, init_database, reset_database
from helpers import STUDENT_IDS, T0, make_activity

S1, S2 = STUDENT_IDS["S1"], STUDENT_IDS["S2"]


def _user_count(settings) -> int:
    conn = db.connect(settings.db_file, settings.db_busy_timeout_ms)
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


# ---------- 初始化与重置（AC-29） ----------

def test_ac29_init_creates_schema_seed_and_wal(settings, clock):
    """AC-29：首次 init 建库、导入账号种子（1 名组织者 + 6 名学生），并开启 WAL。"""
    assert init_database(settings, clock.now()) is True
    conn = db.connect(settings.db_file, settings.db_busy_timeout_ms)
    try:
        roles = [r["role"] for r in conn.execute("SELECT role FROM users ORDER BY id")]
        assert roles.count("organizer") == 1 and roles.count("student") == 6
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_ac29_init_skips_existing_db_and_keeps_data(settings, clock):
    """AC-29 / NFR-02：再次 init 跳过，不清库；重新连接（模拟重启）后数据仍在。"""
    init_database(settings, clock.now())
    conn = db.connect(settings.db_file, settings.db_busy_timeout_ms)
    before = _snapshot(conn)
    act = make_activity(conn, clock.now(), capacity=2)
    conn.close()

    assert init_database(settings, clock.now()) is False

    conn = db.connect(settings.db_file, settings.db_busy_timeout_ms)
    try:
        after = _snapshot(conn)
        assert after["activities"] == before["activities"] + [act]
        assert after["registrations"] == before["registrations"]
    finally:
        conn.close()


def test_ac29_reset_restores_seed(settings, clock):
    """AC-29：reset 清掉全部业务数据，恢复为与新建库完全相同的种子数据。"""
    init_database(settings, clock.now())
    conn = db.connect(settings.db_file, settings.db_busy_timeout_ms)
    seeded = _snapshot(conn)
    make_activity(conn, clock.now(), capacity=2)
    conn.execute("INSERT INTO users (id, name, role) VALUES (500, '临时', 'student')")
    conn.execute("UPDATE registrations SET notify_status = 'READ'")
    conn.close()

    reset_database(settings, clock.now())

    conn = db.connect(settings.db_file, settings.db_busy_timeout_ms)
    try:
        assert _snapshot(conn) == seeded
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == len(ACCOUNTS)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def _snapshot(conn) -> dict:
    return {
        "users": [tuple(r) for r in conn.execute("SELECT * FROM users ORDER BY id")],
        "activities": [r[0] for r in conn.execute("SELECT id FROM activities ORDER BY id")],
        "registrations": [tuple(r) for r in conn.execute("SELECT * FROM registrations ORDER BY id")],
    }


def test_reset_works_on_empty_location(settings, clock):
    """reset 在数据库文件不存在时也能直接建库。"""
    reset_database(settings, clock.now())
    assert _user_count(settings) == len(ACCOUNTS)


# ---------- 事务（03 §7.1、§9.2） ----------

def test_connection_disables_implicit_transactions(conn):
    """03 §7.3：连接必须关闭驱动的隐式事务，并开启外键。"""
    assert conn.isolation_level is None
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_write_tx_rolls_back_on_error(conn):
    """BR-16 / AC-18 的基础：事务中任一步出错，前面的写入全部回滚。"""
    with pytest.raises(RuntimeError):
        with db.write_tx(conn):
            conn.execute("INSERT INTO users (id, name, role) VALUES (600, '甲', 'student')")
            raise RuntimeError("注入故障")
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id = 600").fetchone()[0] == 0
    assert not conn.in_transaction


def test_write_tx_lock_timeout_becomes_system_busy(db_ready):
    """03 §9.2：等写锁超时 → SYSTEM_BUSY（503），而不是未处理的 OperationalError。"""
    holder = db.connect(db_ready.db_file, 5000)
    waiter = db.connect(db_ready.db_file, busy_timeout_ms=100)
    try:
        holder.execute("BEGIN IMMEDIATE")
        with pytest.raises(AppError) as exc:
            with db.write_tx(waiter):
                pass
        assert exc.value.code == "SYSTEM_BUSY" and exc.value.status_code == 503
    finally:
        holder.execute("ROLLBACK")
        holder.close()
        waiter.close()


def test_read_tx_does_not_block_writer(conn, db_ready):
    """03 §7.1：WAL 下读事务不阻塞写事务。"""
    writer = db.connect(db_ready.db_file, busy_timeout_ms=100)
    try:
        with db.read_tx(conn):
            conn.execute("SELECT COUNT(*) FROM users").fetchone()
            with db.write_tx(writer):
                writer.execute("INSERT INTO users (id, name, role) VALUES (601, '乙', 'student')")
    finally:
        writer.close()


# ---------- 约束（03 §4.2，数据库层兜底） ----------

def _insert_reg(conn, act, student, status, *, wait_seq=None, registered_at=None,
                cancel_reason=None, checked_in_at=None):
    ts = to_db(T0)
    conn.execute(
        "INSERT INTO registrations (activity_id, student_id, status, registered_at, wait_seq,"
        " cancel_reason, checked_in_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (act, student, status, registered_at, wait_seq, cancel_reason, checked_in_at, ts, ts),
    )


def test_r1_unique_activity_student(conn, clock):
    """R1 / BR-01 / I2：同一活动 + 学生只能有一条记录。"""
    act = make_activity(conn, clock.now(), capacity=5)
    _insert_reg(conn, act, S1, "REGISTERED", registered_at=to_db(T0))
    with pytest.raises(sqlite3.IntegrityError):
        _insert_reg(conn, act, S1, "WAITLISTED", wait_seq=1)


def test_i3_waitlist_seq_unique_per_activity(conn, clock):
    """I3：同一活动的候补序号不重复（部分唯一索引）。"""
    act = make_activity(conn, clock.now(), capacity=1)
    _insert_reg(conn, act, S1, "WAITLISTED", wait_seq=1)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_reg(conn, act, S2, "WAITLISTED", wait_seq=1)


@pytest.mark.parametrize("kwargs", [
    {"status": "WAITLISTED"},                                       # 候补必须有序号
    {"status": "REGISTERED", "wait_seq": 1, "registered_at": "x"},  # 非候补不能有序号
    {"status": "REGISTERED"},                                       # 已报名必须有 registered_at
    {"status": "CANCELLED"},                                        # 已取消必须有原因
    {"status": "WAITLISTED", "wait_seq": 1, "checked_in_at": "x"},  # I4：只有已报名才能签到
])
def test_registration_check_constraints(conn, clock, kwargs):
    """03 §4.2 registrations 的 CHECK 约束（含 I4）。"""
    act = make_activity(conn, clock.now(), capacity=5)
    kwargs = dict(kwargs)
    status = kwargs.pop("status")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_reg(conn, act, S1, status, **kwargs)


@pytest.mark.parametrize("start, end, deadline", [
    ("2026-10-20T06:00:00Z", "2026-10-20T06:00:00Z", "2026-10-19T00:00:00Z"),  # 结束不晚于开始
    ("2026-10-20T06:00:00Z", "2026-10-20T08:00:00Z", "2026-10-21T00:00:00Z"),  # 截止晚于开始
])
def test_activity_time_order_check(conn, start, end, deadline):
    """BR-21 数据库兜底：T_dl ≤ T_start < T_end。"""
    ts = to_db(T0)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO activities (title, location, start_at, end_at, deadline_at, capacity,"
            " created_by, created_at, updated_at) VALUES ('t', 'l', ?, ?, ?, 1, 1, ?, ?)",
            (start, end, deadline, ts, ts),
        )


# ---------- 时钟与时间格式（NFR-04、03 §4.6） ----------

def test_fixed_clock_is_injectable_and_controllable():
    c = FixedClock(T0)
    assert c.now() == T0
    c.advance(minutes=30)
    assert c.now() == T0 + timedelta(minutes=30)


def test_db_time_format_is_fixed_length_utc():
    beijing = timezone(timedelta(hours=8))
    s = to_db(datetime(2026, 10, 20, 14, 0, tzinfo=beijing))
    assert s == "2026-10-20T06:00:00Z"
    assert from_db(s) == datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        to_db(datetime(2026, 10, 20, 14, 0))  # 不带时区的时间被拒绝
