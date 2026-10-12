"""当前时间来源（NFR-04）与数据库时间格式（03 §4.6）。

业务代码一律通过 Clock.now() 取当前时间，测试中注入 FixedClock。
数据库统一存 UTC，格式固定为 YYYY-MM-DDTHH:MM:SSZ（定长，字符串比较即时间比较）。
"""
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Protocol

DB_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    """测试用：时间只在调用 set / advance 时变化。"""

    def __init__(self, at: datetime):
        self._at = _require_aware(at)

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = _require_aware(at)

    def advance(self, **kwargs) -> None:
        self._at += timedelta(**kwargs)


def to_db(dt: datetime) -> str:
    return _require_aware(dt).astimezone(timezone.utc).strftime(DB_TIME_FORMAT)


def from_db(s: str) -> datetime:
    return datetime.strptime(s, DB_TIME_FORMAT).replace(tzinfo=timezone.utc)


def to_api(s: str | None, tz: tzinfo) -> str | None:
    """数据库时间 → 接口时间：带时区偏移的 ISO 8601，按配置时区展示（03 §4.6）。"""
    return None if s is None else from_db(s).astimezone(tz).isoformat()


def hhmm(s: str, tz: tzinfo) -> str:
    return from_db(s).astimezone(tz).strftime("%H:%M")


def local_day_start_utc(d: date, tz: tzinfo) -> str:
    """配置时区下某一天 00:00 对应的数据库时间，用于日期范围筛选。"""
    return to_db(datetime.combine(d, time.min, tzinfo=tz))


def _require_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("时间必须带时区信息")
    return dt
