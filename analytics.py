"""
analytics.py — run this locally whenever you want to see occupancy data.

Reads from the same Turso DB the scraper writes to.
Set TURSO_URL and TURSO_TOKEN in your shell (or a .env file) before running.

Usage:
    python analytics.py                    # all dates
    python analytics.py --date 2026-04-29  # single date detail
    python analytics.py --weekly           # weekly averages
    python analytics.py --confirmed-only   # exclude slots still in future
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone

import pytz

import config
import db

LOCAL_TZ = pytz.timezone(config.LOCAL_TZ)


def court_name(resource_id: str) -> str:
    return config.COURT_NAMES.get(resource_id, resource_id[:8] + "…")


def opening_minutes(local_date_str: str) -> int:
    d = datetime.strptime(local_date_str, "%Y-%m-%d").date()
    if d.weekday() < 5:
        oh, om = map(int, config.WEEKDAY_OPEN.split(":"))
        ch, cm = map(int, config.WEEKDAY_CLOSE.split(":"))
    else:
        oh, om = map(int, config.WEEKEND_OPEN.split(":"))
        ch, cm = map(int, config.WEEKEND_CLOSE.split(":"))
    return (ch * 60 + cm) - (oh * 60 + om)


def utc_to_local(local_date_str: str, start_time_utc: str) -> datetime:
    naive = datetime.strptime(f"{local_date_str}T{start_time_utc}", "%Y-%m-%dT%H:%M:%S")
    return naive.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)


def report_date(local_date: str, confirmed_only: bool = False):
    sql = "SELECT * FROM bookings WHERE local_date=?"
    if confirmed_only:
        sql += " AND confirmed_booked=1"
    rows = db.execute(sql, (local_date,))

    if not rows:
        print(f"\n  No {'confirmed ' if confirmed_only else ''}bookings for {local_date}.")
        return

    by_court = defaultdict(list)
    for row in rows:
        by_court[row["resource_id"]].append(row)

    open_min = opening_minutes(local_date)
    print(f"\n{'─'*60}")
    print(f"  {local_date}  (club open: {open_min} min)")
    print(f"{'─'*60}")

    total_booked = 0
    for rid, bookings in sorted(by_court.items()):
        booked = sum(b["duration_min"] for b in bookings)
        total_booked += booked
        pct = booked / open_min * 100 if open_min else 0
        print(f"\n  {court_name(rid)}")
        print(f"    Bookings : {len(bookings)}")
        print(f"    Booked   : {booked} min  ({pct:.0f}% of opening hours)")
        for b in sorted(bookings, key=lambda x: x["start_time_utc"]):
            local_dt = utc_to_local(local_date, b["start_time_utc"])
            status = "✓" if b["confirmed_booked"] else "?"
            print(f"      {status}  {local_dt.strftime('%H:%M')} local  "
                  f"{b['duration_min']}min  {b['price']}")

    n = len(by_court)
    overall = total_booked / (open_min * n) * 100 if (open_min and n) else 0
    print(f"\n  Overall occupancy: {overall:.0f}%  "
          f"({total_booked}/{open_min * n} court-minutes)\n")


def report_all(confirmed_only: bool = False):
    rows = db.execute("SELECT DISTINCT local_date FROM bookings ORDER BY local_date")
    if not rows:
        print("No booking data yet.")
        return
    print(f"Data collected for {len(rows)} day(s):")
    for row in rows:
        report_date(row["local_date"], confirmed_only=confirmed_only)


def report_weekly():
    rows = db.execute(
        "SELECT local_date, resource_id, duration_min FROM bookings ORDER BY local_date"
    )
    if not rows:
        print("No booking data yet.")
        return

    by_weekday = defaultdict(lambda: {"booked_min": 0, "days": set()})
    by_week    = defaultdict(lambda: {"booked_min": 0, "open_min": 0})

    for row in rows:
        d = datetime.strptime(row["local_date"], "%Y-%m-%d").date()
        weekday  = d.strftime("%A")
        iso_week = d.strftime("%G-W%V")
        dur = row["duration_min"]

        by_weekday[weekday]["booked_min"] += dur
        by_weekday[weekday]["days"].add(row["local_date"])
        by_week[iso_week]["booked_min"] += dur
        by_week[iso_week]["open_min"]   += opening_minutes(row["local_date"])

    print("\n── Average bookings by weekday ──")
    for day in ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]:
        if day not in by_weekday:
            continue
        info = by_weekday[day]
        n    = len(info["days"])
        avg  = info["booked_min"] / n
        print(f"  {day:<12}  avg {avg:.0f} booked-min/day  (n={n} days)")

    print("\n── Bookings by week ──")
    for week, info in sorted(by_week.items()):
        pct = info["booked_min"] / info["open_min"] * 100 if info["open_min"] else 0
        print(f"  {week}  {info['booked_min']} booked-min  ({pct:.0f}% occupancy)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--weekly",         action="store_true")
    parser.add_argument("--confirmed-only", action="store_true")
    args = parser.parse_args()

    if args.date:
        report_date(args.date, confirmed_only=args.confirmed_only)
    elif args.weekly:
        report_weekly()
    else:
        report_all(confirmed_only=args.confirmed_only)
