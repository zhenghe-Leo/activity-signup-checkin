"""01-spec §6.9 状态—操作矩阵（R2）：每一格至少一条测试。

活动名额 1：T0 时 S1 已报名、S3 候补、已生成口令；然后把时钟拨到各阶段，执行一次操作。
阶段：DRAFT 草稿 / OPEN 报名中 / CLOSED 已截止（签到未开放）/ WINDOW 已截止且签到已开放 /
      ONGOING 进行中 / ENDED 已结束 / CANCELLED 已取消。
期望值 None 表示操作成功，否则为错误码。
"""
from datetime import timedelta

import pytest

from helpers import (
    DEADLINE, END, START, T0, S1, S2, S3, O1, api_create, checkin, hdr, my_reg, new_code, register,
)

PHASE_TIME = {
    "DRAFT": T0, "OPEN": T0, "CANCELLED": T0,
    "CLOSED": DEADLINE + timedelta(hours=1),
    "WINDOW": START - timedelta(minutes=10),
    "ONGOING": START + timedelta(minutes=30),
    "ENDED": END + timedelta(hours=1),
}
# 与下方 MATRIX 的列顺序一致（不能用 list(PHASE_TIME)：字典顺序与列顺序不同）
PHASES = ["DRAFT", "OPEN", "CLOSED", "WINDOW", "ONGOING", "ENDED", "CANCELLED"]
assert set(PHASES) == set(PHASE_TIME)


@pytest.fixture
def scenario(client, clock):
    def build(phase: str):
        a = api_create(client, capacity=1, publish=phase != "DRAFT")
        code = None
        if phase != "DRAFT":
            register(client, a, S1)
            register(client, a, S3)
            code = new_code(client, a)
        if phase == "CANCELLED":
            client.post(f"/api/organizer/activities/{a}/cancel", headers=hdr(O1))
        clock.set(PHASE_TIME[phase])
        return a, code
    return build


def _code(resp):
    return None if resp.status_code < 300 else resp.json()["code"]


MATRIX = {
    # 操作：           DRAFT                    OPEN    CLOSED                 WINDOW                 ONGOING                ENDED                    CANCELLED
    "register":        ["ACTIVITY_NOT_FOUND",   None,   "REG_DEADLINE_PASSED", "REG_DEADLINE_PASSED", "ACTIVITY_STARTED",    "ACTIVITY_STARTED",      "ACTIVITY_CANCELLED"],
    "student_cancel":  ["ACTIVITY_NOT_FOUND",   None,   None,                  None,                  "ACTIVITY_STARTED",    "ACTIVITY_STARTED",      "ACTIVITY_CANCELLED"],
    "checkin":         ["ACTIVITY_NOT_FOUND",   "CHECKIN_NOT_OPEN", "CHECKIN_NOT_OPEN", None,          None,                  "CHECKIN_CLOSED",        "ACTIVITY_CANCELLED"],
    "code_reset":      ["ACTIVITY_NOT_EDITABLE", None,  None,                  None,                  None,                  "ACTIVITY_NOT_EDITABLE", "ACTIVITY_NOT_EDITABLE"],
    "edit_display":    [None,                   None,   None,                  None,                  None,                  "ACTIVITY_NOT_EDITABLE", "ACTIVITY_NOT_EDITABLE"],
    "edit_capacity":   [None,                   "USE_CHANGE_FLOW", "USE_CHANGE_FLOW", "USE_CHANGE_FLOW", "USE_CHANGE_FLOW", "ACTIVITY_NOT_EDITABLE", "ACTIVITY_NOT_EDITABLE"],
    "cancel_activity": ["ACTIVITY_NOT_EDITABLE", None,  None,                  "CHANGE_LOCKED",       "CHANGE_LOCKED",       "CHANGE_LOCKED",         "ACTIVITY_NOT_EDITABLE"],
    "publish":         [None,                   "ACTIVITY_NOT_EDITABLE", "ACTIVITY_NOT_EDITABLE", "ACTIVITY_NOT_EDITABLE", "ACTIVITY_NOT_EDITABLE", "ACTIVITY_NOT_EDITABLE", "ACTIVITY_NOT_EDITABLE"],
    # 调整名额等：草稿直接编辑（edit_capacity 行）；已发布走「预览 → 确认」，签到窗口开放后锁定（M5）
    "change_preview":  ["ACTIVITY_NOT_EDITABLE", None,  None,                  "CHANGE_LOCKED",       "CHANGE_LOCKED",       "CHANGE_LOCKED",         "ACTIVITY_NOT_EDITABLE"],
}
CASES = [(op, phase, expected[i]) for op, expected in MATRIX.items() for i, phase in enumerate(PHASES)]


@pytest.mark.parametrize("op, phase, expected", CASES, ids=[f"{op}-{phase}" for op, phase, _ in CASES])
def test_state_operation_matrix(client, scenario, op, phase, expected):
    a, code = scenario(phase)
    org = f"/api/organizer/activities/{a}"
    if op == "register":
        resp = register(client, a, S2)
    elif op == "student_cancel":
        resp = client.delete(f"/api/activities/{a}/registration", headers=hdr(S1))
    elif op == "checkin":
        resp = checkin(client, a, S1, code or "000000")
    elif op == "code_reset":
        resp = client.post(f"{org}/checkin-code", headers=hdr(O1))
    elif op == "edit_display":
        resp = client.put(org, json={"title": "改后的标题"}, headers=hdr(O1))
    elif op == "edit_capacity":
        resp = client.put(org, json={"capacity": 5}, headers=hdr(O1))
    elif op == "change_preview":
        resp = client.post(f"{org}/changes/preview", json={"capacity": 5}, headers=hdr(O1))
    elif op == "cancel_activity":
        resp = client.post(f"{org}/cancel", headers=hdr(O1))
    else:
        resp = client.post(f"{org}/publish", headers=hdr(O1))
    assert _code(resp) == expected, resp.text
    assert resp.status_code < 500


@pytest.mark.parametrize("phase, visible", [
    ("DRAFT", False), ("OPEN", True), ("CLOSED", True), ("WINDOW", True),
    ("ONGOING", True), ("ENDED", True), ("CANCELLED", False),
])
def test_matrix_student_list_visibility(client, scenario, phase, visible):
    """§6.9 第 1 行：学生列表可见性。"""
    a, _ = scenario(phase)
    assert (a in [i["id"] for i in client.get("/api/activities", headers=hdr(S2)).json()]) is visible


@pytest.mark.parametrize("phase, promoted", [
    ("OPEN", True), ("CLOSED", True), ("WINDOW", True), ("ONGOING", False), ("ENDED", False),
])
def test_matrix_auto_promotion(client, scenario, phase, promoted):
    """§6.9「自动递补」行：开始前已报名者取消 → S3 递补；开始后取消被拒绝，S3 显示候补失效。"""
    a, _ = scenario(phase)
    client.delete(f"/api/activities/{a}/registration", headers=hdr(S1))
    s3 = my_reg(client, a, S3)
    if promoted:
        assert s3["status"] == "REGISTERED"
    else:
        assert s3["display_status"] == "WAITLIST_EXPIRED"
