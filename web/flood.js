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
    situation: null, roads: null, reports: null, selected: null, cameras: null,
    assets: null, facility: null, incidents: null, incident: null, allIncidents: false,
    canWrite: false, changes: null, window: 60,
  };
  const say = PilotText.t;
  let map = null;
  let roadLayer = null;
  let reportLayer = null;
  let outlineLayer = null;
  let selectedLayer = null;
  let cameraLayer = null;
  let facilityLayer = null;
  let evidenceToken = 0;

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
  const textOf = (text) => {
    const span = document.createElement("span");
    span.textContent = text;
    return span;
  };
  const FACILITY_LETTER = { hospital: "H", clinic: "C", school: "S" };
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
    [roadLayer, reportLayer, outlineLayer, selectedLayer, cameraLayer, facilityLayer].forEach((layer) => layer && map.removeLayer(layer));
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
        layer.bindTooltip(textOf(p.name || p.name_en || say(p.road_class === "zone" ? "ev.zone" : "ev.unnamed")), { sticky: true });
        layer.on("click", () => showEvidence(feature));
      },
    }).addTo(map);
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
    ).addTo(map);
    cameraLayer = window.L.layerGroup(
      (state.cameras ? state.cameras.cameras : [])
        .filter((c) => inArea({ type: "Point", coordinates: [c.lon, c.lat] }))
        .map((c) => {
          const colour = c.status === "online" ? "#1e6b33" : c.status === "offline" ? "#a61e1e" : "#4a555b";
          const marker = window.L.circleMarker([c.lat, c.lon], {
            radius: 7, color: colour, weight: 2.5, dashArray: c.placeholder ? "3 3" : null,
            fillColor: colour, fillOpacity: c.placeholder ? 0 : 0.6,
          });
          marker.bindTooltip(textOf(cameraName(c)), { sticky: true });
          return marker;
        }),
    ).addTo(map);
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
    item({ border: "2px dashed #4a555b", borderRadius: "50%", width: "0.7rem", height: "0.7rem" }, say("leg.camera"));
    item({ background: "#e8590c", borderRadius: "4px", width: "0.8rem", height: "0.8rem" }, say("leg.fac.exposed"));
    item({ background: "#c92a2a", borderRadius: "4px", width: "0.8rem", height: "0.8rem" }, say("leg.fac.review"));
    item({ background: "#ffffff", border: "1px solid #6c7a80", borderRadius: "4px", width: "0.8rem", height: "0.8rem" }, say("leg.fac.none"));
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
    const cams = state.cameras ? state.cameras.cameras : [];
    if (cams.length && state.cameras.placeholders_only) {
      row(say("cov.cctv"), say("cov.test"), say("cov.cctv.detail.test", { n: cams.length }), "warn");
    } else if (!cams.length) {
      row(say("cov.cctv"), say("cov.not"), say("cov.cctv.detail"), "none");
    }
    if (state.assets && state.assets.assets.length) {
      const stamp = state.assets.source.osm_timestamp;
      row(say("cov.assets"), say("cov.osm"), say("cov.assets.detail.osm", {
        n: number(state.assets.assets.length), date: stamp ? clock(stamp) : "–",
      }), "ok");
    } else {
      row(say("cov.assets"), say("cov.not"), say("cov.assets.detail"), "none");
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
    const line = say("inc.report", {
      source: sourceName(p.underlying_source), when: ago(p.observed_at), dist: number(report.distance_m ?? 0),
    });
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

  const renderCameras = (row, answer) => {
    if (!answer.cameras.length) {
      row.append(el("span", "", say("cam.none", { r: answer.radius_m })));
      return;
    }
    const items = el("ul", "fl-cams");
    answer.cameras.slice(0, 3).forEach((c) => {
      const li = el("li", "fl-cam");
      li.append(el("span", "fl-cam__name", cameraName(c)));
      li.append(el("span", "fl-cam__meta", [
        say("cam.dist", { n: number(c.distance_m) }),
        say(`cam.status.${c.status}`),
        say(`cam.mode.${c.access_mode}`),
      ].join(" · ")));
      const why = c.reasons.map((r) => say(`cam.reason.${r}`)).join(", ");
      li.append(el("span", "fl-cam__role", c.role === "officer_can_look" ? say("cam.look") : say("cam.cannot", { reasons: why })));
      if (c.viewer_url && !c.placeholder) {
        const link = el("a", "fl-cam__open", say("cam.open"));
        link.href = c.viewer_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        li.append(link);
      }
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
  $("[data-inc-more]").addEventListener("click", () => { state.allIncidents = !state.allIncidents; drawIncidents(); });
  PilotText.onChange(() => { fillAreas(); drawAll(); });

  GRP.bindSignOut();
  GRP.me()
    .then(async (identity) => {
      const isAdmin = identity.is_platform_admin || identity.memberships.some((m) => m.role === "admin");
      $("[data-river-link]").hidden = !isAdmin;
      // ADR-0042: only members of the pilot's Hubs record checks; the server enforces it too.
      state.canWrite = identity.memberships.length > 0;
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
