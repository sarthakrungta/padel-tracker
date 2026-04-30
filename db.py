"""
db.py — database layer using Turso's HTTP API.

Replaces libsql-client (which has Python 3.13 compatibility issues) with
plain HTTPS requests to Turso's /v2/pipeline endpoint. No extra dependencies
beyond `requests`, which we already use for the booking API.

TURSO_URL should be the libsql:// URL from `turso db show --url`.
The code converts it to https:// automatically.
"""

import sqlite3
import requests
import config


# ── Connection helpers ────────────────────────────────────────────────────────

def _is_remote() -> bool:
    return config.TURSO_URL.startswith("libsql://")


def _http_url() -> str:
    """Convert libsql://host to https://host for the HTTP API."""
    return config.TURSO_URL.replace("libsql://", "https://", 1)


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.TURSO_TOKEN}",
            "Content-Type": "application/json"}


# ── Remote (Turso HTTP API) ───────────────────────────────────────────────────

def _remote_execute(sql: str, params: tuple = ()) -> list[dict]:
    """Run one statement against Turso and return rows as dicts."""
    # Turso HTTP API expects named args format; we use positional ? style
    # and pass args as an ordered list of typed values
    args = [_turso_value(p) for p in params]
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": args}},
            {"type": "close"},
        ]
    }
    resp = requests.post(
        f"{_http_url()}/v2/pipeline",
        headers=_headers(),
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    # Check for errors returned in the response body
    result = data["results"][0]
    if result["type"] == "error":
        raise RuntimeError(f"Turso error: {result['error']}")

    rows_data = result["response"]["result"]
    cols = [c["name"] for c in rows_data["cols"]]
    return [dict(zip(cols, [v["value"] for v in row])) for row in rows_data["rows"]]


def _turso_value(v) -> dict:
    """Convert a Python value to Turso's typed value format."""
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _remote_executemany(sql: str, rows: list[tuple]):
    """Run the same statement for each row, batched into one HTTP request."""
    if not rows:
        return
    requests_payload = []
    for row in rows:
        args = [_turso_value(p) for p in row]
        requests_payload.append({"type": "execute", "stmt": {"sql": sql, "args": args}})
    requests_payload.append({"type": "close"})

    resp = requests.post(
        f"{_http_url()}/v2/pipeline",
        headers=_headers(),
        json={"requests": requests_payload},
        timeout=15,
    )
    resp.raise_for_status()
    for result in resp.json()["results"]:
        if result["type"] == "error":
            raise RuntimeError(f"Turso error: {result['error']}")


# ── Local (plain SQLite, for testing without Turso) ───────────────────────────

def _local_execute(sql: str, params: tuple = ()) -> list[dict]:
    path = config.TURSO_URL.replace("file:", "")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        if cur.description:
            return [dict(row) for row in cur.fetchall()]
        return []
    finally:
        conn.close()


def _local_executemany(sql: str, rows: list[tuple]):
    path = config.TURSO_URL.replace("file:", "")
    conn = sqlite3.connect(path)
    try:
        for row in rows:
            conn.execute(sql, row)
        conn.commit()
    finally:
        conn.close()


# ── Public API ────────────────────────────────────────────────────────────────

def execute(sql: str, params: tuple = ()) -> list[dict]:
    if _is_remote():
        return _remote_execute(sql, params)
    return _local_execute(sql, params)


def executemany(sql: str, rows: list[tuple]):
    if _is_remote():
        _remote_executemany(sql, rows)
    else:
        _local_executemany(sql, rows)


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
    for sql in statements:
        execute(sql)
    print(f"[db] initialised — {config.TURSO_URL}")


if __name__ == "__main__":
    init_db()