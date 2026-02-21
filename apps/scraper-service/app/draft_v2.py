from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


DRAFT_V2_SEQUENCE_KEY = "mlbb_standard_bo5"
DRAFT_V2_SEQUENCE = [
    {"type": "ban", "side": "ally", "count": 2, "text": "Ally ban 2 heroes"},
    {"type": "ban", "side": "enemy", "count": 2, "text": "Enemy ban 2 heroes"},
    {"type": "ban", "side": "ally", "count": 1, "text": "Ally ban 1 hero"},
    {"type": "ban", "side": "enemy", "count": 1, "text": "Enemy ban 1 hero"},
    {"type": "pick", "side": "ally", "count": 1, "text": "Ally pick 1 hero"},
    {"type": "pick", "side": "enemy", "count": 2, "text": "Enemy pick 2 heroes"},
    {"type": "pick", "side": "ally", "count": 2, "text": "Ally pick 2 heroes"},
    {"type": "pick", "side": "enemy", "count": 1, "text": "Enemy pick 1 hero"},
    {"type": "ban", "side": "enemy", "count": 1, "text": "Enemy ban 1 hero"},
    {"type": "ban", "side": "ally", "count": 1, "text": "Ally ban 1 hero"},
    {"type": "ban", "side": "enemy", "count": 1, "text": "Enemy ban 1 hero"},
    {"type": "ban", "side": "ally", "count": 1, "text": "Ally ban 1 hero"},
    {"type": "pick", "side": "enemy", "count": 1, "text": "Enemy pick 1 hero"},
    {"type": "pick", "side": "ally", "count": 2, "text": "Ally pick 2 last heroes"},
    {"type": "pick", "side": "enemy", "count": 1, "text": "Enemy pick 1 last hero"},
]

DRAFT_V2_SCORING = {
    "components": [
        "meta_score",
        "counter_score",
        "synergy_score",
        "deny_score",
        "flex_score",
        "feasibility_score",
    ],
    "phaseWeights": {
        "early": {
            "meta": 0.40,
            "counter": 0.11,
            "synergy": 0.06,
            "deny": 0.14,
            "flex": 0.15,
            "feasibility": 0.14,
        },
        "mid": {
            "meta": 0.29,
            "counter": 0.27,
            "synergy": 0.18,
            "deny": 0.12,
            "flex": 0.09,
            "feasibility": 0.05,
        },
        "late": {
            "meta": 0.18,
            "counter": 0.32,
            "synergy": 0.23,
            "deny": 0.09,
            "flex": 0.01,
            "feasibility": 0.17,
        },
    },
}

DEFAULT_ROLE_POWER = 0.70

_ROLE_POOL_CACHE: Dict[str, Any] = {
    "cache_key": None,
    "data": None,
    "warnings": [],
}


class DraftV2ConfigError(RuntimeError):
    pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _role_pool_path() -> Path:
    return _repo_root() / "hero_role_pool.json"


def _role_pool_overrides_path() -> Path:
    return _repo_root() / "hero_role_pool_overrides.json"


def _tier_list_path() -> Path:
    return _repo_root() / "hero_tier_list.json"


