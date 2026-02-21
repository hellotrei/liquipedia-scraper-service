from fastapi import FastAPI, HTTPException
from app.liquipedia_client import LiquipediaClient
from app.s_tier import extract_latest_s_tier, liquipedia_page_slug_from_title
from app.m7_parser import parse_matches
from app.draft_v2 import DraftV2ConfigError, get_draft_v2_meta
from app.draft_v2_engine import (
    DraftV2RequestError,
    assign_from_payload,
    recommend_from_payload,
)
from pathlib import Path
import json

app = FastAPI(title="Liquipedia Scraper Service", version="0.2.0")
client = LiquipediaClient()

@app.on_event("shutdown")
async def shutdown_event():
    await client.close()

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/api/s-tier/latest")
async def latest_s_tier():
    html = await client.parse_page_html("S-Tier_Tournaments")
    return extract_latest_s_tier(html, prefer_year="2026")

@app.get("/api/tournament/{page:path}/matches")
async def tournament_matches(page: str):
    # page is expected like "M7_World_Championship"
    try:
        wikitext = await client.parse_page_wikitext(page)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed fetching page '{page}': {str(e)}")
    return {
        "page": page,
        **parse_matches(wikitext),
    }

@app.get("/api/m7/matches")
async def m7_matches():
    wikitext = await client.parse_page_wikitext("M7_World_Championship")
    return {"page": "M7_World_Championship", **parse_matches(wikitext)}

@app.get("/api/s-tier/latest/matches")
async def latest_s_tier_matches():
    html = await client.parse_page_html("S-Tier_Tournaments")
    latest = extract_latest_s_tier(html, prefer_year="2026")
    if not latest.get("found"):
        raise HTTPException(status_code=404, detail="Latest S-Tier tournament not found")

    latest_data = latest.get("data") or {}
    title = latest_data.get("tournament")
    page = latest_data.get("tournamentPage") or liquipedia_page_slug_from_title(title or "")
    if not page:
        raise HTTPException(status_code=422, detail="Could not derive Liquipedia page slug from tournament title")

    try:
        wikitext = await client.parse_page_wikitext(page)
    except Exception as e:
        # Liquipedia sometimes uses different page titles than the visible tournament name.
        # Return helpful payload so you can decide next mapping in Codex.
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Failed fetching derived page. Tournament title might not match page slug.",
                "tournamentTitle": title,
                "derivedPage": page,
                "slugSource": "link" if latest_data.get("tournamentPage") else "title_to_underscore",
                "error": str(e),
            },
        )

    return {
        "latestTournament": latest_data,
        "derivedPage": page,
        "slugSource": "link" if latest_data.get("tournamentPage") else "title_to_underscore",
        **parse_matches(wikitext),
    }

@app.get("/api/tier-list/m7")
async def m7_tier_list(refresh: bool = False):
    root = Path(__file__).resolve().parent.parent
    out_path = root / "hero_tier_list.json"

    if refresh or not out_path.exists():
        source_files = [
            root / "swiss_stage_matches.json",
            root / "knockout_stage_matches.json",
        ]
        missing = [p.name for p in source_files if not p.exists()]
        if missing:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "Source JSON not found. Generate/fetch Swiss and Knockout data first.",
                    "missingFiles": missing,
                },
            )

        try:
            from build_hero_tier_list import build_tier_list

            data = build_tier_list(source_files)
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed rebuilding tier list: {str(e)}")

    try:
        return json.loads(out_path.read_text())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed reading tier list file: {str(e)}")


@app.get("/api/draft/v2/meta")
async def draft_v2_meta(refresh: bool = False):
    try:
        return get_draft_v2_meta(refresh=refresh)
    except DraftV2ConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/draft/v2/assign")
async def draft_v2_assign(payload: dict, debug: bool = False):
    try:
        return assign_from_payload(payload or {}, debug=debug)
    except (DraftV2ConfigError, DraftV2RequestError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed generating assignment: {str(e)}")


@app.post("/api/draft/v2/recommend")
async def draft_v2_recommend(payload: dict, debug: bool = False):
    try:
        return recommend_from_payload(payload or {}, debug=debug)
    except (DraftV2ConfigError, DraftV2RequestError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed generating recommendation: {str(e)}")
