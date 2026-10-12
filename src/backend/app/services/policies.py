"""可替换的规则函数（03 §0 第 5 点）：只做计算，不读写数据库。

面试现场常被要求修改的规则集中在这里：活动阶段、签到窗口、调整截止点、递补人选。
"""
from datetime import datetime, timedelta

from app.clock import from_db

# 活动所处阶段（01-spec §3.2）；草稿和已取消直接取存储状态
DRAFT = "DRAFT"
OPEN = "OPEN"            # 报名中：now < T_dl
CLOSED = "CLOSED"        # 已截止：T_dl ≤ now < T_start
ONGOING = "ONGOING"      # 进行中：T_start ≤ now < T_end
ENDED = "ENDED"          # 已结束：now ≥ T_end
CANCELLED = "CANCELLED"


def activity_phase(act: dict, now: datetime) -> str:
    if act["status"] == "DRAFT":
        return DRAFT
    if act["status"] == "CANCELLED":
        return CANCELLED
    if now < from_db(act["deadline_at"]):
        return OPEN
    if now < from_db(act["start_at"]):
        return CLOSED
    if now < from_db(act["end_at"]):
        return ONGOING
    return ENDED


def has_started(act: dict, now: datetime) -> bool:
    """BR-09：活动开始后冻结报名、取消、递补。"""
    return now >= from_db(act["start_at"])


def checkin_window(act: dict, open_before_minutes: int) -> tuple[datetime, datetime]:
    """签到窗口 [T_start − 提前量, T_end]（01-spec §3.1）。"""
    start = from_db(act["start_at"])
    return start - timedelta(minutes=open_before_minutes), from_db(act["end_at"])


def change_locked(act: dict, now: datetime, open_before_minutes: int) -> bool:
    """BR-17：签到窗口开放后，不允许调整或取消活动。"""
    return now >= checkin_window(act, open_before_minutes)[0]


def pick_next_promotion(waitlist: list[dict]) -> dict | None:
    """BR-06 / D5：按候补序号从小到大（FIFO）递补。waitlist 为该活动全部候补中的记录。"""
    return min(waitlist, key=lambda r: r["wait_seq"], default=None)


def pick_demotions(registered: list[dict], k: int) -> list[dict]:
    """BR-13 / D7：缩减名额时，成为已报名最晚的 k 人退回候补（同一时刻按记录先后）。返回顺序：最晚的在前。"""
    if k <= 0:
        return []
    latest_first = sorted(registered, key=lambda r: (r["registered_at"], r["id"]), reverse=True)
    return latest_first[:k]
