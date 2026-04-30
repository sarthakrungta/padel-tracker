"""
fetcher.py — fetch the booking API, diff against previous snapshots, infer bookings.
"""

import json
import logging
from datetime import datetime, timezone

import requests

import config
import db

log = logging.getLogger(__name__)


def fetch_slots(local_date: str) -> list:
    params = {**config.API_PARAMS_BASE, "date": local_date}
    resp = requests.get(config.API_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def save_snapshot(local_date: str, data: list, fetched_at_utc: str):
    db.execute(
        "INSERT INTO snapshots (fetched_at_utc, local_date, raw_json) VALUES (?,?,?)",
        (fetched_at_utc, local_date, json.dumps(data)),
    )
    log.info(f"[snapshot] saved for {local_date} at {fetched_at_utc}")


def upsert_slots(local_date: str, data: list, fetched_at_utc: str) -> set:
    """
    Insert new slots and update last_seen_utc for existing ones.
    Returns the set of slot keys visible in this snapshot.
    """
    current_keys = set()
    rows = []
    for court in data:
        rid = court["resource_id"]
        for slot in court.get("slots", []):
            key = (local_date, rid, slot["start_time"], int(slot["duration"]))
            current_keys.add(key)
            rows.append((*key, slot["price"], fetched_at_utc, fetched_at_utc))

    db.executemany("""
        INSERT INTO slots
            (local_date, resource_id, start_time_utc, duration_min,
             price, first_seen_utc, last_seen_utc)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(local_date, resource_id, start_time_utc, duration_min)
        DO UPDATE SET last_seen_utc = excluded.last_seen_utc
    """, rows)
    log.info(f"[slots] upserted {len(current_keys)} slots for {local_date}")
    return current_keys


def detect_bookings(local_date: str, current_keys: set, fetched_at_utc: str):
    """
    Any slot we've seen before that isn't in the current response → probable booking.
    Skip if already recorded in bookings table.
    """
    known = db.execute(
        "SELECT resource_id, start_time_utc, duration_min, price, first_seen_utc "
        "FROM slots WHERE local_date = ?",
        (local_date,),
    )
    new_bookings = 0
    for row in known:
        key = (local_date, row["resource_id"], row["start_time_utc"], int(row["duration_min"]))
        if key in current_keys:
            continue  # still available

        already = db.execute(
            "SELECT id FROM bookings "
            "WHERE local_date=? AND resource_id=? AND start_time_utc=? AND duration_min=?",
            (local_date, row["resource_id"], row["start_time_utc"], row["duration_min"]),
        )
        if already:
            continue  # already recorded from a previous poll

        db.execute(
            "INSERT INTO bookings "
            "(local_date, resource_id, start_time_utc, duration_min, "
            " price, first_seen_utc, booked_after_utc) "
            "VALUES (?,?,?,?,?,?,?)",
            (local_date, row["resource_id"], row["start_time_utc"],
             row["duration_min"], row["price"], row["first_seen_utc"], fetched_at_utc),
        )
        new_bookings += 1
        log.info(f"[booking] {row['resource_id']} @ {row['start_time_utc']} "
                 f"on {local_date} — slot vanished, recorded")

    if new_bookings:
        log.info(f"[bookings] {new_bookings} new probable bookings for {local_date}")


def confirm_bookings():
    """
    Once a slot's UTC start time is in the past it can never reappear,
    so we flip confirmed_booked = 1. This eliminates cancellation ambiguity.
    """
    now_utc = datetime.now(timezone.utc)
    pending = db.execute(
        "SELECT id, local_date, start_time_utc FROM bookings WHERE confirmed_booked = 0"
    )
    confirmed = 0
    for row in pending:
        slot_dt_str = f"{row['local_date']}T{row['start_time_utc']}+00:00"
        try:
            slot_dt = datetime.fromisoformat(slot_dt_str)
        except ValueError:
            continue
        if now_utc > slot_dt:
            db.execute("UPDATE bookings SET confirmed_booked=1 WHERE id=?", (row["id"],))
            confirmed += 1
    if confirmed:
        log.info(f"[confirm] {confirmed} bookings confirmed (start time passed)")


def run_poll(local_date: str):
    fetched_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log.info(f"[poll] fetching {local_date} at {fetched_at_utc}")
    try:
        data = fetch_slots(local_date)
    except Exception as e:
        log.error(f"[poll] API error: {e}")
        return
    save_snapshot(local_date, data, fetched_at_utc)
    current_keys = upsert_slots(local_date, data, fetched_at_utc)
    detect_bookings(local_date, current_keys, fetched_at_utc)
    confirm_bookings()
