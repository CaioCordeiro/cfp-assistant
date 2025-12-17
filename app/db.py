import os
import sqlite3
from typing import Optional
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get("CFP_DB_PATH", os.path.join(os.getcwd(), "cfp.db"))


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_number TEXT NOT NULL,
                title TEXT,
                abstract TEXT,
                email TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
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


def upsert_conversation(user_number: str, state: str, submission_id: Optional[int] = None):
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


def create_submission_draft(user_number: str, title: str, abstract: str) -> int:
    with get_conn() as conn:
        now = _utcnow_iso()
        cur = conn.execute(
            """
            INSERT INTO submissions(user_number, title, abstract, email, status, created_at, updated_at)
            VALUES (?, ?, ?, NULL, 'draft', ?, ?)
            """,
            (user_number, title, abstract, now, now),
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
            (message_sid, message_status, error_code, to_number, from_number, _utcnow_iso()),
        )