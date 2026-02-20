import re
from typing import Any, Dict, List, Optional

def _clean(s: str) -> str:
    s = re.sub(r"<!--.*?-->", "", s or "", flags=re.DOTALL)
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()

def _find_blocks(text: str, start_token: str) -> List[str]:
    """Extracts blocks starting with start_token using brace-depth counting."""
    blocks: List[str] = []
    i = 0
    n = len(text)
    while True:
        start = text.find(start_token, i)
        if start == -1:
            break
        depth = 0
        j = start
        while j < n - 1:
            two = text[j:j+2]
            if two == "{{":
                depth += 1
                j += 2
                continue
            if two == "}}":
                depth -= 1
                j += 2
                if depth == 0:
                    blocks.append(text[start:j])
                    i = j
                    break
                continue
            j += 1
        else:
            break
    return blocks

def _find_match_blocks(wikitext: str) -> List[str]:
    blocks: List[str] = []
    for token in ("{{Match", "{{match"):
        blocks.extend(_find_blocks(wikitext, token))
    return blocks

def _parse_template_params(block: str) -> Dict[str, str]:
    """
    Parse top-level template params safely, ignoring nested {{...}} pipes.
    Returns a lower-cased key -> raw value map.
    """
    b = (block or "").strip()
    if b.startswith("{{"):
        b = b[2:]
    if b.endswith("}}"):
        b = b[:-2]

    parts: List[str] = []
    cur: List[str] = []
    depth = 0
    i = 0
    while i < len(b):
        two = b[i:i+2]
        if two == "{{":
            depth += 1
            cur.append(two)
            i += 2
            continue
        if two == "}}" and depth > 0:
            depth -= 1
            cur.append(two)
            i += 2
            continue
        if b[i] == "|" and depth == 0:
            parts.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(b[i])
        i += 1
    parts.append("".join(cur))

    params: Dict[str, str] = {}
    for p in parts[1:]:  # parts[0] is template name
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        key = _clean(k).lower()
        if key:
            params[key] = v.strip()
    return params

def _get_param(params: Dict[str, str], key: str) -> Optional[str]:
    v = params.get((key or "").lower())
    if v is None:
        return None
    c = _clean(v)
    return c or None

def _extract_team_name(team_opponent_value: str) -> Optional[str]:
    if not team_opponent_value:
        return None

    m = re.search(r"\{\{TeamOpponent\|[^{}]*?\bteam\s*=\s*([^}|]+)", team_opponent_value, re.IGNORECASE)
    if m:
        return _clean(m.group(1))

    m = re.search(r"\{\{TeamOpponent\|([^}|]+)", team_opponent_value, re.IGNORECASE)
    if m:
        return _clean(m.group(1))

    m = re.search(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", team_opponent_value)
    if m:
        return _clean(m.group(1))

    return _clean(team_opponent_value)

def _extract_maps(match_params: Dict[str, str]) -> List[Dict[str, Any]]:
    maps: List[Dict[str, Any]] = []
    for idx in range(1, 8):
        map_key = f"map{idx}"
        map_val = match_params.get(map_key)
        if not map_val:
            continue
        if "finished=skip" in map_val.replace(" ", "").lower():
            continue

        # Extract the {{Map ...}} block from map_val
        map_blocks = _find_blocks(map_val, "{{Map") + _find_blocks(map_val, "{{map")
        if not map_blocks:
            continue
        map_block = map_blocks[0]
        map_params = _parse_template_params(map_block)

        def five(prefix: str) -> List[Optional[str]]:
            return [
                _get_param(map_params, f"{prefix}1"),
                _get_param(map_params, f"{prefix}2"),
                _get_param(map_params, f"{prefix}3"),
                _get_param(map_params, f"{prefix}4"),
                _get_param(map_params, f"{prefix}5"),
            ]

        maps.append({
            "map": idx,
            "winner": _get_param(map_params, "winner"),
            "length": _get_param(map_params, "length"),
            "vod": _get_param(map_params, "vod"),
            "team1side": _get_param(map_params, "team1side"),
            "team2side": _get_param(map_params, "team2side"),
            "comment": _get_param(map_params, "comment"),
            "team1": {"picks": five("t1h"), "bans": five("t1b")},
            "team2": {"picks": five("t2h"), "bans": five("t2b")},
        })
    return maps

def parse_matches(wikitext: str) -> Dict[str, Any]:
    blocks = _find_match_blocks(wikitext)
    matches: List[Dict[str, Any]] = []

    for block in blocks:
        params = _parse_template_params(block)
        opp1_raw = _get_param(params, "opponent1") or ""
        opp2_raw = _get_param(params, "opponent2") or ""
        casters: List[str] = []
        for k in ("caster", "caster1", "caster2", "caster3", "caster4"):
            v = _get_param(params, k)
            if v and v not in casters:
                casters.append(v)

        m = {
            "bestof": _get_param(params, "bestof"),
            "date": _get_param(params, "date"),
            "casters": casters,
            "mvp": _get_param(params, "mvp"),
            "opponent1": _extract_team_name(opp1_raw),
            "opponent2": _extract_team_name(opp2_raw),
            "youtube": _get_param(params, "youtube"),
            "facebook": _get_param(params, "facebook"),
            "maps": _extract_maps(params),
        }
        if m["opponent1"] and m["opponent2"] and m["maps"]:
            matches.append(m)

    return {"found": bool(blocks), "matchesCount": len(matches), "matches": matches}
