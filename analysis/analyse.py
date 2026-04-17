"""
Occupancy Analysis
==================
Reads raw JSONL snapshots and produces:
  - analysis/summary_by_day.csv       — occupancy % per club per date
  - analysis/summary_by_weekday.csv   — avg occupancy % per weekday (Mon–Sun)
  - analysis/summary_by_hour.csv      — avg available courts per hour of day
  - analysis/summary_by_week.csv      — avg occupancy % per ISO week
  - analysis/dashboard_data.json      — single combined file for the dashboard

Run this after the scraper to refresh analytics:
  python analysis/analyse.py
"""

import json
import os
import csv
from datetime import datetime, date
from collections import defaultdict
from statistics import mean

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
OUT_DIR = os.path.join(os.path.dirname(__file__))
ALL_CLUBS_FILE = os.path.join(DATA_DIR, "all_clubs.jsonl")

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def load_snapshots() -> list[dict]:
    if not os.path.exists(ALL_CLUBS_FILE):
        print(f"No data file found at {ALL_CLUBS_FILE}. Run the scraper first.")
        return []
    snapshots = []
    with open(ALL_CLUBS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                snapshots.append(json.loads(line))
    return snapshots


def analyse(snapshots: list[dict]) -> dict:
    # ── Bucket data ───────────────────────────────────────────────────────────
    # For each (club, date) keep only the LATEST snapshot (most recent scrape)
    latest: dict[tuple, dict] = {}
    for s in snapshots:
        key = (s["club_slug"], s["date"])
        existing = latest.get(key)
        if existing is None or s["scraped_at"] > existing["scraped_at"]:
            latest[key] = s

    records = list(latest.values())

    # ── By day ────────────────────────────────────────────────────────────────
    by_day: dict[tuple, list] = defaultdict(list)
    for r in records:
        by_day[(r["club_name"], r["date"])].append(r["occupancy_pct"])

    summary_by_day = [
        {
            "club": club,
            "date": d,
            "weekday": WEEKDAY_NAMES[date.fromisoformat(d).weekday()],
            "iso_week": date.fromisoformat(d).isocalendar()[1],
            "year": date.fromisoformat(d).year,
            "occupancy_pct": round(mean(vals), 1),
        }
        for (club, d), vals in sorted(by_day.items())
    ]

    # ── By weekday ────────────────────────────────────────────────────────────
    weekday_buckets: dict[tuple, list] = defaultdict(list)
    for row in summary_by_day:
        weekday_buckets[(row["club"], row["weekday"])].append(row["occupancy_pct"])

    summary_by_weekday = [
        {
            "club": club,
            "weekday": wd,
            "weekday_index": WEEKDAY_NAMES.index(wd),
            "avg_occupancy_pct": round(mean(vals), 1),
            "sample_days": len(vals),
        }
        for (club, wd), vals in sorted(
            weekday_buckets.items(), key=lambda x: (x[0][0], WEEKDAY_NAMES.index(x[0][1]))
        )
    ]

    # ── By ISO week ───────────────────────────────────────────────────────────
    week_buckets: dict[tuple, list] = defaultdict(list)
    for row in summary_by_day:
        week_buckets[(row["club"], row["year"], row["iso_week"])].append(row["occupancy_pct"])

    summary_by_week = [
        {
            "club": club,
            "year": year,
            "iso_week": week,
            "week_label": f"{year}-W{week:02d}",
            "avg_occupancy_pct": round(mean(vals), 1),
            "sample_days": len(vals),
        }
        for (club, year, week), vals in sorted(week_buckets.items())
    ]

    # ── By hour ───────────────────────────────────────────────────────────────
    # How many courts are typically available at each hour
    hour_buckets: dict[tuple, list] = defaultdict(list)
    for r in records:
        for hour, count in r.get("hourly_available", {}).items():
            hour_buckets[(r["club_name"], hour)].append(count)

    # Also track court utilisation: (num_courts - available_at_hour) / num_courts
    hour_occ_buckets: dict[tuple, list] = defaultdict(list)
    for r in records:
        num_c = r.get("num_courts", 1) or 1
        for hour, count in r.get("hourly_available", {}).items():
            occ = round((num_c - min(count, num_c)) / num_c * 100, 1)
            hour_occ_buckets[(r["club_name"], hour)].append(occ)

    summary_by_hour = [
        {
            "club": club,
            "hour": h,
            "avg_available_courts": round(mean(counts), 2),
            "avg_occupancy_pct": round(mean(hour_occ_buckets.get((club, h), [0])), 1),
            "observations": len(counts),
        }
        for (club, h), counts in sorted(hour_buckets.items())
    ]

    # ── Club meta ─────────────────────────────────────────────────────────────
    clubs_seen = sorted({r["club_name"] for r in records})
    overall = {}
    for club in clubs_seen:
        club_records = [r for r in records if r["club_name"] == club]
        occs = [r["occupancy_pct"] for r in club_records]
        courts = [r["num_courts"] for r in club_records if r["num_courts"]]
        overall[club] = {
            "total_snapshots": len(club_records),
            "date_range": {
                "from": min(r["date"] for r in club_records),
                "to": max(r["date"] for r in club_records),
            },
            "avg_occupancy_pct": round(mean(occs), 1) if occs else None,
            "max_occupancy_pct": max(occs) if occs else None,
            "typical_courts": max(set(courts), key=courts.count) if courts else None,
        }

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "clubs": clubs_seen,
        "overall": overall,
        "by_day": summary_by_day,
        "by_weekday": summary_by_weekday,
        "by_week": summary_by_week,
        "by_hour": summary_by_hour,
    }


def write_csv(path: str, rows: list[dict]):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"  Wrote {len(rows)} rows → {path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    snapshots = load_snapshots()
    if not snapshots:
        return

    print(f"Loaded {len(snapshots)} raw snapshots.")
    result = analyse(snapshots)

    # JSON for dashboard
    dashboard_path = os.path.join(OUT_DIR, "dashboard_data.json")
    with open(dashboard_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"  Wrote → {dashboard_path}")

    # CSVs for easy inspection / import into Google Sheets
    write_csv(os.path.join(OUT_DIR, "summary_by_day.csv"), result["by_day"])
    write_csv(os.path.join(OUT_DIR, "summary_by_weekday.csv"), result["by_weekday"])
    write_csv(os.path.join(OUT_DIR, "summary_by_week.csv"), result["by_week"])
    write_csv(os.path.join(OUT_DIR, "summary_by_hour.csv"), result["by_hour"])

    print("\nOverall occupancy:")
    for club, stats in result["overall"].items():
        print(
            f"  {club}: avg {stats['avg_occupancy_pct']}%, "
            f"peak {stats['max_occupancy_pct']}%, "
            f"{stats['total_snapshots']} snapshots"
        )


if __name__ == "__main__":
    main()
