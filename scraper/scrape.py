"""
Playtomic Padel Court Availability Scraper
==========================================
Fetches available slots from Playtomic API for configured clubs and stores
the raw data as JSON. Run via GitHub Actions on a schedule.

Occupancy Logic:
  - The API returns AVAILABLE slots (not booked ones)
  - Slot times from the API are in UTC — we convert to Melbourne local time
    before filtering. Because of this the API may return slots spanning two
    UTC dates for a single Melbourne date; we filter to only slots that fall
    within the requested Melbourne date and within that day's operating hours.
  - Occupancy = 1 - (available_slot_hours / total_possible_slot_hours)
"""

import json
import os
import sys
from datetime import datetime, timedelta, date as date_type, timezone
import urllib.request
import urllib.error

# Melbourne UTC offset: AEST = UTC+10, AEDT = UTC+11 (Oct–Apr)
# We use a fixed +10 for simplicity; adjust to +11 during daylight saving if needed.
# A production version could use the `zoneinfo` stdlib module (Python 3.9+).
MELBOURNE_UTC_OFFSET = timedelta(hours=10)  # change to 11 during AEDT if needed

# Per-weekday operating hours in Melbourne local time.
# weekday() → 0=Monday … 6=Sunday
# Format: (open_hour_inclusive, close_hour_exclusive)
# e.g. (8, 22) means slots from 08:00 up to but not including 22:00
DEFAULT_WEEKDAY_HOURS = {
    0: (8, 22),  # Monday
    1: (8, 22),  # Tuesday
    2: (8, 22),  # Wednesday
    3: (8, 22),  # Thursday
    4: (8, 22),  # Friday
    5: (8, 21),  # Saturday
    6: (8, 21),  # Sunday
}

# ── Club configuration ────────────────────────────────────────────────────────
CLUBS = [
    {
        "name": "Game4Padel Richmond",
        "slug": "game4padel-richmond",
        "tenant_id": "fd015cf7-b26b-4f7b-9a1f-8ed26f97ca05",
        "sport_id": "PADEL",
        # Override weekday hours here if this club differs from DEFAULT_WEEKDAY_HOURS.
        # If omitted, DEFAULT_WEEKDAY_HOURS is used.
        "weekday_hours": DEFAULT_WEEKDAY_HOURS,
    },
    # Add more clubs below:
    # {
    #     "name": "Padel Club Two",
    #     "slug": "padel-club-two",
    #     "tenant_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    #     "sport_id": "PADEL",
    #     "weekday_hours": DEFAULT_WEEKDAY_HOURS,
    # },
]

API_BASE = "https://playtomic.com/api/clubs/availability"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
DAYS_AHEAD = 7  # scrape today + next N days


def fetch_availability(tenant_id: str, date: str, sport_id: str) -> list:
    """Call the Playtomic availability API for one club on one UTC date."""
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


def utc_slot_to_melb_hour(start_date_str: str, start_time_str: str) -> tuple[str, int] | None:
    """
    Convert a UTC slot (date + time strings from API) to Melbourne local date + hour.
    Returns (melbourne_date_iso, melbourne_hour) or None if parsing fails.
    """
    try:
        dt_utc = datetime.strptime(
            f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
        dt_melb = dt_utc + MELBOURNE_UTC_OFFSET
        return dt_melb.date().isoformat(), dt_melb.hour
    except Exception:
        return None


def summarise(raw: list, club: dict, melb_date: str) -> dict:
    """
    Convert raw API response into a structured snapshot with occupancy metrics.

    raw may contain entries for two UTC dates (because Melbourne is UTC+10/+11).
    We convert every slot to Melbourne time and keep only those that:
      1. Fall on `melb_date` in Melbourne local time
      2. Start within the club's operating hours for that weekday
      3. Have duration == 60 (to avoid double-counting multi-duration options)
    """
    target_date = date_type.fromisoformat(melb_date)
    weekday = target_date.weekday()
    weekday_hours = club.get("weekday_hours", DEFAULT_WEEKDAY_HOURS)
    open_h, close_h = weekday_hours[weekday]
    total_hours_per_court = close_h - open_h

    # Build per-court available slots, filtered to Melbourne date + hours
    courts: dict[str, list[int]] = {}  # resource_id → list of local hours
    for entry in raw:
        rid = entry.get("resource_id", "unknown")
        entry_date = entry.get("start_date", "")  # UTC date from API
        for slot in entry.get("slots", []):
            if slot.get("duration") != 60:
                continue
            result = utc_slot_to_melb_hour(entry_date, slot["start_time"])
            if result is None:
                continue
            slot_melb_date, slot_melb_hour = result
            if slot_melb_date != melb_date:
                continue
            if not (open_h <= slot_melb_hour < close_h):
                continue
            if rid not in courts:
                courts[rid] = []
            courts[rid].append(slot_melb_hour)

    num_courts = len(courts)
    total_possible_slot_hours = num_courts * total_hours_per_court

    available_slot_hours = sum(len(hours) for hours in courts.values())

    occupancy_pct = 0.0
    if total_possible_slot_hours > 0:
        booked = max(0, total_possible_slot_hours - available_slot_hours)
        occupancy_pct = round(booked / total_possible_slot_hours * 100, 1)

    # Hourly breakdown in Melbourne time (HH:00 → available court count)
    hourly_available: dict[str, int] = {}
    for hours in courts.values():
        for h in hours:
            key = f"{h:02d}:00"
            hourly_available[key] = hourly_available.get(key, 0) + 1

    return {
        "club_name": club["name"],
        "club_slug": club["slug"],
        "date": melb_date,
        "weekday": target_date.strftime("%A"),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "num_courts": num_courts,
        "open_hour": open_h,
        "close_hour": close_h,
        "total_possible_slot_hours": total_possible_slot_hours,
        "available_slot_hours": available_slot_hours,
        "occupancy_pct": occupancy_pct,
        "hourly_available": dict(sorted(hourly_available.items())),
        "courts": {
            rid: {
                "available_1h_slots": len(hours),
                "slot_hours": sorted(hours),
            }
            for rid, hours in courts.items()
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
    # Work in Melbourne local time for the date list
    melb_now = datetime.now(timezone.utc) + MELBOURNE_UTC_OFFSET
    melb_dates = [(melb_now.date() + timedelta(days=i)).isoformat() for i in range(DAYS_AHEAD)]

    print(f"Scraping {len(CLUBS)} club(s) × {len(melb_dates)} Melbourne date(s) …")
    total_snapshots = 0

    for club in CLUBS:
        print(f"\n[{club['name']}]")
        for melb_date in melb_dates:
            print(f"  {melb_date} … ", end="", flush=True)

            # The API accepts the Melbourne date but already returns the relevant
            # cross-midnight slots from the prior UTC date automatically
            # (e.g. requesting 2026-04-20 returns Apr-19 22:00/23:00 UTC,
            # which are 08:00/09:00 AEST on Apr-20). One request is sufficient;
            # summarise() converts all returned slots to Melbourne time and filters.
            raw = fetch_availability(club["tenant_id"], melb_date, club["sport_id"])

            if not raw:
                print("no data")
                continue

            snapshot = summarise(raw, club, melb_date)
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