def _normalize_hero_name(name: Any) -> str:
    return str(name or "").strip().lower()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception as e:
        raise DraftV2ConfigError(f"Failed reading JSON file '{path.name}': {e}") from e


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _validate_role_pool(raw: Any) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(raw, dict):
        raise DraftV2ConfigError("hero_role_pool.json must be an object")

    version = str(raw.get("version") or "").strip()
    if not version:
        errors.append("Field 'version' is required")

    source = str(raw.get("source") or "").strip()
    if not source:
        source = "unknown"

    roles_raw = raw.get("roles")
    if not isinstance(roles_raw, list) or not roles_raw:
        errors.append("Field 'roles' must be a non-empty array")
        roles: List[str] = []
    else:
        roles = []
        seen_roles: Set[str] = set()
        for idx, role in enumerate(roles_raw):
            r = str(role or "").strip()
            if not r:
                errors.append(f"roles[{idx}] is empty")
                continue
            if r in seen_roles:
                warnings.append(f"Duplicate role '{r}' was ignored")
                continue
            seen_roles.add(r)
            roles.append(r)

    heroes_raw = raw.get("heroes")
    if not isinstance(heroes_raw, dict) or not heroes_raw:
        errors.append("Field 'heroes' must be a non-empty object")
        heroes_raw = {}

    normalized_heroes: Dict[str, Any] = {}
    role_set = set(roles)

    for hero_name, hero_cfg in heroes_raw.items():
        hero_key = _normalize_hero_name(hero_name)
        if not hero_key:
            warnings.append("Found empty hero key and skipped")
            continue
        if hero_key in normalized_heroes:
            warnings.append(f"Duplicate hero key after normalization: '{hero_key}'")
            continue
        if not isinstance(hero_cfg, dict):
            errors.append(f"Hero '{hero_key}' value must be an object")
            continue

        possible_roles_raw = hero_cfg.get("possibleRoles")
        if not isinstance(possible_roles_raw, list) or not possible_roles_raw:
            errors.append(f"Hero '{hero_key}' must have non-empty possibleRoles")
            continue

        possible_roles: List[str] = []
        seen_possible: Set[str] = set()
        invalid_roles: List[str] = []
        for r in possible_roles_raw:
            rv = str(r or "").strip()
            if not rv:
                continue
            if rv in seen_possible:
                continue
            seen_possible.add(rv)
            if rv not in role_set:
                invalid_roles.append(rv)
                continue
            possible_roles.append(rv)

        if invalid_roles:
            errors.append(
                f"Hero '{hero_key}' has invalid possibleRoles: {', '.join(invalid_roles)}"
            )
            continue
        if not possible_roles:
            errors.append(f"Hero '{hero_key}' has no valid possibleRoles")
            continue

        role_power_raw = hero_cfg.get("rolePower")
        if role_power_raw is None:
            role_power_raw = {}
        if not isinstance(role_power_raw, dict):
            warnings.append(
                f"Hero '{hero_key}' has invalid rolePower type; defaults were applied"
            )
            role_power_raw = {}

        role_power: Dict[str, float] = {}
        for role in possible_roles:
            value = _as_float(role_power_raw.get(role))
            if value is None:
                warnings.append(
                    f"Hero '{hero_key}' missing rolePower for '{role}'; default={DEFAULT_ROLE_POWER}"
                )
                value = DEFAULT_ROLE_POWER
            role_power[role] = round(max(0.0, min(1.0, value)), 4)

        extra_role_power = [k for k in role_power_raw.keys() if k not in possible_roles]
        if extra_role_power:
            warnings.append(
                f"Hero '{hero_key}' has rolePower keys outside possibleRoles: {', '.join(extra_role_power)}"
            )

        tags_raw = hero_cfg.get("tags") or []
        tags: List[str] = []
        if isinstance(tags_raw, list):
            seen_tags: Set[str] = set()
            for tag in tags_raw:
                t = str(tag or "").strip().lower()
                if not t or t in seen_tags:
                    continue
                seen_tags.add(t)
                tags.append(t)
        else:
            warnings.append(f"Hero '{hero_key}' tags is not an array and was ignored")

        normalized_heroes[hero_key] = {
            "possibleRoles": possible_roles,
            "rolePower": role_power,
            "tags": tags,
        }

    if errors:
        raise DraftV2ConfigError("Invalid hero_role_pool.json: " + "; ".join(errors[:20]))

    return {
        "version": version,
        "source": source,
        "roles": roles,
        "heroes": normalized_heroes,
    }, warnings


def _merge_role_pool_overrides(
    base_data: Dict[str, Any], override_raw: Any
) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    if not isinstance(override_raw, dict):
        return base_data, ["hero_role_pool_overrides.json must be an object; file ignored"]

    roles = list(base_data.get("roles") or [])
    role_set = set(roles)
    heroes = dict(base_data.get("heroes") or {})

    heroes_overrides = override_raw.get("heroes") or {}
    if not isinstance(heroes_overrides, dict):
        return base_data, ["hero_role_pool_overrides.json field 'heroes' must be an object; file ignored"]

    for hero_name, patch in heroes_overrides.items():
        hero = _normalize_hero_name(hero_name)
        if not hero:
            warnings.append("Override contains empty hero key and was skipped")
            continue
        if not isinstance(patch, dict):
            warnings.append(f"Override for '{hero}' must be an object")
            continue

        current = dict(heroes.get(hero) or {})
        current_roles = list(current.get("possibleRoles") or [])
        current_role_power = dict(current.get("rolePower") or {})
        current_tags = list(current.get("tags") or [])

        if "possibleRoles" in patch:
            pr = patch.get("possibleRoles")
            if not isinstance(pr, list) or not pr:
                warnings.append(f"Override '{hero}': possibleRoles must be non-empty array")
                continue
            parsed_roles: List[str] = []
            seen: Set[str] = set()
            bad: List[str] = []
            for r in pr:
                rv = str(r or "").strip()
                if not rv or rv in seen:
                    continue
                seen.add(rv)
                if rv not in role_set:
                    bad.append(rv)
                    continue
                parsed_roles.append(rv)
            if bad:
                warnings.append(f"Override '{hero}': invalid roles {', '.join(bad)}")
                continue
            if not parsed_roles:
                warnings.append(f"Override '{hero}': no valid roles after filtering")
                continue
            current_roles = parsed_roles
            current_role_power = {k: v for k, v in current_role_power.items() if k in set(current_roles)}

        if "rolePower" in patch:
            rp = patch.get("rolePower")
            if not isinstance(rp, dict):
                warnings.append(f"Override '{hero}': rolePower must be an object")
                continue
            for role in current_roles:
                if role in rp:
                    val = _as_float(rp.get(role))
                    if val is None:
                        warnings.append(f"Override '{hero}': rolePower.{role} invalid, keep previous/default")
                        continue
                    current_role_power[role] = round(max(0.0, min(1.0, val)), 4)

        if "tags" in patch:
            tg = patch.get("tags")
            parsed_tags: List[str] = []
            if isinstance(tg, list):
                seen_tags: Set[str] = set()
                for t in tg:
                    tv = str(t or "").strip().lower()
                    if not tv or tv in seen_tags:
                        continue
                    seen_tags.add(tv)
                    parsed_tags.append(tv)
                current_tags = parsed_tags
            else:
                warnings.append(f"Override '{hero}': tags must be an array")

        if not current_roles:
            warnings.append(f"Override '{hero}': resulting possibleRoles empty, skipped")
            continue

        for role in current_roles:
            if role not in current_role_power:
                current_role_power[role] = DEFAULT_ROLE_POWER

        heroes[hero] = {
            "possibleRoles": [r for r in roles if r in set(current_roles)],
            "rolePower": {r: current_role_power[r] for r in roles if r in current_role_power and r in set(current_roles)},
            "tags": current_tags,
        }

    out = {
        "version": str(base_data.get("version") or ""),
        "source": str(base_data.get("source") or "unknown"),
        "roles": roles,
        "heroes": heroes,
    }
    if heroes_overrides:
        out["source"] = f"{out['source']}+overrides"
    return out, warnings


