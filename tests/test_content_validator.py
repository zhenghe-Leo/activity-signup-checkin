"""BR-22 内容校验（AC-22）：发布时、发布后编辑简介或注意事项时执行；人工撰写与 AI 生成规则相同。

AC-22 的活动：名额 100，北京时间 2026-10-20 14:00–16:00。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.clock import to_db
from app.services.content_validator import validate
from helpers import O1, api_create, assert_error, hdr

BEIJING = timezone(timedelta(hours=8))
START = datetime(2026, 10, 20, 14, 0, tzinfo=BEIJING)
END = datetime(2026, 10, 20, 16, 0, tzinfo=BEIJING)
ACT = {"start_at": to_db(START), "end_at": to_db(END), "capacity": 100}


def _draft(client, summary="", notes=()):
    return api_create(client, capacity=100, start=START, end=END, publish=False,
                      summary=summary, notes=list(notes))


def _publish(client, a):
    return client.post(f"/api/organizer/activities/{a}/publish", headers=hdr(O1))


@pytest.mark.parametrize("text, message", [
    ("限 50 人", "人数 50 与名额 100 不一致"),
    ("10 月 21 日下午", "日期 10 月 21 日与活动日期 10 月 20 日不一致"),
    ("15:30 开始", "时刻 15:30 与活动开始/结束时刻不一致"),
    ("简" * 501, "简介超出 500 字"),
    ("现场有赌博游戏", "包含敏感词「赌博」"),
])
def test_ac22_publish_rejects_conflicting_content(client, text, message):
    """AC-22：简介与字段矛盾、超长或含敏感词 → 拒绝发布，逐条指出问题。"""
    a = _draft(client, summary=text)
    r = _publish(client, a)
    assert_error(r, 400, "CONTENT_INVALID")
    assert message in [i["message"] for i in r.json()["details"]]
    assert message in r.json()["message"]
    assert client.get(f"/api/organizer/activities/{a}", headers=hdr(O1)).json()["status"] == "DRAFT"


def test_ac22_consistent_content_can_publish(client):
    """AC-22：「限 100 人，14:00 开始」与字段一致 → 允许发布。"""
    a = _draft(client, summary="限 100 人，14:00 开始，16:00 结束", notes=["10 月 20 日下午 2 点准时开始"])
    assert _publish(client, a).status_code == 200


def test_ac22_notes_are_checked_too(client):
    a = _draft(client, summary="欢迎参加", notes=["请提前到场", "限 50 人"])
    r = _publish(client, a)
    assert_error(r, 400, "CONTENT_INVALID")
    assert [(i["field"], i["rule"]) for i in r.json()["details"]] == [("notes[2]", "COUNT_MISMATCH")]


def test_ac22_published_edit_of_summary_is_validated(client):
    """BR-22：发布后编辑简介或注意事项时也执行；只改标题不触发内容校验。"""
    a = _draft(client, summary="欢迎参加")
    _publish(client, a)
    url = f"/api/organizer/activities/{a}"
    assert_error(client.put(url, json={"summary": "15:30 开始"}, headers=hdr(O1)), 400, "CONTENT_INVALID")
    assert_error(client.put(url, json={"notes": ["限 30 名"]}, headers=hdr(O1)), 400, "CONTENT_INVALID")
    assert client.put(url, json={"title": "新标题"}, headers=hdr(O1)).status_code == 200
    assert client.get(url, headers=hdr(O1)).json()["summary"] == "欢迎参加"


def test_draft_save_is_not_blocked_by_content_check(client):
    """内容校验在发布时执行；草稿保存不拦截，方便组织者先保存再修改。"""
    assert _draft(client, summary="限 50 人") > 0


# ---------- 校验器单元测试 ----------

def _rules(summary, notes=(), cfg=None, settings=None):
    return [(i["rule"], i["text"]) for i in validate(summary, list(notes), ACT, cfg or settings)]


@pytest.mark.parametrize("text, expected", [
    ("下午2点开始，4点结束", []),                       # 14:00、16:00 与字段一致
    ("下午3点半签到", [("TIME_MISMATCH", "下午3点半")]),
    ("14：00 开始", []),                                # 全角冒号
    ("2026-10-21 举办", [("DATE_MISMATCH", "2026-10-21")]),
    ("2026年10月20日举办", []),
    ("2025年10月20日举办", [("DATE_MISMATCH", "2025年10月20日")]),
    ("共 100 名同学", []),
    ("3 人一组", [("COUNT_MISMATCH", "3 人")]),            # 保守策略：可能误报
    ("欢迎大三大四同学参加", []),
])
def test_br22_fact_extraction(settings, text, expected):
    assert _rules(text, settings=settings) == expected


def test_br22_notes_count_and_length(settings):
    issues = validate("", ["条目"] * 6 + ["长" * 101], ACT, settings)
    assert ("notes", "TOO_MANY") in [(i["field"], i["rule"]) for i in issues]
    assert ("notes[7]", "TOO_LONG") in [(i["field"], i["rule"]) for i in issues]
