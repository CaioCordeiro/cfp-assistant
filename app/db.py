import os
import sqlite3
from typing import Optional
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get("CFP_DB_PATH", os.path.join(os.getcwd(), "cfp.db"))


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_number TEXT NOT NULL,
                title TEXT,
                abstract TEXT,
                private_message TEXT,
                main_language TEXT,
                talk_type TEXT,
                intended_audience TEXT,
                estimated_duration TEXT,
                live_coding TEXT,
                special_requirements TEXT,
                email TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        existing = {
            row["name"] for row in conn.execute("PRAGMA table_info(submissions)")
        }
        for col, typ in [
            ("private_message", "TEXT"),
            ("main_language", "TEXT"),
            ("talk_type", "TEXT"),
            ("intended_audience", "TEXT"),
            ("estimated_duration", "TEXT"),
            ("live_coding", "INTEGER"),
            ("special_requirements", "TEXT"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE submissions ADD COLUMN {col} {typ}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                user_number TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                submission_id INTEGER,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(submission_id) REFERENCES submissions(id)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS message_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_sid TEXT NOT NULL,
                message_status TEXT NOT NULL,
                error_code TEXT,
                to_number TEXT,
                from_number TEXT,
                created_at TEXT NOT NULL
            );
            """
        )


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_conversation(
    user_number: str, state: str, submission_id: Optional[int] = None
):
    with get_conn() as conn:
        now = _utcnow_iso()
        conn.execute(
            """
            INSERT INTO conversations(user_number, state, submission_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_number) DO UPDATE SET
                state=excluded.state,
                submission_id=excluded.submission_id,
                updated_at=excluded.updated_at
            """,
            (user_number, state, submission_id, now),
        )


def get_conversation(user_number: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT user_number, state, submission_id, updated_at FROM conversations WHERE user_number=?",
            (user_number,),
        )
        return cur.fetchone()


def create_submission_draft(
    user_number: str,
    title: str,
    abstract: str,
    private_message: Optional[str],
    main_language: Optional[str],
    talk_type: Optional[str],
    intended_audience: Optional[str],
    estimated_duration: Optional[str],
    live_coding: Optional[bool],
    special_requirements: Optional[str],
) -> int:
    conn = _connect()
    now = _utcnow_iso()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO submissions (
                user_number, title, abstract,
                private_message, main_language, talk_type, intended_audience,
                estimated_duration, live_coding, special_requirements,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (
                user_number,
                title,
                abstract,
                private_message,
                main_language,
                talk_type,
                intended_audience,
                estimated_duration,
                1 if (live_coding is True) else 0 if (live_coding is False) else None,
                special_requirements,
                now,
                now,
            ),
        )
        return int(cur.lastrowid)


def get_submission(submission_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM submissions WHERE id=?",
            (submission_id,),
        )
        return cur.fetchone()


def delete_submission(submission_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM submissions WHERE id=?", (submission_id,))


def update_submission_email_and_submit(submission_id: int, email: str) -> None:
    with get_conn() as conn:
        now = _utcnow_iso()
        conn.execute(
            """
            UPDATE submissions
            SET email=?, status='submitted', updated_at=?
            WHERE id=?
            """,
            (email, now, submission_id),
        )


def list_submissions_for_user(user_number: str, limit: int = 5) -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT id, title, status, created_at, updated_at
            FROM submissions
            WHERE user_number=?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_number, limit),
        )
        return cur.fetchall()


def record_message_status(
    message_sid: str,
    message_status: str,
    error_code: str | None,
    to_number: str | None,
    from_number: str | None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO message_status(message_sid, message_status, error_code, to_number, from_number, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message_sid,
                message_status,
                error_code,
                to_number,
                from_number,
                _utcnow_iso(),
            ),
        )
