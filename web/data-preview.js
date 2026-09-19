/* Unapproved district preview (backlog Epic P).
 *
 * Draws one district's delivered files — outline, shelters, RP100 flood depth — with the gaps
 * that stop them being a result. It never says "not exposed": a shelter on a no-value pixel is
 * shown as exactly that, because what no-value means is the open DEP-05 decision.
 */
(() => {
  "use strict";

  const STATE_KEY = "grp.datapreview.v1";
  const POLL_MS = 1500;
  const PAGE = "/data-preview.html";

  const $ = (selector) => document.querySelector(selector);
  const form = $("[data-ask]");
  const input = $("[data-input]");
  const candidatesBox = $("[data-candidates]");
  const progressCard = $("[data-progress-card]");
  const progressPill = $("[data-progress-pill]");
  const progressText = $("[data-progress-text]");
  const progressFill = $("[data-progress-fill]");
  const resultCard = $("[data-result]");
  const countsBox = $("[data-counts]");
  const mapBox = $("[data-map]");
  const legendBox = $("[data-legend]");
  const warningsBox = $("[data-warnings]");
  const errorBox = $("[data-error]");

  // Shelter colours by what the flood file says at its location. No green: nothing here is safe.
  const FLOOD_STYLE = {
    on_flood_pixel: { colour: "#08519c", label: "on a flooded pixel" },
    zero_depth: { colour: "#6b7c86", label: "on a 0 m pixel" },
    no_value: { colour: "#963ca0", label: "on a no-value pixel (meaning undecided)" },
    outside_tiles: { colour: "#3a3b3d", label: "outside every flood tile" },
  };
  const ELSEWHERE = { colour: "#c2410c", label: "names this district but lies outside it" };
  const GRADE_LABELS = { blocker: "Blocker", problem: "Problem", known: "Known already" };

  let map = null;
  let layers = null;
  let pollTimer = null;

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const readState = () => {
    try {
      return JSON.parse(localStorage.getItem(STATE_KEY) || "{}");
    } catch (_) {
      return {};
    }
  };

  const writeState = (value) => {
    try {
      localStorage.setItem(STATE_KEY, JSON.stringify(value));
    } catch (_) {
      /* storage blocked: the page just does not remember the district */
    }
  };

  const showError = (message) => {
    errorBox.textContent = message;
    errorBox.hidden = false;
  };

  const setProgress = (state, text, fraction) => {
    progressCard.hidden = false;
    progressPill.textContent = state;
    progressText.textContent = text;
    progressFill.style.width = `${Math.round(fraction * 100)}%`;
  };

  /* ---------- ask, follow, resume ---------- */

  const ask = async (district) => {
    errorBox.hidden = true;
    candidatesBox.hidden = true;
    window.clearTimeout(pollTimer);
    input.value = district;
    setProgress("Checking", "Fingerprinting the boundary, shelter and flood files…", 0.15);
    try {
      const started = await GRP.request("/api/v1/data-inspector/previews", {
        method: "POST",
        body: { district },
      });
      writeState({ district, inspection_id: started.inspection_id });
      if (!started.from_cache) {
        GRP.jobs.track({
          id: started.inspection_id,
          label: `Map preview (${district})`,
          statusPath: `/api/v1/data-inspector/inspections/${started.inspection_id}`,
          href: PAGE,
          ownerPath: PAGE,
        });
        setProgress(
          "Queued",
          "The worker clips the flood tiles to the district. You can leave this page; you will be told when it is ready.",
          0.3
        );
      }
      poll(started.inspection_id, 0);
    } catch (error) {
      progressCard.hidden = true;
      showError(error.message || "The preview could not be asked for.");
    }
  };

  const poll = async (inspectionId, count) => {
    let payload;
    try {
      payload = await GRP.request(`/api/v1/data-inspector/inspections/${inspectionId}`);
    } catch (error) {
      progressCard.hidden = true;
      if (error.status === 404) writeState({});
      else showError(error.message || "The preview could not be read.");
      return;
    }
    if (payload.state !== "queued" && payload.state !== "running") GRP.jobs.done(inspectionId);
    if (payload.state === "succeeded") {
      progressCard.hidden = true;
      render(payload.report || {}, inspectionId);
      return;
    }
    if (payload.state === "failed") {
      progressCard.hidden = true;
      const reason = payload.report && payload.report.not_found;
      showError(reason || `The preview stopped: ${payload.error_code}. Quote ${payload.support_ref}.`);
      return;
    }
    if (count > 120) {
      progressCard.hidden = true;
      showError(
        "The preview is taking longer than expected. It keeps running in the background and " +
          "you will be told when it finishes; if it never does, check that the worker is running."
      );
      return;
    }
    setProgress(
      payload.state === "running" ? "Drawing" : "Queued",
      payload.state === "running"
        ? "Clipping the flood depth to the district and placing the shelters…"
        : "Waiting for the worker to pick this up…",
      Math.min(0.3 + count * 0.04, 0.92)
    );
    pollTimer = window.setTimeout(() => poll(inspectionId, count + 1), POLL_MS);
  };

  /* ---------- the preview ---------- */

  const renderCandidates = (report) => {
    candidatesBox.replaceChildren();
    candidatesBox.append(
      el("p", "inspector-note", `${report.candidates.length} districts share that name. Pick one:`)
    );
    report.candidates.forEach((c) => {
      const button = el("button", "preview-chip", `${c.name_en} (${c.name_th}), ${c.province_en} · ${c.admin_code}`);
      button.type = "button";
      button.addEventListener("click", () => ask(c.admin_code));
      candidatesBox.append(button);
    });
    candidatesBox.hidden = false;
  };

  const renderCounts = (counts, flood) => {
    const tiles = [
      [counts.in_district, "shelters inside the outline", ""],
      [counts.on_flood_pixel, "on a flooded pixel", "is-problem"],
      [counts.on_no_value_pixel, "on a no-value pixel", "is-blocker"],
      [counts.outside_tiles, "outside every flood tile", ""],
      [counts.names_other_district + counts.named_here_but_elsewhere, "misplaced or misnamed", "is-problem"],
    ];
    if (flood && flood.no_value_share !== null && flood.no_value_share !== undefined) {
      tiles.push([`${Math.round(flood.no_value_share * 100)}%`, "of the district has no flood value", "is-blocker"]);
    }
    countsBox.replaceChildren();
    tiles.forEach(([value, label, grade]) => {
      const box = el("div", `inspector-tally__item ${grade}`);
      box.append(el("strong", null, String(value ?? 0)));
      box.append(el("span", null, label));
      countsBox.append(box);
    });
  };

  const renderWarnings = (warnings) => {
    warningsBox.replaceChildren();
    warnings.forEach((w) => {
      const card = el("article", `inspector-finding is-${w.grade}`);
      const head = el("div", "inspector-finding__head");
      head.append(el("span", "inspector-finding__grade", GRADE_LABELS[w.grade] || w.grade));
      head.append(el("h4", null, w.title));
      card.append(head);
      card.append(el("p", null, w.why));
      card.append(el("p", "inspector-finding__affects", `Waits on: ${w.waits_on}`));
      warningsBox.append(card);
    });
  };

  const legendItem = (colour, label, shape = "dot") => {
    const item = el("span", "preview-legend__item");
    const swatch = el("span", `preview-legend__${shape}`);
    swatch.style.background = colour;
    item.append(swatch, document.createTextNode(label));
    return item;
  };

  const renderLegend = (flood) => {
    legendBox.replaceChildren();
    const shelters = el("p", "preview-legend__row");
    shelters.append(el("strong", null, "Shelters: "));
    Object.values(FLOOD_STYLE).forEach((s) => shelters.append(legendItem(s.colour, s.label)));
    shelters.append(legendItem(ELSEWHERE.colour, ELSEWHERE.label));
    legendBox.append(shelters);
    if (flood && flood.available) {
      const depth = el("p", "preview-legend__row");
      depth.append(el("strong", null, "Flood depth (RP100): "));
      flood.classes.forEach((c) =>
        depth.append(legendItem(`rgba(${c.rgba.slice(0, 3).join(",")},${c.rgba[3] / 255})`, c.label, "box"))
      );
      const hatch = legendItem("", flood.no_value.label, "box");
      hatch.querySelector("span").classList.add("preview-legend__hatch");
      depth.append(hatch);
      legendBox.append(depth);
    } else if (flood) {
      legendBox.append(el("p", "inspector-note", flood.reason || "No flood picture for this district."));
    }
    legendBox.append(
      el("p", "inspector-note", "A dashed red ring marks a shelter inside the outline that names another district.")
    );
  };

  const drawMap = (report, inspectionId) => {
    if (typeof L === "undefined") {
      mapBox.textContent = "The map library did not load.";
      return;
    }
    if (!map) {
      map = L.map(mapBox);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors",
        maxZoom: 18,
      }).addTo(map);
      layers = L.layerGroup().addTo(map);
    }
    layers.clearLayers();
    const outline = L.geoJSON(report.outline, {
      style: { color: "#0d2534", weight: 2, fill: false },
      interactive: false,
    }).addTo(layers);
    const flood = report.flood || {};
    if (flood.available) {
      L.imageOverlay(`/api/v1/data-inspector/previews/${inspectionId}/flood.png`, flood.bounds, {
        opacity: 0.85,
        interactive: false,
      }).addTo(layers);
      outline.bringToFront();
    }
    const tooltip = (s, status) =>
      `<strong>${escapeHtml(s.name)}</strong><br>${escapeHtml(status)}` +
      (s.depth_m !== null && s.depth_m !== undefined ? ` · ${s.depth_m} m` : "") +
      `<br>Names: ${escapeHtml(s.named_district || "—")}, ${escapeHtml(s.named_province || "—")}`;
    (report.shelters || []).forEach((s) => {
      const style = FLOOD_STYLE[s.flood] || FLOOD_STYLE.outside_tiles;
      L.circleMarker([s.lat, s.lon], {
        radius: 6,
        color: s.names_this_district ? "#ffffff" : "#d62828",
        dashArray: s.names_this_district ? null : "3 3",
        weight: s.names_this_district ? 1.5 : 3,
        fillColor: style.colour,
        fillOpacity: 0.95,
      })
        .bindTooltip(tooltip(s, style.label))
        .addTo(layers);
    });
    (report.shelters_elsewhere || []).forEach((s) => {
      L.circleMarker([s.lat, s.lon], {
        radius: 6,
        color: "#ffffff",
        weight: 1.5,
        fillColor: ELSEWHERE.colour,
        fillOpacity: 0.95,
      })
        .bindTooltip(tooltip(s, ELSEWHERE.label))
        .addTo(layers);
    });
    // Fit the district; misplaced shelters far away are listed in the warnings, not zoomed to.
    map.fitBounds(outline.getBounds(), { padding: [20, 20] });
    window.setTimeout(() => map.invalidateSize(), 60);
  };

  const escapeHtml = (value) =>
    String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const render = (report, inspectionId) => {
    if (report.candidates) {
      resultCard.hidden = true;
      renderCandidates(report);
      return;
    }
    const d = report.district || {};
    $("[data-result-eyebrow]").textContent =
      `${d.province_en || ""} · admin code ${d.admin_code || "—"} · boundary edition ${d.edition || "—"}`;
    $("[data-result-title]").textContent = `${d.name_en || report.query} (${d.name_th || ""})`;
    resultCard.hidden = false;
    renderCounts(report.counts || {}, report.flood);
    renderWarnings(report.warnings || []);
    renderLegend(report.flood);
    drawMap(report, inspectionId);
  };

  /* ---------- start ---------- */

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const district = input.value.trim();
    if (district) ask(district);
  });
  document.querySelectorAll("[data-try]").forEach((button) =>
    button.addEventListener("click", () => ask(button.dataset.try))
  );

  const saved = readState();
  if (saved.inspection_id) {
    input.value = saved.district || "";
    setProgress("Checking", "Picking up the preview you asked for…", 0.3);
    poll(saved.inspection_id, 0);
  }
})();
