"""数据库连接与事务（03 §7、DEC-02）。

要点：
- isolation_level=None：关闭 sqlite3 驱动的隐式事务。驱动默认只在 INSERT/UPDATE/DELETE
  前隐式 BEGIN，SELECT 不在事务里，「先查人数再写入」会超卖（03 §7.3）。
- write_tx 用 BEGIN IMMEDIATE，事务一开始就拿写锁，「读取 → 判断 → 写入」整体原子。
- 等锁超时（SQLITE_BUSY / SQLITE_LOCKED）统一转成 SYSTEM_BUSY（503）。
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.errors import AppError

SCHEMA_FILE = Path(__file__).with_name("schema.sql")

# 删除顺序：先删有外键依赖的表
TABLES = ["operation_logs", "registrations", "activities", "ai_call_logs", "users"]

_SQLITE_BUSY = 5
_SQLITE_LOCKED = 6


def connect(db_file: Path | str, busy_timeout_ms: int) -> sqlite3.Connection:
    """每个请求一个独立连接，请求结束后关闭；不在请求之间共享。"""
    conn = sqlite3.connect(
        str(db_file),
        isolation_level=None,
        timeout=busy_timeout_ms / 1000,
        # FastAPI 的同步依赖与接口函数可能在线程池的不同线程上执行；连接只被当前请求使用
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def read_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """只读事务：WAL 下得到一致快照，不阻塞写入。"""
    conn.execute("BEGIN DEFERRED")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        _rollback(conn)
        raise


@contextmanager
def write_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """写事务：BEGIN IMMEDIATE 拿整库写锁；异常时 ROLLBACK，不留下部分写入。"""
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as e:
        if _is_busy(e):
            raise AppError("SYSTEM_BUSY") from e
        raise
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException as e:
        _rollback(conn)
        if isinstance(e, sqlite3.OperationalError) and _is_busy(e):
            raise AppError("SYSTEM_BUSY") from e
        raise


def _rollback(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.execute("ROLLBACK")


def _is_busy(e: sqlite3.OperationalError) -> bool:
    code = getattr(e, "sqlite_errorcode", None)
    if code is not None:
        return (code & 0xFF) in (_SQLITE_BUSY, _SQLITE_LOCKED)
    msg = str(e).lower()
    return "locked" in msg or "busy" in msg


# ---------- 建表 / 删表（供 seed.init_database / reset_database 使用） ----------

def enable_wal(conn: sqlite3.Connection) -> None:
    """journal_mode=WAL 写入数据库文件，持久生效；必须在事务外执行。"""
    conn.execute("PRAGMA journal_mode = WAL")


def has_schema(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    return row is not None


def create_schema(conn: sqlite3.Connection) -> None:
    """逐条执行 schema.sql。不用 executescript：它会先隐式 COMMIT，破坏外层事务。"""
    for stmt in _split_statements(SCHEMA_FILE.read_text(encoding="utf-8")):
        conn.execute(stmt)


def drop_schema(conn: sqlite3.Connection) -> None:
    for table in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")


def _split_statements(sql: str) -> Iterator[str]:
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            yield buf.strip()
            buf = ""
    rest = [l for l in buf.splitlines() if l.strip() and not l.strip().startswith("--")]
    if rest:
        raise ValueError(f"schema.sql 末尾存在不完整的语句：{rest!r}")
