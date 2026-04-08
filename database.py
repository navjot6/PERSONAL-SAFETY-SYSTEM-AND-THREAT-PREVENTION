import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "alerts.db"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    # Add email status columns for debugging/visibility (safe re-run).
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()}
    if "email_sent" not in cols:
        conn.execute("ALTER TABLE alerts ADD COLUMN email_sent INTEGER DEFAULT 0")
    if "email_error" not in cols:
        conn.execute("ALTER TABLE alerts ADD COLUMN email_error TEXT")
    conn.commit()
    conn.close()


def add_alert(message: str, latitude: float, longitude: float):
    conn = get_db_connection()
    cur = conn.execute(
        "INSERT INTO alerts(message, latitude, longitude) VALUES (?, ?, ?)",
        (message, latitude, longitude),
    )
    conn.commit()
    alert_id = cur.lastrowid
    conn.close()
    return alert_id


def set_email_status(alert_id: int, email_sent: bool, email_error: str | None = None):
    conn = get_db_connection()
    conn.execute(
        "UPDATE alerts SET email_sent = ?, email_error = ? WHERE id = ?",
        (1 if email_sent else 0, email_error, alert_id),
    )
    conn.commit()
    conn.close()


def get_alerts(limit: int = 20):
    return get_alerts_filtered(limit=limit, hours=24)


def get_alerts_filtered(limit: int = 20, hours: int = 24):
    """
    Return recent alerts only.
    Using `strftime('%s', ...)` makes the filter reliable with SQLite TEXT timestamps.
    """
    conn = get_db_connection()
    hours = int(hours)
    rows = conn.execute(
        """
        SELECT id, message, latitude, longitude, created_at, email_sent, email_error
        FROM alerts
        WHERE strftime('%s', created_at) >= strftime('%s', 'now', ?)
        ORDER BY id DESC
        LIMIT ?
        """,
        (f"-{hours} hours", limit),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
