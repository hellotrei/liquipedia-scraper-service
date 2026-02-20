#!/usr/bin/env python3
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROLE_ORDER = ["exp_lane", "jungle", "mid_lane", "gold_lane", "roam"]
TIER_RULES = {
    "SS": "Best heroes. Must ban or 1st pick",
    "S": "Strong heroes. 1st pick or 2nd pick",
    "A": "Good heroes. Safe picks, work well in teams",
    "B": "Okay heroes. Useful if played well or for special plans",
    "C": "Weaker heroes. Only good in very specific situations",
    "D": "Weakest heroes. Better to pick others",
}
WEIGHTS = {
    "pick_and_win": 0.50,
    "pick": 0.40,
    "ban": 0.10,
}


def _clean_hero_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    value = str(name)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("\xa0", " ").strip().lower()
    value = re.sub(r"\s+", " ", value)
    if not value or value in {"-", "none", "n/a", "unknown"}:
        return None
    return value


def _norm(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return value / max_value


def _role_tier_by_rank(index: int, total: int) -> str:
    # Percentile buckets (high to low): SS, S, A, B, C, D
    p = (index + 1) / max(total, 1)
    if p <= 0.10:
        return "SS"
    if p <= 0.28:
        return "S"
    if p <= 0.52:
        return "A"
    if p <= 0.76:
        return "B"
    if p <= 0.90:
        return "C"
    return "D"


def _load_matches(path: Path) -> List[dict]:
    obj = json.loads(path.read_text())
    return obj.get("matches", [])


def build_tier_list(source_files: List[Path]) -> dict:
    role_stats: Dict[str, Dict[str, dict]] = {r: defaultdict(lambda: {"pick_count": 0, "pick_win_count": 0}) for r in ROLE_ORDER}
    role_matchups: Dict[str, Dict[str, Dict[str, dict]]] = {r: defaultdict(lambda: defaultdict(lambda: {"encounters": 0, "wins": 0, "losses": 0})) for r in ROLE_ORDER}
    global_bans = defaultdict(int)
    map_count = 0

    for source in source_files:
        for match in _load_matches(source):
            for mp in match.get("maps", []):
                map_count += 1
                winner = str(mp.get("winner", "")).strip()
                t1 = mp.get("team1", {})
                t2 = mp.get("team2", {})
                t1_picks = t1.get("picks", [])
                t2_picks = t2.get("picks", [])
                t1_bans = t1.get("bans", [])
                t2_bans = t2.get("bans", [])

                for ban in (t1_bans + t2_bans):
                    h = _clean_hero_name(ban)
                    if h:
                        global_bans[h] += 1

                for i, role in enumerate(ROLE_ORDER):
                    h1 = _clean_hero_name(t1_picks[i] if i < len(t1_picks) else None)
                    h2 = _clean_hero_name(t2_picks[i] if i < len(t2_picks) else None)

                    if h1:
                        role_stats[role][h1]["pick_count"] += 1
                        if winner == "1":
                            role_stats[role][h1]["pick_win_count"] += 1
                    if h2:
                        role_stats[role][h2]["pick_count"] += 1
                        if winner == "2":
                            role_stats[role][h2]["pick_win_count"] += 1

                    if h1 and h2:
                        role_matchups[role][h1][h2]["encounters"] += 1
                        role_matchups[role][h2][h1]["encounters"] += 1
                        if winner == "1":
                            role_matchups[role][h1][h2]["wins"] += 1
                            role_matchups[role][h2][h1]["losses"] += 1
                        elif winner == "2":
                            role_matchups[role][h2][h1]["wins"] += 1
                            role_matchups[role][h1][h2]["losses"] += 1

    roles_out: Dict[str, dict] = {}
    for role in ROLE_ORDER:
        heroes = []
        role_map = role_stats[role]
        max_pick_win = max((v["pick_win_count"] for v in role_map.values()), default=0)
        max_pick = max((v["pick_count"] for v in role_map.values()), default=0)
        max_ban = max((global_bans.get(h, 0) for h in role_map.keys()), default=0)

        for hero, stats in role_map.items():
            pick_wins = stats["pick_win_count"]
            picks = stats["pick_count"]
            bans = global_bans.get(hero, 0)
            score = (
                WEIGHTS["pick_and_win"] * _norm(pick_wins, max_pick_win)
                + WEIGHTS["pick"] * _norm(picks, max_pick)
                + WEIGHTS["ban"] * _norm(bans, max_ban)
            )

            lane_matchups = role_matchups[role].get(hero, {})
            countered_by = []
            strong_against = []
            for opp, m in lane_matchups.items():
                enc = m["encounters"]
                if enc <= 0:
                    continue
                wr = m["wins"] / enc
                lr = m["losses"] / enc
                if lr > 0:
                    countered_by.append({
                        "hero": opp,
                        "encounters": enc,
                        "opponentWinRate": round(lr, 4),
                    })
                if wr > 0:
                    strong_against.append({
                        "hero": opp,
                        "encounters": enc,
                        "winRate": round(wr, 4),
                    })

            countered_by.sort(key=lambda x: (x["opponentWinRate"], x["encounters"]), reverse=True)
            strong_against.sort(key=lambda x: (x["winRate"], x["encounters"]), reverse=True)

            heroes.append({
                "hero": hero,
                "score": round(score, 6),
                "stats": {
                    "pickWinCount": pick_wins,
                    "pickCount": picks,
                    "banCount": bans,
                    "winRate": round((pick_wins / picks), 4) if picks else 0.0,
                },
                "counters": {
                    "counteredBy": countered_by[:5],
                    "strongAgainst": strong_against[:5],
                },
            })

        heroes.sort(
            key=lambda x: (
                x["score"],
                x["stats"]["pickWinCount"],
                x["stats"]["pickCount"],
                x["stats"]["banCount"],
            ),
            reverse=True,
        )

        for idx, entry in enumerate(heroes):
            tier = _role_tier_by_rank(idx, len(heroes))
            entry["tier"] = tier
            entry["recommendation"] = TIER_RULES[tier]

        tiers = {k: [] for k in ["SS", "S", "A", "B", "C", "D"]}
        for entry in heroes:
            tiers[entry["tier"]].append(entry["hero"])

        roles_out[role] = {
            "heroesCount": len(heroes),
            "tiers": tiers,
            "heroDetails": heroes,
        }

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": [str(p.name) for p in source_files],
        "mapsAnalyzed": map_count,
        "roleOrder": ROLE_ORDER,
        "scoring": {
            "formula": "score = 0.50*norm(pick_and_win) + 0.40*norm(pick) + 0.10*norm(ban)",
            "weights": WEIGHTS,
            "tierRules": TIER_RULES,
        },
        "roles": roles_out,
    }


def main() -> None:
    root = Path(__file__).resolve().parent
    source_files = [
        root / "swiss_stage_matches.json",
        root / "knockout_stage_matches.json",
    ]
    for p in source_files:
        if not p.exists():
            raise FileNotFoundError(f"Missing source file: {p}")

    out = build_tier_list(source_files)
    out_path = root / "hero_tier_list.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"Generated: {out_path}")


if __name__ == "__main__":
    main()
