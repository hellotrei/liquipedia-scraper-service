from bs4 import BeautifulSoup
import re
from typing import Any, Dict, List, Optional

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()

def _extract_year_headings(soup: BeautifulSoup) -> List[str]:
    years: List[str] = []

    # Modern Liquipedia headings (e.g. <h3 id="2026">2026</h3>)
    for h in soup.find_all(re.compile(r"^h[2-4]$")):
        candidates = [h.get("id"), _clean(h.get_text())]
        for t in candidates:
            if t and re.fullmatch(r"\d{4}", t):
                years.append(t)
                break

    # Legacy heading structure fallback
    for span in soup.select("span.mw-headline"):
        t = _clean(span.get_text())
        if re.fullmatch(r"\d{4}", t):
            years.append(t)

    return sorted(set(years))

def _find_year_heading(soup: BeautifulSoup, year: str):
    # Modern heading style
    h = soup.find(re.compile(r"^h[2-4]$"), id=year)
    if h:
        return h

    h = soup.find(
        re.compile(r"^h[2-4]$"),
        string=lambda x: x and _clean(x) == year,
    )
    if h:
        return h

    # Legacy heading style
    return soup.find("span", class_="mw-headline", string=lambda x: x and year in x)

def _extract_slug_from_href(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    m = re.match(r"^/mobilelegends/([^?#]+)", href)
    return m.group(1) if m else None

def _extract_latest_row_from_grid_table(grid_table: Any, target_year: str) -> Optional[Dict[str, Any]]:
    rows = grid_table.find_all(
        "div",
        class_=lambda c: c and "gridRow" in c,
        recursive=False,
    )
    if not rows:
        return None

    row = rows[0]
    cells = row.find_all("div", class_=lambda c: c and "gridCell" in c)
    raw_cols = [_clean(td.get_text(" ")) for td in cells if _clean(td.get_text(" "))]

    tournament_cell = row.find(
        "div",
        class_=lambda c: c and "gridCell" in c and "Tournament" in c,
    )

    tournament = None
    tournament_page = None
    if tournament_cell:
        for a in tournament_cell.find_all("a", href=True):
            text = _clean(a.get_text(" "))
            if not text:
                continue
            tournament = text
            tournament_page = _extract_slug_from_href(a.get("href"))
            break
        if not tournament:
            tournament = _clean(tournament_cell.get_text(" "))

    def cell_text(class_token: str) -> Optional[str]:
        c = row.find(
            "div",
            class_=lambda cls: cls and "gridCell" in cls and class_token in cls,
        )
        return _clean(c.get_text(" ")) if c else None

    data = {
        "year": target_year,
        "rawColumns": raw_cols,
        "tournament": tournament,
        "tournamentPage": tournament_page,
        "date": cell_text("Date"),
        "prizePool": cell_text("Prize"),
        "location": cell_text("Location"),
        "pNumber": cell_text("PlayerNumber"),
        "winner": cell_text("FirstPlace"),
        "runnerUp": cell_text("SecondPlace"),
    }
    return data if data.get("tournament") else None

def _extract_latest_row_from_legacy_table(table: Any, target_year: str) -> Optional[Dict[str, Any]]:
    first_row = None
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if tds:
            first_row = tr
            break

    if not first_row:
        return None

    cols = [_clean(td.get_text(" ")) for td in first_row.find_all("td")]

    tournament_page = None
    first_td = first_row.find("td")
    if first_td:
        for a in first_td.find_all("a", href=True):
            if _clean(a.get_text(" ")):
                tournament_page = _extract_slug_from_href(a.get("href"))
                break

    return {
        "year": target_year,
        "rawColumns": cols,
        "tournament": cols[0] if len(cols) > 0 else None,
        "tournamentPage": tournament_page,
        "date": cols[1] if len(cols) > 1 else None,
        "prizePool": cols[2] if len(cols) > 2 else None,
        "location": cols[3] if len(cols) > 3 else None,
        "pNumber": cols[4] if len(cols) > 4 else None,
        "winner": cols[5] if len(cols) > 5 else None,
        "runnerUp": cols[6] if len(cols) > 6 else None,
    }

def _is_break_heading(tag: Any) -> bool:
    if not getattr(tag, "name", None):
        return False

    if tag.name in ("h2", "h3", "h4"):
        txt = tag.get("id") or _clean(tag.get_text(" "))
        return bool(re.fullmatch(r"\d{4}", txt) or tag.name == "h2")

    if tag.name == "div" and "mw-heading" in (tag.get("class") or []):
        h = tag.find(re.compile(r"^h[2-4]$"), recursive=False)
        if not h:
            return False
        txt = h.get("id") or _clean(h.get_text(" "))
        return bool(re.fullmatch(r"\d{4}", txt) or h.name == "h2")

    return False

def extract_latest_s_tier(html: str, prefer_year: str = "2026") -> Dict[str, Any]:
    """Return the first data row under prefer_year if exists, else under latest year."""
    soup = BeautifulSoup(html, "html.parser")
    years = _extract_year_headings(soup)

    if not years:
        return {"found": False, "reason": "No year headings found", "data": None}

    target_year = prefer_year if prefer_year in years else max(years)

    headline = _find_year_heading(soup, target_year)
    if not headline:
        return {"found": False, "reason": f"Year heading {target_year} not found", "data": None}

    start_node = headline.parent if (headline.parent and headline.parent.name == "div" and "mw-heading" in (headline.parent.get("class") or [])) else headline

    for sib in start_node.next_siblings:
        if not getattr(sib, "name", None):
            continue
        if _is_break_heading(sib):
            break

        if sib.name == "div" and "gridTable" in (sib.get("class") or []):
            data = _extract_latest_row_from_grid_table(sib, target_year)
            if data:
                return {"found": True, "data": data}

        for grid in sib.find_all("div", class_=lambda c: c and "gridTable" in c):
            data = _extract_latest_row_from_grid_table(grid, target_year)
            if data:
                return {"found": True, "data": data}

        if sib.name == "table":
            data = _extract_latest_row_from_legacy_table(sib, target_year)
            if data:
                return {"found": True, "data": data}

        for table in sib.find_all("table"):
            data = _extract_latest_row_from_legacy_table(table, target_year)
            if data:
                return {"found": True, "data": data}

    return {"found": False, "reason": f"No data rows found in section {target_year}", "data": None}

def liquipedia_page_slug_from_title(title: str) -> Optional[str]:
    """Best-effort conversion: 'M7 World Championship' -> 'M7_World_Championship'"""
    if not title:
        return None
    t = _clean(title)
    # remove footnote-ish brackets if any (rare)
    t = re.sub(r"\[.*?\]", "", t).strip()
    # Liquipedia uses underscores for spaces
    t = t.replace(" ", "_")
    return t or None
