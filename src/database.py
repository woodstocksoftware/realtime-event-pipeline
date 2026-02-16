"""SQLite database layer."""

import json
import logging
import os
import sqlite3
from typing import List, Optional

from src.config import DATABASE_PATH
from src.models import EventResponse

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    """Create a new database connection."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
    """Create tables and indexes if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            session_id TEXT,
            user_id TEXT,
            payload TEXT,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS event_stats (
            event_type TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0,
            last_seen TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
    """)

    conn.commit()
    conn.close()

    # Restrict file permissions (owner-only read/write)
    try:
        os.chmod(DATABASE_PATH, 0o600)
        os.chmod(DATABASE_PATH.parent, 0o700)
    except OSError:
        logger.warning("Could not set restrictive permissions on database file")


def insert_event(
    event_id: str,
    event_type: str,
    source: str,
    session_id: Optional[str],
    user_id: Optional[str],
    payload: dict,
    timestamp: str,
) -> None:
    """Persist an event and update stats."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO events (id, event_type, source, session_id, user_id, payload, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, event_type, source, session_id, user_id, json.dumps(payload), timestamp),
        )
        cursor.execute(
            """
            INSERT INTO event_stats (event_type, count, last_seen)
            VALUES (?, 1, ?)
            ON CONFLICT(event_type) DO UPDATE SET
                count = count + 1,
                last_seen = excluded.last_seen
            """,
            (event_type, timestamp),
        )
        conn.commit()
    finally:
        conn.close()


def _row_to_event(row: sqlite3.Row) -> EventResponse:
    """Convert a database row to an EventResponse."""
    return EventResponse(
        id=row["id"],
        event_type=row["event_type"],
        source=row["source"],
        session_id=row["session_id"],
        user_id=row["user_id"],
        payload=json.loads(row["payload"]) if row["payload"] else {},
        timestamp=row["timestamp"],
    )


def query_events(
    event_type: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 100,
) -> List[EventResponse]:
    """Query events with optional filters."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        query = "SELECT * FROM events WHERE 1=1"
        params: list = []

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if since:
            query += " AND timestamp > ?"
            params.append(since)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return [_row_to_event(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_event_by_id(event_id: str) -> Optional[EventResponse]:
    """Get a single event by ID."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        row = cursor.fetchone()
        return _row_to_event(row) if row else None
    finally:
        conn.close()


def get_stats() -> dict:
    """Get pipeline statistics from the database."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) as total FROM events")
        total = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT event_type, count, last_seen FROM event_stats ORDER BY count DESC"
        )
        by_type = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT COUNT(*) as count FROM events
            WHERE timestamp > datetime('now', '-1 hour')
        """)
        last_hour = cursor.fetchone()["count"]

        return {
            "total_events": total,
            "events_last_hour": last_hour,
            "by_type": by_type,
        }
    finally:
        conn.close()


def delete_events(before: Optional[str] = None) -> int:
    """Delete events. Returns count of deleted events."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        if before:
            cursor.execute("DELETE FROM events WHERE timestamp < ?", (before,))
            deleted = cursor.rowcount
        else:
            cursor.execute("DELETE FROM events")
            deleted = cursor.rowcount
            cursor.execute("DELETE FROM event_stats")
        conn.commit()
        return deleted
    finally:
        conn.close()
