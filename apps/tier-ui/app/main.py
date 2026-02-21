import os
from typing import Any, Dict, Optional
from pathlib import Path
import json

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
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


async def _proxy_scraper_post(path: str, payload: Dict[str, Any], debug: bool = False) -> Dict[str, Any]:
    params = {"debug": "true"} if debug else None
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{SCRAPER_BASE_URL}{path}", json=payload, params=params)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise HTTPException(status_code=r.status_code, detail=detail)
        return r.json()


async def _proxy_scraper_get(path: str, refresh: bool = False) -> Dict[str, Any]:
    params = {"refresh": "true"} if refresh else None
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(f"{SCRAPER_BASE_URL}{path}", params=params)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise HTTPException(status_code=r.status_code, detail=detail)
        return r.json()


@app.get("/health")
async def health() -> Dict[str, bool]:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    role: Optional[str] = Query(default=None),
    refresh: bool = Query(default=False),
    engine: Optional[str] = Query(default=None),
):
    error: Optional[str] = None
    data: Dict[str, Any] = {}

    try:
        data = await _fetch_tier_data(refresh=refresh)
    except Exception as e:
        error = str(e)

    role_order = data.get("roleOrder", list(ROLE_LABELS.keys()))
    selected_role = role if role in role_order else (role_order[0] if role_order else "exp_lane")
    selected_engine = engine if engine in {"v1", "v2"} else "v2"
    role_data = (data.get("roles") or {}).get(selected_role, {})
    draft_payload = {
        "roleOrder": role_order,
        "roles": data.get("roles") or {},
        "scoring": data.get("scoring") or {},
        "generatedAt": data.get("generatedAt"),
        "mapsAnalyzed": data.get("mapsAnalyzed"),
        "defaultEngine": selected_engine,
        "apiBase": "",
    }

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "error": error,
            "scraper_base_url": SCRAPER_BASE_URL,
            "role_order": role_order,
            "role_labels": ROLE_LABELS,
            "selected_role": selected_role,
            "selected_engine": selected_engine,
            "role_data": role_data,
            "generated_at": data.get("generatedAt"),
            "maps_analyzed": data.get("mapsAnalyzed"),
            "tier_rules": (data.get("scoring") or {}).get("tierRules", {}),
            "draft_data_json": json.dumps(draft_payload, ensure_ascii=False),
        },
    )


@app.get("/api/draft/v2/meta")
async def draft_v2_meta(refresh: bool = Query(default=False)) -> Dict[str, Any]:
    return await _proxy_scraper_get("/api/draft/v2/meta", refresh=refresh)


@app.post("/api/draft/v2/assign")
async def draft_v2_assign(payload: Dict[str, Any], debug: bool = Query(default=False)) -> Dict[str, Any]:
    return await _proxy_scraper_post("/api/draft/v2/assign", payload, debug=debug)


@app.post("/api/draft/v2/recommend")
async def draft_v2_recommend(payload: Dict[str, Any], debug: bool = Query(default=False)) -> Dict[str, Any]:
    return await _proxy_scraper_post("/api/draft/v2/recommend", payload, debug=debug)
