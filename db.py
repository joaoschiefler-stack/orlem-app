# db.py
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("orlem.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
    conn.commit()
    conn.close()


def save_message(session_id: str, role: str, content: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (session_id, ts, role, content) VALUES (?, ?, ?, ?)",
        (session_id, datetime.utcnow().isoformat(), role, content),
    )
    conn.commit()
    conn.close()


def list_sessions(limit: int = 100):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT session_id, MAX(ts) AS last_ts
        FROM messages
        GROUP BY session_id
        ORDER BY last_ts DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session_messages(session_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ts, role, content
        FROM messages
        WHERE session_id = ?
        ORDER BY ts ASC
        """,
        (session_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