def load_role_pool(refresh: bool = False) -> Tuple[Dict[str, Any], List[str]]:
    path = _role_pool_path()
    if not path.exists():
        raise DraftV2ConfigError(f"Missing required file: {path.name}")

    override_path = _role_pool_overrides_path()
    cache_key = (
        path.stat().st_mtime_ns,
        override_path.stat().st_mtime_ns if override_path.exists() else -1,
    )
    if (
        not refresh
        and _ROLE_POOL_CACHE["data"] is not None
        and _ROLE_POOL_CACHE["cache_key"] == cache_key
    ):
        return _ROLE_POOL_CACHE["data"], list(_ROLE_POOL_CACHE["warnings"])

    raw = _load_json(path)
    data, warnings = _validate_role_pool(raw)
    if override_path.exists():
        override_raw = _load_json(override_path)
        data, override_warnings = _merge_role_pool_overrides(data, override_raw)
        warnings.extend(override_warnings)

    _ROLE_POOL_CACHE["cache_key"] = cache_key
    _ROLE_POOL_CACHE["data"] = data
    _ROLE_POOL_CACHE["warnings"] = warnings
    return data, list(warnings)


def _load_tier_list_heroes() -> Set[str]:
    path = _tier_list_path()
    if not path.exists():
        return set()
    raw = _load_json(path)
    out: Set[str] = set()
    roles = (raw.get("roles") or {}).values()
    for role in roles:
        for h in (role or {}).get("heroDetails") or []:
            hero = _normalize_hero_name((h or {}).get("hero"))
            if hero:
                out.add(hero)
    return out


def get_draft_v2_meta(refresh: bool = False) -> Dict[str, Any]:
    role_pool, warnings = load_role_pool(refresh=refresh)

    heroes = role_pool.get("heroes") or {}
    flex_count = sum(1 for v in heroes.values() if len(v.get("possibleRoles") or []) > 1)

    tier_list_heroes = _load_tier_list_heroes()
    pool_heroes = set(heroes.keys())
    covered = len(pool_heroes & tier_list_heroes)
    tier_total = len(tier_list_heroes)
    coverage_rate = round((covered / tier_total), 4) if tier_total else 0.0
    uncovered = sorted(tier_list_heroes - pool_heroes)

    return {
        "engine": "draft_v2",
        "status": "phase_1_data_layer",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sequence": {
            "key": DRAFT_V2_SEQUENCE_KEY,
            "steps": DRAFT_V2_SEQUENCE,
        },
        "rolePool": {
            "version": role_pool.get("version"),
            "source": role_pool.get("source"),
            "roles": role_pool.get("roles"),
            "heroesCount": len(heroes),
            "flexHeroesCount": flex_count,
            "coverage": {
                "tierListHeroes": tier_total,
                "coveredHeroes": covered,
                "coverageRate": coverage_rate,
                "uncoveredHeroesSample": uncovered[:15],
            },
        },
        "scoring": DRAFT_V2_SCORING,
        "warnings": warnings[:30],
    }
