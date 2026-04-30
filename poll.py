"""
poll.py — single poll cycle, designed to be run by GitHub Actions.

Each GitHub Actions run:
  1. calls this script once
  2. the script initialises the DB (no-op if tables already exist)
  3. fetches today's (and tomorrow's, if relevant) slots
  4. diffs against the DB, records any disappeared slots as bookings
  5. exits — Turso persists the data between runs

Usage:
    python poll.py
    python poll.py --date 2026-04-29   # force a specific date (for testing)
"""

import argparse
import logging
from datetime import datetime, timedelta, timezone

import pytz

import config
import db
import fetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

LOCAL_TZ = pytz.timezone(config.LOCAL_TZ)


def parse_hhmm(hhmm: str):
    h, m = hhmm.split(":")
    return int(h), int(m)


def club_poll_window_utc(local_date_str: str):
    """Return (start_utc, stop_utc) for when to poll on a given local date."""
    d = datetime.strptime(local_date_str, "%Y-%m-%d").date()
    if d.weekday() < 5:
        open_h,  open_m  = parse_hhmm(config.WEEKDAY_OPEN)
        close_h, close_m = parse_hhmm(config.WEEKDAY_CLOSE)
    else:
        open_h,  open_m  = parse_hhmm(config.WEEKEND_OPEN)
        close_h, close_m = parse_hhmm(config.WEEKEND_CLOSE)

    open_local  = LOCAL_TZ.localize(datetime(d.year, d.month, d.day, open_h,  open_m))
    close_local = LOCAL_TZ.localize(datetime(d.year, d.month, d.day, close_h, close_m))

    # Start polling 30 min before open, stop at close
    return (
        open_local.astimezone(timezone.utc)  - timedelta(minutes=30),
        close_local.astimezone(timezone.utc),
    )


def should_poll(local_date_str: str) -> bool:
    start, stop = club_poll_window_utc(local_date_str)
    now = datetime.now(timezone.utc)
    return start <= now <= stop


def local_date_str(offset_days: int = 0) -> str:
    return (datetime.now(LOCAL_TZ) + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Force poll for this local date (YYYY-MM-DD)")
    args = parser.parse_args()

    db.init_db()

    if args.date:
        # Manual override — always poll the given date regardless of time
        log.info(f"[poll] Manual date override: {args.date}")
        fetcher.run_poll(args.date)
        return

    # Normal scheduled run: poll today and/or tomorrow if within their windows
    today    = local_date_str(0)
    tomorrow = local_date_str(1)

    polled_anything = False

    if should_poll(today):
        log.info(f"[poll] Within window for {today} — polling")
        fetcher.run_poll(today)
        polled_anything = True

    # Poll tomorrow too if we're in its pre-open window
    # (e.g. 10pm local = early UTC next day for Melbourne)
    if tomorrow != today and should_poll(tomorrow):
        log.info(f"[poll] Within pre-open window for {tomorrow} — polling")
        fetcher.run_poll(tomorrow)
        polled_anything = True

    if not polled_anything:
        log.info(f"[poll] Outside polling window for {today} — nothing to do")


if __name__ == "__main__":
    main()
