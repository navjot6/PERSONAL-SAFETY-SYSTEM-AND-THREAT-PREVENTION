import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "alerts.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute("PRAGMA journal_mode = WAL")

    # ── alerts table ──────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            message    TEXT,
            latitude   REAL,
            longitude  REAL,
            snapshot   TEXT,
            email_sent INTEGER DEFAULT 0,
            email_error TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
""")

    # Back-fill optional columns added after initial schema
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()}
    if "email_sent" not in cols:
        conn.execute("ALTER TABLE alerts ADD COLUMN email_sent INTEGER DEFAULT 0")
    if "email_error" not in cols:
        conn.execute("ALTER TABLE alerts ADD COLUMN email_error TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            google_id  TEXT    UNIQUE NOT NULL,
            email      TEXT    UNIQUE NOT NULL,
            name       TEXT,
            picture    TEXT,
            created_at TEXT    DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT    DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()
    conn.close()

def add_alert(message, latitude, longitude, snapshot=None):
    conn = get_db_connection()
    cur = conn.execute(
        """INSERT INTO alerts (message, latitude, longitude, snapshot)
           VALUES (?, ?, ?, ?)""",
        (message, latitude, longitude, snapshot)
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
    """Return recent alerts only, newest first."""
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT id, message, latitude, longitude, created_at, email_sent, email_error
        FROM   alerts
        WHERE  strftime('%s', created_at) >= strftime('%s', 'now', ?)
        ORDER  BY id DESC
        LIMIT  ?
        """,
        (f"-{int(hours)} hours", limit),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_or_create_google_user(
    google_id: str,
    email: str,
    name: str = "",
    picture: str = "",
) -> dict:
    """
    Find an existing user by their Google sub (google_id).
    • Found  → refresh name / picture / last_login, return the row.
    • New    → insert and return the new row.
    Always returns a plain dict with keys: id, google_id, email, name, picture.
    """
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, google_id, email, name, picture FROM users WHERE google_id = ?",
            (google_id,),
        ).fetchone()

        if row:
            conn.execute(
                """
                UPDATE users
                SET    name       = ?,
                       picture    = ?,
                       last_login = CURRENT_TIMESTAMP
                WHERE  google_id  = ?
                """,
                (name, picture, google_id),
            )
            conn.commit()
            return dict(row)

        # ── New user ──────────────────────────────────────────────────────────
        cur = conn.execute(
            "INSERT INTO users (google_id, email, name, picture) VALUES (?, ?, ?, ?)",
            (google_id, email, name, picture),
        )
        conn.commit()
        return {
            "id":        cur.lastrowid,
            "google_id": google_id,
            "email":     email,
            "name":      name,
            "picture":   picture,
        }
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    """Return a user row by primary key, or None if not found."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT id, google_id, email, name, picture FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None
