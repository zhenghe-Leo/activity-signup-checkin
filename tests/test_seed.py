"""演示种子数据（01-spec §7.1、AC-29、RK2）：任何时刻 reset 后都满足 6 类活动的要求，且可以直接演示。"""
from datetime import datetime, timedelta, timezone

import pytest

from app.seed import reset_database
from helpers import S2, S4, O1, checkin, hdr, new_code, register

BEIJING = timezone(timedelta(hours=8))


@pytest.mark.parametrize("local_now", [
    datetime(2026, 10, 13, 10, 0, tzinfo=BEIJING),   # 白天
    datetime(2026, 10, 13, 23, 50, tzinfo=BEIJING),  # 临近午夜
    datetime(2026, 10, 14, 0, 10, tzinfo=BEIJING),   # 刚过午夜
    datetime(2026, 10, 18, 21, 0, tzinfo=BEIJING),   # 周日晚上
])
def test_seed_satisfies_spec_7_1_at_any_time(client, db_ready, clock, local_now):
    clock.set(local_now)
    reset_database(db_ready, clock.now())
    acts = client.get("/api/organizer/activities", headers=hdr(O1)).json()
    by_title = {a["title"]: a for a in acts}

    # 1. 报名中、名额 2、无人报名
    a1 = by_title["【演示】职业规划讲座"]
    assert (a1["phase"], a1["capacity"], a1["registered_count"]) == ("OPEN", 2, 0)

    # 2. 处于签到窗口内、已有 3 人报名：生成口令后 S2 能签到
    a2 = by_title["【演示】数据库原理学术报告"]
    assert a2["stats"]["registered"] == 3
    assert checkin(client, a2["id"], S2, new_code(client, a2["id"])).status_code == 200

    # 3. 已截止、未开始、已满且有候补；签到窗口尚未开放（还能演示取消后递补）
    a3 = by_title["【演示】校园摄影展志愿者招募"]
    assert a3["phase"] == "CLOSED" and a3["remaining"] == 0 and a3["stats"]["waitlisted"] >= 1
    assert datetime.fromisoformat(a3["start_at"]) - clock.now() > timedelta(minutes=30)

    # 4. 草稿 1 个；5. 已取消 1 个
    assert sum(a["status"] == "DRAFT" for a in acts) == 1
    assert sum(a["status"] == "CANCELLED" for a in acts) == 1

    # 6. 至少 8 个不同标签和日期的普通活动，且都处于报名中
    regular = [a for a in acts if a["status"] == "PUBLISHED" and not a["title"].startswith("【演示】")]
    assert len(regular) >= 8
    assert all(a["phase"] == "OPEN" for a in regular)
    assert len({t for a in regular for t in a["tags"]}) >= 8
    assert len({a["start_at"][:10] for a in regular}) >= 8


def test_seed_demo_flow_register_then_waitlist(client, db_ready, clock):
    """演示活动 1 能直接演示「名额未满 → 满员进入候补」。"""
    reset_database(db_ready, clock.now())
    acts = client.get("/api/organizer/activities", headers=hdr(O1)).json()
    a1 = next(a for a in acts if a["title"] == "【演示】职业规划讲座")["id"]
    assert register(client, a1, 2).json()["status"] == "REGISTERED"
    assert register(client, a1, 3).json()["status"] == "REGISTERED"
    assert register(client, a1, S4).json() == {"status": "WAITLISTED", "waitlist_position": 1}


def test_seed_cancelled_activity_visible_in_my_registrations(client, db_ready, clock):
    """种子中的已取消活动出现在 S1 的「我的报名」里，带未读通知。"""
    reset_database(db_ready, clock.now())
    mine = client.get("/api/me/registrations", headers=hdr(2)).json()
    cancelled = [i for i in mine if i["activity"]["phase"] == "CANCELLED"]
    assert len(cancelled) == 1
    assert cancelled[0]["registration"]["cancel_reason"] == "BY_ACTIVITY"
    assert cancelled[0]["registration"]["notify_status"] == "UNREAD"
