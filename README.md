# Liquipedia Scraper Service (Mobile Legends)

## What it does

### 1) Latest S-Tier tournament
- `GET /api/s-tier/latest`
  - Fetches `S-Tier_Tournaments` and returns the *latest* tournament row.
  - Preference order:
    1. If year **2026** exists, take the **first data row** under 2026.
    2. Otherwise take the **first data row** under the **latest year** found.

### 2) Matches (hero pick/ban per map)
- `GET /api/tournament/{page}/matches`
  - Fetches `{page}` wikitext and parses `{{Match}}` + `{{Map}}` blocks into JSON.

- `GET /api/s-tier/latest/matches`
  - Fetches latest tournament via `S-Tier_Tournaments`, converts the tournament name to a Liquipedia page slug,
    then returns parsed matches for that page (best-effort).

### 3) Convenience shortcut for M7
- `GET /api/m7/matches` (same as calling `/api/tournament/M7_World_Championship/matches`)

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install fastapi uvicorn httpx beautifulsoup4 cachetools
uvicorn app.main:app --reload --port 8080
```

Open:
- http://127.0.0.1:8080/docs

## Notes
- Uses MediaWiki API: `https://liquipedia.net/mobilelegends/api.php`
- Adds `User-Agent` + short in-memory cache to reduce rate-limit issues.
- Wikitext parsing is best-effort (Liquipedia templates can evolve).
