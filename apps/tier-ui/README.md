# Tier UI (SSR)

Simple server-side rendered UI for the M7 hero tier list.

## Run

```bash
cd /Users/treido/Desktop/liquipedia-scraper-service
source .venv/bin/activate
pip install -U fastapi uvicorn httpx jinja2

cd apps/tier-ui
export SCRAPER_BASE_URL=http://127.0.0.1:8080
uvicorn app.main:app --reload --port 8090
```

Open:
- http://127.0.0.1:8090

## Draft Master Engine Mode

- `/?engine=v2` -> engine fleksibel (role-agnostic, rekomendasi dari backend `/api/draft/v2/recommend`)
- `/?engine=v1` -> engine lama (role order)

UI juga menyediakan proxy endpoint ke scraper service:

- `GET /api/draft/v2/meta`
- `POST /api/draft/v2/assign`
- `POST /api/draft/v2/recommend`
