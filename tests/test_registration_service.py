"""报名服务层的顺序执行测试（AC-01、AC-02、AC-05、AC-19 的服务层部分）。接口层的完整流程见 test_registration_flow.py。"""
import json

import pytest

from app.errors import AppError
from app.services.registration import register
from helpers import STUDENT_IDS, make_activity

S1, S2, S3 = STUDENT_IDS["S1"], STUDENT_IDS["S2"], STUDENT_IDS["S3"]


def _logs(conn, act):
    return conn.execute(
        "SELECT action, actor_role, target_student_id, detail FROM operation_logs"
        " WHERE activity_id = ? ORDER BY id",
        (act,),
    ).fetchall()


def test_ac01_register_with_seats_left(conn, clock):
    """AC-01 / BR-03：名额未满 → 已报名，并写入 REGISTER 日志（BR-30）。"""
    act = make_activity(conn, clock.now(), capacity=2)
    assert register(conn, act, S1, clock.now()) == {"status": "REGISTERED", "waitlist_position": None}
    logs = _logs(conn, act)
    assert [(l["action"], l["actor_role"], l["target_student_id"]) for l in logs] == [("REGISTER", "student", S1)]


def test_ac02_full_goes_to_waitlist_with_position(conn, clock):
    """AC-02 / BR-03：名额已满 → 候补，位次从 1 开始，写入 WAITLIST 日志。"""
    act = make_activity(conn, clock.now(), capacity=2)
    register(conn, act, S1, clock.now())
    register(conn, act, S2, clock.now())
    assert register(conn, act, S3, clock.now()) == {"status": "WAITLISTED", "waitlist_position": 1}
    last = _logs(conn, act)[-1]
    assert last["action"] == "WAITLIST" and json.loads(last["detail"]) == {"position": 1}


@pytest.mark.parametrize("capacity, code, message", [
    (2, "ALREADY_REGISTERED", "您已报名该活动"),
    (1, "ALREADY_WAITLISTED", "您已在候补队列中（第 1 位）"),
])
def test_ac05_duplicate_registration_rejected(conn, clock, capacity, code, message):
    """AC-05 / BR-01：已报名或候补中再次报名 → 拒绝，记录数和状态不变。"""
    act = make_activity(conn, clock.now(), capacity=capacity)
    if capacity == 1:
        register(conn, act, S2, clock.now())  # 先占满，S1 进入候补
    first = register(conn, act, S1, clock.now())

    with pytest.raises(AppError) as exc:
        register(conn, act, S1, clock.now())
    assert exc.value.code == code and exc.value.message == message
    rows = conn.execute(
        "SELECT status FROM registrations WHERE activity_id = ? AND student_id = ?", (act, S1)
    ).fetchall()
    assert [r["status"] for r in rows] == [first["status"]]


@pytest.mark.parametrize("activity_id_kind", ["missing", "draft"])
def test_ac19_draft_or_missing_activity_not_found(conn, clock, activity_id_kind):
    """AC-19 / §6.9：草稿对学生不可见，报名草稿或不存在的活动 → ACTIVITY_NOT_FOUND，不写任何数据。"""
    act = 9999 if activity_id_kind == "missing" else make_activity(conn, clock.now(), capacity=2, status="DRAFT")
    with pytest.raises(AppError) as exc:
        register(conn, act, S1, clock.now())
    assert exc.value.code == "ACTIVITY_NOT_FOUND"
    assert conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM operation_logs").fetchone()[0] == 0
