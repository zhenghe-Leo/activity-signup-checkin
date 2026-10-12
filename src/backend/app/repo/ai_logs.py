"""ai_call_logs 的参数化 SQL（BR-30）。不记录密钥和请求头。事务边界由调用方决定。"""
import sqlite3

INPUT_MAX = 500
OUTPUT_MAX = 4000


def exists(conn: sqlite3.Connection, ai_call_id: int) -> bool:
    return conn.execute("SELECT 1 FROM ai_call_logs WHERE id = ?", (ai_call_id,)).fetchone() is not None


def insert(
    conn: sqlite3.Connection,
    *,
    now: str,
    actor_id: int | None,
    feature: str,
    mode: str,
    fallback_reason: str | None,
    model: str | None,
    latency_ms: int,
    input_summary: str,
    output: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO ai_call_logs (occurred_at, actor_id, feature, mode, fallback_reason, model,"
        " latency_ms, input_summary, output) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now, actor_id, feature, mode, fallback_reason, model, latency_ms,
         input_summary[:INPUT_MAX], output[:OUTPUT_MAX]),
    )
    return cur.lastrowid


def get(conn: sqlite3.Connection, ai_call_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM ai_call_logs WHERE id = ?", (ai_call_id,)).fetchone()
    return dict(row) if row else None
