import httpx
from cachetools import TTLCache

BASE_API = "https://liquipedia.net/mobilelegends/api.php"

# Cache: avoid hammering Liquipedia
_cache = TTLCache(maxsize=256, ttl=60)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LiquipediaScraperService/0.2; +https://example.local)",
    "Accept": "application/json,text/html,*/*",
}

class LiquipediaClient:
    def __init__(self, timeout_s: float = 30.0):
        self._client = httpx.AsyncClient(
            timeout=timeout_s,
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
        )

    async def close(self):
        await self._client.aclose()

    async def parse_page_html(self, page: str) -> str:
        cache_key = f"html:{page}"
        if cache_key in _cache:
            return _cache[cache_key]

        params = {"action": "parse", "page": page, "prop": "text", "format": "json"}
        r = await self._client.get(BASE_API, params=params)
        r.raise_for_status()
        data = r.json()
        html = data["parse"]["text"]["*"]
        _cache[cache_key] = html
        return html

    async def parse_page_wikitext(self, page: str) -> str:
        cache_key = f"wikitext:{page}"
        if cache_key in _cache:
            return _cache[cache_key]

        params = {"action": "parse", "page": page, "prop": "wikitext", "format": "json"}
        r = await self._client.get(BASE_API, params=params)
        r.raise_for_status()
        data = r.json()
        wikitext = data["parse"]["wikitext"]["*"]
        _cache[cache_key] = wikitext
        return wikitext
