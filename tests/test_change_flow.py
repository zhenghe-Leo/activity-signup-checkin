"""发布后变更「预览 → 确认」（AC-14~18；BR-11~17）。"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.repo import registrations as reg_repo
from helpers import (
    DEADLINE, END, START, T0, S1, S2, S3, S4, S5, S6, O1, api_create, assert_error, cancel, hdr,
    my_reg, register, roster,
)


def _preview(client, a, **fields):
    return client.post(f"/api/organizer/activities/{a}/changes/preview", json=fields, headers=hdr(O1))


def _confirm(client, a, token, **fields):
    return client.post(f"/api/organizer/activities/{a}/changes/confirm",
                       json={**fields, "preview_token": token}, headers=hdr(O1))


def _names(items):
    return [i["student_id"] for i in items]


def _snapshot(conn, a):
    act = tuple(conn.execute("SELECT * FROM activities WHERE id = ?", (a,)).fetchone())
    regs = [tuple(r) for r in conn.execute("SELECT * FROM registrations WHERE activity_id = ? ORDER BY id", (a,))]
    return act, regs


def _setup(client, capacity, registered, waitlisted=()):
    a = api_create(client, capacity=capacity)
    for s in (*registered, *waitlisted):
        register(client, a, s)
    return a


def test_ac14_shrink_capacity_preview_then_confirm(client, conn):
    """AC-14 / BR-13：名额 4 → 2，预览列出 S4、S3 退回候补，候补顺序 S3、S4、S5，且不修改数据；
    确认后 S1、S2 已报名，S3、S4、S5 依次为候补第 1–3 位，S3、S4 通知未读。"""
    a = _setup(client, 4, (S1, S2, S3, S4), (S5,))
    before = _snapshot(conn, a)

    r = _preview(client, a, capacity=2)
    assert r.status_code == 200, r.text
    p = r.json()
    assert _names(p["demoted"]) == [S4, S3]
    assert _names(p["waitlist_after"]) == [S3, S4, S5]
    assert p["changes"] == {"capacity": {"from": 4, "to": 2}}
    assert _snapshot(conn, a) == before                       # 预览不修改任何数据

    r = _confirm(client, a, p["preview_token"], capacity=2)
    assert r.status_code == 200, r.text
    assert r.json()["activity"]["capacity"] == 2
    rows = roster(client, a)
    assert {s for s, row in rows.items() if row["status"] == "REGISTERED"} == {S1, S2}
    assert [rows[s]["waitlist_position"] for s in (S3, S4, S5)] == [1, 2, 3]
    assert (rows[S3]["notify_status"], rows[S4]["notify_status"], rows[S5]["notify_status"]) == ("UNREAD", "UNREAD", "NONE")
    assert "退回候补" in rows[S3]["notify_message"]

    logs = client.get(f"/api/organizer/activities/{a}/logs", headers=hdr(O1)).json()
    assert [l["action"] for l in logs[:3]] == ["CHANGE_CONFIRM", "DEMOTE", "DEMOTE"]
    assert logs[0]["detail"]["demoted"] == [S4, S3]


def test_ac15_expand_capacity_promotes_fifo(client):
    """AC-15 / BR-14：名额 2 → 4，预览列出 S3、S4 将被递补；确认后 S3、S4 已报名且通知未读，S5 为候补第 1 位。"""
    a = _setup(client, 2, (S1, S2), (S3, S4, S5))
    p = _preview(client, a, capacity=4).json()
    assert _names(p["promoted"]) == [S3, S4] and _names(p["waitlist_after"]) == [S5]

    _confirm(client, a, p["preview_token"], capacity=4)
    rows = roster(client, a)
    assert rows[S3]["status"] == rows[S4]["status"] == "REGISTERED"
    assert rows[S3]["notify_status"] == rows[S4]["notify_status"] == "UNREAD"
    assert rows[S5]["waitlist_position"] == 1


def test_ac16_confirm_rejected_when_data_changed_after_preview(client, conn):
    """AC-16 / BR-16：预览后 S2 取消了报名 → 确认被拒绝「报名数据已变化，请重新预览」，数据保持确认前的状态。"""
    a = _setup(client, 4, (S1, S2, S3, S4))
    p = _preview(client, a, capacity=2).json()
    cancel(client, a, S2)
    before = _snapshot(conn, a)

    assert_error(_confirm(client, a, p["preview_token"], capacity=2), 409, "PREVIEW_STALE", "报名数据已变化，请重新预览")
    assert _snapshot(conn, a) == before

    # 重新预览后可以确认：此时只需退回 S4
    p2 = _preview(client, a, capacity=2).json()
    assert _names(p2["demoted"]) == [S4]
    assert _confirm(client, a, p2["preview_token"], capacity=2).status_code == 200


@pytest.mark.parametrize("how", ["other_params", "title_edited", "new_registration"])
def test_ac16_any_change_after_preview_makes_token_stale(client, how):
    """BR-16：确认参数与预览不同、活动字段被改过、有新报名，都会使预览失效。"""
    a = _setup(client, 4, (S1, S2))
    p = _preview(client, a, capacity=3).json()
    fields = {"capacity": 3}
    if how == "other_params":
        fields = {"capacity": 2}
    elif how == "title_edited":
        client.put(f"/api/organizer/activities/{a}", json={"title": "新标题"}, headers=hdr(O1))
    else:
        register(client, a, S3)
    assert_error(_confirm(client, a, p["preview_token"], **fields), 409, "PREVIEW_STALE")


def test_ac17_location_change_notifies_active_registrations_only(client):
    """AC-17 / BR-15：修改地点 → 预览列出 S1、S3（不含已取消的 S6）；确认后状态不变，通知未读。"""
    a = _setup(client, 1, (S1,), (S3,))
    register(client, a, S6)
    cancel(client, a, S6)

    p = _preview(client, a, location="图书馆报告厅 B").json()
    assert sorted(_names(p["notified"])) == sorted([S1, S3])
    assert p["demoted"] == [] and p["promoted"] == []

    _confirm(client, a, p["preview_token"], location="图书馆报告厅 B")
    rows = roster(client, a)
    assert (rows[S1]["status"], rows[S3]["status"], rows[S6]["status"]) == ("REGISTERED", "WAITLISTED", "CANCELLED")
    assert rows[S1]["notify_status"] == rows[S3]["notify_status"] == "UNREAD"
    assert rows[S6]["notify_status"] == "NONE"
    assert "变更" in rows[S1]["notify_message"]
    assert client.get(f"/api/organizer/activities/{a}", headers=hdr(O1)).json()["location"] == "图书馆报告厅 B"


def test_br15_time_change_notifies_and_deadline_change_does_not(client):
    """BR-15：改时间段通知全部报名者；只改截止时间不改变任何记录的状态，也不通知。"""
    a = _setup(client, 2, (S1,), ())
    new_start, new_end = START + timedelta(days=1), END + timedelta(days=1)
    p = _preview(client, a, start_at=new_start.isoformat(), end_at=new_end.isoformat()).json()
    assert _names(p["notified"]) == [S1]
    assert p["changes"]["start_at"] == {"from": "2026-10-16T10:00:00+08:00", "to": "2026-10-17T10:00:00+08:00"}

    b = _setup(client, 2, (S2,), ())
    p = _preview(client, b, deadline_at=(DEADLINE - timedelta(hours=1)).isoformat()).json()
    assert p["notified"] == []
    _confirm(client, b, p["preview_token"], deadline_at=(DEADLINE - timedelta(hours=1)).isoformat())
    assert my_reg(client, b, S2)["notify_status"] == "NONE"


def test_br15_deadline_moved_into_past_closes_registration(client, clock):
    """BR-15：把截止时间提前到当前时间之前 → 不再接受新报名，已有记录不变。"""
    a = _setup(client, 2, (S1,), ())
    clock.advance(hours=1)
    p = _preview(client, a, deadline_at=T0.isoformat()).json()
    _confirm(client, a, p["preview_token"], deadline_at=T0.isoformat())
    assert_error(register(client, a, S2), 409, "REG_DEADLINE_PASSED")
    assert my_reg(client, a, S1)["status"] == "REGISTERED"


@pytest.mark.parametrize("fields, message", [
    ({"start_at": (T0 - timedelta(hours=1)).isoformat()}, None),
    ({"deadline_at": (START + timedelta(hours=1)).isoformat()}, "报名截止时间不能晚于活动开始时间"),
    ({"capacity": 0}, "名额须为 1–1000 的整数"),
    ({"capacity": 2}, "没有需要调整的字段"),          # 与当前值相同
    ({}, "没有需要调整的字段"),
])
def test_br15_br21_field_rules(client, fields, message):
    a = _setup(client, 2, (), ())
    r = _preview(client, a, **fields)
    assert_error(r, 400, "FIELD_INVALID", message)


def test_br15_new_start_must_be_in_future(client):
    a = _setup(client, 2, (), ())
    end = (T0 + timedelta(hours=1)).isoformat()
    r = _preview(client, a, start_at=(T0 - timedelta(minutes=1)).isoformat(),
                 deadline_at=(T0 - timedelta(hours=1)).isoformat(), end_at=end)
    assert_error(r, 400, "FIELD_INVALID", "活动开始时间必须晚于当前时间")


def test_ac18_locked_after_checkin_window_opens(client, clock):
    """AC-18 场景 1 / BR-17：签到窗口开放后，预览与确认都被拒绝。"""
    a = _setup(client, 4, (S1,), ())
    token = _preview(client, a, capacity=3).json()["preview_token"]
    clock.set(START - timedelta(minutes=30))
    msg = "签到已开放，活动不可再调整或取消"
    assert_error(_preview(client, a, capacity=3), 409, "CHANGE_LOCKED", msg)
    assert_error(_confirm(client, a, token, capacity=3), 409, "CHANGE_LOCKED", msg)


def test_ac18_fault_during_confirm_rolls_back_everything(app, conn, monkeypatch):
    """AC-18 场景 2 / BR-16：确认过程中某一步写入失败 → 活动字段和全部报名记录与调整前完全一致。"""
    with TestClient(app, raise_server_exceptions=False) as client:
        a = _setup(client, 4, (S1, S2, S3, S4), (S5,))
        token = _preview(client, a, capacity=2).json()["preview_token"]
        before = _snapshot(conn, a)

        calls = {"n": 0}
        original = reg_repo.demote

        def failing_demote(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:                  # 第一位已退回候补之后，第二位写入失败
                raise RuntimeError("注入故障")
            return original(*args, **kwargs)

        monkeypatch.setattr(reg_repo, "demote", failing_demote)
        r = _confirm(client, a, token, capacity=2)
        assert r.status_code == 500 and r.json()["code"] == "INTERNAL_ERROR"
        assert calls["n"] == 2
        assert _snapshot(conn, a) == before


def test_change_flow_errors_for_draft_and_cancelled(client):
    """§6.9：草稿直接编辑，不走预览；已取消的活动不能调整。"""
    draft = api_create(client, capacity=2, publish=False)
    assert_error(_preview(client, draft, capacity=3), 409, "ACTIVITY_NOT_EDITABLE")
    a = _setup(client, 2, (), ())
    client.post(f"/api/organizer/activities/{a}/cancel", headers=hdr(O1))
    assert_error(_preview(client, a, capacity=3), 409, "ACTIVITY_NOT_EDITABLE")
    assert_error(_preview(client, 9999, capacity=3), 404, "ACTIVITY_NOT_FOUND")
    assert_error(client.post(f"/api/organizer/activities/{a}/changes/preview", json={"capacity": 3},
                             headers=hdr(S1)), 403, "FORBIDDEN")
