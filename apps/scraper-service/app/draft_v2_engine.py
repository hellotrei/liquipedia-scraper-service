from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from app.draft_v2 import (
    DRAFT_V2_SCORING,
    DRAFT_V2_SEQUENCE,
    DraftV2ConfigError,
    load_role_pool,
)

TIER_SCORE = {
    "SS": 100.0,
    "S": 88.0,
    "A": 74.0,
    "B": 60.0,
    "C": 45.0,
    "D": 30.0,
}
ROLE_COUNT = 5
LOOKAHEAD_DEFAULT = {"enabled": True, "beamWidth": 6, "enemyTopN": 4, "penaltyFactor": 0.25}

_PROFILE_CACHE: Dict[str, Any] = {
    "pool_mtime_ns": None,
    "override_mtime_ns": None,
    "tier_mtime_ns": None,
    "data": None,
}


class DraftV2RequestError(ValueError):
    pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _tier_list_path() -> Path:
    return _repo_root() / "hero_tier_list.json"


def _norm_hero(value: Any) -> str:
    return str(value or "").strip().lower()


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _perm(n: int, r: int) -> int:
    if r < 0 or r > n:
        return 0
    # Python 3.8+ has math.perm, but keep fallback explicit.
    try:
        return math.perm(n, r)
    except AttributeError:
        out = 1
        for i in range(n, n - r, -1):
            out *= i
        return out


def _load_tier_data() -> Dict[str, Any]:
    path = _tier_list_path()
    if not path.exists():
        raise DraftV2ConfigError("Missing required file: hero_tier_list.json")
    try:
        return json.loads(path.read_text())
    except Exception as e:
        raise DraftV2ConfigError(f"Failed reading hero_tier_list.json: {e}") from e


