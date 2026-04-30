"""
Club configuration — edit these values to match the venue.
"""

import os

# ── API ───────────────────────────────────────────────────────────────────────
API_URL = "https://your-booking-api.example.com/availability"  # <-- replace

API_PARAMS_BASE = {
    "tenant_id": "b5a636e5-35d0-421b-b823-d857b8c9f088",
    "sport_id":  "PADEL",
    # "date" is added dynamically
}

# ── Turso database ────────────────────────────────────────────────────────────
# Locally: set these in a .env file or your shell.
# In GitHub Actions: set them as repository secrets (see README).
TURSO_URL   = os.environ.get("TURSO_URL",   "")   # libsql://your-db.turso.io
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")   # eyJ...

# ── Timezone ──────────────────────────────────────────────────────────────────
LOCAL_TZ = "Australia/Melbourne"

# ── Club opening hours (LOCAL time) ──────────────────────────────────────────
WEEKDAY_OPEN  = "06:00"
WEEKDAY_CLOSE = "21:00"
WEEKEND_OPEN  = "08:00"
WEEKEND_CLOSE = "18:00"

# ── Courts (resource_id → friendly name) ─────────────────────────────────────
COURT_NAMES = {
    "6a01f11b-3f57-4e81-bf0d-c1359d82caef": "Court 1",
    "4a5fb5fe-139f-40b0-85e7-634c705d7284": "Court 2",
    "e60b3a03-4c04-4021-a531-626d7d973135": "Court 3",
}
