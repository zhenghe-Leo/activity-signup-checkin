"""签到（AC-10、AC-11、AC-12；BR-18~20）。时间：T0 = 北京时间 10-13 10:00，活动 10-16 10:00–12:00。"""
from datetime import timedelta

import pytest

from helpers import (
    END, START, S2, S3, S4, S6, O1, api_create, assert_error, checkin, hdr, new_code, register,
    roster, stats,
)

IN_WINDOW = START - timedelta(minutes=10)  # 北京时间 09:50


def test_ac10_checkin_success(client, clock):
    """AC-10：签到窗口内、已报名、口令正确 → 成功，返回签到时间；已签到数 +1，名单显示已签到。"""
    a = api_create(client, capacity=2)
    register(client, a, S2)
    clock.set(IN_WINDOW)
    code = new_code(client, a)
    assert len(code) == 6 and code.isdigit()

    r = checkin(client, a, S2, code)
    assert r.status_code == 200
    assert r.json() == {"checked_in_at": "2026-10-16T09:50:00+08:00"}
    assert stats(client, a)["checked_in"] == 1
    assert roster(client, a)[S2]["display_status"] == "CHECKED_IN"


def test_ac11_repeat_checkin_rejected_with_first_time(client, clock):
    """AC-11 / BR-20：重复签到 → 拒绝，提示首次签到时间；已签到数不变。"""
    a = api_create(client, capacity=2)
    register(client, a, S2)
    clock.set(IN_WINDOW)
    code = new_code(client, a)
    checkin(client, a, S2, code)
    clock.advance(minutes=5)

    r = checkin(client, a, S2, code)
    assert_error(r, 409, "ALREADY_CHECKED_IN", "您已于 09:50 签到，请勿重复签到")
    assert r.json()["details"]["checked_in_at"] == "2026-10-16T09:50:00+08:00"
    assert stats(client, a)["checked_in"] == 1


@pytest.fixture
def ac12(client, clock):
    """A 名额 2：S2、S3 已报名，S4 候补，S6 未报名；T0 时已生成口令。"""
    a = api_create(client, capacity=2)
    for s in (S2, S3, S4):
        register(client, a, s)
    return a, new_code(client, a)


@pytest.mark.parametrize("case, code_kind, status, err, message", [
    ("wrong_code", "wrong", 400, "CHECKIN_CODE_INVALID", "签到口令错误"),
    ("old_code", "old", 400, "CHECKIN_CODE_INVALID", "签到口令错误"),
    ("waitlisted", "right", 409, "CHECKIN_WAITLISTED", "您在候补中，未获得名额，无法签到"),
    ("not_registered", "right", 409, "CHECKIN_NOT_REGISTERED", "您未报名该活动"),
    ("before_window", "right", 409, "CHECKIN_NOT_OPEN", "签到尚未开始"),
    ("after_end", "right", 409, "CHECKIN_CLOSED", "签到已结束"),
    ("activity_cancelled", "right", 409, "ACTIVITY_CANCELLED", "活动已取消"),
])
def test_ac12_checkin_eligibility_and_code(client, clock, ac12, case, code_kind, status, err, message):
    """AC-12 / BR-19：不满足签到条件时，按具体原因给出不同提示。"""
    a, code = ac12
    student, when, old = S2, IN_WINDOW, None
    if case == "old_code":
        old, code = code, new_code(client, a)   # 重新生成后旧口令立即失效（BR-18）
    if case == "waitlisted":
        student = S4
    if case == "not_registered":
        student = S6
    if case == "before_window":
        when = START - timedelta(minutes=30, seconds=1)
    if case == "after_end":
        when = END + timedelta(seconds=1)
    if case == "activity_cancelled":
        assert client.post(f"/api/organizer/activities/{a}/cancel", headers=hdr(O1)).status_code == 200

    clock.set(when)
    submitted = {"wrong": "000000" if code != "000000" else "111111", "old": old, "right": code}
    assert_error(checkin(client, a, student, submitted[code_kind]), status, err, message)
    assert stats(client, a)["checked_in"] == 0


def test_checkin_window_boundaries_inclusive(client, clock):
    """签到窗口 [T_start − 30 分钟, T_end] 两端都可签到。"""
    a = api_create(client, capacity=2)
    register(client, a, S2)
    register(client, a, S3)
    code = new_code(client, a)
    clock.set(START - timedelta(minutes=30))
    assert checkin(client, a, S2, code).status_code == 200
    clock.set(END)
    assert checkin(client, a, S3, code).status_code == 200


def test_checkin_rejects_non_ascii_code_without_server_error(client, clock):
    """输入中文等非 ASCII 口令 → 口令错误（400），而不是 500。"""
    a = api_create(client, capacity=2)
    register(client, a, S2)
    new_code(client, a)
    clock.set(IN_WINDOW)
    assert_error(checkin(client, a, S2, "签到口令"), 400, "CHECKIN_CODE_INVALID")


def test_checkin_before_any_code_generated(client, clock):
    """组织者还没生成口令时，任何口令都错误。"""
    a = api_create(client, capacity=2)
    register(client, a, S2)
    clock.set(IN_WINDOW)
    assert_error(checkin(client, a, S2, "123456"), 400, "CHECKIN_CODE_INVALID")
