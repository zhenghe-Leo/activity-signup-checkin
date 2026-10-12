"""报名、候补、取消、递补（AC-01~06、AC-08、AC-09；BR-01~09、BR-29、BR-30），经过 HTTP 接口。"""
from datetime import timedelta

from helpers import (
    DEADLINE, START, S1, S2, S3, S4, S5, O1, api_create, assert_error, cancel, hdr, my_reg,
    register, roster, stats,
)


def test_ac01_register_success(client):
    """AC-01：名额未满 → 已报名；已报名 1、剩余 1；日志新增「报名」。"""
    a = api_create(client, capacity=2)
    r = register(client, a, S1)
    assert r.status_code == 201
    assert r.json() == {"status": "REGISTERED", "waitlist_position": None}
    detail = client.get(f"/api/activities/{a}", headers=hdr(S1)).json()
    assert detail["registered_count"] == 1 and detail["remaining"] == 1
    assert detail["my_registration"]["display_status"] == "REGISTERED"
    logs = client.get(f"/api/organizer/activities/{a}/logs", headers=hdr(O1)).json()
    assert logs[0]["action"] == "REGISTER" and logs[0]["target_student_id"] == S1


def test_ac02_full_goes_to_waitlist(client):
    """AC-02：名额已满 → 候补第 1 位；已报名仍为 2，候补 1。"""
    a = api_create(client, capacity=2)
    register(client, a, S1)
    register(client, a, S2)
    r = register(client, a, S3)
    assert r.status_code == 201
    assert r.json() == {"status": "WAITLISTED", "waitlist_position": 1}
    s = stats(client, a)
    assert s["registered"] == 2 and s["waitlisted"] == 1


def test_ac03_cancel_promotes_and_notification_becomes_read(client):
    """AC-03 / BR-06 / BR-07 / BR-29：已报名者取消 → 候补首位自动递补，通知未读；打开「我的报名」后变为已读。"""
    a = api_create(client, capacity=2)
    for s in (S1, S2, S3, S4):
        register(client, a, s)

    r = cancel(client, a, S1)
    assert r.status_code == 200 and r.json() == {"status": "CANCELLED", "promoted_count": 1}

    assert my_reg(client, a, S1)["status"] == "CANCELLED"
    s3 = my_reg(client, a, S3)
    assert s3["status"] == "REGISTERED" and s3["notify_status"] == "UNREAD"
    assert "递补" in s3["notify_message"]
    s4 = my_reg(client, a, S4)
    assert s4["status"] == "WAITLISTED" and s4["waitlist_position"] == 1
    assert stats(client, a)["registered"] == 2
    assert roster(client, a)[S3]["notify_status"] == "UNREAD"

    logs = client.get(f"/api/organizer/activities/{a}/logs", headers=hdr(O1)).json()
    tail = [(l["action"], l["target_student_id"], l["actor_name"]) for l in reversed(logs)][-2:]
    assert tail == [("CANCEL", S1, "S1 李明"), ("PROMOTE", S3, "系统")]

    # S3 打开「我的报名」：先看到未读的递补提示，页面再调用置为已读
    mine = client.get("/api/me/registrations", headers=hdr(S3)).json()
    item = next(i for i in mine if i["activity"]["id"] == a)
    assert item["registration"]["notify_status"] == "UNREAD" and "递补" in item["registration"]["notify_message"]
    assert client.post("/api/me/notifications/read", headers=hdr(S3)).json() == {"updated": 1}
    assert my_reg(client, a, S3)["notify_status"] == "READ"
    assert roster(client, a)[S3]["notify_status"] == "READ"


def test_ac04_waitlisted_cancel_does_not_promote(client):
    """AC-04 / BR-05：候补者取消 → 后面的人前移一位，已报名不变，不产生递补。"""
    a = api_create(client, capacity=2)
    for s in (S1, S2, S3, S4):
        register(client, a, s)
    r = cancel(client, a, S3)
    assert r.json() == {"status": "CANCELLED", "promoted_count": 0}
    assert my_reg(client, a, S4)["waitlist_position"] == 1
    rows = roster(client, a)
    assert {sid for sid, row in rows.items() if row["status"] == "REGISTERED"} == {S1, S2}
    assert stats(client, a)["promoted_count"] == 0


def test_ac05_duplicate_registration_rejected_over_http(client):
    """AC-05 / BR-01：已报名或候补中再次报名 → 409，记录仍只有 1 条且状态不变。"""
    a = api_create(client, capacity=1)
    register(client, a, S1)
    register(client, a, S2)
    assert_error(register(client, a, S1), 409, "ALREADY_REGISTERED", "您已报名该活动")
    assert_error(register(client, a, S2), 409, "ALREADY_WAITLISTED", "您已在候补队列中（第 1 位）")
    rows = roster(client, a)
    assert len(rows) == 2 and rows[S1]["status"] == "REGISTERED" and rows[S2]["status"] == "WAITLISTED"