def _build_profiles(refresh: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    pool_path = _repo_root() / "hero_role_pool.json"
    override_path = _repo_root() / "hero_role_pool_overrides.json"
    tier_path = _tier_list_path()
    pool_mtime_ns = pool_path.stat().st_mtime_ns if pool_path.exists() else -1
    override_mtime_ns = override_path.stat().st_mtime_ns if override_path.exists() else -1
    tier_mtime_ns = tier_path.stat().st_mtime_ns if tier_path.exists() else -1

    if (
        not refresh
        and _PROFILE_CACHE["data"] is not None
        and _PROFILE_CACHE["pool_mtime_ns"] == pool_mtime_ns
        and _PROFILE_CACHE["override_mtime_ns"] == override_mtime_ns
        and _PROFILE_CACHE["tier_mtime_ns"] == tier_mtime_ns
    ):
        return _PROFILE_CACHE["data"], _PROFILE_CACHE["meta"]

    role_pool, warnings = load_role_pool(refresh=refresh)
    tier = _load_tier_data()

    # Index tier entries by hero + role and gather maxima for normalization.
    by_hero_role: Dict[str, Dict[str, Dict[str, Any]]] = {}
    max_pick_win = 0.0
    max_pick = 0.0
    max_ban = 0.0
    for role, role_data in (tier.get("roles") or {}).items():
        for entry in (role_data or {}).get("heroDetails") or []:
            hero = _norm_hero(entry.get("hero"))
            if not hero:
                continue
            by_hero_role.setdefault(hero, {})[role] = entry
            stats = entry.get("stats") or {}
            max_pick_win = max(max_pick_win, float(stats.get("pickWinCount") or 0.0))
            max_pick = max(max_pick, float(stats.get("pickCount") or 0.0))
            max_ban = max(max_ban, float(stats.get("banCount") or 0.0))

    roles: List[str] = list(role_pool.get("roles") or [])
    role_set = set(roles)
    profiles: Dict[str, Any] = {}
    for hero, cfg in (role_pool.get("heroes") or {}).items():
        possible_roles = [r for r in cfg.get("possibleRoles") or [] if r in role_set]
        if not possible_roles:
            continue
        role_power = cfg.get("rolePower") or {}
        tags = cfg.get("tags") or []

        role_meta: Dict[str, float] = {}
        strong_against: Dict[str, float] = {}
        countered_by: Dict[str, float] = {}
        best_tier_rank = 0.0
        total_entries = 0

        for role in possible_roles:
            entry = (by_hero_role.get(hero) or {}).get(role) or {}
            tier_name = str(entry.get("tier") or "C").upper()
            tier_score = TIER_SCORE.get(tier_name, 45.0)
            best_tier_rank = max(best_tier_rank, tier_score)
            stats = entry.get("stats") or {}
            pick_win_norm = (float(stats.get("pickWinCount") or 0.0) / max_pick_win * 100.0) if max_pick_win else 0.0
            pick_norm = (float(stats.get("pickCount") or 0.0) / max_pick * 100.0) if max_pick else 0.0
            ban_norm = (float(stats.get("banCount") or 0.0) / max_ban * 100.0) if max_ban else 0.0

            rp = float(role_power.get(role) or 0.70)
            role_meta[role] = round(
                _clamp(
                    0.42 * tier_score
                    + 0.28 * pick_win_norm
                    + 0.12 * pick_norm
                    + 0.08 * ban_norm
                    + 0.10 * (rp * 100.0)
                ),
                4,
            )
            total_entries += 1

            counters = entry.get("counters") or {}
            for x in counters.get("strongAgainst") or []:
                opp = _norm_hero(x.get("hero"))
                if not opp:
                    continue
                wr = float(x.get("winRate") or 0.0)
                enc = float(x.get("encounters") or 0.0)
                val = _clamp(wr * min(enc / 5.0, 1.0), 0.0, 1.0)
                strong_against[opp] = max(strong_against.get(opp, 0.0), val)

            for x in counters.get("counteredBy") or []:
                opp = _norm_hero(x.get("hero"))
                if not opp:
                    continue
                owr = float(x.get("opponentWinRate") or 0.0)
                enc = float(x.get("encounters") or 0.0)
                val = _clamp(owr * min(enc / 5.0, 1.0), 0.0, 1.0)
                countered_by[opp] = max(countered_by.get(opp, 0.0), val)

        if not role_meta:
            for role in possible_roles:
                rp = float(role_power.get(role) or 0.70)
                role_meta[role] = round(_clamp(40.0 + rp * 45.0), 4)

        base_meta = round(sum(role_meta.values()) / max(len(role_meta), 1), 4)
        profiles[hero] = {
            "hero": hero,
            "possibleRoles": possible_roles,
            "rolePower": {r: float(role_power.get(r) or 0.70) for r in possible_roles},
            "roleMeta": role_meta,
            "baseMeta": base_meta,
            "bestTierScore": best_tier_rank or 45.0,
            "strongAgainst": strong_against,
            "counteredBy": countered_by,
            "tags": tags,
            "sourceEntries": total_entries,
        }

    # Fallback for heroes present in tier list but missing in role pool.
    for hero, role_entries in by_hero_role.items():
        if hero in profiles:
            continue
        poss = [r for r in role_entries.keys() if r in role_set] or roles[:]
        role_meta = {}
        for role in poss:
            entry = role_entries.get(role) or {}
            tier_name = str(entry.get("tier") or "C").upper()
            role_meta[role] = TIER_SCORE.get(tier_name, 45.0)
        profiles[hero] = {
            "hero": hero,
            "possibleRoles": poss,
            "rolePower": {r: 0.70 for r in poss},
            "roleMeta": role_meta,
            "baseMeta": round(sum(role_meta.values()) / max(len(role_meta), 1), 4),
            "bestTierScore": max(role_meta.values()) if role_meta else 45.0,
            "strongAgainst": {},
            "counteredBy": {},
            "tags": ["unmapped"],
            "sourceEntries": len(role_entries),
        }
        warnings.append(f"Hero '{hero}' missing in role pool; fallback profile applied")

    data = {"roles": roles, "profiles": profiles}
    meta = {"warnings": warnings}
    _PROFILE_CACHE["pool_mtime_ns"] = pool_mtime_ns
    _PROFILE_CACHE["override_mtime_ns"] = override_mtime_ns
    _PROFILE_CACHE["tier_mtime_ns"] = tier_mtime_ns
    _PROFILE_CACHE["data"] = data
    _PROFILE_CACHE["meta"] = meta
    return data, meta


def _unique_list(values: List[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for v in values:
        if v and v not in seen:
            out.append(v)
            seen.add(v)
    return out


def _parse_side_heroes(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return _unique_list([_norm_hero(x) for x in raw if _norm_hero(x)])
    if isinstance(raw, dict):
        # support legacy UI payload: {"exp_lane":"hero", ...}
        vals = [_norm_hero(v) for v in raw.values() if _norm_hero(v)]
        return _unique_list(vals)
    raise DraftV2RequestError("Side picks/bans must be array (or object for legacy picks)")


def normalize_draft_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    picks_raw = payload.get("picks") or {}
    bans_raw = payload.get("bans") or {}
    if not isinstance(picks_raw, dict):
        raise DraftV2RequestError("Field 'picks' must be an object with ally/enemy")
    if not isinstance(bans_raw, dict):
        raise DraftV2RequestError("Field 'bans' must be an object with ally/enemy")

    picks = {
        "ally": _parse_side_heroes(picks_raw.get("ally")),
        "enemy": _parse_side_heroes(picks_raw.get("enemy")),
    }
    bans = {
        "ally": _parse_side_heroes(bans_raw.get("ally")),
        "enemy": _parse_side_heroes(bans_raw.get("enemy")),
    }
    if len(picks["ally"]) > ROLE_COUNT or len(picks["enemy"]) > ROLE_COUNT:
        raise DraftV2RequestError("Each side can have max 5 picks")

    all_picked = set(picks["ally"]) | set(picks["enemy"])
    all_banned = set(bans["ally"]) | set(bans["enemy"])
    if set(picks["ally"]) & set(picks["enemy"]):
        raise DraftV2RequestError("A hero cannot be picked by both teams")
    if all_picked & all_banned:
        raise DraftV2RequestError("A hero cannot be both picked and banned")

    turn_index = int(payload.get("turnIndex") or 0)
    action_progress = int(payload.get("actionProgress") or 0)
    if turn_index < 0:
        turn_index = 0
    if action_progress < 0:
        action_progress = 0

    return {
        "patch": str(payload.get("patch") or "M7"),
        "sequenceKey": str(payload.get("sequenceKey") or "mlbb_standard_bo5"),
        "turnIndex": turn_index,
        "actionProgress": action_progress,
        "picks": picks,
        "bans": bans,
    }


def _get_current_action(state: Dict[str, Any]) -> Tuple[int, int, Dict[str, Any] | None]:
    idx = int(state["turnIndex"])
    progress = int(state["actionProgress"])

    while idx < len(DRAFT_V2_SEQUENCE):
        act = DRAFT_V2_SEQUENCE[idx]
        limit = int(act["count"])
        if act["type"] == "pick":
            side = act["side"]
            remaining = ROLE_COUNT - len(state["picks"][side])
            # keep per-turn limit stable within current action
            limit = min(limit, max(remaining + progress, 0))
        if limit <= 0 or progress >= limit:
            idx += 1
            progress = 0
            continue
        action = {**act, "limit": limit}
        return idx, progress, action
    return idx, progress, None


def _apply_action(state: Dict[str, Any], hero: str) -> Dict[str, Any]:
    out = deepcopy(state)
    idx, progress, action = _get_current_action(out)
    if not action:
        return out

    if hero in out["picks"]["ally"] or hero in out["picks"]["enemy"]:
        return out
    if hero in out["bans"]["ally"] or hero in out["bans"]["enemy"]:
        return out

    if action["type"] == "pick":
        out["picks"][action["side"]].append(hero)
    else:
        out["bans"][action["side"]].append(hero)
    out["turnIndex"] = idx
    out["actionProgress"] = progress + 1

    n_idx, n_progress, _ = _get_current_action(out)
    out["turnIndex"] = n_idx
    out["actionProgress"] = n_progress
    return out


def _assignment_for_side(
    heroes: List[str], profiles: Dict[str, Any], roles: List[str]
) -> Dict[str, Any]:
    picks = _unique_list([_norm_hero(h) for h in heroes if _norm_hero(h)])
    role_set = set(roles)
    n = len(picks)
    if n == 0:
        return {
            "isFeasible": True,
            "bestScore": 0.0,
            "bestAssignment": {},
            "heroToRole": {},
            "openRoles": roles[:],
            "validAssignments": 1,
            "maxAssignments": 1,
            "feasibilityScore": 1.0,
            "heroRoleOptions": {},
        }

    candidates: Dict[str, List[Tuple[str, float]]] = {}
    for h in picks:
        profile = profiles.get(h)
        if profile:
            poss = [r for r in profile.get("possibleRoles") or [] if r in role_set]
            if not poss:
                poss = roles[:]
            cands = [(r, float((profile.get("rolePower") or {}).get(r) or 0.70)) for r in poss]
        else:
            cands = [(r, 0.65) for r in roles]
        candidates[h] = cands

    order = sorted(picks, key=lambda h: len(candidates[h]))
    used: Set[str] = set()
    chosen: Dict[str, str] = {}
    best_assignment: Dict[str, str] | None = None
    best_score = -1.0
    valid_assignments = 0
    hero_role_options: Dict[str, Set[str]] = {h: set() for h in picks}

    def dfs(i: int, score: float) -> None:
        nonlocal best_assignment, best_score, valid_assignments
        if i >= len(order):
            valid_assignments += 1
            if score > best_score:
                best_score = score
                best_assignment = chosen.copy()
            for hero_k, role_k in chosen.items():
                hero_role_options[hero_k].add(role_k)
            return

        hero = order[i]
        for role, power in candidates[hero]:
            if role in used:
                continue
            used.add(role)
            chosen[hero] = role
            dfs(i + 1, score + power)
            chosen.pop(hero, None)
            used.remove(role)

    dfs(0, 0.0)
    max_assignments = _perm(len(roles), n)
    is_feasible = valid_assignments > 0
    if not is_feasible:
        return {
            "isFeasible": False,
            "bestScore": 0.0,
            "bestAssignment": {},
            "heroToRole": {},
            "openRoles": roles[:],
            "validAssignments": 0,
            "maxAssignments": max_assignments,
            "feasibilityScore": 0.0,
            "heroRoleOptions": {k: [] for k in picks},
        }

    hero_to_role = best_assignment or {}
    role_to_hero = {r: h for h, r in hero_to_role.items()}
    ratio = valid_assignments / max(max_assignments, 1)
    avg_power = best_score / max(n, 1)
    feasibility_score = round(_clamp((0.45 * ratio + 0.55 * avg_power) * 100.0, 0.0, 100.0) / 100.0, 4)
    return {
        "isFeasible": True,
        "bestScore": round(best_score, 6),
        "bestAssignment": role_to_hero,
        "heroToRole": hero_to_role,
        "openRoles": [r for r in roles if r not in role_to_hero],
        "validAssignments": valid_assignments,
        "maxAssignments": max_assignments,
        "feasibilityScore": feasibility_score,
        "heroRoleOptions": {k: sorted(v) for k, v in hero_role_options.items()},
    }


def _phase_name(pick_count: int) -> str:
    if pick_count <= 2:
        return "early"
    if pick_count <= 4:
        return "mid"
    return "late"


def _evaluate_pick_candidate(
    state: Dict[str, Any],
    side: str,
    hero: str,
    profiles: Dict[str, Any],
    roles: List[str],
) -> Dict[str, Any]:
    enemy = "enemy" if side == "ally" else "ally"
    profile = profiles.get(hero)
    if not profile:
        return {}

    cur_assign = _assignment_for_side(state["picks"][side], profiles, roles)
    next_picks = state["picks"][side] + [hero]
    next_assign = _assignment_for_side(next_picks, profiles, roles)

    predicted_roles = next_assign.get("heroRoleOptions", {}).get(hero) or profile.get("possibleRoles") or []
    meta = max(
        [float((profile.get("roleMeta") or {}).get(r) or profile.get("baseMeta") or 50.0) for r in predicted_roles],
        default=float(profile.get("baseMeta") or 50.0),
    )

    enemy_picks = state["picks"][enemy]
    if enemy_picks:
        diffs = []
        for e in enemy_picks:
            strong = float((profile.get("strongAgainst") or {}).get(e) or 0.0)
            weak = float((profile.get("counteredBy") or {}).get(e) or 0.0)
            diffs.append((strong - weak) * 100.0)
        counter = _clamp(50.0 + (sum(diffs) / len(diffs)) * 0.60)
    else:
        counter = 50.0

    if not next_assign["isFeasible"]:
        synergy = 0.0
    else:
        cur_open = len(cur_assign.get("openRoles") or roles)
        nxt_open = len(next_assign.get("openRoles") or roles)
        coverage_gain = max(cur_open - nxt_open, 0)
        flex_gain = next_assign.get("feasibilityScore", 0.0) - cur_assign.get("feasibilityScore", 0.0)
        synergy = _clamp(45.0 + coverage_gain * 16.0 + flex_gain * 65.0)

    my_picks = state["picks"][side]
    if my_picks:
        threat = [float((profile.get("strongAgainst") or {}).get(p) or 0.0) * 100.0 for p in my_picks]
        deny = _clamp(sum(threat) / len(threat))
    else:
        deny = _clamp(0.65 * meta)

    flex = _clamp(
        ((len(profile.get("possibleRoles") or []) - 1) / max(len(roles) - 1, 1)) * 100.0
    )
    feasibility = (next_assign.get("feasibilityScore") or 0.0) * 100.0

    phase = _phase_name(len(next_picks))
    w = (DRAFT_V2_SCORING.get("phaseWeights") or {}).get(phase) or {}
    final = (
        float(w.get("meta", 0.0)) * meta
        + float(w.get("counter", 0.0)) * counter
        + float(w.get("synergy", 0.0)) * synergy
        + float(w.get("deny", 0.0)) * deny
        + float(w.get("flex", 0.0)) * flex
        + float(w.get("feasibility", 0.0)) * feasibility
    )

    reasons: List[str] = []
    if counter >= 62:
        reasons.append("Counter positif terhadap draft lawan saat ini")
    if synergy >= 62:
        reasons.append("Menjaga komposisi role tetap fleksibel dan feasible")
    if flex >= 45:
        reasons.append("Hero flex untuk beberapa role")
    if not reasons:
        reasons.append("Stabil sebagai pick aman berdasarkan meta saat ini")

    return {
        "hero": hero,
        "tierScore": float(profile.get("bestTierScore") or 45.0),
        "predictedRoles": predicted_roles,
        "components": {
            "meta": round(meta, 4),
            "counter": round(counter, 4),
            "synergy": round(synergy, 4),
            "deny": round(deny, 4),
            "flex": round(flex, 4),
            "feasibility": round(feasibility, 4),
        },
        "phase": phase,
        "baseScore": round(final, 6),
        "score": round(final, 6),
        "reasons": reasons[:3],
    }


def _enemy_best_response_score(
    state_after_pick: Dict[str, Any],
    acting_side: str,
    profiles: Dict[str, Any],
    roles: List[str],
    top_n: int,
) -> float:
    enemy = "enemy" if acting_side == "ally" else "ally"
    occupied = set(state_after_pick["picks"]["ally"]) | set(state_after_pick["picks"]["enemy"])
    banned = set(state_after_pick["bans"]["ally"]) | set(state_after_pick["bans"]["enemy"])
    candidates = [h for h in profiles.keys() if h not in occupied and h not in banned]
    if not candidates:
        return 0.0

    scores: List[float] = []
    for hero in candidates:
        ev = _evaluate_pick_candidate(state_after_pick, enemy, hero, profiles, roles)
        if not ev:
            continue
        if ev["components"]["feasibility"] <= 0:
            continue
        scores.append(float(ev["baseScore"]))
    scores.sort(reverse=True)
    if not scores:
        return 0.0
    return sum(scores[: max(top_n, 1)]) / max(min(top_n, len(scores)), 1)


def _recommend_pick(
    state: Dict[str, Any],
    action: Dict[str, Any],
    profiles: Dict[str, Any],
    roles: List[str],
    lookahead_cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    side = action["side"]
    occupied = set(state["picks"]["ally"]) | set(state["picks"]["enemy"])
    banned = set(state["bans"]["ally"]) | set(state["bans"]["enemy"])
    candidates = [h for h in profiles.keys() if h not in occupied and h not in banned]

    evals: List[Dict[str, Any]] = []
    for hero in candidates:
        ev = _evaluate_pick_candidate(state, side, hero, profiles, roles)
        if not ev:
            continue
        # Avoid dead-end role composition.
        if ev["components"]["feasibility"] <= 0:
            continue
        evals.append(ev)

    evals.sort(key=lambda x: (x["tierScore"], x["baseScore"]), reverse=True)
    if not evals:
        return []

    if bool(lookahead_cfg.get("enabled", True)):
        beam_width = int(lookahead_cfg.get("beamWidth", LOOKAHEAD_DEFAULT["beamWidth"]))
        enemy_top_n = int(lookahead_cfg.get("enemyTopN", LOOKAHEAD_DEFAULT["enemyTopN"]))
        penalty_factor = float(lookahead_cfg.get("penaltyFactor", LOOKAHEAD_DEFAULT["penaltyFactor"]))
        beam = evals[: max(beam_width, 1)]
        for ev in beam:
            simulated = _apply_action(state, ev["hero"])
            n_idx, n_prog, n_action = _get_current_action(simulated)
            simulated["turnIndex"] = n_idx
            simulated["actionProgress"] = n_prog
            if n_action and n_action.get("type") == "pick" and n_action.get("side") != side:
                enemy_resp = _enemy_best_response_score(simulated, side, profiles, roles, enemy_top_n)
                ev["score"] = round(float(ev["baseScore"]) - penalty_factor * enemy_resp, 6)
                ev["lookaheadPenalty"] = round(penalty_factor * enemy_resp, 6)
            else:
                ev["score"] = ev["baseScore"]

    evals.sort(key=lambda x: (x["tierScore"], x["score"]), reverse=True)
    return evals[:6]


def _recommend_ban(
    state: Dict[str, Any],
    action: Dict[str, Any],
    profiles: Dict[str, Any],
    roles: List[str],
) -> List[Dict[str, Any]]:
    side = action["side"]
    enemy = "enemy" if side == "ally" else "ally"
    occupied = set(state["picks"]["ally"]) | set(state["picks"]["enemy"])
    banned = set(state["bans"]["ally"]) | set(state["bans"]["enemy"])
    candidates = [h for h in profiles.keys() if h not in occupied and h not in banned]

    enemy_assign = _assignment_for_side(state["picks"][enemy], profiles, roles)
    enemy_open = set(enemy_assign.get("openRoles") or roles)

    recs: List[Dict[str, Any]] = []
    for hero in candidates:
        profile = profiles.get(hero) or {}
        poss = profile.get("possibleRoles") or roles
        role_fit = sorted([r for r in poss if r in enemy_open]) or poss
        if not role_fit:
            continue

        # Ban score = how dangerous this hero is if enemy gets it now.
        as_enemy = _evaluate_pick_candidate(state, enemy, hero, profiles, roles)
        if not as_enemy:
            continue
        fit_bonus = _clamp((len(role_fit) / max(len(roles), 1)) * 15.0)
        as_enemy["score"] = round(float(as_enemy["baseScore"]) + fit_bonus, 6)
        as_enemy["baseScore"] = as_enemy["score"]
        as_enemy["predictedRoles"] = role_fit
        as_enemy["reasons"] = [
            "Deny power pick lawan berdasarkan meta saat ini",
            "Role hero cocok dengan kebutuhan role lawan",
        ]
        recs.append(as_enemy)

    recs.sort(key=lambda x: (x["tierScore"], x["score"]), reverse=True)
    return recs[:12]


def _composition_block(state: Dict[str, Any], side: str, profiles: Dict[str, Any], roles: List[str]) -> Dict[str, Any]:
    assign = _assignment_for_side(state["picks"][side], profiles, roles)
    return {
        "isFeasible": bool(assign["isFeasible"]),
        "bestAssignment": assign["bestAssignment"],
        "openRoles": assign["openRoles"],
        "feasibilityScore": assign["feasibilityScore"],
        "validAssignments": assign["validAssignments"],
        "maxAssignments": assign["maxAssignments"],
    }


def _collect_unknown_heroes(state: Dict[str, Any], profiles: Dict[str, Any]) -> List[str]:
    known = set(profiles.keys())
    all_heroes = (
        list(state["picks"]["ally"])
        + list(state["picks"]["enemy"])
        + list(state["bans"]["ally"])
        + list(state["bans"]["enemy"])
    )
    return sorted({h for h in all_heroes if h not in known})


def _candidate_pool_size(state: Dict[str, Any], profiles: Dict[str, Any]) -> int:
    occupied = set(state["picks"]["ally"]) | set(state["picks"]["enemy"])
    banned = set(state["bans"]["ally"]) | set(state["bans"]["enemy"])
    return sum(1 for h in profiles.keys() if h not in occupied and h not in banned)


def recommend_from_payload(payload: Dict[str, Any], debug: bool = False) -> Dict[str, Any]:
    data, meta = _build_profiles(refresh=bool(payload.get("refresh", False)))
    profiles = data["profiles"]
    roles = data["roles"]
    state = normalize_draft_state(payload)
    debug_enabled = bool(debug or payload.get("debug"))

    idx, progress, action = _get_current_action(state)
    state["turnIndex"] = idx
    state["actionProgress"] = progress

    composition = {
        "ally": _composition_block(state, "ally", profiles, roles),
        "enemy": _composition_block(state, "enemy", profiles, roles),
    }
    warnings = list(meta.get("warnings", [])[:30])
    unknown_heroes = _collect_unknown_heroes(state, profiles)
    if unknown_heroes:
        warnings.append(
            f"Unknown heroes in draft state (ignored in scoring): {', '.join(unknown_heroes[:12])}"
        )

    if not action:
        out = {
            "mode": None,
            "side": None,
            "turn": None,
            "composition": composition,
            "recommendations": [],
            "warnings": warnings,
            "message": "Draft sequence selesai",
        }
        if debug_enabled:
            out["debug"] = {
                "normalizedState": state,
                "sequenceLength": len(DRAFT_V2_SEQUENCE),
                "candidatePoolSize": _candidate_pool_size(state, profiles),
                "unknownHeroes": unknown_heroes,
            }
        return out

    lookahead_cfg = payload.get("lookahead") or {}
    mode = action["type"]
    side = action["side"]
    lookahead_eff = {**LOOKAHEAD_DEFAULT, **lookahead_cfg}
    if mode == "pick":
        recs = _recommend_pick(state, action, profiles, roles, lookahead_eff)
    else:
        recs = _recommend_ban(state, action, profiles, roles)

    recommendations = []
    for r in recs:
        item = {
            "hero": r["hero"],
            "score": round(float(r["score"]), 4),
            "tierScore": round(float(r["tierScore"]), 4),
            "predictedRoles": r.get("predictedRoles") or [],
            "components": r.get("components") or {},
            "reasons": r.get("reasons") or [],
        }
        if debug_enabled:
            item["debug"] = {
                "baseScore": round(float(r.get("baseScore", r["score"])), 6),
                "phase": r.get("phase"),
                "lookaheadPenalty": round(float(r.get("lookaheadPenalty", 0.0)), 6),
            }
        recommendations.append(item)

    out = {
        "mode": mode,
        "side": side,
        "turn": {
            "index": idx,
            "text": action["text"],
            "limit": action["limit"],
            "progress": progress,
            "remaining": max(action["limit"] - progress, 0),
        },
        "composition": composition,
        "recommendations": recommendations,
        "warnings": warnings,
    }
    if debug_enabled:
        out["debug"] = {
            "normalizedState": state,
            "currentAction": action,
            "candidatePoolSize": _candidate_pool_size(state, profiles),
            "unknownHeroes": unknown_heroes,
            "lookahead": lookahead_eff if mode == "pick" else {"enabled": False},
            "topCandidatesRaw": [
                {
                    "hero": r["hero"],
                    "tierScore": round(float(r.get("tierScore", 0.0)), 4),
                    "baseScore": round(float(r.get("baseScore", r.get("score", 0.0))), 6),
                    "finalScore": round(float(r.get("score", 0.0)), 6),
                }
                for r in recs[:12]
            ],
        }
    return out


def assign_from_payload(payload: Dict[str, Any], debug: bool = False) -> Dict[str, Any]:
    data, meta = _build_profiles(refresh=bool(payload.get("refresh", False)))
    profiles = data["profiles"]
    roles = data["roles"]
    debug_enabled = bool(debug or payload.get("debug"))

    heroes_raw = payload.get("heroes")
    if heroes_raw is None:
        picks = payload.get("picks") or {}
        side = str(payload.get("side") or "ally").strip().lower()
        if side not in {"ally", "enemy"}:
            side = "ally"
        heroes_raw = (picks or {}).get(side, [])

    heroes = _parse_side_heroes(heroes_raw)
    if len(heroes) > ROLE_COUNT:
        raise DraftV2RequestError("heroes length cannot exceed 5")

    assign = _assignment_for_side(heroes, profiles, roles)
    warnings = list(meta.get("warnings", [])[:30])
    unknown_heroes = sorted([h for h in heroes if h not in profiles])
    if unknown_heroes:
        warnings.append(f"Unknown heroes in assign request: {', '.join(unknown_heroes)}")

    out = {
        "heroes": heroes,
        "roles": roles,
        "assignment": {
            "isFeasible": assign["isFeasible"],
            "bestAssignment": assign["bestAssignment"],
            "heroToRole": assign["heroToRole"],
            "openRoles": assign["openRoles"],
            "feasibilityScore": assign["feasibilityScore"],
            "validAssignments": assign["validAssignments"],
            "maxAssignments": assign["maxAssignments"],
            "heroRoleOptions": assign["heroRoleOptions"],
        },
        "warnings": warnings,
    }
    if debug_enabled:
        out["debug"] = {
            "unknownHeroes": unknown_heroes,
            "heroProfiles": {
                h: {
                    "possibleRoles": (profiles.get(h) or {}).get("possibleRoles", []),
                    "rolePower": (profiles.get(h) or {}).get("rolePower", {}),
                    "tags": (profiles.get(h) or {}).get("tags", []),
                }
                for h in heroes
            },
        }
    return out
