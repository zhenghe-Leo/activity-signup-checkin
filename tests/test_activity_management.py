"""活动管理（AC-13、AC-19、AC-31；BR-10、BR-11、BR-18、BR-21、BR-23、BR-30）。"""
from datetime import timedelta

import pytest

from helpers import (
    DEADLINE, START, T0, S1, S2, S3, O1, api_create, assert_error, checkin, hdr, my_reg,
    new_code, register,
)


def _create(client, **overrides):
    body = {
        "title": "活动 B", "location": "图书馆报告厅", "capacity": 10, "tags": ["讲座"],
        "start_at": START.isoformat(), "end_at": (START + timedelta(hours=2)).isoformat(),
        "deadline_at": DEADLINE.isoformat(), **overrides,
    }
    return client.post("/api/organizer/activities", json=body, headers=hdr(O1))


def _publish(client, activity_id):
    return client.post(f"/api/organizer/activities/{activity_id}/publish", headers=hdr(O1))


def _put(client, activity_id, **fields):
    return client.put(f"/api/organizer/activities/{activity_id}", json=fields, headers=hdr(O1))


# ---------- AC-13 取消活动 ----------

def test_ac13_cancel_activity_cascades(client, clock):
    """AC-13 / BR-10：取消活动 → 已报名和候补都变为已取消（活动取消）、通知未读；之后报名、签到被拒绝；
    学生列表中不再出现，但仍在「我的报名」里。"""
    a = api_create(client, capacity=1)
    register(client, a, S1)
    register(client, a, S3)
    code = new_code(client, a)

    r = client.post(f"/api/organizer/activities/{a}/cancel", headers=hdr(O1))
    assert r.status_code == 200 and r.json() == {"cancelled_registrations": 2}
    assert client.get(f"/api/organizer/activities/{a}", headers=hdr(O1)).json()["status"] == "CANCELLED"
    for s in (S1, S3):
        mine = my_reg(client, a, s)
        assert (mine["status"], mine["cancel_reason"], mine["notify_status"]) == ("CANCELLED", "BY_ACTIVITY", "UNREAD")

    assert_error(register(client, a, S2), 409, "ACTIVITY_CANCELLED", "活动已取消")
    clock.set(START - timedelta(minutes=10))
    assert_error(checkin(client, a, S1, code), 409, "ACTIVITY_CANCELLED", "活动已取消")

    listed = [x["id"] for x in client.get("/api/activities", headers=hdr(S1)).json()]
    assert a not in listed
    mine = client.get("/api/me/registrations", headers=hdr(S1)).json()
    assert [i["activity"]["phase"] for i in mine if i["activity"]["id"] == a] == ["CANCELLED"]


def test_ac18_cancel_activity_locked_after_checkin_opens(client, clock):
    """AC-18 场景 1（取消部分）/ BR-17：签到窗口开放后不能取消活动。"""
    a = api_create(client, capacity=1)
    clock.set(START - timedelta(minutes=30))
    assert_error(client.post(f"/api/organizer/activities/{a}/cancel", headers=hdr(O1)),
                 409, "CHANGE_LOCKED", "签到已开放，活动不可再调整或取消")


# ---------- AC-19 字段校验与草稿可见性 ----------

@pytest.mark.parametrize("overrides, field, message", [
    ({"deadline_at": (START + timedelta(hours=1)).isoformat()}, "deadline_at", "报名截止时间不能晚于活动开始时间"),
    ({"end_at": START.isoformat()}, "end_at", "结束时间必须晚于开始时间"),
    ({"capacity": 0}, "capacity", "名额须为 1–1000 的整数"),
    ({"capacity": 1001}, "capacity", "名额须为 1–1000 的整数"),
    ({"title": "长" * 51}, "title", "标题不能超过 50 字"),
    ({"title": "   "}, "title", "请填写标题"),
    ({"tags": ["讲座", "竞赛", "文体", "学术", "就业", "社团"]}, "tags", "请选择 1–5 个标签"),
    ({"tags": ["不存在的标签"]}, "tags", "标签「不存在的标签」不在标签库中"),
])
def test_ac19_save_validation(client, overrides, field, message):
    """AC-19 / BR-21 / BR-23：保存时的字段校验，逐项给出中文提示。"""
    r = _create(client, **overrides)
    assert_error(r, 400, "FIELD_INVALID", message)
    assert r.json()["details"] == {"field": field}


def test_ac19_publish_rejects_past_deadline(client, clock):
    """AC-19：截止时间已过 → 不能发布。"""
    a = _create(client, deadline_at=(T0 + timedelta(hours=1)).isoformat()).json()["id"]
    clock.set(T0 + timedelta(hours=1))
    assert_error(_publish(client, a), 400, "FIELD_INVALID", "报名截止时间已过，无法发布")


def test_ac19_publish_requires_tags(client):
    """AC-19：标签为空 → 可以保存草稿，但不能发布。"""
    a = _create(client, tags=[]).json()["id"]
    assert_error(_publish(client, a), 400, "FIELD_INVALID", "请选择 1–5 个标签")


