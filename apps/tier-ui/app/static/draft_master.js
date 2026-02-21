(function () {
  const dataNode = document.getElementById("draft-data");
  if (!dataNode) return;

  const payload = JSON.parse(dataNode.textContent || "{}");
  const roleOrder = payload.roleOrder || ["exp_lane", "jungle", "mid_lane", "gold_lane", "roam"];
  const roles = payload.roles || {};
  const apiBase = payload.apiBase || "";

  const roleLabels = {
    exp_lane: "Exp Lane",
    jungle: "Jungle",
    mid_lane: "Mid Lane",
    gold_lane: "Gold Lane",
    roam: "Roam",
  };

  const tierWeights = { SS: 30, S: 22, A: 14, B: 8, C: 3, D: 0 };
  const sequence = [
    { type: "ban", side: "ally", count: 2, text: "Ally ban 2 heroes" },
    { type: "ban", side: "enemy", count: 2, text: "Enemy ban 2 heroes" },
    { type: "ban", side: "ally", count: 1, text: "Ally ban 1 hero" },
    { type: "ban", side: "enemy", count: 1, text: "Enemy ban 1 hero" },
    { type: "pick", side: "ally", count: 1, text: "Ally pick 1 hero" },
    { type: "pick", side: "enemy", count: 2, text: "Enemy pick 2 heroes" },
    { type: "pick", side: "ally", count: 2, text: "Ally pick 2 heroes" },
    { type: "pick", side: "enemy", count: 1, text: "Enemy pick 1 hero" },
    { type: "ban", side: "enemy", count: 1, text: "Enemy ban 1 hero" },
    { type: "ban", side: "ally", count: 1, text: "Ally ban 1 hero" },
    { type: "ban", side: "enemy", count: 1, text: "Enemy ban 1 hero" },
    { type: "ban", side: "ally", count: 1, text: "Ally ban 1 hero" },
    { type: "pick", side: "enemy", count: 1, text: "Enemy pick 1 hero" },
    { type: "pick", side: "ally", count: 2, text: "Ally pick 2 last heroes" },
    { type: "pick", side: "enemy", count: 1, text: "Enemy pick 1 last hero" },
  ];

  const CONTRAST_STORAGE_KEY = "draft_master_high_contrast";
  const ENGINE_STORAGE_KEY = "draft_master_engine";
  const DEFAULT_ENGINE = payload.defaultEngine === "v1" ? "v1" : "v2";

  const state = {
    engine: DEFAULT_ENGINE,
    turnIndex: 0,
    actionProgress: 0,
    picks: {
      ally: Object.fromEntries(roleOrder.map((r) => [r, null])),
      enemy: Object.fromEntries(roleOrder.map((r) => [r, null])),
    },
    freePicks: { ally: [], enemy: [] },
    bans: { ally: [], enemy: [] },
    log: [],
    v2: {
      loading: false,
      error: null,
      lastKey: null,
      requestId: 0,
      recommendations: [],
      composition: null,
      turn: null,
      warnings: [],
      analyzeAssignments: null,
    },
  };

  const el = {
    draftRoot: document.getElementById("draft-master"),
    contrastToggleBtn: document.getElementById("contrast-toggle-btn"),
    engineSelect: document.getElementById("engine-select"),
    engineStatus: document.getElementById("engine-status"),
    allyCount: document.getElementById("ally-count"),
    enemyCount: document.getElementById("enemy-count"),
    allySlots: document.getElementById("ally-slots"),
    enemySlots: document.getElementById("enemy-slots"),
    allyRoleIndicators: document.getElementById("ally-role-indicators"),
    enemyRoleIndicators: document.getElementById("enemy-role-indicators"),
    allyBans: document.getElementById("ally-bans"),
    enemyBans: document.getElementById("enemy-bans"),
    turnLabel: document.getElementById("turn-label"),
    turnHint: document.getElementById("turn-hint"),
    turnProgress: document.getElementById("turn-progress"),
    turnWarning: document.getElementById("turn-warning"),
    recommendWrap: document.querySelector(".recommend-wrap"),
    recommendList: document.getElementById("recommend-list"),
    manualSelect: document.getElementById("manual-hero-select"),
    manualActionBtn: document.getElementById("manual-action-btn"),
    skipTurnBtn: document.getElementById("skip-turn-btn"),
    clearBtn: document.getElementById("clear-matchup-btn"),
    clearBtnBottom: document.getElementById("clear-matchup-btn-bottom"),
    draftOrder: document.getElementById("draft-order"),
    analyzeBtn: document.getElementById("analyze-btn"),
    analysis: document.getElementById("analysis-result"),
    analysisWinner: document.getElementById("analysis-winner"),
    allyTotal: document.getElementById("ally-total"),
    enemyTotal: document.getElementById("enemy-total"),
    allyBreakdown: document.getElementById("ally-breakdown"),
    enemyBreakdown: document.getElementById("enemy-breakdown"),
    analysisProb: document.getElementById("analysis-prob"),
  };

  function titleHero(name) {
    if (!name) return "-";
    return String(name)
      .split(" ")
      .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : ""))
      .join(" ");
  }

  function tierFromScore(score) {
    const s = Number(score) || 0;
    if (s >= 96) return "SS";
    if (s >= 86) return "S";
    if (s >= 72) return "A";
    if (s >= 58) return "B";
    if (s >= 43) return "C";
    return "D";
  }

  function uniqueList(values) {
    const out = [];
    const seen = new Set();
    values.forEach((v) => {
      const x = String(v || "").trim().toLowerCase();
      if (!x || seen.has(x)) return;
      seen.add(x);
      out.push(x);
    });
    return out;
  }

  function setEngineParamInUrl(engine) {
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("engine", engine);
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    } catch (e) {
      // ignore
    }
  }

  function syncEngineLinks(engine) {
    document.querySelectorAll("a[href]").forEach((a) => {
      try {
        const raw = a.getAttribute("href") || "";
        if (!raw) return;
        const u = new URL(raw, window.location.origin);
        if (!u.searchParams.has("engine")) return;
        u.searchParams.set("engine", engine);
        a.setAttribute("href", `${u.pathname}${u.search}${u.hash}`);
      } catch (e) {
        // ignore malformed href
      }
    });
  }

  function listHeroesForRole(role) {
    return ((roles[role] || {}).heroDetails || []).slice();
  }

  function getHeroDetail(role, hero) {
    const exact = listHeroesForRole(role).find((h) => h.hero === hero) || null;
    if (exact) return exact;

    let best = null;
    roleOrder.forEach((r) => {
      const hit = listHeroesForRole(r).find((h) => h.hero === hero);
      if (!hit) return;
      if (!best || Number(hit.score || 0) > Number(best.score || 0)) {
        best = hit;
      }
    });
    return best;
  }

  function getAllHeroEntries() {
    const best = new Map();
    roleOrder.forEach((role) => {
      listHeroesForRole(role).forEach((h) => {
        const prev = best.get(h.hero);
        if (!prev || Number(h.score || 0) > Number(prev.score || 0)) {
          best.set(h.hero, { role, ...h });
        }
      });
    });
    return Array.from(best.values());
  }

  const allHeroEntries = getAllHeroEntries();

  function hasKnownHero(hero) {
    return allHeroEntries.some((h) => h.hero === hero);
  }

  function rolePicksToList(side) {
    return roleOrder.map((r) => state.picks[side][r]).filter(Boolean);
  }

  function currentPicks(side) {
    return state.engine === "v2" ? state.freePicks[side].slice() : rolePicksToList(side);
  }

  function pickCount(side) {
    return currentPicks(side).length;
  }

  function isBanned(hero) {
    return state.bans.ally.includes(hero) || state.bans.enemy.includes(hero);
  }

  function isPicked(hero) {
    return currentPicks("ally").includes(hero) || currentPicks("enemy").includes(hero);
  }

  function pushLog(line) {
    state.log.push(line);
    if (state.log.length > 18) state.log.shift();
  }

  function getCurrentAction() {
    while (state.turnIndex < sequence.length) {
      const act = sequence[state.turnIndex];
      const remainingSlots = roleOrder.length - pickCount(act.side);
      const limit = act.type === "pick"
        ? Math.min(act.count, Math.max(remainingSlots + state.actionProgress, 0))
        : act.count;

      if (limit <= 0 || state.actionProgress >= limit) {
        state.turnIndex += 1;
        state.actionProgress = 0;
        continue;
      }
      return { ...act, limit };
    }
    return null;
  }

  function nextOpenRole(side) {
    if (state.engine === "v2") return null;
    return roleOrder.find((r) => !state.picks[side][r]) || null;
  }

  function projectedRoleMap(side) {
    if (state.engine !== "v2") return state.picks[side];
    if (state.v2.analyzeAssignments && state.v2.analyzeAssignments[side]) {
      return state.v2.analyzeAssignments[side];
    }
    return (state.v2.composition && state.v2.composition[side] && state.v2.composition[side].bestAssignment) || {};
  }

  function openRoles(side) {
    if (state.engine !== "v2") {
      return roleOrder.filter((r) => !state.picks[side][r]);
    }
    const fromApi = state.v2.composition && state.v2.composition[side] && state.v2.composition[side].openRoles;
    if (Array.isArray(fromApi) && fromApi.length) return fromApi.slice();
    const map = projectedRoleMap(side);
    return roleOrder.filter((r) => !map[r]);
  }

  function picksOf(side) {
    return currentPicks(side);
  }

  function roleOfHero(side, hero) {
    const map = projectedRoleMap(side);
    return roleOrder.find((r) => map[r] === hero) || null;
  }

  function targetRolesForPickAction(action) {
    if (!action || action.type !== "pick") return [];
    const open = openRoles(action.side);
    const remaining = Math.max(action.limit - state.actionProgress, 0);
    return open.slice(0, remaining);
  }

  function normalizeEncounters(encounters) {
    return Math.min((Number(encounters) || 0) / 5, 1);
  }

  function toCounterMap(hero, keyField, valueField) {
    const m = new Map();
    ((hero.counters || {})[keyField] || []).forEach((x) => {
      m.set(x.hero, Number(x[valueField] || 0));
    });
    return m;
  }

  function counterImpact(hero, targetHero) {
    const strongList = ((hero.counters || {}).strongAgainst || []);
    const weakList = ((hero.counters || {}).counteredBy || []);
    const strong = strongList.find((x) => x.hero === targetHero);
    const weak = weakList.find((x) => x.hero === targetHero);

    const strongVal = strong ? (Number(strong.winRate || 0) * normalizeEncounters(strong.encounters)) : 0;
    const weakVal = weak ? (Number(weak.opponentWinRate || 0) * normalizeEncounters(weak.encounters)) : 0;
    return { strongVal, weakVal, net: strongVal - weakVal };
  }

  function recommendationScoreForPick(hero, side) {
    const enemySide = side === "ally" ? "enemy" : "ally";
    const enemyPicks = picksOf(enemySide);
    const strong = toCounterMap(hero, "strongAgainst", "winRate");
    const weak = toCounterMap(hero, "counteredBy", "opponentWinRate");

    let score = hero.score * 100 + (tierWeights[hero.tier] || 0) + (hero.stats.winRate || 0) * 20;
    enemyPicks.forEach((e) => {
      if (strong.has(e)) score += strong.get(e) * 35;
      if (weak.has(e)) score -= weak.get(e) * 30;
    });
    return score;
  }

  function recommendationScoreForBan(hero, side) {
    const myPicks = picksOf(side);
    const strong = toCounterMap(hero, "strongAgainst", "winRate");
    const weak = toCounterMap(hero, "counteredBy", "opponentWinRate");

    let score = hero.score * 100 + (tierWeights[hero.tier] || 0) + (hero.stats.banCount || 0) * 0.5;
    myPicks.forEach((mine) => {
      if (strong.has(mine)) score += strong.get(mine) * 40;
      if (weak.has(mine)) score -= weak.get(mine) * 15;
    });
    return score;
  }

  function mapV2Recommendation(mode, r) {
    const rolesPred = Array.isArray(r.predictedRoles) ? r.predictedRoles : [];
    const tier = tierFromScore(r.tierScore);
    return {
      hero: r.hero,
      role: rolesPred[0] || "",
      roles: rolesPred,
      tier,
      tierRank: Number(r.tierScore || 0),
      score: Number(r.score || 0),
      mode,
      reasons: Array.isArray(r.reasons) ? r.reasons : [],
      components: r.components || {},
      debug: r.debug || null,
      flex: rolesPred.length > 1,
    };
  }

  function getRecommendations(action) {
    if (!action) return [];

    if (state.engine === "v2") {
      return state.v2.recommendations || [];
    }

    const availableRoles = new Set(openRoles(action.side));
    if (action.type === "pick") {
      const role = nextOpenRole(action.side);
      if (!role) return [];

      return listHeroesForRole(role)
        .filter((h) => !isBanned(h.hero) && !isPicked(h.hero))
        .map((h) => ({
          hero: h.hero,
          role,
          roles: [role],
          tier: h.tier,
          tierRank: tierWeights[h.tier] || 0,
          score: recommendationScoreForPick(h, action.side),
          mode: "pick",
          reasons: [],
          flex: false,
        }))
        .sort((a, b) => (b.tierRank - a.tierRank) || (b.score - a.score))
        .slice(0, 6);
    }

    return allHeroEntries
      .filter((h) => !isBanned(h.hero) && !isPicked(h.hero))
      .filter((h) => availableRoles.has(h.role))
      .map((h) => ({
        hero: h.hero,
        role: h.role,
        roles: [h.role],
        tier: h.tier,
        tierRank: tierWeights[h.tier] || 0,
        score: recommendationScoreForBan(h, action.side),
        mode: "ban",
        reasons: [],
        flex: false,
      }))
      .sort((a, b) => (b.tierRank - a.tierRank) || (b.score - a.score))
      .slice(0, 12);
  }

  function serializeV2State() {
    return {
      turnIndex: state.turnIndex,
      actionProgress: state.actionProgress,
      picks: {
        ally: currentPicks("ally"),
        enemy: currentPicks("enemy"),
      },
      bans: {
        ally: state.bans.ally.slice(),
        enemy: state.bans.enemy.slice(),
      },
    };
  }

  async function refreshV2Recommendations(force = false) {
    if (state.engine !== "v2") return;

    const body = serializeV2State();
    const key = JSON.stringify(body);
    if (!force && state.v2.lastKey === key) return;

    state.v2.lastKey = key;
    const reqId = ++state.v2.requestId;
    state.v2.loading = true;
    state.v2.error = null;

    render();

    try {
      const res = await fetch(`${apiBase}/api/draft/v2/recommend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      let json = null;
      try {
        json = await res.json();
      } catch (e) {
        json = null;
      }

      if (!res.ok) {
        const detail = (json && json.detail) ? json.detail : `HTTP ${res.status}`;
        throw new Error(String(detail));
      }

      if (reqId !== state.v2.requestId) return;

      state.v2.loading = false;
      state.v2.error = null;
      state.v2.composition = json.composition || null;
      state.v2.turn = json.turn || null;
      state.v2.warnings = Array.isArray(json.warnings) ? json.warnings : [];
      state.v2.recommendations = (json.recommendations || []).map((r) => mapV2Recommendation(json.mode, r));

      if (!json.mode && json.composition) {
        state.v2.analyzeAssignments = {
          ally: ((json.composition.ally || {}).bestAssignment || {}),
          enemy: ((json.composition.enemy || {}).bestAssignment || {}),
        };
      }

      render();
    } catch (err) {
      if (reqId !== state.v2.requestId) return;
      state.v2.loading = false;
      state.v2.recommendations = [];
      state.v2.error = (err && err.message) ? err.message : "Gagal memuat rekomendasi engine v2";
      render();
    }
  }

  async function fetchV2Assign(heroes) {
    const res = await fetch(`${apiBase}/api/draft/v2/assign`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ heroes }),
    });

    let json = null;
    try {
      json = await res.json();
    } catch (e) {
      json = null;
    }

    if (!res.ok) {
      const detail = (json && json.detail) ? json.detail : `HTTP ${res.status}`;
      throw new Error(String(detail));
    }
    return json;
  }

  function setRolePicksFromList(side, heroes, preferredRoleMap) {
    const next = Object.fromEntries(roleOrder.map((r) => [r, null]));
    const heroList = uniqueList(heroes);
    const used = new Set();

    const pref = preferredRoleMap || {};
    roleOrder.forEach((role) => {
      const hero = String(pref[role] || "").trim().toLowerCase();
      if (!hero || used.has(hero) || !heroList.includes(hero)) return;
      next[role] = hero;
      used.add(hero);
    });

    heroList.forEach((hero) => {
      if (used.has(hero)) return;
      const open = roleOrder.find((r) => !next[r]);
      if (!open) return;
      next[open] = hero;
      used.add(hero);
    });

    state.picks[side] = next;
  }

  function switchEngine(nextEngine) {
    const target = nextEngine === "v1" ? "v1" : "v2";
    if (target === state.engine) return;

    const allyHeroes = currentPicks("ally");
    const enemyHeroes = currentPicks("enemy");

    const allyPref = state.engine === "v2"
      ? ((state.v2.composition && state.v2.composition.ally && state.v2.composition.ally.bestAssignment) || {})
      : state.picks.ally;
    const enemyPref = state.engine === "v2"
      ? ((state.v2.composition && state.v2.composition.enemy && state.v2.composition.enemy.bestAssignment) || {})
      : state.picks.enemy;

    state.engine = target;
    localStorage.setItem(ENGINE_STORAGE_KEY, target);
    setEngineParamInUrl(target);
    syncEngineLinks(target);

    if (target === "v2") {
      state.freePicks.ally = uniqueList(allyHeroes).slice(0, roleOrder.length);
      state.freePicks.enemy = uniqueList(enemyHeroes).slice(0, roleOrder.length);
      state.v2.lastKey = null;
      state.v2.error = null;
      state.v2.analyzeAssignments = null;
    } else {
      setRolePicksFromList("ally", allyHeroes, allyPref);
      setRolePicksFromList("enemy", enemyHeroes, enemyPref);
      state.v2.analyzeAssignments = null;
    }

    render();
  }

  function applyAction(heroName) {
    const action = getCurrentAction();
    if (!action) return;

    const hero = String(heroName || "").trim().toLowerCase();
    if (!hero) return;
    if (isBanned(hero) || isPicked(hero)) return;

    if (action.type === "pick") {
      if (pickCount(action.side) >= roleOrder.length) return;

      if (state.engine === "v2") {
        if (!hasKnownHero(hero)) return;
        state.freePicks[action.side] = uniqueList(state.freePicks[action.side].concat([hero])).slice(0, roleOrder.length);
        state.v2.analyzeAssignments = null;
        pushLog(`${action.side.toUpperCase()} PICK ${titleHero(hero)} (Auto Role)`);
      } else {
        const role = nextOpenRole(action.side);
        if (!role) return;
        const candidate = getHeroDetail(role, hero);
        if (!candidate) return;
        state.picks[action.side][role] = hero;
        pushLog(`${action.side.toUpperCase()} PICK ${titleHero(hero)} (${roleLabels[role]})`);
      }
    } else {
      if (!hasKnownHero(hero)) return;
      state.bans[action.side].push(hero);
      pushLog(`${action.side.toUpperCase()} BAN ${titleHero(hero)}`);
    }

    state.actionProgress += 1;
    getCurrentAction();
    render();
  }

  function skipAction() {
    const action = getCurrentAction();
    if (!action) return;

    state.actionProgress = action.limit;
    pushLog(`${action.side.toUpperCase()} ${action.type.toUpperCase()} skipped`);
    getCurrentAction();
    render();
  }

  function resetDraft() {
    state.turnIndex = 0;
    state.actionProgress = 0;
    state.bans = { ally: [], enemy: [] };
    state.picks = {
      ally: Object.fromEntries(roleOrder.map((r) => [r, null])),
      enemy: Object.fromEntries(roleOrder.map((r) => [r, null])),
    };
    state.freePicks = { ally: [], enemy: [] };
    state.log = [];

    state.v2.loading = false;
    state.v2.error = null;
    state.v2.lastKey = null;
    state.v2.recommendations = [];
    state.v2.composition = null;
    state.v2.turn = null;
    state.v2.warnings = [];
    state.v2.analyzeAssignments = null;

    el.analysis.classList.add("hidden");
    render();
  }

  function renderSlots(side, mount, action) {
    mount.innerHTML = "";
    const targetRoles = new Set(action && action.side === side ? targetRolesForPickAction(action) : []);
    const roleMap = projectedRoleMap(side);

    roleOrder.forEach((role) => {
      const hero = roleMap[role] || null;
      const div = document.createElement("div");
      const isTarget = !hero && targetRoles.has(role);
      div.className = `slot-item ${hero ? "filled" : "empty"}${isTarget ? " target-slot" : ""}`;
      div.innerHTML = `
        <div class="slot-head">
          <strong>${roleLabels[role]}</strong>
          <em class="slot-state ${hero ? "locked" : isTarget ? "target" : "open"}">
            ${hero ? "LOCKED" : isTarget ? "NEXT PICK" : "OPEN"}
          </em>
        </div>
        <span>${hero ? titleHero(hero) : "Empty Slot"}</span>
      `;
      mount.appendChild(div);
    });

    if (state.engine === "v2") {
      const assigned = new Set(Object.values(roleMap).filter(Boolean));
      const unassigned = currentPicks(side).filter((h) => !assigned.has(h));
      if (unassigned.length) {
        const note = document.createElement("div");
        note.className = "slot-unassigned";
        note.textContent = `Unassigned: ${unassigned.map(titleHero).join(", ")}`;
        mount.appendChild(note);
      }
    }
  }

  function renderRoleIndicators(side, mount, action) {
    mount.innerHTML = "";
    const targetRoles = new Set(action && action.side === side ? targetRolesForPickAction(action) : []);
    const roleMap = projectedRoleMap(side);
    const open = new Set(openRoles(side));

    roleOrder.forEach((role) => {
      const filled = !!roleMap[role] || !open.has(role);
      const isTarget = !filled && targetRoles.has(role);
      const chip = document.createElement("span");
      chip.className = `role-chip ${filled ? "locked" : isTarget ? "target" : "open"}`;
      chip.textContent = roleLabels[role];
      mount.appendChild(chip);
    });
  }

  function renderBans(side, mount) {
    mount.innerHTML = "";
    if (!state.bans[side].length) {
      mount.innerHTML = '<span class="ban-chip empty">No bans yet</span>';
      return;
    }

    state.bans[side].forEach((h) => {
      const chip = document.createElement("span");
      chip.className = "ban-chip";
      chip.textContent = titleHero(h);
      mount.appendChild(chip);
    });
  }

  function renderDraftOrder(action) {
    if (!el.draftOrder) return;
    el.draftOrder.innerHTML = "";

    sequence.forEach((s, idx) => {
      const li = document.createElement("li");
      li.className = idx < state.turnIndex ? "done" : idx === state.turnIndex ? "active" : "pending";
      const marker = idx === state.turnIndex && action ? ` (${state.actionProgress}/${action.limit})` : "";
      li.textContent = `${idx + 1}. ${s.text}${marker}`;
      el.draftOrder.appendChild(li);
    });

    if (state.log.length) {
      const logTitle = document.createElement("li");
      logTitle.className = "log-title";
      logTitle.textContent = "Recent Actions";
      el.draftOrder.appendChild(logTitle);

      state.log.slice().reverse().forEach((line) => {
        const log = document.createElement("li");
        log.className = "log-line";
        log.textContent = `- ${line}`;
        el.draftOrder.appendChild(log);
      });
    }
  }

  function renderManualOptions(action, recommendations) {
    el.manualSelect.innerHTML = "";

    if (!action) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Draft completed";
      el.manualSelect.appendChild(opt);
      return;
    }

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = action.type === "pick" ? "Select hero to pick" : "Select hero to ban";
    el.manualSelect.appendChild(placeholder);

    let list = recommendations.slice();

    if (!list.length) {
      const availableRoles = new Set(openRoles(action.side));
      if (action.type === "pick") {
        if (state.engine === "v2") {
          list = allHeroEntries
            .filter((h) => !isBanned(h.hero) && !isPicked(h.hero))
            .map((h) => ({
              hero: h.hero,
              roles: [h.role],
              role: h.role,
              tier: h.tier,
              score: (h.score || 0) * 100,
              flex: false,
            }))
            .sort((a, b) => ((tierWeights[b.tier] || 0) - (tierWeights[a.tier] || 0)) || (b.score - a.score))
            .slice(0, 30);
        } else {
          const role = nextOpenRole(action.side);
          list = role
            ? listHeroesForRole(role)
              .filter((h) => !isBanned(h.hero) && !isPicked(h.hero))
              .map((h) => ({ hero: h.hero, roles: [role], role, tier: h.tier, score: (h.score || 0) * 100, flex: false }))
            : [];
        }
      } else {
        list = allHeroEntries
          .filter((h) => !isBanned(h.hero) && !isPicked(h.hero))
          .filter((h) => state.engine === "v2" || availableRoles.has(h.role))
          .map((h) => ({ hero: h.hero, roles: [h.role], role: h.role, tier: h.tier, score: (h.score || 0) * 100, flex: false }))
          .sort((a, b) => ((tierWeights[b.tier] || 0) - (tierWeights[a.tier] || 0)) || (b.score - a.score))
          .slice(0, 30);
      }
    }

    list.forEach((r) => {
      if (isBanned(r.hero) || isPicked(r.hero)) return;
      const roleText = (r.roles && r.roles.length)
        ? r.roles.map((x) => roleLabels[x] || x).join("/")
        : (roleLabels[r.role] || r.role || "-");
      const opt = document.createElement("option");
      opt.value = r.hero;
      opt.textContent = `${titleHero(r.hero)} (${roleText}, ${r.tier || "-"}${r.flex ? ", Flex" : ""})`;
      el.manualSelect.appendChild(opt);
    });
  }

  function renderRecommendations(action, recommendations) {
    el.recommendList.innerHTML = "";

    if (!action) {
      if (el.recommendWrap) el.recommendWrap.classList.add("is-hidden");
      return;
    }

    if (state.engine === "v2" && state.v2.loading && !recommendations.length) {
      if (el.recommendWrap) el.recommendWrap.classList.remove("is-hidden");
      el.recommendList.innerHTML = '<p class="small">Memuat rekomendasi engine v2...</p>';
      return;
    }

    if (state.engine === "v2" && state.v2.error && !recommendations.length) {
      if (el.recommendWrap) el.recommendWrap.classList.remove("is-hidden");
      el.recommendList.innerHTML = `<p class="small">Gagal load rekomendasi: ${state.v2.error}</p>`;
      return;
    }

    if (!recommendations.length) {
      if (el.recommendWrap) el.recommendWrap.classList.add("is-hidden");
      return;
    }

    if (el.recommendWrap) el.recommendWrap.classList.remove("is-hidden");

    recommendations.forEach((r) => {
      const roleText = (r.roles && r.roles.length)
        ? r.roles.map((x) => roleLabels[x] || x).join("/")
        : (roleLabels[r.role] || r.role || "-");

      const btn = document.createElement("button");
      btn.className = "rec-card";
      btn.type = "button";
      btn.innerHTML = `
        <span class="rec-head">
          <strong>${titleHero(r.hero)}</strong>
          ${r.flex ? '<span class="rec-badge">FLEX</span>' : ""}
        </span>
        <span>${roleText} | Tier ${r.tier || "-"}</span>
        <span>Score ${Number(r.score || 0).toFixed(2)}</span>
        ${r.reasons && r.reasons[0] ? `<span class="rec-reason">${r.reasons[0]}</span>` : ""}
      `;
      btn.addEventListener("click", () => applyAction(r.hero));
      el.recommendList.appendChild(btn);
    });
  }

  function getRoleMapForMetrics(side, overrideMap) {
    if (overrideMap) return overrideMap;
    return projectedRoleMap(side);
  }

  function teamMetrics(side, overrideMap, overrideEnemyMap) {
    const enemy = side === "ally" ? "enemy" : "ally";
    const roleMap = getRoleMapForMetrics(side, overrideMap);
    const enemyRoleMap = getRoleMapForMetrics(enemy, overrideEnemyMap);

    const picks = roleOrder.map((r) => ({ role: r, hero: roleMap[r] })).filter((x) => x.hero);
    const enemyPicks = roleOrder.map((r) => enemyRoleMap[r]).filter(Boolean);

    let heroPower = 0;
    let laneEdge = 0;
    let counterMatrix = 0;
    let stability = 0;
    let threat = 0;

    picks.forEach((p) => {
      const hero = getHeroDetail(p.role, p.hero);
      if (!hero) return;

      heroPower += (Number(hero.score || 0) * 35) + (Number((hero.stats || {}).winRate || 0) * 20) + ((tierWeights[hero.tier] || 0) * 1.2);
      stability += (Number((hero.stats || {}).winRate || 0) * 8) + (Math.log1p(Number((hero.stats || {}).pickCount || 0)) * 1.5);
      threat += Number((hero.stats || {}).banCount || 0) * 0.08;

      const enemyRoleHero = enemyRoleMap[p.role];
      if (enemyRoleHero) {
        const lane = counterImpact(hero, enemyRoleHero);
        laneEdge += lane.net * 65;
      }

      enemyPicks.forEach((e) => {
        const impact = counterImpact(hero, e);
        counterMatrix += impact.net * 22;
      });
    });

    const total = heroPower + laneEdge + counterMatrix + stability + threat;
    return { total, heroPower, laneEdge, counterMatrix, stability, threat };
  }

  async function analyzeMatchup() {
    if (pickCount("ally") < roleOrder.length || pickCount("enemy") < roleOrder.length) return;

    if (state.engine === "v2") {
      try {
        el.analyzeBtn.disabled = true;
        const [allyAssign, enemyAssign] = await Promise.all([
          fetchV2Assign(currentPicks("ally")),
          fetchV2Assign(currentPicks("enemy")),
        ]);

        state.v2.analyzeAssignments = {
          ally: ((allyAssign.assignment || {}).bestAssignment || {}),
          enemy: ((enemyAssign.assignment || {}).bestAssignment || {}),
        };

        if (!((allyAssign.assignment || {}).isFeasible) || !((enemyAssign.assignment || {}).isFeasible)) {
          el.analysisWinner.textContent = "Draft Tidak Feasible";
          el.allyTotal.textContent = "0.0";
          el.enemyTotal.textContent = "0.0";
          el.allyBreakdown.textContent = "Role assignment ally tidak feasible.";
          el.enemyBreakdown.textContent = "Role assignment enemy tidak feasible.";
          el.analysisProb.textContent = "Perbaiki komposisi hero agar semua role bisa terisi.";
          el.analysis.classList.remove("hidden");
          render();
          return;
        }
      } catch (err) {
        const msg = (err && err.message) ? err.message : "Gagal analyze dengan engine v2";
        if (el.turnWarning) {
          el.turnWarning.textContent = msg;
          el.turnWarning.classList.remove("hidden");
        }
        render();
        return;
      }
    }

    const allyMap = state.engine === "v2" ? (state.v2.analyzeAssignments || {}).ally : null;
    const enemyMap = state.engine === "v2" ? (state.v2.analyzeAssignments || {}).enemy : null;

    const ally = teamMetrics("ally", allyMap, enemyMap);
    const enemy = teamMetrics("enemy", enemyMap, allyMap);
    const diff = ally.total - enemy.total;
    const allyProb = (1 / (1 + Math.exp(-(diff / 35)))) * 100;
    const enemyProb = 100 - allyProb;

    const winner = Math.abs(diff) < 8
      ? "Balanced Draft"
      : ally.total > enemy.total
        ? "Ally Team Advantage"
        : "Enemy Team Advantage";

    el.analysisWinner.textContent = winner;
    el.allyTotal.textContent = ally.total.toFixed(1);
    el.enemyTotal.textContent = enemy.total.toFixed(1);
    el.allyBreakdown.textContent = `Power ${ally.heroPower.toFixed(1)} | LaneEdge ${ally.laneEdge.toFixed(1)} | Counter ${ally.counterMatrix.toFixed(1)} | Stability ${ally.stability.toFixed(1)} | Threat ${ally.threat.toFixed(1)}`;
    el.enemyBreakdown.textContent = `Power ${enemy.heroPower.toFixed(1)} | LaneEdge ${enemy.laneEdge.toFixed(1)} | Counter ${enemy.counterMatrix.toFixed(1)} | Stability ${enemy.stability.toFixed(1)} | Threat ${enemy.threat.toFixed(1)}`;
    el.analysisProb.textContent = `Prediction: Ally ${allyProb.toFixed(1)}% vs Enemy ${enemyProb.toFixed(1)}% (edge ${diff.toFixed(1)})`;
    el.analysis.classList.remove("hidden");

    render();
  }

  function applyContrastMode(enabled) {
    if (!el.draftRoot || !el.contrastToggleBtn) return;
    el.draftRoot.classList.toggle("hc", !!enabled);
    el.contrastToggleBtn.setAttribute("aria-pressed", enabled ? "true" : "false");
    el.contrastToggleBtn.textContent = `Kontras Tinggi: ${enabled ? "Nyala" : "Mati"}`;
  }

  function initContrastMode() {
    const saved = localStorage.getItem(CONTRAST_STORAGE_KEY);
    applyContrastMode(saved === "1");
  }

  function toggleContrastMode() {
    const next = !el.draftRoot.classList.contains("hc");
    localStorage.setItem(CONTRAST_STORAGE_KEY, next ? "1" : "0");
    applyContrastMode(next);
  }

  function initEngine() {
    const qsEngine = (() => {
      try {
        const params = new URLSearchParams(window.location.search || "");
        const e = params.get("engine");
        return (e === "v1" || e === "v2") ? e : null;
      } catch (err) {
        return null;
      }
    })();
    const saved = localStorage.getItem(ENGINE_STORAGE_KEY);
    if (qsEngine) {
      state.engine = qsEngine;
    } else if (saved === "v1" || saved === "v2") {
      state.engine = saved;
    }
    localStorage.setItem(ENGINE_STORAGE_KEY, state.engine);
    setEngineParamInUrl(state.engine);
    syncEngineLinks(state.engine);
    if (el.engineSelect) {
      el.engineSelect.value = state.engine;
    }
  }

  function renderWarnings(action) {
    if (!el.turnWarning) return;

    let message = "";
    if (state.engine === "v2") {
      if (state.v2.error) {
        message = `Engine v2 error: ${state.v2.error}`;
      } else if (state.v2.composition && action && action.type === "pick") {
        const sideComp = state.v2.composition[action.side] || {};
        if (sideComp.isFeasible === false) {
          message = "Komposisi draft saat ini tidak feasible untuk semua role."
        }
      }

      if (!message && Array.isArray(state.v2.warnings) && state.v2.warnings.length) {
        message = state.v2.warnings[0];
      }
    }

    if (!message) {
      el.turnWarning.classList.add("hidden");
      el.turnWarning.textContent = "";
      return;
    }

    el.turnWarning.textContent = message;
    el.turnWarning.classList.remove("hidden");
  }

  function render() {
    const action = getCurrentAction();

    if (state.engine === "v2") {
      refreshV2Recommendations();
    }

    const recommendations = getRecommendations(action);
    const allyPicked = pickCount("ally");
    const enemyPicked = pickCount("enemy");

    el.allyCount.textContent = `${allyPicked}/5`;
    el.enemyCount.textContent = `${enemyPicked}/5`;

    if (el.engineSelect && el.engineSelect.value !== state.engine) {
      el.engineSelect.value = state.engine;
    }
    if (el.engineStatus) {
      el.engineStatus.textContent = state.engine === "v2" ? "Mode fleksibel aktif" : "Mode role-order aktif";
    }

    renderRoleIndicators("ally", el.allyRoleIndicators, action);
    renderRoleIndicators("enemy", el.enemyRoleIndicators, action);
    renderSlots("ally", el.allySlots, action);
    renderSlots("enemy", el.enemySlots, action);
    renderBans("ally", el.allyBans);
    renderBans("enemy", el.enemyBans);
    renderDraftOrder(action);

    if (!action) {
      el.turnLabel.textContent = "Draft Complete";
      el.turnHint.textContent = "All picks/ban steps selesai.";
      el.turnProgress.textContent = "";
      el.manualActionBtn.disabled = true;
      el.skipTurnBtn.disabled = true;
    } else {
      const sideName = action.side === "ally" ? "Ally Team" : "Enemy Team";
      el.turnLabel.textContent = `${sideName} ${action.type.toUpperCase()} TURN`;

      if (state.engine === "v2") {
        el.turnHint.textContent = action.type === "pick"
          ? "Pilih hero bebas role, sistem akan proyeksikan role otomatis."
          : "Ban bebas role. Fokus deny hero power lawan.";
      } else {
        const nextRole = action.type === "pick" ? nextOpenRole(action.side) : null;
        el.turnHint.textContent = action.type === "pick"
          ? `Current role: ${roleLabels[nextRole] || nextRole} (follow role order)`
          : "Ban bebas role. Pilih hero ancaman tertinggi.";
      }

      el.turnProgress.textContent = `${action.text} (${state.actionProgress}/${action.limit})`;
      el.manualActionBtn.disabled = false;
      el.skipTurnBtn.disabled = false;
    }

    renderWarnings(action);
    renderManualOptions(action, recommendations);
    renderRecommendations(action, recommendations);

    el.manualActionBtn.textContent = action ? (action.type === "pick" ? "Pick Hero" : "Ban Hero") : "Done";
    el.analyzeBtn.disabled = !(allyPicked === roleOrder.length && enemyPicked === roleOrder.length);
    if (el.analyzeBtn.disabled) {
      el.analysis.classList.add("hidden");
    }
  }

  el.manualActionBtn.addEventListener("click", () => {
    applyAction(el.manualSelect.value);
  });
  el.skipTurnBtn.addEventListener("click", skipAction);
  el.clearBtn.addEventListener("click", resetDraft);
  el.clearBtnBottom.addEventListener("click", resetDraft);
  el.analyzeBtn.addEventListener("click", () => {
    analyzeMatchup();
  });

  if (el.contrastToggleBtn) {
    el.contrastToggleBtn.addEventListener("click", toggleContrastMode);
  }

  if (el.engineSelect) {
    el.engineSelect.addEventListener("change", (evt) => {
      switchEngine((evt.target && evt.target.value) || "v2");
    });
  }

  initContrastMode();
  initEngine();
  render();
})();
