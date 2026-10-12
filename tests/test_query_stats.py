"""浏览、筛选、统计、操作记录（AC-27、AC-28、AC-30；BR-28、BR-30）。"""
from datetime import datetime, timedelta, timezone

from app.seed import reset_database
from helpers import (
    START, S1, S2, S3, S4, O1, api_create, assert_error, cancel, checkin, hdr, new_code, register, stats,
)

BEIJING = timezone(timedelta(hours=8))


def _list(client, **params):
    r = client.get("/api/activities", params=params, headers=hdr(S1))
    assert r.status_code == 200, r.text
    return r.json()


def test_ac27_search_and_filter_on_seed_data(client, db_ready, clock):
    """AC-27：关键词「讲座」+ 标签「学术」+ 仅看有余量 → 每个结果都满足全部条件；清空条件恢复完整列表。"""
    reset_database(db_ready, clock.now())

    result = _list(client, keyword="讲座", tags="学术", has_seats="true")
    assert result, "种子数据中应有符合条件的活动"
    for item in result:
        detail = client.get(f"/api/activities/{item['id']}", headers=hdr(S1)).json()
        assert "讲座" in detail["title"] or "讲座" in detail["summary"]
        assert "学术" in item["tags"] and item["remaining"] > 0
        assert item["phase"] not in ("DRAFT", "CANCELLED")
    titles = {i["title"] for i in result}
    assert "AI 前沿讲座（名额已满）" not in titles

    full = _list(client)
    assert len(full) > len(result)
    assert all(i["phase"] not in ("DRAFT", "CANCELLED") for i in full)
    org = client.get("/api/organizer/activities", headers=hdr(O1)).json()
    assert len(full) == sum(a["status"] == "PUBLISHED" for a in org)

    detail = client.get(f"/api/activities/{full[0]['id']}", headers=hdr(S1)).json()
    assert {"deadline_at", "summary", "notes", "remaining", "my_registration", "location"} <= set(detail)


def test_filter_by_tags_any_of_and_location_free_keyword(client):
    a = api_create(client, title="围棋比赛", tags=["竞赛"])
    b = api_create(client, title="书法展", tags=["展览"])
    api_create(client, title="篮球赛", tags=["文体"])
    assert {i["id"] for i in _list(client, tags="竞赛,展览")} == {a, b}
    assert _list(client, keyword="不存在的关键词") == []
    assert [i["id"] for i in _list(client, keyword="%")] == []  # LIKE 通配符被转义


def test_filter_by_date_range_uses_local_timezone(client):
    """日期范围按配置时区（北京时间）的自然日、对开始时间筛选。北京 10-16 00:30 = UTC 10-15 16:30。"""
    early = datetime(2026, 10, 16, 0, 30, tzinfo=BEIJING)
    a = api_create(client, title="凌晨活动", start=early)
    assert [i["id"] for i in _list(client, date_from="2026-10-16", date_to="2026-10-16")] == [a]
    assert _list(client, date_to="2026-10-15") == []
    assert_error(client.get("/api/activities", params={"date_from": "2026-10-17", "date_to": "2026-10-16"},
                            headers=hdr(S1)), 422, "VALIDATION_ERROR", "开始日期不能晚于结束日期")


def test_has_seats_excludes_full_activities(client):
    a = api_create(client, title="满员", capacity=1)
    b = api_create(client, title="有余量", capacity=2)
    register(client, a, S1)
    register(client, b, S1)
    assert [i["id"] for i in _list(client, has_seats="true")] == [b]


def test_ac28_stats_and_summary_table(client, clock):
    """AC-28 / BR-28：已报名 2、候补 1、已签到 1、已取消 1、签到率 50%、递补人次 1；汇总表中的数字一致。"""
    a = api_create(client, capacity=2)
    for s in (S1, S2, S3, S4):
        register(client, a, s)
    cancel(client, a, S1)
    clock.set(START - timedelta(minutes=10))
    checkin(client, a, S2, new_code(client, a))

    expected = {"registered": 2, "waitlisted": 1, "checked_in": 1, "cancelled": 1,
                "checkin_rate": 0.5, "promoted_count": 1}
    assert stats(client, a) == expected
    rows = client.get("/api/organizer/activities", headers=hdr(O1)).json()
    assert next(r for r in rows if r["id"] == a)["stats"] == expected


def test_br28_reregistered_student_not_counted_as_cancelled(client):
    """BR-28：取消后又再报名的学生不再计入已取消。"""
    a = api_create(client, capacity=2)
    register(client, a, S1)
    cancel(client, a, S1)
    assert stats(client, a)["cancelled"] == 1
    register(client, a, S1)
    assert stats(client, a)["cancelled"] == 0
    assert stats(client, a)["checkin_rate"] == 0.0


def test_ac30_operation_logs_traceable(client):
    """AC-30 / BR-30：按时间顺序能看到报名、进入候补、取消、递补，每条有时间、操作人、涉及的学生和结果。"""
    a = api_create(client, capacity=2)
    for s in (S1, S2, S3, S4):
        register(client, a, s)
    cancel(client, a, S1)

    logs = list(reversed(client.get(f"/api/organizer/activities/{a}/logs", headers=hdr(O1)).json()))
    seq = [(l["action"], l["target_student_id"]) for l in logs
           if l["action"] in ("REGISTER", "WAITLIST", "CANCEL", "PROMOTE")]
    assert seq == [("REGISTER", S1), ("REGISTER", S2), ("WAITLIST", S3), ("WAITLIST", S4),
                   ("CANCEL", S1), ("PROMOTE", S3)]
    for l in logs:
        assert l["occurred_at"].endswith("+08:00") and l["actor_name"]
    promote = next(l for l in logs if l["action"] == "PROMOTE")
    assert (promote["actor_role"], promote["actor_name"], promote["target_student_name"]) == ("system", "系统", "S3 张伟")
    assert promote["detail"] == {"from_position": 1}
    waitlist = next(l for l in logs if l["action"] == "WAITLIST" and l["target_student_id"] == S4)
    assert waitlist["detail"] == {"position": 2}


def test_my_registrations_lists_all_records(client):
    a = api_create(client, title="A", capacity=1)
    b = api_create(client, title="B", capacity=1)
    register(client, a, S1)
    register(client, b, S2)
    register(client, b, S1)
    mine = client.get("/api/me/registrations", headers=hdr(S1)).json()
    by_title = {i["activity"]["title"]: i["registration"] for i in mine}
    assert by_title["A"]["status"] == "REGISTERED"
    assert by_title["B"]["status"] == "WAITLISTED" and by_title["B"]["waitlist_position"] == 1
