"""users 表的参数化 SQL。事务边界由调用方决定。"""
import sqlite3


def list_users(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name, role, grade FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, name, role, grade FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return dict(row) if row else None


def insert_user(conn: sqlite3.Connection, user_id: int, name: str, role: str, grade: str | None) -> None:
    conn.execute(
        "INSERT INTO users (id, name, role, grade) VALUES (?, ?, ?, ?)",
        (user_id, name, role, grade),
    )
