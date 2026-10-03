// ADR-0038: Bangkok Live Risk Intelligence. Stored Floodboard evidence with freshness and lineage.
// Provider text is always set with textContent; only this file's own strings use innerHTML.
(() => {
  const $ = (selector) => document.querySelector(selector);
  const PILOT = "bangkok";
  const API = `/api/v1/pilot/flood/${PILOT}`;
  const TZ = "Asia/Bangkok";
  const REFRESH_MS = 2 * 60 * 1000;
  const NEAR_M = 200;
  const NEAR_HOURS = 6;
  const NOW_BANDS = new Set(["current", "recent", "aging"]);
  const COLOURS = { ok: "#2f9e44", caution: "#e0a800", risky: "#e8590c", blocked: "#c92a2a" };
  const OLD = "#8a959b";
  const OPACITY = { current: 0.95, recent: 0.9, aging: 0.7, stale: 0.45, expired: 0.55, future: 0.5 };
  const state = {
    config: null, areas: [], area: "corridor", vehicle: "sedan", all: false,
    situation: null, roads: null, reports: null, selected: null,
  };
  const say = PilotText.t;
  let map = null;
  let roadLayer = null;
  let reportLayer = null;
  let outlineLayer = null;
  let selectedLayer = null;

  const clock = (iso) => new Intl.DateTimeFormat(PilotText.locale(), {
    timeZone: TZ, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(new Date(iso));
  const ago = (iso) => {
    const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (minutes < 90) return say("ago.min", { n: minutes });
    if (minutes < 48 * 60) return say("ago.hour", { n: Math.round(minutes / 60) });
    return say("ago.day", { n: Math.round(minutes / 1440) });
  };
  const number = (value) => new Intl.NumberFormat(PilotText.locale()).format(value);
  const sourceName = (id) => (say(`src.${id}`) === `src.${id}` ? id : say(`src.${id}`));

  const showBanner = (message) => {
    const banner = $("[data-banner]");
    banner.textContent = message || "";
    banner.hidden = !message;
  };

  // --- Geometry helpers (display only; the server owns analysis) ---------------------------
  const lines = (geometry) => (geometry.type === "MultiLineString" ? geometry.coordinates : [geometry.coordinates]);
  const vertices = (geometry) => lines(geometry).flat();
  const insideRing = ([x, y], ring) => {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
      const [xi, yi] = ring[i];
      const [xj, yj] = ring[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  };
  const insidePolygon = (point, rings) => insideRing(point, rings[0]) && !rings.slice(1).some((r) => insideRing(point, r));
  const insideArea = (point, outline) => {
    const polygons = outline.type === "MultiPolygon" ? outline.coordinates : [outline.coordinates];
    return polygons.some((rings) => insidePolygon(point, rings));
  };
  const metres = ([lon1, lat1], [lon2, lat2]) => {
    const rad = Math.PI / 180;
    const x = (lon2 - lon1) * rad * Math.cos(((lat1 + lat2) / 2) * rad);
    const y = (lat2 - lat1) * rad;
    return Math.sqrt(x * x + y * y) * 6371000;
  };

  const params = new URL(window.location.href).searchParams;
  const setUrl = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete("area");
    url.searchParams.delete("road");
    if (state.area !== "corridor") url.searchParams.set("area", state.area);
    if (state.selected) url.searchParams.set("road", state.selected.properties.id);
    window.history.replaceState(null, "", url);
  };

  // "all", one district code, or "corridor": the owner's demo corridor from the pilot config.
  const corridorCodes = () => (state.config && state.config.demo_corridor ? state.config.demo_corridor.areas || [] : []);
  const currentAreas = () => {
    if (state.area === "corridor") return state.areas.filter((a) => corridorCodes().includes(a.admin_code));
    return state.areas.filter((a) => a.admin_code === state.area);
  };
  const currentArea = () => currentAreas()[0] || null;
  const inArea = (geometry) => {
    const areas = currentAreas();
    if (!areas.length) return true;
    const points = geometry.type === "Point" ? [geometry.coordinates] : vertices(geometry);
    return points.some((p) => areas.some((area) => insideArea(p, area.outline)));
  };
  const visibleRoads = () => (state.roads ? state.roads.features.filter((f) => inArea(f.geometry)) : []);
  const visibleReports = () => (state.reports ? state.reports.features.filter((f) => inArea(f.geometry)) : []);

  // --- Map ---------------------------------------------------------------------------------
  const styleFor = (feature) => {
    const p = feature.properties;
    const verdict = p.provider_verdict ? p.provider_verdict[state.vehicle] : null;
    const derived = p.evidence_class === "provider_derived";
    return {
      color: verdict ? COLOURS[verdict] : OLD,
      weight: verdict === "blocked" ? 7 : verdict === "ok" ? 3 : 6,
      opacity: OPACITY[p.freshness] ?? 0.6,
      dashArray: derived ? "2 7" : p.freshness === "stale" ? "8 6" : null,
    };
  };

  const ensureMap = () => {
    if (map) return;
    const view = state.config.map;
    map = window.L.map($("[data-map]"), { scrollWheelZoom: true }).setView(view.center, view.zoom);
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap contributors · Flood data © Floodboard, CC BY 4.0",
    }).addTo(map);
  };

  const drawMap = () => {
    ensureMap();
    [roadLayer, reportLayer, outlineLayer, selectedLayer].forEach((layer) => layer && map.removeLayer(layer));
    selectedLayer = null;
    const area = currentArea();
    outlineLayer = area
      ? window.L.geoJSON({
          type: "FeatureCollection",
          features: currentAreas().map((a) => ({ type: "Feature", geometry: a.outline, properties: {} })),
        }, {
          style: { color: "#0d2534", weight: 2, dashArray: "6 5", fill: true, fillOpacity: 0.03 },
          interactive: false,
        }).addTo(map)
      : null;
    // Reports sit under the roads: the roads are the main signal, the dots are context.
    reportLayer = window.L.layerGroup(
      visibleReports()
        .filter((f) => f.properties.freshness !== "expired")
        .map((f) => window.L.circleMarker([f.geometry.coordinates[1], f.geometry.coordinates[0]], {
          radius: 2.5, color: "#7950f2", weight: 0, fillColor: "#7950f2",
          fillOpacity: NOW_BANDS.has(f.properties.freshness) ? 0.55 : 0.25, interactive: false,
        })),
    ).addTo(map);
    roadLayer = window.L.geoJSON({ type: "FeatureCollection", features: visibleRoads() }, {
      style: styleFor,
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        // Leaflet renders a string tooltip as HTML; provider names go in as text only.
        const tip = document.createElement("span");
        tip.textContent = p.name || p.name_en || say(p.road_class === "zone" ? "ev.zone" : "ev.unnamed");
        layer.bindTooltip(tip, { sticky: true });
        layer.on("click", () => showEvidence(feature));
      },
    }).addTo(map);
    if (area && outlineLayer) map.fitBounds(outlineLayer.getBounds(), { padding: [20, 20] });
  };

  const drawLegend = () => {
    const legend = $("[data-legend]");
    legend.replaceChildren();
    const item = (swatchStyle, text) => {
      const li = document.createElement("li");
      const swatch = document.createElement("span");
      swatch.className = "fl-swatch";
      Object.assign(swatch.style, swatchStyle);
      const label = document.createElement("span");
      label.textContent = text;
      li.append(swatch, label);
      legend.append(li);
    };
    Object.entries(COLOURS).forEach(([key, colour]) => item({ background: colour }, say(`leg.${key}`)));
    item({ background: OLD }, say("leg.old"));
    item({ background: "repeating-linear-gradient(90deg,#e8590c 0 3px,transparent 3px 8px)" }, say("leg.derived"));
    item({ background: "#7950f2", borderRadius: "50%", width: "0.6rem", height: "0.6rem" }, say("leg.report"));
  };

  // --- Cards and coverage --------------------------------------------------------------------
  const drawCards = () => {
    const roads = visibleRoads();
    const flooded = roads.filter((f) => !f.properties.cleared);
    const now = flooded.filter((f) => NOW_BANDS.has(f.properties.freshness));
    const set = (key, value) => { $(`[data-card="${key}"]`).textContent = number(value); };
    set("affected", now.length);
    set("blocked", now.filter((f) => f.properties.provider_verdict[state.vehicle] === "blocked").length);
    set("closed", now.filter((f) => f.properties.closed_all).length);
    set("old", flooded.length - now.length);
    const hourAgo = Date.now() - 3600 * 1000;
    set("reports", visibleReports().filter((f) => new Date(f.properties.observed_at).getTime() >= hourAgo).length);
    const notOk = state.situation.sources.filter((s) => s.state !== "ok").length;
    set("sources", notOk);
    $("[data-card-sources]").classList.toggle("is-warn", notOk > 0);
    const vehicle = say(`veh.${state.vehicle}`);
    $('[data-card-label="blocked"]').textContent = say("card.blocked", {
      vehicle: PilotText.lang() === "en" ? vehicle.toLowerCase() : vehicle,
    });
    const snapshot = state.roads.snapshot_retrieved_at;
    $("[data-asof]").textContent = snapshot
      ? say("fl.asof", { time: clock(new Date().toISOString()), age: ago(snapshot) })
      : say("fl.asof.none");
  };

  const drawCoverage = () => {
    const body = $("[data-coverage]");
    body.replaceChildren();
    const row = (what, stateText, detail, tone) => {
      const tr = document.createElement("tr");
      const cells = [what, stateText, detail].map((text) => {
        const td = document.createElement("td");
        td.textContent = text;
        return td;
      });
      cells[1].className = `fl-state fl-state--${tone}`;
      tr.append(...cells);
      body.append(tr);
    };
    state.situation.sources.forEach((s) => {
      const tone = s.state === "ok" ? "ok" : s.state === "degraded" ? "warn" : "bad";
      const detail = s.last_success_at
        ? say("cov.fb.detail", { age: ago(s.last_success_at), n: number(s.last_success_records ?? 0), license: s.license })
        : say("cov.fb.never");
      row(say(s.source_id === "floodboard_roads" ? "cov.fb.roads" : "cov.fb.reports"), say(`cov.${s.state}`), detail, tone);
    });
    row(say("cov.bma"), say("cov.not"), say("cov.bma.detail"), "none");
    row(say("cov.cctv"), say("cov.not"), say("cov.cctv.detail"), "none");
    row(say("cov.assets"), say("cov.not"), say("cov.assets.detail"), "none");
    row(say("cov.geoglows"), say("cov.elsewhere"), say("cov.geoglows.detail"), "none");
    $("[data-coverage-note]").textContent = `${say("cov.note")} ${say("cov.note.bbt")}`;
  };

  // --- Evidence card -----------------------------------------------------------------------
  const nearbyReports = (feature) => {
    const since = Date.now() - NEAR_HOURS * 3600 * 1000;
    const points = vertices(feature.geometry);
    return (state.reports ? state.reports.features : []).filter((r) => {
      if (new Date(r.properties.observed_at).getTime() < since) return false;
      const at = r.geometry.coordinates;
      return points.some((p) => metres(p, at) <= NEAR_M);
    });
  };

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const highlight = (feature) => {
    if (selectedLayer) map.removeLayer(selectedLayer);
    selectedLayer = window.L.geoJSON(feature, {
      style: { color: "#0d2534", weight: 12, opacity: 0.35 }, interactive: false,
    }).addTo(map);
    selectedLayer.bringToBack();
  };

  const showEvidence = (feature) => {
    state.selected = feature;
    setUrl();
    if (map) highlight(feature);
    const p = feature.properties;
    const box = $("[data-evidence]");
    box.replaceChildren();
    const title = p.road_class === "zone" ? say("ev.zone") : (PilotText.lang() === "en" && p.name_en) || p.name || p.name_en || say("ev.unnamed");
    box.append(el("h2", "fl-evidence__title", title));
    const badges = el("p", "fl-badges");
    badges.append(el("span", `fl-badge fl-badge--${p.evidence_class}`, say(`ev.class.${p.evidence_class}`)));
    badges.append(el("span", `fl-badge fl-badge--fresh-${p.freshness}`, say(`fresh.${p.freshness}`)));
    box.append(badges);

    box.append(el("h3", "fl-evidence__sub", say("ev.now")));
    const facts = el("dl", "rw-facts");
    const fact = (label, value) => { facts.append(el("dt", "", label), el("dd", "", value)); };
    fact(say("ev.depth"), p.depth_cm == null ? say("ev.depth.none") : `${number(p.depth_cm)} cm`);
    const status = [];
    status.push(say(p.cleared ? "ev.cleared" : "ev.flooded"));
    if (p.closed_all) status.push(say("ev.closedAll"));
    else if (p.closed_small) status.push(say("ev.closedSmall"));
    fact("", status.join(" · "));
    fact(say("ev.updated"), `${clock(p.reported_at)} (${ago(p.reported_at)})`);
    box.append(facts);

    box.append(el("h3", "fl-evidence__sub", say("ev.verdicts")));
    if (p.provider_verdict) {
      const chips = el("p", "fl-chips");
      ["motorbike", "sedan", "pickup", "truck"].forEach((v) => {
        const chip = el("span", `fl-chip fl-chip--${p.provider_verdict[v]}`, `${say(`veh.${v}`)}: ${say(`leg.${p.provider_verdict[v]}`)}`);
        chips.append(chip);
      });
      box.append(chips);
    } else {
      box.append(el("p", "fl-muted", say("ev.verdicts.gone")));
    }

    box.append(el("h3", "fl-evidence__sub", say("ev.rows")));
    const list = el("ul", "fl-rows");
    const evidenceRow = (name, text, tone) => {
      const li = el("li", `fl-row fl-row--${tone}`);
      li.append(el("strong", "", name), el("span", "", text));
      list.append(li);
    };
    const conf = p.provider_confidence == null ? "–" : number(Math.round(p.provider_confidence * 100) / 100);
    evidenceRow(say("ev.row.floodboard"), say("ev.row.floodboard.v", {
      state: say(p.cleared ? "ev.cleared" : "ev.flooded"), age: ago(p.reported_at), conf,
    }), "have");
    const lineage = (p.underlying_sources || []).map(sourceName).join(", ");
    if (lineage) evidenceRow(say("ev.row.lineage"), say("ev.row.lineage.v", { list: lineage }), "have");
    const viaBma = (p.underlying_sources || []).some((s) => s === "bma_sensor" || s === "bma_dds");
    evidenceRow(say("ev.row.bma"), say(viaBma ? "ev.row.bma.via" : "ev.row.bma.none"), viaBma ? "have" : "missing");
    const near = nearbyReports(feature);
    if (near.length) {
      const counts = {};
      near.forEach((r) => { counts[r.properties.underlying_source] = (counts[r.properties.underlying_source] || 0) + 1; });
      const text = Object.entries(counts).map(([s, n]) => `${sourceName(s)} ${n}`).join(", ");
      evidenceRow(say("ev.row.near"), say("ev.row.near.v", { n: near.length, list: text }), "have");
    } else {
      evidenceRow(say("ev.row.near"), say("ev.row.near.none"), "missing");
    }
    evidenceRow(say("ev.row.cctv"), say("ev.row.cctv.v"), "missing");
    evidenceRow(say("ev.row.check"), say("ev.row.check.v"), "pending");
    box.append(list);

    box.append(el("h3", "fl-evidence__sub", say("ev.affected")));
    box.append(el("p", "fl-muted", say("ev.affected.v")));
  };

  // --- Loading -----------------------------------------------------------------------------
  const drawAll = () => {
    if (!state.situation || !state.roads) return;
    drawCards();
    drawCoverage();
    drawLegend();
    drawMap();
    if (!state.roads.snapshot_retrieved_at) showBanner(say("fl.empty"));
    if (state.selected) {
      const again = state.roads.features.find((f) => f.properties.id === state.selected.properties.id);
      if (again) showEvidence(again);
    } else if (params.get("road")) {
      const linked = state.roads.features.find((f) => f.properties.id === params.get("road"));
      if (linked) {
        showEvidence(linked);
        if (!currentArea()) map.fitBounds(window.L.geoJSON(linked).getBounds(), { maxZoom: 16 });
      }
      params.delete("road");
    }
  };

  const load = async () => {
    try {
      const roadsUrl = `${API}/roads${state.all ? "?all=true" : ""}`;
      const [situation, roads, reports] = await Promise.all([
        GRP.request(`${API}/situation`),
        GRP.request(roadsUrl),
        GRP.request(`${API}/reports?hours=${NEAR_HOURS}`),
      ]);
      Object.assign(state, { situation, roads, reports });
      showBanner("");
      drawAll();
    } catch (error) {
      if (error.status === 401) {
        window.location.replace("/");
        return;
      }
      showBanner(error.status === 403 ? error.message : say("fl.error"));
    }
  };

  const fillAreas = () => {
    const select = $("[data-area]");
    select.replaceChildren();
    const all = el("option", "", say("fl.area.all"));
    all.value = "all";
    select.append(all);
    const corridor = state.config && state.config.demo_corridor;
    if (corridor && corridorCodes().length) {
      const option = el("option", "", corridor.title[PilotText.lang()] || corridor.title.en);
      option.value = "corridor";
      select.append(option);
    }
    const nameOf = (a) => (PilotText.lang() === "th" ? a.name_th : a.name);
    [...state.areas]
      .sort((a, b) => nameOf(a).localeCompare(nameOf(b), PilotText.locale()))
      .forEach((a) => {
        const option = el("option", "", nameOf(a));
        option.value = a.admin_code;
        select.append(option);
      });
    select.value = state.area;
  };

  $("[data-area]").addEventListener("change", (event) => {
    state.area = event.target.value;
    state.selected = null;
    setUrl();
    $("[data-evidence]").replaceChildren(el("p", "fl-evidence__empty", say("ev.empty")));
    drawAll();
  });
  $("[data-vehicle]").addEventListener("change", (event) => { state.vehicle = event.target.value; drawAll(); });
  $("[data-all]").addEventListener("change", (event) => { state.all = event.target.checked; load(); });
  $("[data-refresh]").addEventListener("click", load);
  PilotText.onChange(() => { fillAreas(); drawAll(); });

  GRP.bindSignOut();
  GRP.me()
    .then(async (identity) => {
      const isAdmin = identity.is_platform_admin || identity.memberships.some((m) => m.role === "admin");
      $("[data-river-link]").hidden = !isAdmin;
      const [config, areas] = await Promise.all([GRP.request(API), GRP.request(`${API}/areas`)]);
      state.config = config;
      state.areas = areas.areas;
      const asked = params.get("area");
      if (asked === "all" || state.areas.some((a) => a.admin_code === asked)) state.area = asked;
      if (state.area === "corridor" && !corridorCodes().length) state.area = "all";
      fillAreas();
      await load();
      window.setInterval(load, REFRESH_MS);
    })
    .catch((error) => {
      if (error.status === 401) {
        window.location.replace("/");
        return;
      }
      showBanner(error.message || say("fl.error"));
    });
})();
