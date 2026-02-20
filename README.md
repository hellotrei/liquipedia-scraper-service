# Liquipedia Monorepo (Python-only)

Monorepo berisi 2 app:

- `apps/scraper-service`: FastAPI service untuk scraping + parsing match + generate tier list JSON
- `apps/tier-ui`: FastAPI + Jinja2 SSR UI untuk menampilkan tier list

## Struktur

```text
apps/
  scraper-service/
    app/
    build_hero_tier_list.py
    swiss_stage_matches.json
    knockout_stage_matches.json
    hero_tier_list.json
  tier-ui/
    app/
      templates/
      static/
packages/
  shared/
```

## Setup Local

```bash
cd /Users/treido/Desktop/liquipedia-scraper-service
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install fastapi uvicorn httpx beautifulsoup4 cachetools jinja2
```

## Run Scraper Service

```bash
cd /Users/treido/Desktop/liquipedia-scraper-service/apps/scraper-service
uvicorn app.main:app --reload --port 8080
```

Open docs:
- http://127.0.0.1:8080/docs

## Run UI Service (SSR)

```bash
cd /Users/treido/Desktop/liquipedia-scraper-service/apps/tier-ui
export SCRAPER_BASE_URL=http://127.0.0.1:8080
uvicorn app.main:app --reload --port 8090
```

Open UI:
- http://127.0.0.1:8090

## Run Both Services (One Command)

```bash
cd /Users/treido/Desktop/liquipedia-scraper-service
make run-all
```

Stop both: `Ctrl+C`

## Endpoint penting scraper

- `GET /api/tournament/{page}/matches`
- `GET /api/tournament/M7_World_Championship/Swiss_Stage/matches`
- `GET /api/tournament/M7_World_Championship/Knockout_Stage/matches`
- `GET /api/tier-list/m7`
- `GET /api/tier-list/m7?refresh=true`
