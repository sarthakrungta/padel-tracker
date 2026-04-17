# 🎾 Padel Court Occupancy Tracker

Automatically scrapes Playtomic availability data for Melbourne padel clubs and tracks occupancy over time — all for free using GitHub Actions.

## How it works

```
GitHub Actions (every 2h)
    │
    ▼
scraper/scrape.py          ← hits Playtomic API, saves raw JSONL snapshots
    │
    ▼
data/raw/<club>.jsonl      ← append-only log of every snapshot
    │
    ▼
analysis/analyse.py        ← aggregates into day / weekday / hour / week summaries
    │
    ▼
analysis/dashboard_data.json   ← consumed by the dashboard
analysis/summary_*.csv         ← easy to import into Google Sheets
```

### Key insight
The Playtomic API returns **available** slots, not booked ones. So:

```
Occupancy % = 1 − (available 1-hour slots / total possible 1-hour slots)
```

Total possible slots = courts × operating hours per day.

## Setup (5 minutes)

### 1. Fork / clone this repo
```bash
git clone https://github.com/YOUR-USERNAME/padel-tracker.git
cd padel-tracker
```

### 2. Add your clubs
Edit `scraper/scrape.py` — the `CLUBS` list at the top:

```python
CLUBS = [
    {
        "name": "Game4Padel Richmond",
        "slug": "game4padel-richmond",
        "tenant_id": "fd015cf7-b26b-4f7b-9a1f-8ed26f97ca05",
        "sport_id": "PADEL",
        "open_hour": 7,
        "close_hour": 22,
    },
    # Paste more clubs here
]
```

**Finding a club's `tenant_id`:**
1. Open the club's Playtomic page in Chrome
2. Open DevTools → Network tab
3. Filter by `availability`
4. The URL will contain `tenant_id=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

### 3. Enable GitHub Actions
Push to GitHub — Actions will run automatically on the schedule.

You can also trigger manually: **Actions → Scrape Padel Availability → Run workflow**

### 4. GitHub Actions permissions
Go to your repo → **Settings → Actions → General → Workflow permissions**
Set to **Read and write permissions** (needed to commit scraped data).

## Local development

```bash
# Run scraper
python scraper/scrape.py

# Run analysis
python analysis/analyse.py

# No external dependencies — pure Python standard library only!
```

## File structure

```
padel-tracker/
├── .github/
│   └── workflows/
│       └── scrape.yml          ← GitHub Actions schedule
├── scraper/
│   └── scrape.py               ← Playtomic API scraper
├── analysis/
│   ├── analyse.py              ← Aggregation & metrics
│   ├── dashboard_data.json     ← Generated: dashboard input
│   ├── summary_by_day.csv      ← Generated: daily occupancy
│   ├── summary_by_weekday.csv  ← Generated: Mon–Sun averages
│   ├── summary_by_hour.csv     ← Generated: hourly heat-map data
│   └── summary_by_week.csv     ← Generated: weekly trends
├── data/
│   └── raw/
│       ├── all_clubs.jsonl     ← All snapshots (append-only)
│       └── <club-slug>.jsonl   ← Per-club snapshots
└── README.md
```

## Viewing the dashboard

Open `dashboard/index.html` in any browser — it reads from `analysis/dashboard_data.json`.

For a live version, enable GitHub Pages on the `main` branch and point it to the root.

## Cost

**$0** — GitHub Actions free tier gives 2,000 minutes/month. Each scrape run takes ~30 seconds. Running every 2 hours = 12 runs/day × 0.5 min = 6 min/day = ~180 min/month. Well within the free tier.

## Adding more clubs

1. Find the `tenant_id` (see step 2 above)
2. Add an entry to the `CLUBS` list in `scraper/scrape.py`
3. Commit and push — the next scheduled run will include the new club

## Data format

### Raw snapshot (`data/raw/<club>.jsonl`)
One JSON object per line:
```json
{
  "club_name": "Game4Padel Richmond",
  "club_slug": "game4padel-richmond",
  "date": "2026-04-18",
  "scraped_at": "2026-04-18T06:00:12.345Z",
  "num_courts": 6,
  "total_possible_slot_hours": 90,
  "available_slot_hours": 42,
  "occupancy_pct": 53.3,
  "hourly_available": {"07:00": 5, "08:00": 3, "09:00": 1},
  "courts": {
    "fd015cf7-...": {"available_1h_slots": 7, "slot_times": ["07:00","08:00"]}
  }
}
```
