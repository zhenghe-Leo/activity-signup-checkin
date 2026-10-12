"""发布后变更（T5.1：BR-11~17；03 §6.4）：名额、报名截止时间、时间段与地点按「预览 → 确认」修改。

- 预览只计算、不修改数据，返回影响与 preview_token（活动字段 + 全部报名记录 + 变更参数的指纹）；
- 确认在一个写事务内重新计算指纹，与预览不一致则拒绝（PREVIEW_STALE）；一致则修改字段并按同样的计算结果
  更新报名记录。任一步出错整体回滚（AC-18）。
"""
import hashlib
import json
import sqlite3
from datetime import datetime

from app.clock import from_db, to_api, to_db
from app.config import Settings
from app.db import read_tx, write_tx
from app.errors import AppError
from app.repo import activities, logs, registrations
from app.services import activity as activity_service
from app.services import policies, registration
from app.services.query import organizer_activity

CHANGE_FIELDS = ("capacity", "deadline_at", "start_at", "end_at", "location")
NOTIFY_FIELDS = ("start_at", "end_at", "location")  # 修改这些字段时通知全部报名者（BR-15）


def preview(conn: sqlite3.Connection, activity_id: int, data: dict, now: datetime, cfg: Settings) -> dict:
    with read_tx(conn):
        act, changes, merged = _prepare(conn, activity_id, data, now, cfg)
        impact = _impact(conn, act, merged, changes)
        token = _fingerprint(conn, act, changes)
    return {**_present(act, changes, impact, cfg), "preview_token": token}


def confirm(conn: sqlite3.Connection, organizer_id: int, activity_id: int, data: dict, token: str,
            now: datetime, cfg: Settings) -> dict:
    ts = to_db(now)
    with write_tx(conn):
        act, changes, merged = _prepare(conn, activity_id, data, now, cfg)
        if _fingerprint(conn, act, changes) != token:
            raise AppError("PREVIEW_STALE")
        impact = _impact(conn, act, merged, changes)
        result = _present(act, changes, impact, cfg)

        activities.update(conn, activity_id, changes, ts)
        title = act["title"]
        if any(f in changes for f in NOTIFY_FIELDS):
            for reg in impact["notified"]:
                registrations.notify(conn, reg["id"], f"活动时间或地点已变更：{title}，请查看最新信息", ts)

        # BR-13：退回候补的人排在候补队首，彼此保持原来成为已报名的先后顺序
        demoted = sorted(impact["demoted"], key=lambda r: (r["registered_at"], r["id"]))
        if demoted:
            head = min((r["wait_seq"] for r in impact["waitlist"]), default=1)
            for i, reg in enumerate(demoted):
                registrations.demote(conn, reg["id"], head - len(demoted) + i, ts)
                registrations.notify(conn, reg["id"], f"活动名额调整，您已退回候补：{title}", ts)
                logs.add_operation(conn, now=ts, actor_id=None, actor_role="system", action="DEMOTE",
                                   activity_id=activity_id, target_student_id=reg["student_id"])

        # BR-14：扩大名额后按 FIFO 递补（与预览使用同一套 policies）
        promoted = registration.promote_waitlist(conn, activities.get(conn, activity_id), now)
        if promoted != [r["student_id"] for r in impact["promoted"]]:
            raise RuntimeError("递补结果与预览计算不一致")  # 不应发生；抛出后整个事务回滚

        logs.add_operation(conn, now=ts, actor_id=organizer_id, actor_role="organizer", action="CHANGE_CONFIRM",
                           activity_id=activity_id, detail={
                               "changes": result["changes"],
                               "demoted": [r["student_id"] for r in result["demoted"]],
                               "promoted": [r["student_id"] for r in result["promoted"]],
                           })
    return {**result, "activity": organizer_activity(conn, activity_id, now, cfg)}


# ---------- 计算 ----------

def _prepare(conn, activity_id: int, data: dict, now: datetime, cfg: Settings):
    """检查顺序（03 §5.5）：活动已发布 → 签到窗口尚未开放 → 字段合法。"""
    act = activities.get(conn, activity_id)
    if act is None:
        raise AppError("ACTIVITY_NOT_FOUND")
    if act["status"] != "PUBLISHED":
        raise AppError("ACTIVITY_NOT_EDITABLE")
    if policies.change_locked(act, now, cfg.checkin_open_before_minutes):
        raise AppError("CHANGE_LOCKED")
    normalized = activity_service.normalize_fields({k: v for k, v in data.items() if k in CHANGE_FIELDS})
    changes = {k: v for k, v in normalized.items() if v != act[k]}
    if not changes:
        raise AppError("FIELD_INVALID", "没有需要调整的字段")
    merged = {**act, **changes}
    activity_service.validate_fields(merged, cfg)
    if "start_at" in changes and from_db(changes["start_at"]) <= now:
        raise AppError("FIELD_INVALID", "活动开始时间必须晚于当前时间", details={"field": "start_at"})
    return act, changes, merged


def _impact(conn, act: dict, merged: dict, changes: dict) -> dict:
    regs = registrations.list_for_activity(conn, act["id"])
    registered = [r for r in regs if r["status"] == "REGISTERED"]
    waitlist = sorted((r for r in regs if r["status"] == "WAITLISTED"), key=lambda r: r["wait_seq"])
    capacity = merged["capacity"]

    demoted = policies.pick_demotions(registered, len(registered) - capacity)
    promoted = []
    free = capacity - len(registered)
    queue = list(waitlist)
    while free > 0:
        nxt = policies.pick_next_promotion(queue)
        if nxt is None:
            break
        promoted.append(nxt)
        queue.remove(nxt)
        free -= 1
    demoted_in_order = sorted(demoted, key=lambda r: (r["registered_at"], r["id"]))
    notified = registered + waitlist if any(f in changes for f in NOTIFY_FIELDS) else []
    return {
        "demoted": demoted, "promoted": promoted, "notified": notified, "waitlist": waitlist,
        "waitlist_after": demoted_in_order + queue,
    }


def _present(act: dict, changes: dict, impact: dict, cfg: Settings) -> dict:
    student = lambda r: {"student_id": r["student_id"], "student_name": r["student_name"]}  # noqa: E731
    shown = lambda k, v: to_api(v, cfg.tz) if k.endswith("_at") else v  # noqa: E731
    return {
        "changes": {k: {"from": shown(k, act[k]), "to": shown(k, v)} for k, v in changes.items()},
        "demoted": [student(r) for r in impact["demoted"]],
        "promoted": [student(r) for r in impact["promoted"]],
        "notified": [student(r) for r in impact["notified"]],
        "waitlist_after": [student(r) for r in impact["waitlist_after"]],
    }


def _fingerprint(conn, act: dict, changes: dict) -> str:
    """活动字段 + 全部报名记录 + 变更参数。预览之后任何一项变化，确认都会被拒绝（BR-16）。"""
    regs = [(r["id"], r["status"], r["wait_seq"], r["registered_at"], r["checked_in_at"])
            for r in registrations.list_for_activity(conn, act["id"])]
    fields = {k: act[k] for k in ("title", "summary", "notes", "tags", "status", "updated_at", *CHANGE_FIELDS)}
    payload = json.dumps([fields, sorted(regs), changes], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
