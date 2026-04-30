"""
db.py — database layer using Turso (hosted libSQL / SQLite).

When TURSO_URL starts with "file:" it uses a local SQLite file — useful for
testing on your laptop without a Turso account.

When TURSO_URL is a libsql:// URL it connects to the remote Turso database
using TURSO_TOKEN for auth — this is what GitHub Actions uses.
"""

import libsql_client
import config


def _client():
    """Create a fresh sync client. Call .close() when done."""
    kwargs = {"url": config.TURSO_URL}
    if config.TURSO_TOKEN:
        kwargs["auth_token"] = config.TURSO_TOKEN
    return libsql_client.create_client_sync(**kwargs)


def init_db():
    """Create tables if they don't exist. Safe to call on every run."""
    statements = [
        """CREATE TABLE IF NOT EXISTS snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at_utc  TEXT NOT NULL,
            local_date      TEXT NOT NULL,
            raw_json        TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS slots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            local_date      TEXT NOT NULL,
            resource_id     TEXT NOT NULL,
            start_time_utc  TEXT NOT NULL,
            duration_min    INTEGER NOT NULL,
            price           TEXT NOT NULL,
            first_seen_utc  TEXT NOT NULL,
            last_seen_utc   TEXT NOT NULL,
            UNIQUE(local_date, resource_id, start_time_utc, duration_min)
        )""",
        """CREATE TABLE IF NOT EXISTS bookings (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            local_date       TEXT NOT NULL,
            resource_id      TEXT NOT NULL,
            start_time_utc   TEXT NOT NULL,
            duration_min     INTEGER NOT NULL,
            price            TEXT NOT NULL,
            first_seen_utc   TEXT NOT NULL,
            booked_after_utc TEXT NOT NULL,
            confirmed_booked INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS idx_slots_date    ON slots(local_date)",
        "CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(local_date)",
    ]
    with _client() as c:
        for sql in statements:
            c.execute(sql)
    print(f"[db] initialised — {config.TURSO_URL}")


def execute(sql: str, params: tuple = ()) -> list[dict]:
    """
    Run any SQL statement.
    Returns a list of dicts for SELECT, empty list for writes.
    """
    with _client() as c:
        result = c.execute(sql, list(params))
        if result.columns:
            return [dict(zip(result.columns, row)) for row in result.rows]
        return []


def executemany(sql: str, rows: list[tuple]):
    """Run the same SQL for each row in `rows`."""
    with _client() as c:
        for row in rows:
            c.execute(sql, list(row))


if __name__ == "__main__":
    init_db()
