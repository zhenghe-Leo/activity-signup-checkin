"""BR-22 内容校验：事实一致、长度、敏感词。AI 生成与人工撰写的内容规则相同。

事实一致是保守策略：简介和注意事项中出现的日期必须等于活动日期，时刻必须是开始或结束时刻之一，
人数必须等于名额。可能误报，组织者可以改写表述。地点不做比对（01-spec N8）。
"""
import re
from datetime import datetime

from app.clock import from_db
from app.config import Settings

# 内置敏感词表（演示用，可按需扩充）
SENSITIVE_WORDS = ["赌博", "博彩", "色情", "毒品", "代考", "枪支", "诈骗", "传销", "刷单"]

_DATE_CN = re.compile(r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_DATE_ISO = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_TIME = re.compile(
    r"(上午|早上|中午|下午|晚上|傍晚)?\s*(\d{1,2})\s*(?:[:：]\s*(\d{2})|点\s*(?:(\d{1,2})\s*分|(半))?)"
)
_COUNT = re.compile(r"(\d+)\s*(?:人|名)")


def validate(summary: str, notes: list[str], act: dict, cfg: Settings) -> list[dict]:
    """act 需要 start_at、end_at（数据库格式）和 capacity。返回问题列表，空列表表示通过。"""
    issues: list[dict] = []
    start = from_db(act["start_at"]).astimezone(cfg.tz)
    end = from_db(act["end_at"]).astimezone(cfg.tz)

    if len(summary) > cfg.summary_max_len:
        issues.append(_issue("summary", "TOO_LONG", summary[:20], f"简介超出 {cfg.summary_max_len} 字"))
    if len(notes) > cfg.notes_max_items:
        issues.append(_issue("notes", "TOO_MANY", "", f"注意事项超过 {cfg.notes_max_items} 条"))
    for i, note in enumerate(notes, start=1):
        if len(note) > cfg.note_max_len:
            issues.append(_issue(f"notes[{i}]", "TOO_LONG", note[:20], f"第 {i} 条注意事项超出 {cfg.note_max_len} 字"))

    texts = [("summary", summary)] + [(f"notes[{i}]", n) for i, n in enumerate(notes, start=1)]
    for field, text in texts:
        issues += _check_dates(field, text, start, end)
        issues += _check_times(field, text, start, end)
        issues += _check_counts(field, text, act["capacity"])
        for word in SENSITIVE_WORDS:
            if word in text:
                issues.append(_issue(field, "SENSITIVE", word, f"包含敏感词「{word}」"))
    return issues


def _check_dates(field: str, text: str, start: datetime, end: datetime) -> list[dict]:
    allowed = {(start.year, start.month, start.day), (end.year, end.month, end.day)}
    issues = []
    found = [(m, m.group(1), m.group(2), m.group(3)) for m in _DATE_CN.finditer(text)]
    found += [(m, m.group(1), m.group(2), m.group(3)) for m in _DATE_ISO.finditer(text)]
    for match, year, month, day in found:
        month, day = int(month), int(day)
        ok = any((year is None or int(year) == y) and (month, day) == (mo, d) for y, mo, d in allowed)
        if not ok:
            issues.append(_issue(field, "DATE_MISMATCH", match.group(0),
                                 f"日期 {month} 月 {day} 日与活动日期 {start.month} 月 {start.day} 日不一致"))
    return issues


def _check_times(field: str, text: str, start: datetime, end: datetime) -> list[dict]:
    allowed = {(start.hour, start.minute), (end.hour, end.minute)}
    issues = []
    period = None
    for m in _TIME.finditer(text):
        # 没写「上午 / 下午」的时刻沿用前一个，例如「下午2点开始，4点结束」中的 4 点是 16:00
        period, hour = m.group(1) or period, int(m.group(2))
        minute = int(m.group(3) or m.group(4) or (30 if m.group(5) else 0))
        if period in ("下午", "晚上", "傍晚") and hour < 12:
            hour += 12
        elif period == "中午" and hour <= 2:
            hour += 12
        if hour > 23 or minute > 59:
            continue
        if (hour, minute) not in allowed:
            issues.append(_issue(field, "TIME_MISMATCH", m.group(0).strip(),
                                 f"时刻 {hour:02d}:{minute:02d} 与活动开始/结束时刻不一致"))
    return issues


def _check_counts(field: str, text: str, capacity: int) -> list[dict]:
    return [
        _issue(field, "COUNT_MISMATCH", m.group(0), f"人数 {m.group(1)} 与名额 {capacity} 不一致")
        for m in _COUNT.finditer(text)
        if int(m.group(1)) != capacity
    ]


def _issue(field: str, rule: str, text: str, message: str) -> dict:
    return {"field": field, "rule": rule, "text": text, "message": message}
