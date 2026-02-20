from fastapi import FastAPI, HTTPException
from app.liquipedia_client import LiquipediaClient
from app.s_tier import extract_latest_s_tier, liquipedia_page_slug_from_title
from app.m7_parser import parse_matches

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
