import os
from typing import Any, Dict, Optional
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

SCRAPER_BASE_URL = os.getenv("SCRAPER_BASE_URL", "http://127.0.0.1:8080")
ROLE_LABELS = {
    "exp_lane": "Exp Lane",
    "jungle": "Jungle",
    "mid_lane": "Mid Lane",
    "gold_lane": "Gold Lane",
    "roam": "Roam",
}

app = FastAPI(title="Tier List UI", version="0.1.0")
APP_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


async def _fetch_tier_data(refresh: bool = False) -> Dict[str, Any]:
    params = {"refresh": "true"} if refresh else None
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(f"{SCRAPER_BASE_URL}/api/tier-list/m7", params=params)
        r.raise_for_status()
        return r.json()


@app.get("/health")
async def health() -> Dict[str, bool]:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    role: Optional[str] = Query(default=None),
    refresh: bool = Query(default=False),
):
    error: Optional[str] = None
    data: Dict[str, Any] = {}

    try:
        data = await _fetch_tier_data(refresh=refresh)
    except Exception as e:
        error = str(e)

    role_order = data.get("roleOrder", list(ROLE_LABELS.keys()))
    selected_role = role if role in role_order else (role_order[0] if role_order else "exp_lane")
    role_data = (data.get("roles") or {}).get(selected_role, {})

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "error": error,
            "scraper_base_url": SCRAPER_BASE_URL,
            "role_order": role_order,
            "role_labels": ROLE_LABELS,
            "selected_role": selected_role,
            "role_data": role_data,
            "generated_at": data.get("generatedAt"),
            "maps_analyzed": data.get("mapsAnalyzed"),
            "tier_rules": (data.get("scoring") or {}).get("tierRules", {}),
        },
    )