def test_ac06_reregister_reuses_record_at_waitlist_tail(client):
    """AC-06 / BR-02：取消后再报名复用原记录；已满时排在候补队尾。"""
    a = api_create(client, capacity=2)
    register(client, a, S1)
    cancel(client, a, S1)
    for s in (S2, S5, S4):
        register(client, a, s)
    r = register(client, a, S1)
    assert r.json() == {"status": "WAITLISTED", "waitlist_position": 2}
    rows = client.get(f"/api/organizer/activities/{a}/registrations", headers=hdr(O1)).json()
    assert [row["student_id"] for row in rows].count(S1) == 1
    mine = my_reg(client, a, S1)
    assert mine["cancel_reason"] is None and mine["status"] == "WAITLISTED"


def test_ac06_reregister_with_seats_left_becomes_registered(client):
    """BR-02：再报名时有余量 → 直接已报名。"""
    a = api_create(client, capacity=2)
    register(client, a, S1)
    cancel(client, a, S1)
    assert register(client, a, S1).json() == {"status": "REGISTERED", "waitlist_position": None}


def test_ac08_after_deadline_reject_new_but_cancel_still_promotes(client, clock):
    """AC-08 / BR-08 / D6：截止后拒绝新报名；取消仍然有效，并继续递补。"""
    a = api_create(client, capacity=2)
    for s in (S1, S2, S3):
        register(client, a, s)
    clock.set(DEADLINE + timedelta(hours=1))

    assert_error(register(client, a, S5), 409, "REG_DEADLINE_PASSED", "报名已截止")
    r = cancel(client, a, S1)
    assert r.status_code == 200 and r.json()["promoted_count"] == 1
    assert my_reg(client, a, S3)["status"] == "REGISTERED"


def test_ac08_reregister_after_deadline_rejected(client, clock):
    """BR-08：截止后再报名（复用记录）同样被拒绝。"""
    a = api_create(client, capacity=2)
    register(client, a, S1)
    cancel(client, a, S1)
    clock.set(DEADLINE)
    assert_error(register(client, a, S1), 409, "REG_DEADLINE_PASSED")


def test_ac09_after_start_frozen_and_waitlist_expired(client, clock):
    """AC-09 / BR-09：活动开始后拒绝取消；候补显示「候补失效」，候补数为 0，不会再递补。"""
    a = api_create(client, capacity=1)
    register(client, a, S2)
    register(client, a, S4)
    clock.set(START + timedelta(minutes=1))

    assert_error(cancel(client, a, S2), 409, "ACTIVITY_STARTED", "活动已开始，无法取消")
    assert_error(register(client, a, S5), 409, "ACTIVITY_STARTED", "活动已开始")
    s4 = my_reg(client, a, S4)
    assert s4["display_status"] == "WAITLIST_EXPIRED" and s4["waitlist_position"] is None
    assert roster(client, a)[S4]["display_status"] == "WAITLIST_EXPIRED"
    assert stats(client, a)["waitlisted"] == 0
    assert client.get(f"/api/activities/{a}", headers=hdr(S4)).json()["waitlist_count"] == 0
    assert_error(cancel(client, a, S4), 409, "ACTIVITY_STARTED")


def test_cancel_without_registration_and_after_checkin(client, clock):
    """BR-05：没有有效记录 → NOT_REGISTERED；已签到 → 不能取消。"""
    a = api_create(client, capacity=2)
    assert_error(cancel(client, a, S1), 409, "NOT_REGISTERED", "您没有可取消的报名")
    register(client, a, S1)
    cancel(client, a, S1)
    assert_error(cancel(client, a, S1), 409, "NOT_REGISTERED")

    register(client, a, S2)
    clock.set(START - timedelta(minutes=10))
    code = client.post(f"/api/organizer/activities/{a}/checkin-code", headers=hdr(O1)).json()["code"]
    client.post(f"/api/activities/{a}/checkin", json={"code": code}, headers=hdr(S2))
    assert_error(cancel(client, a, S2), 409, "CANCEL_AFTER_CHECKIN", "已签到，不能取消报名")


def test_promotion_fills_all_free_seats_in_fifo_order(client):
    """BR-06 / D5：递补按进入候补的先后顺序（FIFO）。"""
    a = api_create(client, capacity=1)
    for s in (S1, S2, S3, S4):
        register(client, a, s)
    cancel(client, a, S1)
    assert my_reg(client, a, S2)["status"] == "REGISTERED"
    assert my_reg(client, a, S3)["waitlist_position"] == 1
    assert my_reg(client, a, S4)["waitlist_position"] == 2
