#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.draft_v2 import DRAFT_V2_SEQUENCE
from app.draft_v2_engine import recommend_from_payload


ROLE_ORDER = ["exp_lane", "jungle", "mid_lane", "gold_lane", "roam"]
TIER_WEIGHTS = {"SS": 30, "S": 22, "A": 14, "B": 8, "C": 3, "D": 0}


def _clean_hero(value: Any) -> Optional[str]:
    x = str(value or "").strip().lower()
    if not x or x in {"-", "none", "unknown", "n/a"}:
        return None
    return x


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _workspace_root() -> Path:
    return _repo_root().parent.parent


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def _load_maps(limit_maps: int) -> List[Dict[str, Any]]:
    root = _repo_root()
    src_files = [
        root / "swiss_stage_matches.json",
        root / "knockout_stage_matches.json",
    ]
    out: List[Dict[str, Any]] = []
    for src in src_files:
        data = _load_json(src)
        for match in data.get("matches", []):
            for mp in match.get("maps", []):
                t1 = mp.get("team1") or {}
                t2 = mp.get("team2") or {}
                ally_picks = [_clean_hero(h) for h in (t1.get("picks") or [])]
                enemy_picks = [_clean_hero(h) for h in (t2.get("picks") or [])]
                ally_bans = [_clean_hero(h) for h in (t1.get("bans") or [])]
                enemy_bans = [_clean_hero(h) for h in (t2.get("bans") or [])]

                ally_picks = [h for h in ally_picks if h][:5]
                enemy_picks = [h for h in enemy_picks if h][:5]
                ally_bans = [h for h in ally_bans if h][:5]
                enemy_bans = [h for h in enemy_bans if h][:5]
                if len(ally_picks) < 5 or len(enemy_picks) < 5:
                    continue

                out.append(
                    {
                        "source": src.name,
                        "map": mp.get("map"),
                        "allyPicks": ally_picks,
                        "enemyPicks": enemy_picks,
                        "allyBans": ally_bans,
                        "enemyBans": enemy_bans,
                    }
                )
                if len(out) >= limit_maps:
                    return out
    return out


def _build_tier_index(tier_json: Dict[str, Any]) -> Dict[str, Any]:
    roles = tier_json.get("roles") or {}
    by_role: Dict[str, Dict[str, Any]] = {}
    best_global: Dict[str, Dict[str, Any]] = {}
    for role, role_data in roles.items():
        role_map: Dict[str, Any] = {}
        for h in (role_data or {}).get("heroDetails", []):
            hero = _clean_hero(h.get("hero"))
            if not hero:
                continue
            role_map[hero] = h
            prev = best_global.get(hero)
            if not prev or float(h.get("score") or 0.0) > float(prev.get("score") or 0.0):
                best_global[hero] = {"role": role, **h}
        by_role[role] = role_map
    return {"byRole": by_role, "bestGlobal": best_global}


