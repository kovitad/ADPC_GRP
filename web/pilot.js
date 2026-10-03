// ADR-0036: River Watch pilot. A GEOGLOWS river forecast, written for someone without hydrology training.
(() => {
  const $ = (selector) => document.querySelector(selector);
  const SVG = "http://www.w3.org/2000/svg";
  const TZ = "Asia/Bangkok";
  const POOL_M3 = 2500; // An Olympic swimming pool.
  const BATHTUB_M3 = 0.15;
  const state = { reaches: [], reachId: null, view: null, mode: "bbt", districts: [], district: null };
  const say = PilotText.t;
  // Leaflet renders a string tooltip as HTML; place names from data go in as text only.
  const textNode = (text) => {
    const span = document.createElement("span");
    span.textContent = text;
    return span;
  };

  const number = (value, digits = 3) =>
    new Intl.NumberFormat(PilotText.locale(), { maximumSignificantDigits: digits }).format(value);
  const parts = (iso, options) =>
    new Intl.DateTimeFormat(PilotText.locale(), { timeZone: TZ, ...options }).format(new Date(iso));
  const day = (iso) => parts(iso, { weekday: "short", day: "numeric", month: "short" });
  const clock = (iso) => parts(iso, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const hourOf = (iso) => Number(parts(iso, { hour: "2-digit", hourCycle: "h23" }));
  const partOfDay = (iso) => {
    const hour = hourOf(iso);
    if (hour >= 5 && hour < 12) return "morning";
    if (hour >= 12 && hour < 17) return "afternoon";
    if (hour >= 17 && hour < 21) return "evening";
    return "night";
  };
  const when = (iso) => say("when", { day: day(iso), part: say(`day.${partOfDay(iso)}`) });

  // A picture of the amount: pools per second, pools per minute, or bathtubs per second.
  const scale = (m3s) => {
    if (m3s >= POOL_M3) return say("scale.poolsSec", { n: number(m3s / POOL_M3, 2) });
    const perMinute = (m3s * 60) / POOL_M3;
    if (perMinute >= 1) return say("scale.poolsMin", { n: number(perMinute, 2) });
    return say("scale.tubs", { n: number(Math.max(1, Math.round(m3s / BATHTUB_M3))) });
  };

  const TREND = { rise: "is-rise", steady: "is-steady", fall: "is-fall" };

  const showBanner = (text) => {
    const banner = $("[data-banner]");
    banner.textContent = text;
    banner.hidden = !text;
  };

  const setLoading = (on) => {
    $("[data-loading]").hidden = !on;
  };

  const renderReaches = () => {
    const box = $("[data-reaches]");
    box.replaceChildren();
    state.reaches.forEach((reach) => {
      const label = document.createElement("label");
      label.className = "rw-reach";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "reach";
      input.value = String(reach.reach_id);
      input.checked = reach.reach_id === state.reachId;
      input.addEventListener("change", () => {
        state.reachId = reach.reach_id;
        const url = new URL(window.location.href);
        url.searchParams.set("reach", String(reach.reach_id));
        window.history.replaceState(null, "", url);
        renderWhere();
        load();
      });
      const name = document.createElement("span");
      name.className = "rw-reach__name";
      const labelKey = `reach.${reach.reach_id}`;
      name.textContent = say(labelKey) === labelKey ? reach.label : say(labelKey);
      const id = document.createElement("span");
      id.className = "rw-reach__id";
      id.textContent = say("reach.id", { id: reach.reach_id });
      label.append(input, name, id);
      box.append(label);
    });
    $("[data-picker-section]").hidden = false;
  };

  // Where the chosen river is: the model's line over the OpenStreetMap background. In Bang Bua
  // Thong mode the named canals nearby are highlighted; in Bangkok mode the district outline and
  // every model river in it are drawn, and tapping one chooses it.
  const where = { map: null, layer: null };
  const thai = () => PilotText.lang() === "th";
  const waterwayName = (w) => (thai() ? w.name_th || w.name_en : w.name_en || w.name_th);
  const districtName = (d) => (thai() ? d.name_th || d.name : d.name || d.name_th);

  // The chosen river's details, whichever mode it came from.
  const chosen = () => {
    if (state.mode === "bkk") {
      const d = state.district;
      const info = d && d.reaches.find((r) => r.reach_id === state.reachId);
      return info ? { info, point: null } : null;
    }
    const reach = state.reaches.find((r) => r.reach_id === state.reachId);
    return reach && reach.map ? { info: reach.map, point: reach.query_point } : null;
  };

  // A short plain name for the chosen river, shown above the forecast headline.
  const riverLabel = () => {
    const pick = chosen();
    if (!pick) return "";
    if (state.mode !== "bkk") return say(`reach.${state.reachId}`);
    const { info } = pick;
    const base = info.likely
      ? say("river.probably", { name: thai() ? info.likely.name_th : info.likely.name_en })
      : say(`size.${info.size}`);
    return `${base} · ${say("bkk.districtOf", { name: districtName(state.district) })}`;
  };

  const ensureMap = (mapBox) => {
    if (where.map) return;
    where.map = window.L.map(mapBox, { scrollWheelZoom: false });
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "© OpenStreetMap contributors",
    }).addTo(where.map);
  };

  const renderWhere = () => {
    const box = $("[data-where]");
    const pick = chosen();
    if (!pick) { box.hidden = true; return; }
    const { info, point } = pick;
    box.hidden = false;
    box.dataset.mode = state.mode;

    $("[data-where-size]").textContent = say(`where.size.${info.size}`, {
      area: number(info.upstream_area_km2, 3), len: number(info.length_km, 2),
    });
    const likely = $("[data-where-likely]");
    if (info.likely) {
      const name = thai() ? info.likely.name_th : info.likely.name_en;
      likely.textContent = say(`where.likely.${info.likely.reason}`, { name });
      likely.hidden = false;
    } else {
      likely.hidden = true;
    }
    const names = [...new Set(info.waterways.map(waterwayName).filter(Boolean))];
    $("[data-where-along]").textContent = names.length ? say("where.along", { names: names.join(", ") }) : "";

    const mapBox = $("[data-map]");
    mapBox.setAttribute("aria-label", say("where.aria"));
    if (!window.L) { mapBox.hidden = true; return; }
    ensureMap(mapBox);
    if (where.layer) where.layer.remove();
    const toLatLng = (line) => line.map(([lon, lat]) => [lat, lon]);
    const group = window.L.featureGroup();

    if (state.mode === "bkk") {
      group.addLayer(window.L.geoJSON(state.district.outline, {
        style: { color: "#0d2534", weight: 2, dashArray: "6 5", fill: true, fillOpacity: 0.04 },
        interactive: false,
      }));
      state.district.reaches.forEach((r) => {
        if (r.reach_id === state.reachId) return;
        const line = window.L.polyline(toLatLng(r.line), { color: "#2f7fb6", weight: 4, opacity: 0.8 });
        line.bindTooltip(say("where.tip.pick", { size: say(`size.${r.size}`) }));
        line.on("click", () => chooseReach(r.reach_id));
        group.addLayer(line);
      });
    } else {
      const labelled = new Set();
      info.waterways.forEach((w) => {
        if (!w.line) return;
        const line = window.L.polyline(toLatLng(w.line), { color: "#2380b0", weight: 9, opacity: 0.45 });
        const name = waterwayName(w);
        if (name && !labelled.has(name)) {
          line.bindTooltip(textNode(name), { permanent: true, direction: "top", className: "rw-map-label" });
          labelled.add(name);
        } else if (name) {
          line.bindTooltip(textNode(name));
        }
        group.addLayer(line);
      });
    }
    group.addLayer(window.L.polyline(toLatLng(info.line), { color: "#e8590c", weight: 5, opacity: 0.95 })
      .bindTooltip(say("where.tip.model", { id: state.reachId })));
    if (point) {
      group.addLayer(window.L.circleMarker([point[0], point[1]], {
        radius: 6, color: "#ffffff", weight: 2, fillColor: "#58595b", fillOpacity: 1,
      }).bindTooltip(say("where.key.search")));
    }
    group.addTo(where.map);
    where.layer = group;
    where.map.invalidateSize();
    where.map.fitBounds(group.getBounds(), { padding: [24, 24], maxZoom: 15 });
  };

  // ---------- Bangkok, by district ----------

  const setUrl = (params) => {
    const url = new URL(window.location.href);
    Object.entries(params).forEach(([k, v]) => {
      if (v == null) url.searchParams.delete(k);
      else url.searchParams.set(k, String(v));
    });
    window.history.replaceState(null, "", url);
  };

  const renderDistrictOptions = () => {
    const select = $("[data-district]");
    const current = state.district && state.district.admin_code;
    select.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = say("bkk.choose");
    select.append(placeholder);
    const collator = new Intl.Collator(PilotText.locale());
    [...state.districts]
      .sort((a, b) => collator.compare(districtName(a), districtName(b)))
      .forEach((d) => {
        const option = document.createElement("option");
        option.value = d.admin_code;
        option.textContent = d.inland ? districtName(d) : say("bkk.riverside", { name: districtName(d) });
        option.selected = d.admin_code === current;
        select.append(option);
      });
  };

  const renderDistrictNote = () => {
    const d = state.district;
    const note = $("[data-district-note]");
    const inland = $("[data-inland]");
    if (!d) { note.hidden = true; inland.hidden = true; return; }
    note.textContent = d.reaches.length ? say("bkk.count", { n: d.reaches.length }) : say("bkk.none");
    note.hidden = false;
    inland.hidden = !d.inland;
  };

  const chooseReach = (reachId) => {
    state.reachId = reachId;
    setUrl({ reach: reachId });
    renderWhere();
    load();
  };

  const openDistrict = async (code) => {
    if (!code) {
      state.district = null;
      state.reachId = null;
      setUrl({ district: null, reach: null });
      renderDistrictNote();
      renderWhere();
      cancelLoad();
      return;
    }
    const district = await GRP.request(`/api/v1/pilot/river-watch/districts/${encodeURIComponent(code)}`);
    state.district = district;
    $("[data-district]").value = code;
    setUrl({ district: code });
    renderDistrictNote();
    if (district.main_reach) {
      const asked = Number(new URL(window.location.href).searchParams.get("reach"));
      chooseReach(district.reaches.some((r) => r.reach_id === asked) ? asked : district.main_reach);
    } else {
      state.reachId = null;
      renderWhere();
      cancelLoad();
    }
  };

  const setMode = async (mode) => {
    state.mode = mode;
    setUrl({ mode });
    document.querySelectorAll("[data-mode]").forEach((b) => {
      b.setAttribute("aria-selected", String(b.dataset.mode === mode));
    });
    $("[data-mode-bbt]").hidden = mode !== "bbt";
    $("[data-mode-bkk]").hidden = mode !== "bkk";
    cancelLoad();
    state.view = null;
    if (mode === "bkk") {
      if (!state.districts.length) {
        state.districts = (await GRP.request("/api/v1/pilot/river-watch/districts")).districts;
      }
      renderDistrictOptions();
      const code = (state.district && state.district.admin_code)
        || new URL(window.location.href).searchParams.get("district");
      if (code && state.districts.some((d) => d.admin_code === code)) {
        await openDistrict(code);
      } else {
        state.reachId = null;
        renderDistrictNote();
        renderWhere();
      }
    } else {
      setUrl({ district: null });
      const asked = Number(new URL(window.location.href).searchParams.get("reach"));
      state.reachId = state.reaches.some((r) => r.reach_id === asked) ? asked : state.reaches[0].reach_id;
      renderReaches();
      renderWhere();
      await load();
    }
  };

  const renderAnswer = (view) => {
    const s = view.summary;
    const trend = TREND[s.trend] ? s.trend : "steady";
    const headline = $("[data-headline]");
    headline.className = `rw-headline ${TREND[trend]}`;
    const atStart = s.median_peak_valid_at_utc === view.series[0].valid_at_utc;
    // A rise that turns and drops again by the end of the week is said as such.
    const turns = s.trend === "rise" && s.last_median_m3s < s.median_peak_m3s * 0.95;
    headline.replaceChildren(
      say("head.pre"),
      Object.assign(document.createElement("strong"), { textContent: say(`trend.${trend}`) }),
      turns ? say("head.turn", { day: day(s.median_peak_valid_at_utc) }) : say("head.week"),
    );
    const q = number(s.median_peak_m3s);
    $("[data-peak]").textContent = atStart
      ? say("peak.now", { q })
      : say("peak.at", { q, when: when(s.median_peak_valid_at_utc) });
    $("[data-scale]").textContent = say("scale.that", { scale: scale(s.median_peak_m3s) });
    $("[data-range]").textContent =
      s.p25_at_peak_m3s != null && s.p75_at_peak_m3s != null
        ? say("range.both", {
          lo: number(s.p25_at_peak_m3s), hi: number(s.p75_at_peak_m3s), now: number(s.first_median_m3s),
        })
        : say("range.now", { now: number(s.first_median_m3s) });

    const pill = $("[data-fresh-pill]");
    const older = s.quality_state !== "latest";
    pill.className = `rw-pill ${older ? "is-older" : "is-latest"}`;
    pill.textContent = say(older ? "fresh.older" : "fresh.latest");
    pill.title = say(older ? "fresh.olderTip" : "fresh.latestTip");
    const made = say("made", {
      day: day(s.issued_at_utc), time: clock(s.issued_at_utc), checked: clock(s.retrieved_at_utc),
    });
    $("[data-made]").textContent = view.problem
      ? made + say("made.problem", { problem: view.problem })
      : made;
    $("[data-source]").textContent = say("source", { name: view.source.name });
    $("[data-answer-river]").textContent = say("answer.river", { river: riverLabel() });
    $("[data-answer]").hidden = false;
  };

  const el = (name, attrs = {}, text) => {
    const node = document.createElementNS(SVG, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== undefined) node.textContent = text;
    return node;
  };

  // Time on the x-axis (the steps are not evenly spaced); the y-axis starts at zero so a small
  // change is not made to look dramatic.
  const renderChart = (view) => {
    // Drawn at the box's own width so the text stays readable on a phone.
    const box = $("[data-chart]");
    $("[data-chart-card]").hidden = false;
    const W = Math.max(320, Math.round(box.clientWidth || 720));
    const narrow = W < 560;
    const H = narrow ? 240 : 300, L = narrow ? 48 : 64, R = 12, T = 28, B = 44;
    const tick = (iso) => (narrow ? parts(iso, { weekday: "narrow", day: "numeric" }) : day(iso));
    const s = view.summary;
    const rows = view.series;
    const start = Date.parse(s.window_start_utc);
    const end = Date.parse(s.window_end_utc);
    const top = Math.max(...rows.map((r) => (r.p75_m3s != null ? r.p75_m3s : r.median_m3s))) * 1.1 || 1;
    const x = (iso) => L + ((Date.parse(iso) - start) / (end - start)) * (W - L - R);
    const y = (v) => T + (1 - v / top) * (H - T - B);

    const svg = el("svg", {
      viewBox: `0 0 ${W} ${H}`,
      role: "img",
      "aria-label": say("chart.aria", { q: number(s.median_peak_m3s), when: when(s.median_peak_valid_at_utc) }),
    });

    // Horizontal guide lines with values.
    for (let i = 0; i <= 4; i += 1) {
      const v = (top / 4) * i;
      svg.append(el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "rw-grid" }));
      svg.append(el("text", { x: L - 8, y: y(v) + 4, class: "rw-axis", "text-anchor": "end" }, number(v)));
    }
    // A label at each Bangkok midnight.
    const first = new Date(start);
    const bangkokMidnight = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), first.getUTCDate()) - 7 * 3600e3;
    for (let t = bangkokMidnight; t <= end; t += 86400e3) {
      if (t < start) continue;
      const iso = new Date(t).toISOString();
      svg.append(el("line", { x1: x(iso), x2: x(iso), y1: T, y2: H - B, class: "rw-day" }));
      svg.append(el("text", { x: x(iso) + 4, y: H - B + 18, class: "rw-axis" }, tick(iso)));
    }

    // The band only where both ends exist; split into runs at gaps.
    const runs = [];
    let current = [];
    rows.forEach((r) => {
      if (r.p25_m3s != null && r.p75_m3s != null) current.push(r);
      else if (current.length) { runs.push(current); current = []; }
    });
    if (current.length) runs.push(current);
    runs.forEach((run) => {
      const upper = run.map((r) => `${x(r.valid_at_utc)},${y(r.p75_m3s)}`);
      const lower = run.slice().reverse().map((r) => `${x(r.valid_at_utc)},${y(r.p25_m3s)}`);
      svg.append(el("polygon", { points: [...upper, ...lower].join(" "), class: "rw-band" }));
    });

    svg.append(el("polyline", {
      points: rows.map((r) => `${x(r.valid_at_utc)},${y(r.median_m3s)}`).join(" "),
      class: "rw-line",
    }));

    // "Now" at the left edge, and the highest point.
    svg.append(el("text", { x: L + 4, y: T - 10, class: "rw-now" }, say("chart.now")));
    const px = x(s.median_peak_valid_at_utc);
    const py = y(s.median_peak_m3s);
    svg.append(el("circle", { cx: px, cy: py, r: 6, class: "rw-dot" }));
    const anchor = px > W - 130 ? "end" : "start";
    svg.append(el("text", {
      x: anchor === "end" ? px - 10 : px + 10, y: Math.max(T + 12, py - 10), class: "rw-peak-label", "text-anchor": anchor,
    }, say("chart.highest", { q: number(s.median_peak_m3s) })));

    box.replaceChildren(svg);
  };

  const renderSpecialist = (view) => {
    const s = view.summary;
    const facts = [
      [say("fact.source"), view.source.name],
      [say("fact.reach"), String(view.reach.reach_id)],
      [say("fact.run"), `${s.run} (${s.issued_at_utc})`],
      [say("fact.window"), say("fact.windowValue", { a: s.window_start_utc, b: s.window_end_utc })],
      [say("fact.values"), say("fact.valuesValue", { m: s.median_steps_in_window, n: s.steps_in_window })],
      [say("fact.retrieved"), s.retrieved_at_utc],
      [say("fact.request"), view.evidence.request_url],
      [say("fact.sha"), view.evidence.raw_sha256],
      [say("fact.scope"), s.scope_note],
    ];
    const dl = $("[data-facts]");
    dl.replaceChildren();
    facts.forEach(([term, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = term;
      const dd = document.createElement("dd");
      dd.textContent = value;
      dl.append(dt, dd);
    });
    const body = $("[data-table]");
    body.replaceChildren();
    view.series.forEach((r) => {
      const tr = document.createElement("tr");
      [
        `${day(r.valid_at_utc)} ${clock(r.valid_at_utc)}`,
        number(r.median_m3s),
        r.p25_m3s == null ? "—" : number(r.p25_m3s),
        r.p75_m3s == null ? "—" : number(r.p75_m3s),
      ].forEach((text) => {
        const td = document.createElement("td");
        td.textContent = text;
        tr.append(td);
      });
      body.append(tr);
    });
    $("[data-specialist]").hidden = false;
  };

  // Forget any forecast still on its way, and clear the cards.
  let loadSeq = 0;
  const cancelLoad = () => {
    loadSeq += 1;
    hideAll();
    setLoading(false);
  };

  const hideAll = () => {
    ["[data-answer]", "[data-unavailable]", "[data-chart-card]", "[data-guidance]", "[data-specialist]", "[data-feed]"].forEach((sel) => {
      $(sel).hidden = true;
    });
  };

  // Draw the current forecast again in the chosen language, without fetching.
  const redraw = () => {
    if (state.reaches.length) renderReaches();
    if (state.districts.length) { renderDistrictOptions(); renderDistrictNote(); }
    renderWhere();
    const view = state.view;
    if (!view) return;
    if (!view.available) {
      $("[data-unavailable-reason]").textContent = view.problem || say("rw.unavailable.default");
      return;
    }
    renderAnswer(view);
    renderChart(view);
    renderSpecialist(view);
  };

  const load = async () => {
    if (!state.reachId) return;
    const mine = ++loadSeq;
    hideAll();
    showBanner("");
    setLoading(true);
    $("[data-feed]").open = false;
    try {
      const view = await GRP.request(`/api/v1/pilot/river-watch/${state.reachId}`);
      // A slower answer for an earlier choice must not replace the current one.
      if (mine !== loadSeq) return;
      state.view = view;
      if (!view.available) {
        $("[data-unavailable-reason]").textContent = view.problem || say("rw.unavailable.default");
        $("[data-unavailable]").hidden = false;
      } else {
        renderAnswer(view);
        renderChart(view);
        renderSpecialist(view);
        // The card's own preview, built from the same summary, so the two always agree.
        $("[data-feed-json]").textContent = JSON.stringify(view.feed_preview, null, 2);
        $("[data-feed]").hidden = false;
      }
      $("[data-guidance]").hidden = false;
    } catch (error) {
      if (mine === loadSeq) showBanner(error.message);
    } finally {
      if (mine === loadSeq) setLoading(false);
    }
  };

  const downloadRaw = () => {
    const s = state.view && state.view.summary;
    if (!s) return;
    GRP.download(`/api/v1/pilot/river-watch/${state.reachId}/raw/${s.run}`, {
      fallbackName: `geoglows_${state.reachId}_${s.run}.json`,
    }).catch((error) => showBanner(error.message));
  };

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      if (state.view && state.view.available && !$("[data-chart-card]").hidden) renderChart(state.view);
    }, 200);
  });
  PilotText.onChange(redraw);
  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.mode !== state.mode) setMode(button.dataset.mode).catch((e) => showBanner(e.message));
    });
  });
  $("[data-district]").addEventListener("change", (event) => {
    setUrl({ reach: null });
    openDistrict(event.target.value).catch((e) => showBanner(e.message));
  });
  $("[data-refresh]").addEventListener("click", load);
  $("[data-retry]").addEventListener("click", load);
  $("[data-raw]").addEventListener("click", downloadRaw);

  GRP.bindSignOut();
  GRP.me()
    .then(async (identity) => {
      const isAdmin = identity.is_platform_admin || identity.memberships.some((m) => m.role === "admin");
      if (!isAdmin) {
        setLoading(false);
        showBanner(say("rw.adminOnly"));
        return;
      }
      const { reaches } = await GRP.request("/api/v1/pilot/river-watch/reaches");
      state.reaches = reaches;
      $("[data-picker-section]").hidden = false;
      const mode = new URL(window.location.href).searchParams.get("mode") === "bkk" ? "bkk" : "bbt";
      await setMode(mode);
    })
    .catch((error) => {
      if (error.status === 401) {
        window.location.replace("/");
        return;
      }
      setLoading(false);
      showBanner(error.message);
    });
})();