def test_ac19_draft_invisible_to_students(client):
    """AC-19：草稿不出现在学生列表和搜索中，直接访问详情或报名返回「活动不存在」。"""
    b = api_create(client, title="草稿活动 B", publish=False)
    assert b not in [x["id"] for x in client.get("/api/activities", headers=hdr(S1)).json()]
    assert client.get("/api/activities", params={"keyword": "草稿活动"}, headers=hdr(S1)).json() == []
    assert_error(client.get(f"/api/activities/{b}", headers=hdr(S1)), 404, "ACTIVITY_NOT_FOUND", "活动不存在")
    assert_error(register(client, b, S1), 404, "ACTIVITY_NOT_FOUND")


# ---------- 编辑与发布（BR-11） ----------

def test_draft_all_fields_editable_and_publish(client):
    a = _create(client).json()["id"]
    r = _put(client, a, capacity=20, location="信息楼 101", summary="  简介  ", tags=["学术", "学术"])
    assert r.status_code == 200
    body = r.json()
    assert (body["capacity"], body["location"], body["summary"], body["tags"]) == (20, "信息楼 101", "简介", ["学术"])
    r = _publish(client, a)
    assert r.status_code == 200 and r.json()["status"] == "PUBLISHED" and r.json()["published_at"]
    assert_error(_publish(client, a), 409, "ACTIVITY_NOT_EDITABLE")


def test_published_display_fields_editable_but_capacity_needs_change_flow(client):
    """BR-11：已发布活动可直接改标题、简介、标签、注意事项；名额等需走「预览 → 确认」。"""
    a = api_create(client, capacity=2)
    r = _put(client, a, title="新标题", summary="新简介", tags=["学术"], notes=["带学生证"])
    assert r.status_code == 200 and r.json()["title"] == "新标题" and r.json()["notes"] == ["带学生证"]

    r = _put(client, a, capacity=3)
    assert_error(r, 409, "USE_CHANGE_FLOW")
    assert r.json()["details"] == {"fields": ["capacity"]}
    # 前端提交完整表单时，未改动的名额不算修改
    assert _put(client, a, capacity=2, title="再改标题").status_code == 200
    # 已发布活动的标签仍须 1–5 个
    assert_error(_put(client, a, tags=[]), 400, "FIELD_INVALID", "请选择 1–5 个标签")


def test_edit_and_code_reset_rejected_after_end(client, clock):
    """§6.9：已结束的活动不能编辑、不能生成口令。"""
    a = api_create(client, capacity=2)
    clock.set(START + timedelta(hours=3))
    assert_error(_put(client, a, title="x"), 409, "ACTIVITY_NOT_EDITABLE")
    assert_error(client.post(f"/api/organizer/activities/{a}/checkin-code", headers=hdr(O1)),
                 409, "ACTIVITY_NOT_EDITABLE")


def test_code_reset_changes_code(client):
    """BR-18：重新生成后得到不同的新口令。"""
    a = api_create(client, capacity=2)
    first = new_code(client, a)
    second = new_code(client, a)
    assert first != second
    assert client.get(f"/api/organizer/activities/{a}", headers=hdr(O1)).json()["checkin_code"] == second


def test_br30_management_actions_logged(client):
    """BR-30：创建、发布、生成口令、取消活动都写入操作日志（操作人为组织者）。"""
    a = api_create(client, capacity=2)
    new_code(client, a)
    client.post(f"/api/organizer/activities/{a}/cancel", headers=hdr(O1))
    logs = client.get(f"/api/organizer/activities/{a}/logs", headers=hdr(O1)).json()
    assert [l["action"] for l in reversed(logs)] == ["CREATE", "PUBLISH", "CODE_RESET", "CANCEL_ACTIVITY"]
    assert {l["actor_role"] for l in logs} == {"organizer"}


def test_unknown_activity_returns_404(client):
    assert_error(client.get("/api/organizer/activities/9999", headers=hdr(O1)), 404, "ACTIVITY_NOT_FOUND")
    assert_error(_publish(client, 9999), 404, "ACTIVITY_NOT_FOUND")


def test_unknown_ai_call_id_rejected(client):
    assert_error(_create(client, ai_call_id=12345), 400, "FIELD_INVALID", "AI 生成记录不存在")


# ---------- AC-31 请求结构与角色 ----------

def test_ac31_missing_field_or_wrong_type_is_422(client):
    body = {"title": "x", "location": "y", "capacity": "很多",
            "start_at": START.isoformat(), "end_at": START.isoformat()}
    r = client.post("/api/organizer/activities", json=body, headers=hdr(O1))
    assert_error(r, 422, "VALIDATION_ERROR")
    fields = {d["field"] for d in r.json()["details"]}
    assert {"body.capacity", "body.deadline_at"} <= fields


def test_ac31_naive_datetime_and_unknown_field_rejected(client):
    assert_error(_create(client, start_at="2026-10-16T10:00:00"), 422, "VALIDATION_ERROR")
    assert_error(_create(client, status="PUBLISHED"), 422, "VALIDATION_ERROR")


def test_ac31_roles_enforced_on_business_endpoints(client):
    """AC-31：学生调用组织者接口 → 403；组织者调用学生接口 → 403。"""
    a = api_create(client, capacity=2)
    assert_error(client.get("/api/organizer/activities", headers=hdr(S1)), 403, "FORBIDDEN", "无权限")
    assert_error(client.post(f"/api/organizer/activities/{a}/cancel", headers=hdr(S1)), 403, "FORBIDDEN")
    assert_error(register(client, a, O1), 403, "FORBIDDEN")
    assert_error(client.get("/api/activities"), 401, "UNAUTHENTICATED")
