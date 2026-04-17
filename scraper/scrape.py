"""
Playtomic Padel Court Availability Scraper
==========================================
Fetches available slots from Playtomic API for configured clubs and stores
the raw data as JSON. Run via GitHub Actions on a schedule.

Occupancy Logic:
  - The API returns AVAILABLE slots (not booked ones)
  - We define a "session grid" (e.g. 08:00-22:00 in 1h blocks) per court
  - Occupancy = 1 - (available_slot_hours / total_possible_slot_hours)
  - We capture a "snapshot" each run. Over time, we build a picture of
    how availability changes throughout the day / week.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
import urllib.request
import urllib.error

# ── Club configuration ────────────────────────────────────────────────────────
# Add / remove clubs here. tenant_id comes from the Playtomic API URL.
CLUBS = [
    {
        "name": "Game4Padel Richmond",
        "slug": "game4padel-richmond",
        "tenant_id": "fd015cf7-b26b-4f7b-9a1f-8ed26f97ca05",
        "sport_id": "PADEL",
        # Business hours used to calculate total possible slot hours.
        # Adjust per club if opening hours differ.
        "open_hour": 7,   # inclusive
        "close_hour": 22, # exclusive  (22:00 = last slot start at 21:00)
    },
    # Add more clubs below — same structure, different name / tenant_id:
    # {
    #     "name": "Padel Club Two",
    #     "slug": "padel-club-two",
    #     "tenant_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    #     "sport_id": "PADEL",
    #     "open_hour": 8,
    #     "close_hour": 22,
    # },
]

API_BASE = "https://playtomic.com/api/clubs/availability"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
DAYS_AHEAD = 7  # scrape today + next N days


def fetch_availability(tenant_id: str, date: str, sport_id: str) -> list:
    """Call the Playtomic availability API for one club on one date."""
    url = f"{API_BASE}?tenant_id={tenant_id}&date={date}&sport_id={sport_id}"
    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (compatible; PadelOccupancyScraper/1.0; "
            "+https://github.com/your-username/padel-tracker)"
        ),
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} for {url}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  Error fetching {url}: {e}", file=sys.stderr)
        return []


def summarise(raw: list, club: dict, date: str) -> dict:
    """
    Convert raw API response into a structured snapshot with occupancy metrics.

    Returns a dict suitable for appending to a JSONL log file.
    """
    # Count unique courts (resource_ids)
    courts = {}
    for entry in raw:
        rid = entry.get("resource_id", "unknown")
        if rid not in courts:
            courts[rid] = []
        for slot in entry.get("slots", []):
            courts[rid].append(slot)

    num_courts = len(courts)
    open_h = club["open_hour"]
    close_h = club["close_hour"]
    total_hours_per_court = close_h - open_h  # e.g. 7-22 = 15 h
    total_possible_slot_hours = num_courts * total_hours_per_court

    # Sum up available 1-hour-equivalent slot hours
    # We only count duration == 60 (1h slots) to avoid double-counting
    # multi-duration options for the same time block.
    available_slot_hours = sum(
        1
        for slots in courts.values()
        for slot in slots
        if slot.get("duration") == 60
    )

    occupancy_pct = 0.0
    if total_possible_slot_hours > 0:
        booked = max(0, total_possible_slot_hours - available_slot_hours)
        occupancy_pct = round(booked / total_possible_slot_hours * 100, 1)

    # Slot breakdown by hour for the heat-map
    hourly_available: dict[str, int] = {}
    for slots in courts.values():
        for slot in slots:
            if slot.get("duration") == 60:
                h = slot["start_time"][:5]  # "09:00"
                hourly_available[h] = hourly_available.get(h, 0) + 1

    return {
        "club_name": club["name"],
        "club_slug": club["slug"],
        "date": date,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "num_courts": num_courts,
        "total_possible_slot_hours": total_possible_slot_hours,
        "available_slot_hours": available_slot_hours,
        "occupancy_pct": occupancy_pct,
        "hourly_available": hourly_available,
        # Keep a compact court-level breakdown
        "courts": {
            rid: {
                "available_1h_slots": sum(1 for s in slots if s.get("duration") == 60),
                "slot_times": sorted(
                    {s["start_time"][:5] for s in slots if s.get("duration") == 60}
                ),
            }
            for rid, slots in courts.items()
        },
    }


def save_snapshot(snapshot: dict):
    """Append snapshot to a per-club JSONL file and a combined file."""
    os.makedirs(DATA_DIR, exist_ok=True)

    def append_jsonl(path: str, record: dict):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    slug = snapshot["club_slug"]
    append_jsonl(os.path.join(DATA_DIR, f"{slug}.jsonl"), snapshot)
    append_jsonl(os.path.join(DATA_DIR, "all_clubs.jsonl"), snapshot)


def main():
    today = datetime.now(timezone.utc).date()
    dates = [(today + timedelta(days=i)).isoformat() for i in range(DAYS_AHEAD)]

    print(f"Scraping {len(CLUBS)} club(s) × {len(dates)} date(s) …")
    total_snapshots = 0

    for club in CLUBS:
        print(f"\n[{club['name']}]")
        for date in dates:
            print(f"  {date} … ", end="", flush=True)
            raw = fetch_availability(club["tenant_id"], date, club["sport_id"])
            if not raw:
                print("no data")
                continue
            snapshot = summarise(raw, club, date)
            save_snapshot(snapshot)
            print(
                f"{snapshot['num_courts']} courts, "
                f"{snapshot['available_slot_hours']}/{snapshot['total_possible_slot_hours']} avail slots, "
                f"occupancy {snapshot['occupancy_pct']}%"
            )
            total_snapshots += 1

    print(f"\nDone. {total_snapshots} snapshots saved to {DATA_DIR}/")


if __name__ == "__main__":
    main()