def _counter_map(hero_obj: Dict[str, Any], key_field: str, value_field: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for x in ((hero_obj.get("counters") or {}).get(key_field) or []):
        h = _clean_hero(x.get("hero"))
        if not h:
            continue
        out[h] = float(x.get(value_field) or 0.0)
    return out


@dataclass
class V1State:
    turn_index: int
    action_progress: int
    picks: Dict[str, Dict[str, Optional[str]]]
    bans: Dict[str, List[str]]


@dataclass
class V2State:
    turn_index: int
    action_progress: int
    picks: Dict[str, List[str]]
    bans: Dict[str, List[str]]


def _pick_count_v1(st: V1State, side: str) -> int:
    return sum(1 for r in ROLE_ORDER if st.picks[side].get(r))


def _pick_count_v2(st: V2State, side: str) -> int:
    return len(st.picks[side])


def _current_action(turn_index: int, action_progress: int, pick_count_fn, side_picker) -> Tuple[int, int, Optional[Dict[str, Any]]]:
    idx = int(turn_index)
    prog = int(action_progress)
    while idx < len(DRAFT_V2_SEQUENCE):
        act = DRAFT_V2_SEQUENCE[idx]
        limit = int(act["count"])
        if act["type"] == "pick":
            side = side_picker(act)
            remaining = 5 - pick_count_fn(side)
            limit = min(limit, max(remaining + prog, 0))
        if limit <= 0 or prog >= limit:
            idx += 1
            prog = 0
            continue
        return idx, prog, {**act, "limit": limit}
    return idx, prog, None


def _v1_get_action(st: V1State) -> Tuple[int, int, Optional[Dict[str, Any]]]:
    return _current_action(
        st.turn_index,
        st.action_progress,
        lambda s: _pick_count_v1(st, s),
        lambda act: act["side"],
    )


def _v2_get_action(st: V2State) -> Tuple[int, int, Optional[Dict[str, Any]]]:
    return _current_action(
        st.turn_index,
        st.action_progress,
        lambda s: _pick_count_v2(st, s),
        lambda act: act["side"],
    )


def _v1_next_open_role(st: V1State, side: str) -> Optional[str]:
    for r in ROLE_ORDER:
        if not st.picks[side].get(r):
            return r
    return None


def _is_picked_v1(st: V1State, hero: str) -> bool:
    for side in ("ally", "enemy"):
        for r in ROLE_ORDER:
            if st.picks[side].get(r) == hero:
                return True
    return False


def _is_banned_v1(st: V1State, hero: str) -> bool:
    return hero in st.bans["ally"] or hero in st.bans["enemy"]


def _v1_recommend(st: V1State, action: Dict[str, Any], tier_idx: Dict[str, Any]) -> List[str]:
    by_role = tier_idx["byRole"]
    best_global = tier_idx["bestGlobal"]
    side = action["side"]

    if action["type"] == "pick":
        role = _v1_next_open_role(st, side)
        if not role:
            return []
        role_map = by_role.get(role) or {}
        enemy_side = "enemy" if side == "ally" else "ally"
        enemy_picks = [st.picks[enemy_side][r] for r in ROLE_ORDER if st.picks[enemy_side][r]]
        out = []
        for hero, h in role_map.items():
            if _is_picked_v1(st, hero) or _is_banned_v1(st, hero):
                continue
            strong = _counter_map(h, "strongAgainst", "winRate")
            weak = _counter_map(h, "counteredBy", "opponentWinRate")
            score = float(h.get("score") or 0.0) * 100.0 + TIER_WEIGHTS.get(str(h.get("tier") or "D"), 0) + float((h.get("stats") or {}).get("winRate") or 0.0) * 20.0
            for ep in enemy_picks:
                if ep in strong:
                    score += strong[ep] * 35.0
                if ep in weak:
                    score -= weak[ep] * 30.0
            out.append((hero, TIER_WEIGHTS.get(str(h.get("tier") or "D"), 0), score))
        out.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return [x[0] for x in out[:6]]

    # BAN
    open_roles = [r for r in ROLE_ORDER if not st.picks[side].get(r)]
    my_picks = [st.picks[side][r] for r in ROLE_ORDER if st.picks[side][r]]
    out = []
    for hero, h in best_global.items():
        if _is_picked_v1(st, hero) or _is_banned_v1(st, hero):
            continue
        if h.get("role") not in open_roles:
            continue
        strong = _counter_map(h, "strongAgainst", "winRate")
        weak = _counter_map(h, "counteredBy", "opponentWinRate")
        score = float(h.get("score") or 0.0) * 100.0 + TIER_WEIGHTS.get(str(h.get("tier") or "D"), 0) + float((h.get("stats") or {}).get("banCount") or 0.0) * 0.5
        for mp in my_picks:
            if mp in strong:
                score += strong[mp] * 40.0
            if mp in weak:
                score -= weak[mp] * 15.0
        out.append((hero, TIER_WEIGHTS.get(str(h.get("tier") or "D"), 0), score))
    out.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return [x[0] for x in out[:12]]


def _advance_v1(st: V1State, hero: Optional[str]) -> None:
    idx, prog, action = _v1_get_action(st)
    st.turn_index, st.action_progress = idx, prog
    if not action:
        return
    if hero:
        if action["type"] == "pick":
            role = _v1_next_open_role(st, action["side"])
            if role:
                st.picks[action["side"]][role] = hero
        else:
            st.bans[action["side"]].append(hero)
    st.action_progress += 1
    n_idx, n_prog, _ = _v1_get_action(st)
    st.turn_index, st.action_progress = n_idx, n_prog


def _advance_v2(st: V2State, hero: Optional[str]) -> None:
    idx, prog, action = _v2_get_action(st)
    st.turn_index, st.action_progress = idx, prog
    if not action:
        return
    if hero:
        if action["type"] == "pick":
            if hero not in st.picks[action["side"]]:
                st.picks[action["side"]].append(hero)
        else:
            st.bans[action["side"]].append(hero)
    st.action_progress += 1
    n_idx, n_prog, _ = _v2_get_action(st)
    st.turn_index, st.action_progress = n_idx, n_prog


def _v2_recommend(st: V2State) -> Tuple[Optional[Dict[str, Any]], List[str], Dict[str, Any]]:
    payload = {
        "turnIndex": st.turn_index,
        "actionProgress": st.action_progress,
        "picks": {"ally": st.picks["ally"], "enemy": st.picks["enemy"]},
        "bans": {"ally": st.bans["ally"], "enemy": st.bans["enemy"]},
        "lookahead": {"enabled": True, "beamWidth": 6, "enemyTopN": 4, "penaltyFactor": 0.25},
    }
    res = recommend_from_payload(payload, debug=False)
    mode = res.get("mode")
    side = res.get("side")
    if not mode or not side:
        return None, [], res
    action = {"type": mode, "side": side}
    recs = [_clean_hero(x.get("hero")) for x in (res.get("recommendations") or [])]
    return action, [x for x in recs if x], res


def _next_truth_hero(remaining_ordered: List[str], consumed: Set[str]) -> Optional[str]:
    for h in remaining_ordered:
        if h not in consumed:
            return h
    return None


def _safe_ratio(a: int, b: int) -> float:
    return round((a / b), 4) if b else 0.0


def evaluate(limit_maps: int = 30) -> Dict[str, Any]:
    maps = _load_maps(limit_maps=limit_maps)
    tier_data = _load_json(_repo_root() / "hero_tier_list.json")
    tier_idx = _build_tier_index(tier_data)

    agg = {
        "v1": {"pick": {"hit": 0, "top1": 0, "total": 0}, "ban": {"hit": 0, "top1": 0, "total": 0}},
        "v2": {"pick": {"hit": 0, "top1": 0, "total": 0}, "ban": {"hit": 0, "top1": 0, "total": 0}},
        "v2FeasibleChecks": {"allyFalse": 0, "enemyFalse": 0, "total": 0},
        "samples": [],
        "mapsEvaluated": 0,
    }

    for map_idx, mp in enumerate(maps, start=1):
        st1 = V1State(
            turn_index=0,
            action_progress=0,
            picks={side: {r: None for r in ROLE_ORDER} for side in ("ally", "enemy")},
            bans={"ally": [], "enemy": []},
        )
        st2 = V2State(
            turn_index=0,
            action_progress=0,
            picks={"ally": [], "enemy": []},
            bans={"ally": [], "enemy": []},
        )

        truth = {
            "ally": {"pick": mp["allyPicks"], "ban": mp["allyBans"]},
            "enemy": {"pick": mp["enemyPicks"], "ban": mp["enemyBans"]},
        }
        consumed = {
            "ally": {"pick": set(), "ban": set()},
            "enemy": {"pick": set(), "ban": set()},
        }

        step = 0
        first_sample_row = None
        while True:
            a1_idx, a1_prog, a1 = _v1_get_action(st1)
            a2, recs_v2, res_v2 = _v2_recommend(st2)
            st1.turn_index, st1.action_progress = a1_idx, a1_prog

            if not a1 or not a2:
                break

            # Keep replay synchronized to sequence/side/type.
            if a1["type"] != a2["type"] or a1["side"] != a2["side"]:
                break

            side = a1["side"]
            mode = a1["type"]  # pick|ban
            remaining_truth = [h for h in truth[side][mode] if h not in consumed[side][mode]]
            if remaining_truth:
                recs_v1 = _v1_recommend(st1, a1, tier_idx)
                truth_set = set(remaining_truth)

                agg["v1"][mode]["total"] += 1
                agg["v2"][mode]["total"] += 1

                if any(h in truth_set for h in recs_v1):
                    agg["v1"][mode]["hit"] += 1
                if recs_v1 and recs_v1[0] in truth_set:
                    agg["v1"][mode]["top1"] += 1

                if any(h in truth_set for h in recs_v2):
                    agg["v2"][mode]["hit"] += 1
                if recs_v2 and recs_v2[0] in truth_set:
                    agg["v2"][mode]["top1"] += 1

                if first_sample_row is None:
                    first_sample_row = {
                        "step": step + 1,
                        "mode": mode,
                        "side": side,
                        "truthRemaining": remaining_truth,
                        "v1Top3": recs_v1[:3],
                        "v2Top3": recs_v2[:3],
                    }

            comp = res_v2.get("composition") or {}
            ally_comp = comp.get("ally") or {}
            enemy_comp = comp.get("enemy") or {}
            agg["v2FeasibleChecks"]["total"] += 1
            if ally_comp.get("isFeasible") is False:
                agg["v2FeasibleChecks"]["allyFalse"] += 1
            if enemy_comp.get("isFeasible") is False:
                agg["v2FeasibleChecks"]["enemyFalse"] += 1

            chosen = _next_truth_hero(truth[side][mode], consumed[side][mode])
            if chosen:
                consumed[side][mode].add(chosen)
            _advance_v1(st1, chosen)
            _advance_v2(st2, chosen)
            step += 1

            if step > 80:
                break

        agg["mapsEvaluated"] += 1
        if first_sample_row:
            agg["samples"].append(
                {
                    "mapIndex": map_idx,
                    "source": mp["source"],
                    "map": mp.get("map"),
                    **first_sample_row,
                }
            )

    def metric(side: str, mode: str) -> Dict[str, Any]:
        d = agg[side][mode]
        return {
            "hit": d["hit"],
            "top1": d["top1"],
            "total": d["total"],
            "hitRate": _safe_ratio(d["hit"], d["total"]),
            "top1Rate": _safe_ratio(d["top1"], d["total"]),
        }

    summary = {
        "v1": {
            "pick": metric("v1", "pick"),
            "ban": metric("v1", "ban"),
        },
        "v2": {
            "pick": metric("v2", "pick"),
            "ban": metric("v2", "ban"),
        },
        "delta": {
            "pickHitRate": round(metric("v2", "pick")["hitRate"] - metric("v1", "pick")["hitRate"], 4),
            "banHitRate": round(metric("v2", "ban")["hitRate"] - metric("v1", "ban")["hitRate"], 4),
            "pickTop1Rate": round(metric("v2", "pick")["top1Rate"] - metric("v1", "pick")["top1Rate"], 4),
            "banTop1Rate": round(metric("v2", "ban")["top1Rate"] - metric("v1", "ban")["top1Rate"], 4),
        },
        "v2Feasibility": {
            "checks": agg["v2FeasibleChecks"]["total"],
            "allyFalse": agg["v2FeasibleChecks"]["allyFalse"],
            "enemyFalse": agg["v2FeasibleChecks"]["enemyFalse"],
            "allyFalseRate": _safe_ratio(agg["v2FeasibleChecks"]["allyFalse"], agg["v2FeasibleChecks"]["total"]),
            "enemyFalseRate": _safe_ratio(agg["v2FeasibleChecks"]["enemyFalse"], agg["v2FeasibleChecks"]["total"]),
        },
    }

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "config": {
            "mapsRequested": limit_maps,
            "mapsEvaluated": agg["mapsEvaluated"],
            "pickTopK": 6,
            "banTopK": 12,
            "evaluationMethod": "hit if recommendation intersects remaining ground-truth picks/bans at each draft micro-step",
        },
        "summary": summary,
        "sampleRows": agg["samples"][:8],
    }


