"""并发报名测试（AC-07、BR-04、R3；03 §7、DEC-02、02-plan T1.4 / RK1）。

每个线程使用独立连接，与「每个请求一个连接」的运行方式一致；用 Barrier 让所有线程同时开始。
race_window_ms 在「统计已报名人数」之后人为插入等待，放大竞态窗口：
有写锁时结果不受影响；没有写锁时（对照组）必然超卖，证明本测试能发现超卖。
"""
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from app import db
from app.clock import to_db
from app.errors import AppError
from app.repo import registrations as reg_repo
from app.services.registration import register
from helpers import START, S3, add_students, api_create, assert_invariants, make_activity, new_code
from helpers import cancel as http_cancel
from helpers import checkin as http_checkin
from helpers import register as http_register


def run_concurrently(settings, calls):
    """calls: [(fn, args)]。所有调用在 Barrier 后同时开始；返回 [("ok", 结果) | ("err", 异常)]。"""
    barrier = threading.Barrier(len(calls))

    def worker(fn, args):
        conn = db.connect(settings.db_file, settings.db_busy_timeout_ms)
        try:
            barrier.wait()
            return ("ok", fn(conn, *args))
        except Exception as e:  # noqa: BLE001 —— 收集所有异常，由断言判断
            return ("err", e)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(worker, fn, args) for fn, args in calls]
        return [f.result() for f in futures]


@pytest.fixture
def widen_race_window(monkeypatch):
    def apply(ms: int):
        if ms == 0:
            return
        original = reg_repo.count_registered

        def slow_count(conn, activity_id):
            n = original(conn, activity_id)
            time.sleep(ms / 1000)
            return n

        monkeypatch.setattr(reg_repo, "count_registered", slow_count)

    return apply


@pytest.mark.parametrize("race_window_ms", [0, 20])
def test_ac07_20_students_compete_for_5_seats(conn, db_ready, clock, widen_race_window, race_window_ms):
    """AC-07 / BR-04：20 个并发报名抢 5 个名额 → 恰好 5 人已报名、15 人候补，位次 1–15 不重复，无异常。"""
    widen_race_window(race_window_ms)
    act = make_activity(conn, clock.now(), capacity=5)
    students = add_students(conn, 20)

    results = run_concurrently(db_ready, [(register, (act, s, clock.now())) for s in students])

    errors = [r for kind, r in results if kind == "err"]
    assert errors == [], f"并发报名出现异常（含 SYSTEM_BUSY）：{errors!r}"
    statuses = [r["status"] for _, r in results]
    assert statuses.count("REGISTERED") == 5
    assert statuses.count("WAITLISTED") == 15
    positions = sorted(r["waitlist_position"] for _, r in results if r["status"] == "WAITLISTED")
    assert positions == list(range(1, 16))

    rows = conn.execute(
        "SELECT status, wait_seq FROM registrations WHERE activity_id = ?", (act,)
    ).fetchall()
    assert len(rows) == 20
    assert sum(r["status"] == "REGISTERED" for r in rows) == 5
    assert sorted(r["wait_seq"] for r in rows if r["status"] == "WAITLISTED") == list(range(1, 16))
    assert_invariants(conn)


@pytest.mark.parametrize(
    "capacity, expected_status, expected_error",
    [(5, "REGISTERED", "ALREADY_REGISTERED"), (1, "WAITLISTED", "ALREADY_WAITLISTED")],
)
def test_ac07_same_student_two_concurrent_requests_create_one_record(
    conn, db_ready, clock, widen_race_window, capacity, expected_status, expected_error
):
    """AC-07 / BR-01：同一学生同时发出 2 个报名请求 → 只产生 1 条记录，另一个被拒绝。
    capacity=1 时先让别人占满名额，验证候补路径同样去重。"""
    widen_race_window(20)
    act = make_activity(conn, clock.now(), capacity=capacity)
    other, student = add_students(conn, 2)
    if capacity == 1:
        register(conn, act, other, clock.now())

    results = run_concurrently(db_ready, [(register, (act, student, clock.now()))] * 2)

    oks = [r for kind, r in results if kind == "ok"]
    errs = [r for kind, r in results if kind == "err"]
    assert len(oks) == 1 and oks[0]["status"] == expected_status
    assert len(errs) == 1 and isinstance(errs[0], AppError) and errs[0].code == expected_error
    count = conn.execute(
        "SELECT COUNT(*) FROM registrations WHERE activity_id = ? AND student_id = ?", (act, student)
    ).fetchone()[0]
    assert count == 1
    assert_invariants(conn)


def run_http_concurrently(requests):
    """requests: [无参函数]，每个发出一次 HTTP 请求。Barrier 后同时开始，返回响应列表。"""
    barrier = threading.Barrier(len(requests))

    def worker(send):
        barrier.wait()
        return send()

    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        return [f.result() for f in [pool.submit(worker, r) for r in requests]]


def test_ac07_http_20_concurrent_registrations_no_5xx(client, conn, widen_race_window):
    """AC-07（接口层）：20 个报名请求同时发出 → 恰好 5 人已报名、15 人候补，位次 1–15，没有任何 5xx。"""
    widen_race_window(20)
    a = api_create(client, capacity=5)
    students = add_students(conn, 20)

    responses = run_http_concurrently([lambda s=s: http_register(client, a, s) for s in students])

    assert [r.status_code for r in responses] == [201] * 20, [r.text for r in responses if r.status_code != 201]
    bodies = [r.json() for r in responses]
    assert sum(b["status"] == "REGISTERED" for b in bodies) == 5
    assert sorted(b["waitlist_position"] for b in bodies if b["status"] == "WAITLISTED") == list(range(1, 16))
    assert_invariants(conn)


