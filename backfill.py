"""
backfill.py — inject a saved API response into the database.

Useful for seeding data you already have before the scraper started running.

Usage:
    python backfill.py --date 2026-04-29 --file response.json
    python backfill.py --date 2026-04-29 --json '[{"resource_id":...}]'
    python backfill.py --date 2026-04-29 --file response.json --time 2026-04-29T07:35:00Z
"""

import argparse
import json
from datetime import datetime, timezone

import db
import fetcher


def backfill(local_date: str, data: list, fetched_at_utc: str = None):
    if not fetched_at_utc:
        fetched_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    total_slots = sum(len(c.get("slots", [])) for c in data)
    print(f"Backfilling {local_date}: {total_slots} slots as of {fetched_at_utc}")

    db.init_db()
    fetcher.save_snapshot(local_date, data, fetched_at_utc)
    current_keys = fetcher.upsert_slots(local_date, data, fetched_at_utc)
    fetcher.detect_bookings(local_date, current_keys, fetched_at_utc)
    fetcher.confirm_bookings()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",      required=True)
    parser.add_argument("--file",      help="Path to JSON file")
    parser.add_argument("--json",      dest="json_str", help="Raw JSON string")
    parser.add_argument("--time",      dest="fetched_at", help="UTC ISO8601 timestamp")
    args = parser.parse_args()

    if args.file:
        with open(args.file) as f:
            data = json.load(f)
    elif args.json_str:
        data = json.loads(args.json_str)
    else:
        parser.error("Provide --file or --json")

    backfill(args.date, data, fetched_at_utc=args.fetched_at)
