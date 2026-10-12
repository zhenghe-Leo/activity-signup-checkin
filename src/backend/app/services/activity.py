"""活动管理（T2.1）：创建与编辑、发布（BR-21）、取消活动并联动报名（BR-10）、签到口令（BR-18）。

发布后修改名额、时间、地点、截止时间走「预览 → 确认」（M5 change_service），这里只拒绝。
BR-22 内容校验在发布、以及发布后编辑简介或注意事项时执行。
"""
import secrets
import sqlite3
from datetime import datetime

from app.clock import to_db
from app.config import TAG_LIBRARY, Settings
from app.db import write_tx
from app.errors import AppError
from app.repo import activities, ai_logs, logs, registrations
from app.services import content_validator, policies
from app.services.query import organizer_activity

# 发布后只能通过「预览 → 确认」修改的字段（BR-11）
CHANGE_FLOW_FIELDS = ("capacity", "location", "start_at", "end_at", "deadline_at")


def create(conn: sqlite3.Connection, organizer_id: int, data: dict, now: datetime, cfg: Settings) -> dict:
    fields = normalize_fields(data)
    ts = to_db(now)
    with write_tx(conn):
        validate_fields(fields, cfg)
        _check_ai_call(conn, fields.get("ai_call_id"))
        activity_id = activities.insert(conn, fields, organizer_id, ts)
        logs.add_operation(conn, now=ts, actor_id=organizer_id, actor_role="organizer",
                           action="CREATE", activity_id=activity_id)
    return organizer_activity(conn, activity_id, now, cfg)


def update(conn: sqlite3.Connection, organizer_id: int, activity_id: int, data: dict,
           now: datetime, cfg: Settings) -> dict:
    """草稿：全部字段可改。已发布：只能直接改标题、简介、标签、注意事项（BR-11）。"""
    changes = normalize_fields(data)
    ts = to_db(now)
    with write_tx(conn):
        act = _get(conn, activity_id)
        if policies.activity_phase(act, now) in (policies.ENDED, policies.CANCELLED):
            raise AppError("ACTIVITY_NOT_EDITABLE")
        if act["status"] == "PUBLISHED":
            changed = [k for k in CHANGE_FLOW_FIELDS if k in changes and changes[k] != act[k]]
            if changed:
                raise AppError("USE_CHANGE_FLOW", details={"fields": changed})
        merged = {**act, **changes}
        validate_fields(merged, cfg)
        if act["status"] == "PUBLISHED":
            _validate_tag_count(merged["tags"], cfg)
            if "summary" in changes or "notes" in changes:
                _validate_content(merged, cfg)
        _check_ai_call(conn, changes.get("ai_call_id"))
        activities.update(conn, activity_id, changes, ts)
        logs.add_operation(conn, now=ts, actor_id=organizer_id, actor_role="organizer",
                           action="UPDATE", activity_id=activity_id, detail={"fields": sorted(changes)})
    return organizer_activity(conn, activity_id, now, cfg)


def publish(conn: sqlite3.Connection, organizer_id: int, activity_id: int, now: datetime, cfg: Settings) -> dict:
    ts = to_db(now)
    with write_tx(conn):
        act = _get(conn, activity_id)
        if act["status"] != "DRAFT":
            raise AppError("ACTIVITY_NOT_EDITABLE")
        validate_fields(act, cfg)
        _validate_tag_count(act["tags"], cfg)
        if act["deadline_at"] <= ts:
            raise _field_error("deadline_at", "报名截止时间已过，无法发布")
        _validate_content(act, cfg)
        activities.set_published(conn, activity_id, ts)
        logs.add_operation(conn, now=ts, actor_id=organizer_id, actor_role="organizer",
                           action="PUBLISH", activity_id=activity_id)
    return organizer_activity(conn, activity_id, now, cfg)


def cancel(conn: sqlite3.Connection, organizer_id: int, activity_id: int, now: datetime, cfg: Settings) -> dict:
    """BR-10：已报名和候补中的记录全部变为已取消（活动取消），通知置为未读；签到开放后不允许（BR-17）。"""
    ts = to_db(now)
    with write_tx(conn):
        act = _get(conn, activity_id)
        if act["status"] != "PUBLISHED":
            raise AppError("ACTIVITY_NOT_EDITABLE")
        if policies.change_locked(act, now, cfg.checkin_open_before_minutes):
            raise AppError("CHANGE_LOCKED")
        affected = registrations.active(conn, activity_id)
        for reg in affected:
            registrations.cancel(conn, reg["id"], "BY_ACTIVITY", ts)
            registrations.notify(conn, reg["id"], f"活动已取消：{act['title']}", ts)
        activities.set_cancelled(conn, activity_id, ts)
        logs.add_operation(conn, now=ts, actor_id=organizer_id, actor_role="organizer",
                           action="CANCEL_ACTIVITY", activity_id=activity_id,
                           detail={"cancelled_students": [r["student_id"] for r in affected]})
    return {"cancelled_registrations": len(affected)}