def test_ac11_same_student_concurrent_checkin_recorded_once(client, conn, clock):
    """AC-11 / BR-20：同一学生同时提交 2 次签到 → 只有 1 次成功，另一次为 ALREADY_CHECKED_IN。"""
    a = api_create(client, capacity=5)
    http_register(client, a, S3)
    clock.set(START - timedelta(minutes=10))
    code = new_code(client, a)

    responses = run_http_concurrently([lambda: http_checkin(client, a, S3, code)] * 2)

    assert sorted(r.status_code for r in responses) == [200, 409]
    assert next(r for r in responses if r.status_code == 409).json()["code"] == "ALREADY_CHECKED_IN"
    assert conn.execute(
        "SELECT COUNT(*) FROM operation_logs WHERE activity_id = ? AND action = 'CHECKIN'", (a,)
    ).fetchone()[0] == 1
    assert_invariants(conn)


def test_concurrent_cancel_and_register_mixed(client, conn, widen_race_window):
    """DEC-02：「取消（触发递补）」与「新报名」并发混合 → 名额始终不超，递补次数与取消次数一致，候补序号不重复。"""
    widen_race_window(10)
    a = api_create(client, capacity=5)
    students = add_students(conn, 15)
    for s in students[:10]:                       # 5 人已报名，5 人候补
        http_register(client, a, s)
    cancellers, newcomers = students[:3], students[10:]

    responses = run_http_concurrently(
        [lambda s=s: http_cancel(client, a, s) for s in cancellers]
        + [lambda s=s: http_register(client, a, s) for s in newcomers]
    )

    assert all(r.status_code < 300 for r in responses), [r.text for r in responses]
    assert sum(r.json().get("promoted_count", 0) for r in responses[:3]) == 3
    registered = conn.execute(
        "SELECT COUNT(*) FROM registrations WHERE activity_id = ? AND status = 'REGISTERED'", (a,)
    ).fetchone()[0]
    assert registered == 5
    waitlisted = conn.execute(
        "SELECT COUNT(*) FROM registrations WHERE activity_id = ? AND status = 'WAITLISTED'", (a,)
    ).fetchone()[0]
    assert waitlisted == 5 - 3 + len(newcomers)
    assert_invariants(conn)


def test_change_confirm_concurrent_with_registrations(client, conn, widen_race_window):
    """BR-04 / BR-16：「确认缩减名额」与 5 个新报名同时发出 → 确认要么成功、要么因数据变化被拒绝，
    不会出现 5xx；结束时已报名人数不超过名额，I1–I4 成立。"""
    widen_race_window(10)
    a = api_create(client, capacity=4)
    students = add_students(conn, 9)
    for s in students[:4]:
        http_register(client, a, s)
    token = client.post(f"/api/organizer/activities/{a}/changes/preview", json={"capacity": 2},
                        headers={"X-User-Id": "1"}).json()["preview_token"]

    confirm = lambda: client.post(f"/api/organizer/activities/{a}/changes/confirm",  # noqa: E731
                                  json={"capacity": 2, "preview_token": token}, headers={"X-User-Id": "1"})
    responses = run_http_concurrently([confirm] + [lambda s=s: http_register(client, a, s) for s in students[4:]])

    assert all(r.status_code < 500 for r in responses), [r.text for r in responses]
    assert responses[0].status_code in (200, 409)
    if responses[0].status_code == 409:
        assert responses[0].json()["code"] == "PREVIEW_STALE"
    capacity = conn.execute("SELECT capacity FROM activities WHERE id = ?", (a,)).fetchone()[0]
    registered = conn.execute(
        "SELECT COUNT(*) FROM registrations WHERE activity_id = ? AND status = 'REGISTERED'", (a,)
    ).fetchone()[0]
    assert registered == min(capacity, 4)
    assert_invariants(conn)


def test_control_without_write_lock_oversells(db_ready, clock):
    """对照组（03 §7.3 驱动陷阱、RK1）：沿用 sqlite3 默认的隐式事务，SELECT 不在事务内，
    「先查人数、再写入」在并发下超卖。证明上面的并发测试确实能发现超卖，而不是碰巧串行执行。"""
    setup = db.connect(db_ready.db_file, db_ready.db_busy_timeout_ms)
    act = make_activity(setup, clock.now(), capacity=5)
    students = add_students(setup, 20)
    ts = to_db(clock.now())

    def naive_register(_conn, student_id):
        conn = sqlite3.connect(str(db_ready.db_file), timeout=5)  # 默认 isolation_level=""
        try:
            cap = conn.execute("SELECT capacity FROM activities WHERE id = ?", (act,)).fetchone()[0]
            n = conn.execute(
                "SELECT COUNT(*) FROM registrations WHERE activity_id = ? AND status = 'REGISTERED'",
                (act,),
            ).fetchone()[0]
            time.sleep(0.05)
            if n < cap:
                conn.execute(
                    "INSERT INTO registrations (activity_id, student_id, status, registered_at,"
                    " created_at, updated_at) VALUES (?, ?, 'REGISTERED', ?, ?, ?)",
                    (act, student_id, ts, ts, ts),
                )
                conn.commit()
        finally:
            conn.close()

    run_concurrently(db_ready, [(naive_register, (s,)) for s in students])

    registered = setup.execute(
        "SELECT COUNT(*) FROM registrations WHERE activity_id = ? AND status = 'REGISTERED'", (act,)
    ).fetchone()[0]
    setup.close()
    assert registered > 5, "对照组未出现超卖：并发测试可能没有真正并发执行"
