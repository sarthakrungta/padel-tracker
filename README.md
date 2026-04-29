# Padel Club Occupancy Scraper

Polls a padel club booking API every 30 minutes via **GitHub Actions**, infers bookings from slots that disappear between snapshots, and stores everything in **Turso** (free hosted SQLite).

---

## How it works

1. GitHub Actions runs `poll.py` every 30 minutes
2. `poll.py` checks if we're within club opening hours — if not, it exits immediately (most overnight runs are instant no-ops)
3. If within hours: fetch the API, diff against what was previously seen in the DB
4. Any slot that **vanished** since the last snapshot → recorded as a probable booking
5. Once a slot's start time passes, the booking is **confirmed** (rules out cancellation ambiguity)

---

## Setup — step by step

### 1. Create a free Turso database

```bash
# Install the Turso CLI
curl -sSfL https://get.tur.so/install.sh | bash

# Log in (creates a free account)
turso auth login

# Create a database
turso db create padel-scraper

# Get the URL and a token — copy both, you'll need them in step 3
turso db show padel-scraper --url
turso db tokens create padel-scraper
```

The URL looks like: `libsql://padel-scraper-yourname.turso.io`
The token looks like: `eyJhbGci...` (long JWT string)

---

### 2. Fork / push this repo to GitHub

Create a new GitHub repo and push this folder to it.

---

### 3. Add secrets to GitHub

In your repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name   | Value                                      |
|---------------|--------------------------------------------|
| `TURSO_URL`   | `libsql://padel-scraper-yourname.turso.io` |
| `TURSO_TOKEN` | `eyJhbGci...`                              |

---

### 4. Edit config.py

- Set `API_URL` to the real booking endpoint
- Double-check `API_PARAMS_BASE` (tenant_id, sport_id)
- Update `COURT_NAMES` if you know the mapping

Commit and push — GitHub Actions will pick up the new config automatically.

---

### 5. Initialise the database (one-time)

Run this once from your laptop to create the tables:

```bash
export TURSO_URL="libsql://padel-scraper-yourname.turso.io"
export TURSO_TOKEN="eyJhbGci..."
python db.py
```

---

### 6. Let it run

The workflow at `.github/workflows/poll.yml` fires every 30 minutes automatically. You can watch runs in the **Actions** tab of your repo.

To trigger a manual run (e.g. to test or force a specific date):
- Actions tab → "Padel Poll" → "Run workflow"
- Optionally enter a date like `2026-04-29` to force that date regardless of time

---

## Analytics (run locally)

```bash
export TURSO_URL="libsql://padel-scraper-yourname.turso.io"
export TURSO_TOKEN="eyJhbGci..."

python analytics.py                    # all dates collected so far
python analytics.py --date 2026-04-29  # detail for one day
python analytics.py --weekly           # weekly averages
python analytics.py --confirmed-only   # exclude slots whose start time hasn't passed yet
```

---

## Seeding historical data

If you have past API responses saved, inject them:

```bash
python backfill.py --date 2026-04-29 --file my_response.json
python backfill.py --date 2026-04-29 --json '[{"resource_id":...}]' --time 2026-04-29T07:35:00Z
```

The `--time` flag sets the snapshot timestamp in UTC — use the actual time you made the call.

---

## File overview

| File | Purpose |
|------|---------|
| `config.py` | Club settings, API params, timezone, court names |
| `db.py` | Turso/libSQL database layer |
| `fetcher.py` | API fetch + diff engine |
| `poll.py` | Single-run entrypoint called by GitHub Actions |
| `analytics.py` | Local occupancy reports |
| `backfill.py` | Inject historical snapshots |
| `.github/workflows/poll.yml` | The cron schedule |

---

## Confirmed vs unconfirmed bookings

Analytics output shows `✓` (confirmed) or `?` (unconfirmed):

- **`?`** — slot disappeared from the API but its scheduled start time hasn't passed yet. *Could* theoretically be a cancellation that gets re-released before the session starts.
- **`✓`** — slot's start time has passed. It can never reappear, so the booking is certain.

Use `--confirmed-only` for the conservative, high-confidence numbers.
