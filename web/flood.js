// ADR-0038: Bangkok Live Risk Intelligence. Stored Floodboard evidence with freshness and lineage.
// Provider text is always set with textContent; only this file's own strings use innerHTML.
(() => {
  const $ = (selector) => document.querySelector(selector);
  const PILOT = "bangkok";
  const LIVE_API = `/api/v1/pilot/flood/${PILOT}`;
  // ADR-0044: ?replay=<id> opens a replay namespace. Its ID shape is checked before any request.
  const REPLAY = (() => {
    const value = new URL(window.location.href).searchParams.get("replay");
    return value && /^r[0-9a-f]{11}$/.test(value) ? value : null;
  })();
  const API = REPLAY ? `/api/v1/pilot/flood/${REPLAY}` : LIVE_API;
  let replayClockMs = null;
  // Every age and window on the page is measured from this: wall time live, the replay clock
  // in a replay, so simulated data never reads as hours old.
  const nowMs = () => (REPLAY && replayClockMs != null ? replayClockMs : Date.now());
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
    situation: null, roads: null, reports: null, selected: null, cameras: null,
    assets: null, facility: null, incidents: null, incident: null, allIncidents: false,
    canWrite: false, changes: null, window: 60, weather: null,
  };
  const say = PilotText.t;
  let map = null;
  let roadLayer = null;
  let reportLayer = null;
  let outlineLayer = null;
  let selectedLayer = null;
  let facilityLayer = null;
  // Map layers the officer can switch on and off, one per source. Remembered in this browser only.
  let toggleLayers = {};
  let layerCounts = {};
  const LAYER_ORDER = ["roads", "rep_traffy", "rep_crowd", "rep_bma", "rep_doh", "rep_longdo", "rep_other",
    "facilities", "cam_traffic", "cam_bma", "cam_longdo", "cam_other", "outline"];
  const REPORT_GROUPS = {
    traffy: ["traffy"], crowd: ["crowd"], bma: ["bma_sensor", "bma_dds"], doh: ["doh"],
    longdo: ["itic", "longdo", "longdo_user"],
  };
  const reportGroup = (f) => `rep_${Object.keys(REPORT_GROUPS)
    .find((g) => REPORT_GROUPS[g].includes(f.properties.underlying_source)) || "other"}`;
  const CAMERA_GROUPS = { BMA_TRAFFIC: "cam_traffic", BMA_DDS: "cam_bma", ITIC_LONGDO: "cam_longdo" };
  const LAYER_KEY = "grp.flood.hiddenLayers";
  const hiddenLayers = (() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(LAYER_KEY) || "[]");
      return new Set(Array.isArray(saved) ? saved.filter((k) => LAYER_ORDER.includes(k)) : []);
    } catch (error) {
      return new Set();
    }
  })();
  let evidenceToken = 0;

  const clock = (iso) => new Intl.DateTimeFormat(PilotText.locale(), {
    timeZone: TZ, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(new Date(iso));
  const ago = (iso) => {
    const minutes = Math.max(0, Math.round((nowMs() - new Date(iso).getTime()) / 60000));
    if (minutes < 90) return say("ago.min", { n: minutes });
    if (minutes < 48 * 60) return say("ago.hour", { n: Math.round(minutes / 60) });
    return say("ago.day", { n: Math.round(minutes / 1440) });
  };
  const number = (value) => new Intl.NumberFormat(PilotText.locale()).format(value);
  const textOf = (text) => {
    const span = document.createElement("span");
    span.textContent = text;
    return span;
  };
  const FACILITY_LETTER = { hospital: "H", clinic: "C", school: "S", evacuation_centre: "E" };
  const facilityName = (a) => (PilotText.lang() === "en" && a.name_en) || a.name || a.name_en
    || say("fac.unnamed", { type: say(`fac.type.${a.asset_type}`) });
  const cameraName = (c) => c.name[PilotText.lang()] || c.name.en;
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
    url.searchParams.delete("facility");
    url.searchParams.delete("incident");
    if (state.incident) url.searchParams.set("incident", state.incident);
    if (state.facility) url.searchParams.set("facility", state.facility.asset_id);
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
  const visibleFacilities = () => (state.assets ? state.assets.assets.filter(
    (a) => inArea({ type: "Point", coordinates: [a.lon, a.lat] }),
  ) : []);
  const visibleIncidents = () => (state.incidents ? state.incidents.incidents.filter(
    (i) => inArea({ type: "Point", coordinates: i.center }),
  ) : []);
  const incidentName = (incident) => {
    const names = [];
    (state.roads ? state.roads.features : []).forEach((f) => {
      if (!incident.road_keys.includes(f.properties.id)) return;
      const name = (PilotText.lang() === "en" && f.properties.name_en) || f.properties.name;
      if (name && !names.includes(name)) names.push(name);
    });
    return names.length ? names.slice(0, 2).join(", ") + (names.length > 2 ? " …" : "") : say("inc.unnamed");
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
    [...Object.values(toggleLayers), reportLayer, selectedLayer].forEach((layer) => layer && map.removeLayer(layer));
    toggleLayers = {};
    layerCounts = {};
    selectedLayer = null;
    const area = currentArea();
    outlineLayer = area
      ? window.L.geoJSON({
          type: "FeatureCollection",
          features: currentAreas().map((a) => ({ type: "Feature", geometry: a.outline, properties: {} })),
        }, {
          style: { color: "#0d2534", weight: 2, dashArray: "6 5", fill: true, fillOpacity: 0.03 },
          interactive: false,
        })
      : null;
    // Reports sit under the roads: the roads are the main signal, the dots are context.
    const reports = visibleReports().filter((f) => f.properties.freshness !== "expired");
    // Injected replay reports always show: they are what the replay is testing.
    const synthetic = (f) => f.properties.evidence_class === "synthetic_demo";
    reportLayer = window.L.layerGroup(
      reports.filter(synthetic).map((f) => window.L.circleMarker([f.geometry.coordinates[1], f.geometry.coordinates[0]], {
            radius: 9, color: "#d6336c", weight: 3, dashArray: "3 3", fillColor: "#d6336c", fillOpacity: 0.25,
          }).bindTooltip(textOf(say("inc.synthetic")), { permanent: true, direction: "top" })),
    ).addTo(map);
    const reportGroups = {};
    reports.filter((f) => !synthetic(f)).forEach((f) => {
      const key = reportGroup(f);
      (reportGroups[key] = reportGroups[key] || []).push(
        window.L.circleMarker([f.geometry.coordinates[1], f.geometry.coordinates[0]], {
          radius: 2.5, color: "#7950f2", weight: 0, fillColor: "#7950f2",
          fillOpacity: NOW_BANDS.has(f.properties.freshness) ? 0.55 : 0.25, interactive: false,
        }));
    });
    Object.entries(reportGroups).forEach(([key, markers]) => {
      toggleLayers[key] = window.L.featureGroup(markers);
      layerCounts[key] = markers.length;
    });
    roadLayer = window.L.geoJSON({ type: "FeatureCollection", features: visibleRoads() }, {
      style: styleFor,
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        // Leaflet renders a string tooltip as HTML; provider names go in as text only.
        layer.bindTooltip(textOf(p.name || p.name_en || say(p.road_class === "zone" ? "ev.zone" : "ev.unnamed")), { sticky: true });
        layer.on("click", () => showEvidence(feature));
      },
    });
    facilityLayer = window.L.layerGroup(
      visibleFacilities().map((a) => {
        const tone = ["access_under_review", "access_disrupted_confirmed"].includes(a.access_state) ? "review"
          : a.exposure_state === "potentially_exposed" ? "exposed" : "none";
        const marker = window.L.marker([a.lat, a.lon], {
          // The icon holds only this file's own letter; names go in the tooltip as text.
          icon: window.L.divIcon({
            className: `fl-fac fl-fac--${tone}`,
            html: FACILITY_LETTER[a.asset_type] || "?",
            iconSize: [20, 20],
          }),
        });
        marker.bindTooltip(textOf(facilityName(a)), { sticky: true });
        marker.on("click", () => showFacility(a));
        return marker;
      }),
    );
    const cameraGroups = {};
    (state.cameras ? state.cameras.cameras : [])
      .filter((c) => inArea({ type: "Point", coordinates: [c.lon, c.lat] }))
      .forEach((c) => {
        const key = CAMERA_GROUPS[c.provider] || "cam_other";
        (cameraGroups[key] = cameraGroups[key] || []).push((() => {
          const colour = c.status === "online" ? "#1e6b33" : c.status === "offline" ? "#a61e1e" : "#4a555b";
          const marker = window.L.circleMarker([c.lat, c.lon], {
            radius: 7, color: colour, weight: 2.5, dashArray: c.placeholder ? "3 3" : null,
            fillColor: colour, fillOpacity: c.placeholder ? 0 : 0.6,
          });
          marker.bindTooltip(textOf(cameraName(c)), { sticky: true });
          marker.on("click", () => showCamera(c));
          return marker;
        })());
      });
    Object.entries(cameraGroups).forEach(([key, markers]) => {
      toggleLayers[key] = window.L.layerGroup(markers);
      layerCounts[key] = markers.length;
    });
    toggleLayers.roads = roadLayer;
    layerCounts.roads = visibleRoads().length;
    toggleLayers.facilities = facilityLayer;
    layerCounts.facilities = visibleFacilities().length;
    if (outlineLayer) {
      toggleLayers.outline = outlineLayer;
      layerCounts.outline = currentAreas().length;
    }
    applyLayers();
    drawLayerControls();
    if (area && outlineLayer) map.fitBounds(outlineLayer.getBounds(), { padding: [20, 20] });
  };

  // Show or hide each source's layer. Reports stay under the roads: the roads are the main signal.
  const applyLayers = () => {
    LAYER_ORDER.forEach((key) => {
      const layer = toggleLayers[key];
      if (!layer) return;
      const show = !hiddenLayers.has(key);
      if (show && !map.hasLayer(layer)) {
        layer.addTo(map);
        if (key.startsWith("rep_")) layer.bringToBack();
      } else if (!show && map.hasLayer(layer)) {
        map.removeLayer(layer);
      }
    });
    if (selectedLayer) selectedLayer.bringToFront();
  };

  const drawLayerControls = () => {
    const box = $("[data-layers]");
    if (!box) return;
    box.replaceChildren(el("legend", "fl-layers__title", say("lay.title")));
    LAYER_ORDER.filter((key) => toggleLayers[key]).forEach((key) => {
      const label = el("label", "fl-layers__item");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = !hiddenLayers.has(key);
      input.addEventListener("change", () => {
        if (input.checked) hiddenLayers.delete(key); else hiddenLayers.add(key);
        try {
          window.localStorage.setItem(LAYER_KEY, JSON.stringify([...hiddenLayers]));
        } catch (error) {
          // Not remembered in this browser; the switch still works for this visit.
        }
        applyLayers();
      });
      label.append(input, el("span", "", `${say(`lay.${key}`)} · ${number(layerCounts[key] || 0)}`));
      box.append(label);
    });
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
    item({ border: "2px dashed #4a555b", borderRadius: "50%", width: "0.7rem", height: "0.7rem" }, say("leg.camera"));
    item({ background: "#e8590c", borderRadius: "4px", width: "0.8rem", height: "0.8rem" }, say("leg.fac.exposed"));
    item({ background: "#c92a2a", borderRadius: "4px", width: "0.8rem", height: "0.8rem" }, say("leg.fac.review"));
    item({ background: "#ffffff", border: "1px solid #6c7a80", borderRadius: "4px", width: "0.8rem", height: "0.8rem" }, say("leg.fac.none"));
  };

  // --- Cards and coverage --------------------------------------------------------------------
  // Rain (ADR-0049): context only. Unknown is never shown as "no rain".
  const RAIN_ORDER = ["no_rain", "very_light", "light", "moderate", "heavy", "very_heavy"];
  const rainWord = (level) => say(`rain.level.${RAIN_ORDER.includes(level) ? level : "unknown"}`);
  const heaviest = (levels) => levels.filter((l) => RAIN_ORDER.includes(l))
    .sort((a, b) => RAIN_ORDER.indexOf(b) - RAIN_ORDER.indexOf(a))[0];

  const drawRainCard = () => {
    const w = state.weather;
    const nowNode = $("[data-rain-now]");
    const in30 = $("[data-rain-30]");
    if (!w || !w.available) {
      nowNode.textContent = w && w.reason === "replay" ? say("rain.replay") : say("rain.unknown");
      in30.textContent = "";
      return;
    }
    const codes = state.area === "corridor" ? corridorCodes() : state.area === "all" ? null : [state.area];
    const districts = w.scopes.filter((x) => x.kind === "district" && (!codes || codes.includes(x.id)));
    const now = heaviest(districts.map((x) => x.rain_now && x.rain_now.max_level));
    const later = heaviest(districts.map((x) => (x.forecast || []).filter((f) => f.available).map((f) => f.max_level).pop()));
    nowNode.textContent = now ? rainWord(now) : say("rain.unknown");
    in30.textContent = say("rain.card.in30", { level: later ? rainWord(later) : say("rain.unknown") });
  };

  const drawCards = () => {
    drawRainCard();
    const roads = visibleRoads();
    const flooded = roads.filter((f) => !f.properties.cleared);
    const now = flooded.filter((f) => NOW_BANDS.has(f.properties.freshness));
    const set = (key, value) => { $(`[data-card="${key}"]`).textContent = number(value); };
    set("affected", now.length);
    set("blocked", now.filter((f) => f.properties.provider_verdict[state.vehicle] === "blocked").length);
    set("closed", now.filter((f) => f.properties.closed_all).length);
    set("old", flooded.length - now.length);
    const hourAgo = nowMs() - 3600 * 1000;
    set("reports", visibleReports().filter((f) => new Date(f.properties.observed_at).getTime() >= hourAgo).length);
    const notOk = state.situation.sources.filter((s) => s.state !== "ok").length;
    set("sources", notOk);
    const facilities = visibleFacilities();
    set("exposed", facilities.filter((a) => a.exposure_state === "potentially_exposed").length);
    set("access", facilities.filter((a) => ["access_under_review", "access_disrupted_confirmed"].includes(a.access_state)).length);
    $("[data-card-sources]").classList.toggle("is-warn", notOk > 0);
    const vehicle = say(`veh.${state.vehicle}`);
    $('[data-card-label="blocked"]').textContent = say("card.blocked", {
      vehicle: PilotText.lang() === "en" ? vehicle.toLowerCase() : vehicle,
    });
    const snapshot = state.roads.snapshot_retrieved_at;
    $("[data-asof]").textContent = snapshot
      ? say("fl.asof", { time: clock(new Date(nowMs()).toISOString()), age: ago(snapshot) })
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
      const label = { floodboard_roads: "cov.fb.roads", floodboard_reports: "cov.fb.reports", longdo_events: "cov.longdo_events" }[s.source_id];
      row(label ? say(label) : s.source_id, say(`cov.${s.state}`), detail, tone);
    });
    row(say("cov.bma"), say("cov.not"), say("cov.bma.detail"), "none");
    const cams = state.cameras ? state.cameras.cameras : [];
    if (cams.length && state.cameras.placeholders_only) {
      row(say("cov.cctv"), say("cov.test"), say("cov.cctv.detail.test", { n: cams.length }), "warn");
    } else if (!cams.length) {
      row(say("cov.cctv"), say("cov.not"), say("cov.cctv.detail"), "none");
    } else {
      const count = (provider) => cams.filter((c) => c.provider === provider).length;
      row(say("cov.cctv"), say("cov.cams"), say("cov.cctv.detail.combined", {
        n: number(cams.length), traffic: number(count("BMA_TRAFFIC")), bma: number(count("BMA_DDS")),
        itic: number(count("ITIC_LONGDO")),
      }), "warn");
    }
    if (state.assets && state.assets.assets.length) {
      const stamp = state.assets.source.osm_timestamp;
      row(say("cov.assets"), say("cov.osm"), say("cov.assets.detail.osm", {
        n: number(state.assets.assets.length), date: stamp ? clock(stamp) : "–",
      }), "ok");
    } else {
      row(say("cov.assets"), say("cov.not"), say("cov.assets.detail"), "none");
    }
    const w = state.weather;
    if (w && w.available) {
      row(say("cov.weather"), say("cov.ok"), say("cov.weather.detail", { time: clock(w.observed_at) }), "ok");
    } else if (!REPLAY) {
      row(say("cov.weather"), say("cov.not"), say("cov.weather.none"), "none");
    }
    row(say("cov.geoglows"), say("cov.elsewhere"), say("cov.geoglows.detail"), "none");
    $("[data-coverage-note]").textContent = `${say("cov.note")} ${say("cov.note.bbt")}`;
  };

  // --- What changed (slice 7a): computed by the server, no AI ---------------------------------
  const CHANGE_KINDS = ["new", "grew", "conflict_started", "access_to_check", "confidence_down",
    "confidence_up", "reactivated", "receded", "shrank", "closed", "officer_reviews"];

  const loadChanges = async () => {
    const box = $("[data-changes]");
    try {
      state.changes = await GRP.request(`${API}/changes?area=${encodeURIComponent(state.area)}&since_minutes=${state.window}`);
    } catch (error) {
      state.changes = null;
      box.replaceChildren(el("p", "fl-muted", say("fl.error")));
      return;
    }
    drawChanges();
  };

  const drawChanges = () => {
    const box = $("[data-changes]");
    box.replaceChildren();
    const c = state.changes;
    if (!c) {
      box.append(el("p", "fl-muted", say("ch.loading")));
      return;
    }
    if (c.window_starts_before_tracking && c.tracked_since) {
      box.append(el("p", "fl-tracked", say("ch.tracked", { time: clock(c.tracked_since) })));
    }
    const list = el("ul", "fl-changes__list");
    const byId = new Map((state.incidents ? state.incidents.incidents : []).map((i) => [i.incident_id, i]));
    CHANGE_KINDS.forEach((kind) => {
      const ids = (c.incidents || {})[kind] || [];
      if (!ids.length) return;
      const li = el("li", "");
      li.append(el("span", "fl-changes__what", say(`ch.${kind}`, { n: ids.length })));
      const chips = el("span", "fl-chips");
      ids.slice(0, 4).forEach((id) => {
        const incident = byId.get(id);
        if (!incident) return;
        const chip = el("button", "fl-linkbtn", incidentName(incident));
        chip.type = "button";
        chip.addEventListener("click", () => showIncident(id));
        chips.append(chip);
      });
      li.append(chips);
      list.append(li);
    });
    const assetsById = new Map((state.assets ? state.assets.assets : []).map((a) => [a.asset_id, a]));
    const names = (ids) => ids.map((id) => assetsById.get(id)).filter(Boolean).map(facilityName).join(", ");
    const fac = c.facilities || {};
    if ((fac.newly_near_flooding || []).length) list.append(el("li", "", say("ch.fac.new", { list: names(fac.newly_near_flooding) })));
    if ((fac.no_longer_near_flooding || []).length) list.append(el("li", "", say("ch.fac.gone", { list: names(fac.no_longer_near_flooding) })));
    if (!list.children.length) box.append(el("p", "fl-muted", say("ch.none")));
    else box.append(list);
    if (c.demo_area_active_then != null && c.demo_area_active_now != null) {
      box.append(el("p", "fl-muted", say("ch.active", { then: c.demo_area_active_then, now: c.demo_area_active_now })));
    }
  };

  // --- Ask (slice 7b): computed facts first; AI wording only if it passed the server's gate --
  const ASK_SUGGESTIONS = ["ask.q1", "ask.q2", "ask.q3", "ask.q4"];
  let lastAnswer = null;

  // Model text is never parsed as HTML: text goes in as text, and only [label] tokens become
  // buttons that open the cited incident, facility or section.
  const citedText = (text, labels) => {
    const box = el("div", "fl-answer__text");
    text.split("\n").forEach((line) => {
      const p = el("p", "");
      let last = 0;
      line.replace(/\[([A-Z]\d{0,2})\]/g, (match, label, offset) => {
        p.append(document.createTextNode(line.slice(last, offset)));
        const ref = labels[label];
        const chip = el("button", "fl-cite", label);
        chip.type = "button";
        if (ref && ref.kind === "incident") {
          chip.addEventListener("click", () => showIncident(ref.ref));
        } else if (ref && ref.kind === "facility") {
          chip.addEventListener("click", () => {
            const asset = state.assets && state.assets.assets.find((a) => a.asset_id === ref.ref);
            if (asset) showFacility(asset);
          });
        } else if (ref) {
          chip.title = say(`ask.cite.${label}`);
          const target = { S: "[data-cards]", C: ".fl-changes", L: ".fl-coverage" }[label];
          chip.addEventListener("click", () => { const node = $(target); if (node) node.scrollIntoView({ behavior: "smooth" }); });
        }
        p.append(chip);
        last = offset + match.length;
        return match;
      });
      p.append(document.createTextNode(line.slice(last)));
      box.append(p);
    });
    return box;
  };

  const drawAnswer = () => {
    const box = $("[data-ask-result]");
    box.replaceChildren();
    const answer = lastAnswer;
    if (!answer) return;
    if (answer.ai) {
      const card = el("section", "fl-answer fl-answer--ai");
      card.append(el("h3", "", say("ask.ai")), citedText(answer.ai.text, answer.labels));
      card.append(el("p", "fl-muted", `${say("ask.ai.note")} (${answer.ai.model})`));
      box.append(card);
    } else if (answer.withheld) {
      const reason = answer.withheld.reason;
      const known = say(`ask.withheld.${reason}`) !== `ask.withheld.${reason}`;
      const problems = (answer.withheld.problems || []).map((p) => say(`ask.problem.${p}`)).join(", ");
      box.append(el("p", "fl-tracked", known ? say(`ask.withheld.${reason}`, { problems }) : say("ask.withheld.other")));
    }
    const computed = el("section", "fl-answer");
    computed.append(el("h3", "", say("ask.computed")), citedText(answer.computed, answer.labels));
    box.append(computed);
    const details = el("details", "rw-more");
    details.append(el("summary", "", say("ask.facts", { n: answer.facts.length })));
    details.append(el("pre", "rw-json", answer.facts.map((f) => JSON.stringify(f)).join("\n")));
    box.append(details);
  };

  const drawSuggestions = () => {
    const box = $("[data-ask-suggestions]");
    box.replaceChildren();
    ASK_SUGGESTIONS.forEach((key) => {
      const chip = el("button", "fl-chip fl-ask__chip", say(key));
      chip.type = "button";
      chip.addEventListener("click", () => { $("[data-ask-q]").value = say(key); });
      box.append(chip);
    });
    if (!$("[data-ask-q]").value) $("[data-ask-q]").value = say("ask.q1");
  };

  const askQuestion = async () => {
    const question = $("[data-ask-q]").value.trim();
    if (!question) return;
    const button = $("[data-ask]");
    const status = $("[data-ask-status]");
    button.disabled = true;
    status.textContent = say("ask.working");
    try {
      lastAnswer = await post(`${API}/ask`, {
        question, area: state.area, since_minutes: state.window, lang: PilotText.lang(),
      });
      status.textContent = "";
      drawAnswer();
    } catch (error) {
      status.textContent = say("ask.failed", { msg: error.message || "" });
    } finally {
      button.disabled = false;
    }
  };

  // --- Incidents (slice 5a) ---------------------------------------------------------------
  const confidenceBadge = (confidence) => el("span", `fl-conf fl-conf--${confidence}`, say(`inc.conf.${confidence}`));

  const drawIncidents = () => {
    const list = $("[data-incidents]");
    list.replaceChildren();
    const items = visibleIncidents();
    const active = items.filter((i) => i.status === "active").length;
    $("[data-inc-count]").textContent = say("inc.count", { a: active, r: items.length - active });
    const more = $("[data-inc-more]");
    if (!items.length) {
      list.append(el("li", "fl-inc-empty", say("inc.none")));
      more.hidden = true;
      return;
    }
    const shown = state.allIncidents ? items : items.slice(0, 8);
    shown.forEach((incident, index) => {
      const li = el("li", "fl-inc");
      const button = el("button", "fl-inc__btn");
      button.type = "button";
      button.setAttribute("aria-pressed", String(state.incident === incident.incident_id));
      button.append(el("span", "fl-inc__rank", String(index + 1)));
      const body = el("span", "fl-inc__body");
      body.append(el("span", "fl-inc__name", incidentName(incident)));
      const tags = el("span", "fl-inc__tags");
      tags.append(confidenceBadge(incident.confidence));
      if (incident.status !== "active") tags.append(el("span", "fl-badge", say(`inc.status.${incident.status}`)));
      if (incident.verification && incident.verification !== "unverified") {
        tags.append(el("span", `fl-badge fl-badge--officer fl-badge--${incident.verification}`, say(`rev.badge.${incident.verification}`)));
      }
      if (incident.access_to_check) tags.append(el("span", "fl-badge fl-badge--warn", say("inc.access")));
      if (incident.hospital_near) tags.append(el("span", "fl-badge fl-badge--warn", say("inc.hospital")));
      body.append(tags);
      body.append(el("span", "fl-inc__meta", [
        say("inc.roads", { n: incident.road_keys.length }),
        say("inc.reports", { n: incident.report_keys.length }),
        say(`inc.fresh.${incident.freshness_basis}`, { age: ago(incident.newest_evidence_at) }),
      ].join(" · ")));
      button.append(body);
      button.addEventListener("click", () => showIncident(incident.incident_id));
      li.append(button);
      list.append(li);
    });
    more.hidden = items.length <= 8;
    more.textContent = state.allIncidents ? say("inc.less") : say("inc.more", { n: items.length });
  };

  const reasonText = (code, incident) => {
    if (code.startsWith("source_types:")) {
      return say("inc.reason.source_types", {
        list: incident.source_families.map((f) => say(`inc.family.${f}`)).join(", "),
      });
    }
    return say(`inc.reason.${code}`);
  };

  const reportLine = (report) => {
    const p = report.properties;
    const what = p.cleared ? say("inc.report.dry")
      : p.depth_cm == null ? "" : say("inc.report.depth", { n: number(p.depth_cm) });
    let line = say("inc.report", {
      source: sourceName(p.underlying_source), when: ago(p.observed_at), dist: number(report.distance_m ?? 0),
    });
    if (p.evidence_class === "synthetic_demo") line = `${say("inc.synthetic")} · ${line}`;
    return what ? `${line} · ${what}` : line;
  };

  const eventText = (event) => {
    const d = event.detail || {};
    const conf = (value) => (value ? say(`inc.conf.${value}`) : "–");
    if (event.kind === "officer_review") return say("inc.event.officer_review", { action: say(`rev.action.${d.action}`) });
    return say(`inc.event.${event.kind}`, {
      before: event.kind === "confidence_changed" ? conf(d.before) : d.before,
      after: event.kind === "confidence_changed" ? conf(d.after) : d.after,
    });
  };

  // Officer checks (slice 5b): a person's own observation, saved with the CSRF header by GRP.request.
  const post = (url, body) => GRP.request(url, { method: "POST", body });

  const reviewForm = (detail) => {
    const form = el("form", "fl-review");
    form.append(el("p", "fl-review__prompt", say("rev.prompt")));
    const note = el("textarea", "fl-review__note");
    note.maxLength = 500;
    note.rows = 2;
    note.setAttribute("aria-label", say("rev.note"));
    note.placeholder = say("rev.note");
    const usable = (detail.cameras || []).filter((c) => !c.placeholder && c.viewer_url);
    let camera = null;
    if (usable.length) {
      camera = el("select", "fl-review__camera");
      camera.setAttribute("aria-label", say("rev.camera"));
      const none = el("option", "", say("rev.camera.none"));
      none.value = "";
      camera.append(none);
      usable.forEach((c) => {
        const option = el("option", "", cameraName(c));
        option.value = c.camera_id;
        camera.append(option);
      });
    }
    const status = el("p", "fl-review__status");
    status.setAttribute("aria-live", "polite");
    const buttons = el("div", "fl-review__buttons");
    ["flooding_seen", "dry_seen", "cannot_tell"].forEach((action) => {
      const button = el("button", `button button--secondary button--compact fl-review__btn fl-review__btn--${action}`, say(`rev.action.${action}`));
      button.type = "button";
      button.addEventListener("click", async () => {
        buttons.querySelectorAll("button").forEach((b) => { b.disabled = true; });
        status.textContent = say("rev.saving");
        try {
          await post(`${API}/incidents/${detail.incident_id}/reviews`, {
            action, note: note.value.trim() || null, camera_id: camera && camera.value ? camera.value : null,
          });
          status.textContent = say("rev.saved");
          await load();
        } catch (error) {
          status.textContent = say("rev.failed", { msg: error.message || "" });
          buttons.querySelectorAll("button").forEach((b) => { b.disabled = false; });
        }
      });
      buttons.append(button);
    });
    form.append(buttons, note);
    if (camera) form.append(camera);
    form.append(status);
    return form;
  };

  const facilityForm = (asset) => {
    const form = el("form", "fl-review");
    const note = el("textarea", "fl-review__note");
    note.maxLength = 500;
    note.rows = 2;
    note.placeholder = say("rev.note");
    note.setAttribute("aria-label", say("rev.note"));
    const status = el("p", "fl-review__status");
    status.setAttribute("aria-live", "polite");
    const confirmed = asset.access_state === "access_disrupted_confirmed";
    const action = confirmed ? "withdraw" : "access_disrupted";
    const button = el("button", "button button--secondary button--compact", say(confirmed ? "fac.withdraw" : "fac.confirm"));
    button.type = "button";
    button.addEventListener("click", async () => {
      button.disabled = true;
      status.textContent = say("rev.saving");
      try {
        await post(`${API}/facilities/access`, { asset_id: asset.asset_id, action, note: note.value.trim() || null });
        status.textContent = say("rev.saved");
        await load();
      } catch (error) {
        status.textContent = say("rev.failed", { msg: error.message || "" });
        button.disabled = false;
      }
    });
    form.append(button, note, status);
    return form;
  };

  const showIncident = async (incidentId) => {
    stopLive();
    state.incident = incidentId;
    state.selected = null;
    state.facility = null;
    setUrl();
    drawIncidents();
    const token = ++evidenceToken;
    let detail;
    try {
      detail = await GRP.request(`${API}/incidents/${incidentId}`);
    } catch (error) {
      detail = null;
    }
    if (token !== evidenceToken) return;
    const box = $("[data-evidence]");
    box.replaceChildren();
    if (!detail) {
      state.incident = null;
      box.append(el("p", "fl-evidence__empty", say("ev.empty")));
      return;
    }
    if (selectedLayer) map.removeLayer(selectedLayer);
    if (detail.roads.length) {
      selectedLayer = window.L.geoJSON({ type: "FeatureCollection", features: detail.roads }, {
        style: { color: "#0d2534", weight: 12, opacity: 0.3 }, interactive: false,
      }).addTo(map);
      selectedLayer.bringToBack();
      // Zoom only when an incident is opened, not on every refresh.
      if (state.fitted !== incidentId) {
        map.fitBounds(selectedLayer.getBounds(), { maxZoom: 16, padding: [30, 30] });
        state.fitted = incidentId;
      }
    }
    box.append(el("p", "fl-evidence__kicker", say("inc.heading")));
    box.append(el("h2", "fl-evidence__title", incidentName(detail)));
    const badges = el("p", "fl-badges");
    badges.append(confidenceBadge(detail.confidence));
    badges.append(el("span", "fl-badge", say(`inc.status.${detail.status}`)));
    badges.append(el("span", `fl-badge fl-badge--fresh-${detail.freshness}`,
      say(`inc.fresh.${detail.freshness_basis}`, { age: ago(detail.newest_evidence_at) })));
    box.append(badges);

    box.append(el("h3", "fl-evidence__sub", say("inc.why")));
    const why = el("ul", "fl-why");
    detail.reasons.forEach((code) => why.append(el("li", "", reasonText(code, detail))));
    box.append(why);

    box.append(el("h3", "fl-evidence__sub", say("inc.facts")));
    const facts = el("dl", "rw-facts");
    const fact = (label, value) => { facts.append(el("dt", "", label), el("dd", "", value)); };
    fact(say("inc.roadCount"), String(detail.road_keys.length));
    fact(say("inc.depth"), detail.max_depth_cm == null ? say("ev.depth.none") : `${number(detail.max_depth_cm)} cm`);
    fact(say("inc.closed"), String(detail.closed_roads));
    if (detail.worst_verdict && detail.worst_verdict.sedan) fact(say("inc.worst"), say(`leg.${detail.worst_verdict.sedan}`));
    box.append(facts);

    if (detail.conflict) {
      box.append(el("h3", "fl-evidence__sub", say("inc.against")));
      const against = el("ul", "fl-rows");
      detail.reports.filter((r) => detail.contrary_keys.includes(r.properties.id)).forEach((r) => {
        against.append(el("li", "fl-row fl-row--pending", reportLine(r)));
      });
      box.append(against);
    }

    box.append(el("h3", "fl-evidence__sub", say("inc.timeline")));
    const timeline = detail.reports
      .filter((r) => detail.report_keys.includes(r.properties.id))
      .sort((a, b) => (a.properties.observed_at < b.properties.observed_at ? 1 : -1));
    if (!timeline.length) {
      box.append(el("p", "fl-muted", say("inc.timeline.none")));
    } else {
      const ul = el("ul", "fl-timeline");
      timeline.slice(0, 20).forEach((r) => ul.append(el("li", "", reportLine(r))));
      box.append(ul);
    }

    box.append(el("h3", "fl-evidence__sub", say("ev.affected")));
    if (!detail.facilities.length) {
      box.append(el("p", "fl-muted", say("ev.affected.none", { m: number(state.assets ? state.assets.near_m : 150) })));
    } else {
      const ul = el("ul", "fl-facs");
      detail.facilities.forEach((a) => {
        const button = el("button", "fl-linkbtn", `${say(`fac.type.${a.asset_type}`)} · ${facilityName(a)}`);
        button.type = "button";
        button.addEventListener("click", () => showFacility(a));
        const li = el("li", "");
        li.append(button);
        ul.append(li);
      });
      box.append(ul);
    }

    box.append(el("h3", "fl-evidence__sub", say("rain.section")));
    const rain = detail.weather && detail.weather.scope;
    if (!detail.weather || !detail.weather.available) {
      box.append(el("p", "fl-muted", detail.weather && detail.weather.reason === "replay" ? say("rain.replay") : say("rain.unknown")));
    } else if (!rain) {
      box.append(el("p", "fl-muted", say("rain.unknown")));
    } else {
      const ul = el("ul", "fl-timeline");
      ul.append(el("li", "", rain.rain_now
        ? say("rain.now", { level: rainWord(rain.rain_now.max_level), pct: number(rain.rain_now.coverage_pct) })
        : say("rain.now", { level: say("rain.unknown"), pct: "–" })));
      (rain.forecast || []).forEach((f, index) => {
        ul.append(el("li", "", say("rain.at", { min: (index + 1) * 15, level: f.available ? rainWord(f.max_level) : say("rain.unknown") })));
      });
      box.append(ul);
      box.append(el("p", "fl-muted", say("rain.source", { time: clock(detail.weather.observed_at) })));
    }

    box.append(el("h3", "fl-evidence__sub", say("ev.row.cctv")));
    const camRow = el("div", "fl-row fl-row--missing");
    renderCameras(camRow, { cameras: detail.cameras, radius_m: state.cameras ? state.cameras.default_radius_m : 400 });
    box.append(camRow);

    box.append(el("h3", "fl-evidence__sub", say("inc.events")));
    const events = el("ul", "fl-timeline");
    detail.events.slice(0, 12).forEach((e) => events.append(el("li", "", `${clock(e.at)} · ${eventText(e)}`)));
    box.append(events);

    box.append(el("h3", "fl-evidence__sub", say("inc.check")));
    box.append(el("p", `fl-officer fl-officer--${detail.verification}`, say(`rev.state.${detail.verification}`, {
      time: detail.verified_at ? clock(detail.verified_at) : "", until: detail.verified_until ? clock(detail.verified_until) : "",
    })));
    if (state.canWrite && detail.status !== "closed") {
      box.append(reviewForm(detail));
    } else if (!state.canWrite) {
      box.append(el("p", "fl-muted", say("rev.readonly")));
    }
    if (detail.reviews && detail.reviews.length) {
      box.append(el("h3", "fl-evidence__sub", say("rev.history")));
      const ul = el("ul", "fl-timeline");
      detail.reviews.forEach((r) => {
        const li = el("li", "", say("rev.item", { by: r.by, when: clock(r.at), action: say(`rev.action.${r.action}`) })
          + (r.current ? "" : ` ${say("rev.expired")}`));
        if (r.note) li.append(el("span", "fl-note", r.note));
        ul.append(li);
      });
      box.append(ul);
    }
    box.append(el("p", "fl-muted", say("rev.rule")));
    box.append(el("p", "fl-muted", say("inc.engine", { v: detail.rule_version })));
  };

  // --- Evidence card -----------------------------------------------------------------------
  const nearbyReports = (feature) => {
    const since = nowMs() - NEAR_HOURS * 3600 * 1000;
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

  // The CCTV row: nearby cameras from the server, each with every reason it cannot confirm.
  const fillCameras = async (row, roadId) => {
    const token = ++evidenceToken;
    let answer;
    try {
      answer = await GRP.request(`${API}/roads/${roadId}/cameras`);
    } catch (error) {
      answer = null;
    }
    if (token !== evidenceToken) return;
    row.replaceChildren(el("strong", "", say("ev.row.cctv")));
    if (!answer) {
      row.append(el("span", "", say("ev.row.cctv.v")));
      return;
    }
    renderCameras(row, answer);
  };

  // --- Live camera views (ADR-0047): played by the officer's browser, one at a time ---------
  const HLS_JS = "https://cdn.jsdelivr.net/npm/hls.js@1.5.17/dist/hls.min.js";
  let livePlayer = null;
  let hlsLoading = null;

  const stopLive = () => {
    if (!livePlayer) return;
    if (livePlayer.hls) livePlayer.hls.destroy();
    livePlayer.video.pause();
    livePlayer.video.removeAttribute("src");
    livePlayer.video.load();
    window.clearTimeout(livePlayer.timer);
    if (livePlayer.img) livePlayer.img.removeAttribute("src");
    livePlayer.box.replaceChildren();
    livePlayer = null;
  };

  const loadHlsJs = () => {
    if (window.Hls) return Promise.resolve(window.Hls);
    hlsLoading = hlsLoading || new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = HLS_JS;
      script.onload = () => resolve(window.Hls);
      script.onerror = reject;
      document.head.append(script);
    });
    return hlsLoading;
  };

  // ADR-0051: pictures relayed by GRP (bmatraffic.com, local demo only), about one a second. The
  // next picture is asked for only after the last one arrived, and asking stops after 10 minutes.
  const FRAME_MS = 1000;
  const FRAMES_FOR_MS = 10 * 60 * 1000;

  const playFrames = (camera, box) => {
    const img = document.createElement("img");
    img.className = "fl-live__frame fl-live__frame--img";
    img.alt = cameraName(camera);
    const status = el("p", "fl-live__status", say("cam.connecting"));
    const credit = el("p", "fl-live__credit", say("cam.relay", { source: camera.source_label }));
    box.replaceChildren(img, status, credit);
    const player = { video: document.createElement("video"), box, hls: null, timer: null, img };
    livePlayer = player;
    const started = Date.now();
    let failures = 0;
    const next = () => {
      if (livePlayer !== player) return;
      if (Date.now() - started > FRAMES_FOR_MS) {
        status.textContent = say("cam.paused");
        const again = el("button", "button button--secondary button--compact", say("cam.continue"));
        again.type = "button";
        again.addEventListener("click", () => playFrames(camera, box));
        status.append(" ", again);
        return;
      }
      img.src = `${camera.live.url}?t=${Date.now()}`;
    };
    img.addEventListener("load", () => {
      if (livePlayer !== player) return;
      failures = 0;
      status.textContent = "";
      status.classList.remove("is-bad");
      player.timer = window.setTimeout(next, FRAME_MS);
    });
    img.addEventListener("error", () => {
      if (livePlayer !== player) return;
      failures += 1;
      if (failures >= 3) {
        status.textContent = say("cam.failed");
        status.classList.add("is-bad");
        return;
      }
      player.timer = window.setTimeout(next, FRAME_MS * 2);
    });
    next();
  };

  const playLive = async (camera, box) => {
    stopLive();
    if (camera.live.kind === "frames") {
      playFrames(camera, box);
      return;
    }
    if (camera.live.kind === "iframe") {
      // The provider's own player page (bmatraffic.com), embedded as the owner asked. Sandboxed:
      // it may run its own scripts but never navigate this page or open windows.
      const frame = document.createElement("iframe");
      frame.className = "fl-live__frame";
      frame.src = camera.live.url;
      frame.title = cameraName(camera);
      frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
      frame.setAttribute("referrerpolicy", "no-referrer");
      frame.setAttribute("scrolling", "no");
      frame.loading = "lazy";
      box.replaceChildren(frame, el("p", "fl-live__credit", say("cam.live", { source: camera.source_label })));
      livePlayer = { video: document.createElement("video"), box, hls: null, timer: null };
      return;
    }
    const video = document.createElement("video");
    video.className = "fl-live__video";
    video.muted = true;
    video.autoplay = true;
    video.playsInline = true;
    video.controls = true;
    const status = el("p", "fl-live__status", say("cam.connecting"));
    const credit = el("p", "fl-live__credit", say("cam.live", { source: camera.source_label }));
    box.replaceChildren(video, status, credit);
    const player = { video, box, hls: null, timer: null };
    livePlayer = player;
    const fail = () => {
      if (livePlayer !== player) return;
      status.textContent = say("cam.failed");
      status.classList.add("is-bad");
    };
    video.addEventListener("playing", () => {
      window.clearTimeout(player.timer);
      status.textContent = "";
    });
    video.addEventListener("error", fail);
    player.timer = window.setTimeout(() => { if (video.readyState < 2) fail(); }, 12000);
    const { kind, url } = camera.live;
    if (kind === "hls" && !video.canPlayType("application/vnd.apple.mpegurl")) {
      try {
        const Hls = await loadHlsJs();
        if (livePlayer !== player) return;
        if (!Hls || !Hls.isSupported()) { fail(); return; }
        player.hls = new Hls({ liveDurationInfinity: true });
        player.hls.on(Hls.Events.ERROR, (_, data) => { if (data.fatal) fail(); });
        player.hls.loadSource(url);
        player.hls.attachMedia(video);
      } catch (error) {
        fail();
      }
    } else {
      video.src = url;
    }
  };

  const liveControls = (camera) => {
    const wrap = el("div", "fl-live");
    if (!camera.live) {
      // No in-page player: bmatraffic.com when the local demo relay (ADR-0051) is off. Its pictures
      // need a bmatraffic session, which a browser never sends from inside another site.
      if (!camera.placeholder && /^https?:\/\//.test(camera.viewer_url || "")) {
        const link = el("a", "button button--secondary button--compact", say("cam.tab"));
        link.href = camera.viewer_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        wrap.append(link, el("p", "fl-muted", say("cam.tab.hint", { source: camera.source_label })));
      }
      return wrap;
    }
    const box = el("div", "fl-live__box");
    const button = el("button", "button button--secondary button--compact", say("cam.play"));
    button.type = "button";
    button.addEventListener("click", () => {
      if (livePlayer && livePlayer.box === box) {
        stopLive();
        button.textContent = say("cam.play");
      } else {
        document.querySelectorAll(".fl-live button").forEach((b) => { b.textContent = say("cam.play"); });
        playLive(camera, box);
        button.textContent = say("cam.stop");
      }
    });
    wrap.append(button, box);
    return wrap;
  };

  const showCamera = (camera) => {
    stopLive();
    state.selected = null;
    state.facility = null;
    state.incident = null;
    const box = $("[data-evidence]");
    box.replaceChildren();
    box.append(el("p", "fl-evidence__kicker", say("cam.kicker")));
    box.append(el("h2", "fl-evidence__title", cameraName(camera)));
    box.append(el("p", "fl-muted", say("cam.source", { source: camera.source_label })));
    if (camera.related_sensor_ids && camera.related_sensor_ids.length) {
      box.append(el("p", "fl-muted", say("cam.sensor", { id: camera.related_sensor_ids.join(", ") })));
    }
    box.append(liveControls(camera));
    box.append(el("p", "fl-muted", say("cam.card.note")));
  };

  const renderCameras = (row, answer) => {
    if (!answer.cameras.length) {
      row.append(el("span", "", say("cam.none", { r: answer.radius_m })));
      return;
    }
    const items = el("ul", "fl-cams");
    answer.cameras.slice(0, 5).forEach((c) => {
      const li = el("li", "fl-cam");
      li.append(el("span", "fl-cam__name", cameraName(c)));
      li.append(el("span", "fl-cam__meta", [
        say("cam.dist", { n: number(c.distance_m) }),
        say(`cam.status.${c.status}`),
        say(`cam.mode.${c.access_mode}`),
      ].join(" · ")));
      if (c.related_sensor_ids && c.related_sensor_ids.length) {
        li.append(el("span", "fl-cam__meta", say("cam.sensor", { id: c.related_sensor_ids.join(", ") })));
      }
      const why = c.reasons.map((r) => say(`cam.reason.${r}`)).join(", ");
      li.append(el("span", "fl-cam__role", c.role === "officer_can_look" ? say("cam.look") : say("cam.cannot", { reasons: why })));
      li.append(el("span", "fl-cam__meta", say("cam.source", { source: c.source_label })));
      li.append(liveControls(c));
      items.append(li);
    });
    row.append(items);
    if (answer.cameras.some((c) => c.placeholder)) row.append(el("span", "fl-cam__note", say("cam.placeholderNote")));
  };

  const highlight = (feature) => {
    if (selectedLayer) map.removeLayer(selectedLayer);
    selectedLayer = window.L.geoJSON(feature, {
      style: { color: "#0d2534", weight: 12, opacity: 0.35 }, interactive: false,
    }).addTo(map);
    selectedLayer.bringToBack();
  };

  const showFacility = (asset) => {
    stopLive();
    state.selected = null;
    state.incident = null;
    state.facility = asset;
    setUrl();
    if (selectedLayer) { map.removeLayer(selectedLayer); selectedLayer = null; }
    const box = $("[data-evidence]");
    box.replaceChildren();
    box.append(el("h2", "fl-evidence__title", facilityName(asset)));
    const badges = el("p", "fl-badges");
    badges.append(el("span", "fl-badge", say(`fac.type.${asset.asset_type}`)));
    badges.append(el("span", "fl-badge", "OpenStreetMap"));
    box.append(badges);
    box.append(el("h3", "fl-evidence__sub", say("fac.exposure")));
    box.append(el("p", "", say(`fac.exposure.${asset.exposure_state}`, {
      d: number(asset.nearest_distance_m ?? 0), m: number(state.assets.near_m),
    })));
    const road = asset.nearest_road_key && state.roads
      ? state.roads.features.find((f) => f.properties.id === asset.nearest_road_key) : null;
    if (road) {
      const label = road.properties.name || road.properties.name_en || say("ev.unnamed");
      const button = el("button", "fl-linkbtn", `${say("fac.nearest")}: ${label}`);
      button.type = "button";
      button.addEventListener("click", () => showEvidence(road));
      box.append(button);
    }
    box.append(el("h3", "fl-evidence__sub", say("fac.access")));
    box.append(el("p", "", say(`fac.access.${asset.access_state}`, { f: number(state.assets.frontage_m) })));
    if (asset.officer) {
      box.append(el("p", "fl-officer fl-officer--officer_saw_flooding", say("fac.confirmed", {
        time: clock(asset.officer.confirmed_at), until: clock(asset.officer.confirmed_until),
      })));
    }
    box.append(el("h3", "fl-evidence__sub", say("fac.check")));
    if (state.canWrite) box.append(facilityForm(asset));
    else box.append(el("p", "fl-muted", say("rev.readonly")));
    box.append(el("p", "fl-muted", say("fac.osm")));
    if (asset.rule_version) box.append(el("p", "fl-muted", say("fac.rule", { v: asset.rule_version })));
  };

  const showEvidence = (feature) => {
    stopLive();
    state.facility = null;
    state.incident = null;
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

    const parent = state.incidents
      ? state.incidents.incidents.find((i) => i.road_keys.includes(p.id)) : null;
    if (parent) {
      const link = el("button", "fl-linkbtn", say("inc.open"));
      link.type = "button";
      link.addEventListener("click", () => showIncident(parent.incident_id));
      box.append(link);
    }
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
    const cctv = el("li", "fl-row fl-row--missing");
    cctv.append(el("strong", "", say("ev.row.cctv")), el("span", "", say("cam.loading")));
    list.append(cctv);
    evidenceRow(say("ev.row.check"), say("ev.row.check.v"), "pending");
    box.append(list);
    fillCameras(cctv, p.id);

    box.append(el("h3", "fl-evidence__sub", say("ev.affected")));
    const nearFacilities = state.assets ? state.assets.assets.filter((a) => a.road_keys.includes(p.id)) : [];
    const nearM = state.assets ? state.assets.near_m : 150;
    if (!state.assets) {
      box.append(el("p", "fl-muted", say("ev.affected.v")));
    } else if (!nearFacilities.length) {
      box.append(el("p", "fl-muted", say("ev.affected.none", { m: number(nearM) })));
    } else {
      box.append(el("p", "fl-muted", say("ev.affected.list", { n: nearFacilities.length, m: number(nearM) })));
      const ul = el("ul", "fl-facs");
      nearFacilities.forEach((a) => {
        const li = el("li", "");
        const button = el("button", "fl-linkbtn", `${say(`fac.type.${a.asset_type}`)} · ${facilityName(a)}`);
        button.type = "button";
        button.addEventListener("click", () => showFacility(a));
        li.append(button);
        ul.append(li);
      });
      box.append(ul);
    }
  };

  // --- Loading -----------------------------------------------------------------------------
  const drawAll = () => {
    if (!state.situation || !state.roads) return;
    drawCards();
    drawIncidents();
    drawChanges();
    drawCoverage();
    drawLegend();
    drawMap();
    if (!state.roads.snapshot_retrieved_at) showBanner(say("fl.empty"));
    if (state.incident) {
      showIncident(state.incident);
      return;
    }
    if (params.get("incident")) {
      const linked = params.get("incident");
      params.delete("incident");
      showIncident(linked);
      return;
    }
    if (!state.facility && !state.selected && params.get("facility") && state.assets) {
      const linked = state.assets.assets.find((x) => x.asset_id === params.get("facility"));
      params.delete("facility");
      if (linked) {
        showFacility(linked);
        return;
      }
    }
    if (state.facility && state.assets) {
      const again = state.assets.assets.find((a) => a.asset_id === state.facility.asset_id);
      if (again) showFacility(again);
    } else if (state.selected) {
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
      const [situation, roads, reports, assets, incidents] = await Promise.all([
        GRP.request(`${API}/situation`),
        GRP.request(roadsUrl),
        GRP.request(`${API}/reports?hours=${NEAR_HOURS}`),
        GRP.request(`${API}/assets`),
        GRP.request(`${API}/incidents`),
      ]);
      Object.assign(state, { situation, roads, reports, assets, incidents });
      try {
        state.weather = await GRP.request(`${API}/weather`);
      } catch (error) {
        state.weather = null;  // rain is context: the page works without it
      }
      loadChanges();
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

  $("[data-ch-window]").addEventListener("change", (event) => {
    state.window = Number(event.target.value);
    loadChanges();
  });
  $("[data-area]").addEventListener("change", (event) => {
    state.area = event.target.value;
    loadChanges();
    state.selected = null;
    setUrl();
    $("[data-evidence]").replaceChildren(el("p", "fl-evidence__empty", say("ev.empty")));
    drawAll();
  });
  $("[data-vehicle]").addEventListener("change", (event) => { state.vehicle = event.target.value; drawAll(); });
  $("[data-all]").addEventListener("change", (event) => { state.all = event.target.checked; load(); });
  $("[data-refresh]").addEventListener("click", load);
  $("[data-ask]").addEventListener("click", askQuestion);
  $("[data-inc-more]").addEventListener("click", () => { state.allIncidents = !state.allIncidents; drawIncidents(); });
  PilotText.onChange(() => {
    $("[data-ask-q]").value = "";
    drawSuggestions();
    drawAnswer();
    fillAreas();
    drawAll();
  });
  drawSuggestions();

  // --- Replay (slice 6a) ----------------------------------------------------------------------
  const REPLAYS = `${LIVE_API}/replays`;
  const player = { playing: false, speed: 20, info: null, lastClock: null, pending: 0 };

  const drawReplayBar = () => {
    const bar = $("[data-replay-bar]");
    const info = player.info;
    if (!REPLAY || !info) return;
    bar.hidden = false;
    $("[data-player]").hidden = false;
    bar.textContent = info.clock
      ? say("rp.banner", { time: clock(info.clock) })
      : say("rp.banner.building", { done: info.steps_done, total: info.steps_total });
    document.title = `REPLAY · ${say("fl.page.title")}`;
    $("[data-player-clock]").textContent = say("rp.clock", {
      time: info.clock ? clock(info.clock) : "–", start: clock(info.start_at), end: clock(info.end_at),
    });
    $("[data-player-progress]").textContent = say("rp.progress", { done: info.steps_done, total: info.steps_total });
    $("[data-player-play]").textContent = say(player.playing ? "rp.pause" : "rp.play");
    if (!state.canControl) {
      $("[data-player]").querySelectorAll("button, select").forEach((n) => { n.disabled = true; });
      $("[data-player-status]").textContent = say("rp.watchOnly");
    }
  };

  const drawInjections = () => {
    const list = $("[data-inject-list]");
    list.replaceChildren();
    (player.info ? player.info.injections : []).forEach((i) => {
      const text = i.kind === "report"
        ? say("rp.inject.list.report", {
          time: clock(i.at), source: sourceName(i.source),
          what: i.cleared ? say("inc.report.dry") : i.depth_cm == null ? "" : say("inc.report.depth", { n: number(i.depth_cm) }),
          state: say(i.done ? "rp.inject.done" : "rp.inject.pending"),
        })
        : say("rp.inject.list.outage", { feed: say(`rp.inject.feed.${i.source_id}`), start: clock(i.start), end: clock(i.end) });
      list.append(el("li", "", text));
    });
  };

  const syncInjectForm = () => {
    const kind = $("[data-inject-kind]").value;
    document.querySelectorAll("[data-inject-only]").forEach((n) => { n.hidden = n.dataset.injectOnly !== kind; });
    $("[data-inject-depth]").disabled = $("[data-inject-dry]").checked;
  };

  const addInjection = async () => {
    const status = $("[data-inject-status]");
    if (!player.info || !player.info.clock) return;
    const base = new Date(player.info.clock).getTime() + Number($("[data-inject-after]").value) * 60000;
    const at = new Date(base).toISOString();
    try {
      if ($("[data-inject-kind]").value === "report") {
        const center = map.getCenter();
        const dry = $("[data-inject-dry]").checked;
        player.info = await post(`${REPLAYS}/${REPLAY}/inject-report`, {
          at, lat: center.lat, lon: center.lng, source: $("[data-inject-source]").value,
          depth_cm: dry ? 0 : Number($("[data-inject-depth]").value), cleared: dry,
        });
      } else {
        const end = new Date(base + Number($("[data-inject-for]").value) * 60000).toISOString();
        player.info = await post(`${REPLAYS}/${REPLAY}/inject-outage`, {
          source_id: $("[data-inject-feed]").value, start: at, end,
        });
      }
      status.textContent = say("rp.inject.added");
      drawInjections();
    } catch (error) {
      status.textContent = error.message || "";
    }
  };

  const pollReplay = async () => {
    try {
      player.info = await GRP.request(`${REPLAYS}/${REPLAY}`);
    } catch (error) {
      showBanner(error.message || say("fl.error"));
      return;
    }
    if (player.info.clock) replayClockMs = new Date(player.info.clock).getTime();
    drawReplayBar();
    drawInjections();
    if (player.info.clock && player.info.clock !== player.lastClock) {
      player.lastClock = player.info.clock;
      await load();
    }
    if (player.playing && player.info.clock && player.info.clock >= player.info.end_at) {
      player.playing = false;
      $("[data-player-status]").textContent = say("rp.end");
      drawReplayBar();
    }
  };

  const advanceBy = async (minutes) => {
    try {
      player.info = await post(`${REPLAYS}/${REPLAY}/advance`, { by_minutes: Math.max(1, Math.round(minutes)) });
      drawReplayBar();
    } catch (error) {
      $("[data-player-status]").textContent = error.message || "";
    }
  };

  const startReplay = async () => {
    await pollReplay();
    window.setInterval(pollReplay, 3000);
    // "N×" plays N simulated minutes per real minute. Ticks are 3 s; whole minutes are sent.
    window.setInterval(() => {
      if (!player.playing || !player.info || player.info.status !== "ready") return;
      player.pending += (player.speed * 3) / 60;
      if (player.pending >= 1) {
        const minutes = Math.floor(player.pending);
        player.pending -= minutes;
        advanceBy(minutes);
      }
    }, 3000);
    $("[data-player-play]").addEventListener("click", () => { player.playing = !player.playing; drawReplayBar(); });
    $("[data-inject-kind]").addEventListener("change", syncInjectForm);
    $("[data-inject-dry]").addEventListener("change", syncInjectForm);
    $("[data-inject-add]").addEventListener("click", addInjection);
    syncInjectForm();
    $("[data-player-speed]").addEventListener("change", (event) => { player.speed = Number(event.target.value); });
    document.querySelectorAll("[data-player-step]").forEach((b) => b.addEventListener("click", () => advanceBy(Number(b.dataset.playerStep))));
    $("[data-player-restart]").addEventListener("click", async () => {
      player.playing = false;
      player.info = await post(`${REPLAYS}/${REPLAY}/restart`, {});
      player.lastClock = null;
      drawReplayBar();
    });
    $("[data-player-delete]").addEventListener("click", async () => {
      await GRP.request(`${REPLAYS}/${REPLAY}`, { method: "DELETE" });
      window.location.href = "/flood.html";
    });
  };

  const loadReplays = async () => {
    let answer;
    try {
      answer = await GRP.request(REPLAYS);
    } catch (error) {
      return;
    }
    const section = $("[data-replays]");
    section.hidden = false;
    const { first, last } = answer.available;
    $("[data-rp-available]").textContent = first ? say("rp.available", { first: clock(first), last: clock(last) }) : say("rp.none");
    const select = $("[data-rp-start]");
    select.replaceChildren();
    if (first) {
      const step = 30 * 60 * 1000;
      for (let t = Math.ceil(new Date(first).getTime() / step) * step; t < new Date(last).getTime(); t += step) {
        const option = el("option", "", clock(new Date(t).toISOString()));
        option.value = new Date(t).toISOString();
        select.append(option);
      }
    }
    $("[data-rp-length]").querySelectorAll("option").forEach((o) => { o.textContent = say("rp.h", { n: o.value }); });
    $("[data-rp-create]").disabled = !first || !state.canControl;
    const list = $("[data-rp-list]");
    list.replaceChildren();
    answer.replays.forEach((r) => {
      const li = el("li", "", say("rp.item", { start: clock(r.start_at), end: clock(r.end_at), status: say(`rp.status.${r.status}`) }) + " ");
      const link = el("a", "", say("rp.open"));
      link.href = `/flood.html?replay=${encodeURIComponent(r.replay_id)}`;
      li.append(link);
      list.append(li);
    });
  };

  $("[data-rp-create]").addEventListener("click", async () => {
    const status = $("[data-rp-status]");
    const start = new Date($("[data-rp-start]").value);
    const hours = Number($("[data-rp-length]").value);
    const latest = Date.now() - 60 * 1000;
    const end = new Date(Math.min(start.getTime() + hours * 3600 * 1000, latest));
    status.textContent = say("rp.creating");
    try {
      const replay = await post(REPLAYS, { start_at: start.toISOString(), end_at: end.toISOString() });
      window.location.href = `/flood.html?replay=${encodeURIComponent(replay.replay_id)}`;
    } catch (error) {
      status.textContent = say("rp.failed", { msg: error.message || "" });
    }
  });

  GRP.bindSignOut();
  GRP.me()
    .then(async (identity) => {
      const isAdmin = identity.is_platform_admin || identity.memberships.some((m) => m.role === "admin");
      $("[data-river-link]").hidden = !isAdmin;
      // ADR-0042: only members of the pilot's Hubs record checks; the server enforces it too.
      state.canWrite = identity.memberships.length > 0 && !REPLAY;
      state.canControl = identity.memberships.length > 0;
      const [config, areas, cameras] = await Promise.all([
        GRP.request(API), GRP.request(`${API}/areas`), GRP.request(`${API}/cameras`),
      ]);
      state.config = config;
      state.cameras = cameras;
      state.areas = areas.areas;
      const asked = params.get("area");
      if (asked === "all" || state.areas.some((a) => a.admin_code === asked)) state.area = asked;
      if (state.area === "corridor" && !corridorCodes().length) state.area = "all";
      fillAreas();
      if (REPLAY) {
        await startReplay();
      } else {
        await load();
        window.setInterval(load, REFRESH_MS);
        loadReplays();
      }
    })
    .catch((error) => {
      if (error.status === 401) {
        window.location.replace("/");
        return;
      }
      showBanner(error.message || say("fl.error"));
    });
})();