def reset_checkin_code(conn: sqlite3.Connection, organizer_id: int, activity_id: int,
                       now: datetime) -> dict:
    """BR-18：发布后、结束前生成 6 位数字口令；重新生成后旧口令立即失效。"""
    ts = to_db(now)
    with write_tx(conn):
        act = _get(conn, activity_id)
        if policies.activity_phase(act, now) not in (policies.OPEN, policies.CLOSED, policies.ONGOING):
            raise AppError("ACTIVITY_NOT_EDITABLE")
        code = act["checkin_code"]
        while code == act["checkin_code"]:
            code = f"{secrets.randbelow(10 ** 6):06d}"
        activities.set_checkin_code(conn, activity_id, code, ts)
        logs.add_operation(conn, now=ts, actor_id=organizer_id, actor_role="organizer",
                           action="CODE_RESET", activity_id=activity_id)
    return {"code": code}


# ---------- 校验与工具 ----------

def _get(conn: sqlite3.Connection, activity_id: int) -> dict:
    act = activities.get(conn, activity_id)
    if act is None:
        raise AppError("ACTIVITY_NOT_FOUND")
    return act


def normalize_fields(data: dict) -> dict:
    """去掉未提供的字段；时间转数据库格式；去掉首尾空白、重复标签和空的注意事项。"""
    out = {}
    for key, value in data.items():
        if value is None and key != "ai_call_id":
            continue
        if isinstance(value, datetime):
            value = to_db(value)
        elif key in ("title", "location", "summary"):
            value = value.strip()
        elif key == "tags":
            value = list(dict.fromkeys(t.strip() for t in value if t.strip()))
        elif key == "notes":
            value = [n.strip() for n in value if n.strip()]
        out[key] = value
    return out


def validate_fields(f: dict, cfg: Settings) -> None:
    """BR-21 保存时的字段校验。"""
    if not f["title"]:
        raise _field_error("title", "请填写标题")
    if len(f["title"]) > cfg.title_max_len:
        raise _field_error("title", f"标题不能超过 {cfg.title_max_len} 字")
    if not f["location"]:
        raise _field_error("location", "请填写地点")
    if not 1 <= f["capacity"] <= cfg.capacity_max:
        raise _field_error("capacity", f"名额须为 1–{cfg.capacity_max} 的整数")
    if f["end_at"] <= f["start_at"]:
        raise _field_error("end_at", "结束时间必须晚于开始时间")
    if f["deadline_at"] > f["start_at"]:
        raise _field_error("deadline_at", "报名截止时间不能晚于活动开始时间")
    for tag in f.get("tags", []):
        if tag not in TAG_LIBRARY:
            raise _field_error("tags", f"标签「{tag}」不在标签库中")
    if len(f.get("tags", [])) > cfg.tags_max:
        raise _field_error("tags", f"请选择 {cfg.tags_min}–{cfg.tags_max} 个标签")


def _validate_tag_count(tags: list[str], cfg: Settings) -> None:
    """BR-21 发布时：标签 1–5 个。"""
    if not cfg.tags_min <= len(tags) <= cfg.tags_max:
        raise _field_error("tags", f"请选择 {cfg.tags_min}–{cfg.tags_max} 个标签")


def _validate_content(act: dict, cfg: Settings) -> None:
    """BR-22：任意一项不通过 → 拒绝，details 中逐条列出问题和原因。"""
    issues = content_validator.validate(act["summary"], act["notes"], act, cfg)
    if issues:
        raise AppError("CONTENT_INVALID", "内容校验未通过：" + "；".join(i["message"] for i in issues),
                       details=issues)


def _check_ai_call(conn: sqlite3.Connection, ai_call_id: int | None) -> None:
    if ai_call_id is not None and not ai_logs.exists(conn, ai_call_id):
        raise _field_error("ai_call_id", "AI 生成记录不存在")


def _field_error(field: str, message: str) -> AppError:
    return AppError("FIELD_INVALID", message, details={"field": field})