def write_markdown_report(result: Dict[str, Any], out_md: Path) -> None:
    c = result["config"]
    s = result["summary"]
    lines = [
        "# Draft Engine Phase 5 Validation Report",
        "",
        f"- Generated: `{result['generatedAt']}`",
        f"- Maps evaluated: `{c['mapsEvaluated']}` / requested `{c['mapsRequested']}`",
        f"- Method: {c['evaluationMethod']}",
        "",
        "## Summary",
        "",
        "| Metric | v1 | v2 | Delta (v2-v1) |",
        "|---|---:|---:|---:|",
        f"| Pick Hit Rate | {s['v1']['pick']['hitRate']:.4f} | {s['v2']['pick']['hitRate']:.4f} | {s['delta']['pickHitRate']:+.4f} |",
        f"| Pick Top1 Rate | {s['v1']['pick']['top1Rate']:.4f} | {s['v2']['pick']['top1Rate']:.4f} | {s['delta']['pickTop1Rate']:+.4f} |",
        f"| Ban Hit Rate | {s['v1']['ban']['hitRate']:.4f} | {s['v2']['ban']['hitRate']:.4f} | {s['delta']['banHitRate']:+.4f} |",
        f"| Ban Top1 Rate | {s['v1']['ban']['top1Rate']:.4f} | {s['v2']['ban']['top1Rate']:.4f} | {s['delta']['banTop1Rate']:+.4f} |",
        "",
        "## Feasibility (v2)",
        "",
        f"- Checks: `{s['v2Feasibility']['checks']}`",
        f"- Ally infeasible rate: `{s['v2Feasibility']['allyFalseRate']:.4f}`",
        f"- Enemy infeasible rate: `{s['v2Feasibility']['enemyFalseRate']:.4f}`",
        "",
        "## Notes",
        "",
        "- Hit-rate dipakai sebagai proxy objektif dari relevansi rekomendasi ke data historis.",
        "- Top1-rate menggambarkan kualitas ranking hero rekomendasi teratas.",
        "- Untuk validasi coaching quality final, tetap perlu uji playtest user secara manual di UI.",
    ]
    out_md.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Draft Engine v2 vs baseline v1")
    parser.add_argument("--maps", type=int, default=30, help="Number of maps to evaluate (default: 30)")
    parser.add_argument(
        "--out-json",
        type=str,
        default=str((_repo_root() / "draft_phase5_report.json")),
        help="Output JSON report path",
    )
    parser.add_argument(
        "--out-md",
        type=str,
        default=str((_workspace_root() / "docs" / "draft_phase5_report.md")),
        help="Output markdown report path",
    )
    args = parser.parse_args()

    result = evaluate(limit_maps=max(1, args.maps))
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    write_markdown_report(result, out_md)

    print(f"Wrote JSON report: {out_json}")
    print(f"Wrote Markdown report: {out_md}")
    print("Summary:")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
