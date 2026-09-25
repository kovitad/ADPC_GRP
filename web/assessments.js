(() => {
  const $ = (selector) => document.querySelector(selector);
  const STATUS_TEXT = {
    potentially_exposed: "Potentially exposed under this scenario",
    not_exposed_under_scenario: "Not exposed under this scenario",
    unable_to_assess: "Unable to assess",
  };
  const STATUS_COLOR = {
    potentially_exposed: "#c2410c",
    not_exposed_under_scenario: "#0f766e",
    unable_to_assess: "#6b7280",
  };
  const ERROR_TEXT = {
    INPUT_FINGERPRINT_MISMATCH: "A required dataset has changed. Please run the assessment again.",
    INPUT_VERSION_MISSING: "A required dataset is missing.",
    RESULT_RULE_FAILED: "The assessment could not be completed.",
    ACCESS_NOT_AUTHORIZED: "Access not authorized.",
  };

  let hubCode = null;
  let boundaries = [];
  let datasets = [];
  let pollTimer = null;
  let map = null;
  let layers = null;

  const option = (select, value, text) => {
    const item = document.createElement("option");
    item.value = value;
    item.textContent = text;
    select.append(item);
  };

  const centerOptionText = (dataset) => {
    const status = dataset.is_current ? "Recommended · Ready" : "Previous version · Ready";
    const count = Number(dataset.feature_count || 0);
    const names = `${dataset.title_th ? `${dataset.title_th} / ` : ""}${dataset.title}`;
    const countText = count ? ` · ${count.toLocaleString()} centres` : "";
    return `${status} · ${names}${countText} · v${dataset.version_id.slice(0, 8)}`;
  };

  const setAssessmentUrl = (id) => {
    const url = new URL(window.location.href);
    url.searchParams.set("assessment_id", id);
    window.history.replaceState({}, "", url);
  };

  // The chosen area is the sub-district when one is picked, otherwise the district. One helper, so
  // the map outline, the dataset compatibility check and the submitted id cannot disagree.
  const selectedAreaId = () => {
    const sub = $("[data-subdistrict]");
    return (sub && !sub.disabled && sub.value) || $("[data-boundary]").value || "";
  };

  const selectedArea = () => boundaries.find((item) => item.id === selectedAreaId()) || null;

  // A past result can be for an area outside the province currently loaded in the picker, so its
  // outline is fetched on demand rather than assumed to be in memory (backlog U2).
  const outlineCache = new Map();
  const areaOutline = async (detail) => {
    if (!detail || !detail.id) return null;
    const known = boundaries.find((item) => item.id === detail.id);
    if (known && known.geometry) return known;
    if (outlineCache.has(detail.id)) return outlineCache.get(detail.id);
    const params = new URLSearchParams({ hub_code: hubCode, level: detail.admin_level });
    if (detail.admin_level === "subdistrict") {
      params.set("parent_admin_code", String(detail.admin_code).slice(0, 4));
    } else {
      params.set("province_code", String(detail.admin_code).slice(0, 2));
    }
    let found = null;
    try {
      const payload = await GRP.request(`/api/v1/catalog/boundaries?${params}`);
      found = payload.boundaries.find((item) => item.id === detail.id) || null;
    } catch (error) {
      found = null;
    }
    outlineCache.set(detail.id, found);
    return found;
  };

  const showCompatibleDatasets = () => {
    const boundary = selectedArea();
    const hazard = $("[data-hazard]");
    const centers = $("[data-centers]");
    hazard.replaceChildren();
    centers.replaceChildren();
    if (!boundary) return;
    const compatible = datasets.filter(
      (dataset) => Boolean(dataset.synthetic) === Boolean(boundary.synthetic),
    );
    compatible
      .filter((dataset) => dataset.type === "hazard")
      .forEach((dataset) => option(
        hazard,
        dataset.version_id,
        `RP${dataset.return_period_years} · ${dataset.title} (${dataset.provider})`,
      ));
    const seenVersions = new Set();
    [true, false].forEach((isCurrent) => {
      const group = document.createElement("optgroup");
      group.label = isCurrent ? "Recommended dataset" : "Previous versions";
      compatible
        .filter((dataset) => dataset.type === "evacuation_centers" && dataset.is_current === isCurrent)
        .filter((dataset) => {
          if (seenVersions.has(dataset.version_id)) return false;
          seenVersions.add(dataset.version_id);
          return true;
        })
        .sort((left, right) => Number(right.is_current) - Number(left.is_current))
        .forEach((dataset) => option(
          group,
          dataset.version_id,
          centerOptionText(dataset),
        ));
      if (group.children.length) centers.append(group);
    });
    const ready = Boolean(hazard.options.length && centers.options.length);
    $("[data-submit-button]").disabled = !ready;
    $("[data-compatibility-note]").textContent = ready
      ? boundary.synthetic
        ? "Synthetic test area: only synthetic test inputs are available."
        : "Real district: synthetic test inputs are excluded."
      : "No compatible flood and evacuation-centre data is available for this area.";
  };

  const ensureMap = () => {
    if (map) return;
    map = window.L.map("result-map").setView([15.05, 100.07], 11);
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
    layers = window.L.layerGroup().addTo(map);
  };

  // Districts without geometry, only for the type-ahead. Outlines are fetched one province at a
  // time, because sending 928 polygons just to fill a dropdown made this page slow (backlog U2).
  let searchIndex = [];

  const areaLabel = (area) => {
    const thai = area.name_th ? ` · ${area.name_th}` : "";
    return `${area.name}${thai}${area.synthetic ? " (synthetic)" : ""}`;
  };

  const fillSubdistricts = async (district) => {
    const field = $("[data-subdistrict-field]");
    const select = $("[data-subdistrict]");
    select.replaceChildren();
    select.disabled = true;
    field.hidden = true;
    if (!district || district.synthetic) return;
    const payload = await GRP.request(
      `/api/v1/catalog/boundaries?hub_code=${encodeURIComponent(hubCode)}`
      + `&level=subdistrict&parent_admin_code=${encodeURIComponent(district.admin_code)}`,
    );
    if (!payload.boundaries.length) return;
    // Merge so selectedArea() can find a sub-district, and keep its outline for the map.
    boundaries = boundaries
      .filter((item) => item.admin_level !== "subdistrict")
      .concat(payload.boundaries);
    option(select, "", `Whole district (${district.name})`);
    payload.boundaries.forEach((item) => option(select, item.id, areaLabel(item)));
    select.disabled = false;
    field.hidden = false;
  };

  const fillDistricts = async (provinceCode, { select: preselect = null } = {}) => {
    const boundarySelect = $("[data-boundary]");
    boundarySelect.replaceChildren();
    if (!provinceCode) return;
    const payload = await GRP.request(
      `/api/v1/catalog/boundaries?hub_code=${encodeURIComponent(hubCode)}`
      + `&level=district&province_code=${encodeURIComponent(provinceCode)}`,
    );
    boundaries = payload.boundaries.slice();
    payload.boundaries.forEach((item) => option(boundarySelect, item.id, areaLabel(item)));
    if (preselect && payload.boundaries.some((item) => item.id === preselect)) {
      boundarySelect.value = preselect;
    }
    await fillSubdistricts(selectedArea());
    showCompatibleDatasets();
  };

  const loadCatalog = async () => {
    const query = `?hub_code=${encodeURIComponent(hubCode)}`;
    const [provincePayload, index, datasetPayload, methods] = await Promise.all([
      GRP.request(`/api/v1/catalog/provinces${query}`),
      GRP.request(`/api/v1/catalog/boundaries${query}&include_geometry=false`),
      GRP.request(`/api/v1/catalog/datasets${query}`),
      GRP.request(`/api/v1/catalog/methods${query}`),
    ]);
    datasets = datasetPayload.datasets;
    searchIndex = index.boundaries;

    const provinceSelect = $("[data-province]");
    const provinceCodes = new Set(provincePayload.provinces.map((item) => item.code));
    provincePayload.provinces.forEach((item) => option(
      provinceSelect,
      item.code,
      `${item.name}${item.name_th ? ` · ${item.name_th}` : ""} (${item.district_count})`,
    ));
    // The synthetic test district carries no real province code, so it gets its own entry rather
    // than being hidden behind a province a planner would never think to open.
    const synthetic = searchIndex.filter((item) => item.synthetic);
    synthetic.forEach((item) => {
      const code = item.admin_code.slice(0, 2);
      if (provinceCodes.has(code)) return;
      provinceCodes.add(code);
      option(provinceSelect, code, `${item.name} (test data)`);
    });

    const searchBox = $("[data-area-search]");
    const datalist = $("#area-search-options");
    searchIndex.forEach((item) => {
      const entry = document.createElement("option");
      entry.value = areaLabel(item);
      entry.dataset.id = item.id;
      datalist.append(entry);
    });
    const jumpToSearch = async () => {
      const wanted = searchBox.value.trim().toLowerCase();
      if (!wanted) return;
      const match = searchIndex.find((item) => areaLabel(item).toLowerCase() === wanted)
        || searchIndex.find((item) => item.name.toLowerCase() === wanted)
        || searchIndex.find((item) => item.name.toLowerCase().includes(wanted));
      if (!match) {
        $("[data-compatibility-note]").textContent =
          `No supported district matches "${searchBox.value.trim()}".`;
        return;
      }
      provinceSelect.value = match.admin_code.slice(0, 2);
      await fillDistricts(provinceSelect.value, { select: match.id });
    };
    searchBox.addEventListener("change", jumpToSearch);
    searchBox.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      // This input sits inside the run form; Enter means "find that area", not "run".
      event.preventDefault();
      jumpToSearch();
    });

    provinceSelect.addEventListener("change", () => fillDistricts(provinceSelect.value));
    $("[data-boundary]").addEventListener("change", async () => {
      await fillSubdistricts(boundaries.find((item) => item.id === $("[data-boundary]").value));
      showCompatibleDatasets();
    });
    $("[data-subdistrict]").addEventListener("change", showCompatibleDatasets);
    await fillDistricts(provinceSelect.value);
    methods.methods.forEach((m) => option($("[data-method]"), `${m.key}@${m.version}`,
      `${m.key} ${m.version}${m.status === "approved" ? "" : " (draft, not approved)"}`));
    $("[data-new-card]").hidden = false;
    $("[data-recent-card]").hidden = false;
  };

  const hazardYears = () => {
    const text = $("[data-hazard]").selectedOptions[0]?.textContent || "";
    return Number((text.match(/RP(\d+)/) || [])[1]);
  };

  // How many rows to show before the planner asks for more. The table was the tallest thing on
  // the page and most of it was history nobody was acting on (backlog U3).
  const RECENT_VISIBLE = 5;
  let recentExpanded = false;

  const SHARING_TEXT = {
    private: "Private",
    shared: "Shared with SIG",
    sig_unavailable: "SIG unavailable",
    receipt_issued: "Public receipt issued",
    unshared: "Withdrawn",
  };

  // One line a planner can act on: what the run concluded, or why there is nothing to read yet.
  const resultText = (a) => {
    if (a.state === "queued") return "Waiting to start";
    if (a.state === "running") return "Running…";
    if (a.state === "cancelled") return "Cancelled";
    if (a.state === "failed") return ERROR_TEXT[a.error_code] || "Failed";
    const s = a.summary || {};
    if (typeof s.potentially_exposed !== "number" || typeof s.in_scope !== "number") {
      return "Completed";
    }
    if (!s.in_scope) return "No evacuation centres are recorded in this area";
    // The delivered flood layer records a depth only where it floods, so an unassessed centre is
    // not a safe one. Where nothing could be assessed, say that rather than "0 may be exposed",
    // which reads as an all-clear (see handovers.md 0.2).
    if (!s.potentially_exposed && s.unable_to_assess === s.in_scope) {
      return `None of ${s.in_scope.toLocaleString()} centres could be assessed `
        + "— no modelled flood depth there";
    }
    const parts = [`${s.potentially_exposed.toLocaleString()} of `
      + `${s.in_scope.toLocaleString()} centres may be exposed`];
    if (s.unable_to_assess) {
      parts.push(`${s.unable_to_assess.toLocaleString()} could not be assessed`);
    }
    return parts.join(" · ");
  };

  const recentRow = (a) => {
    const row = document.createElement("tr");

    const area = GRP.cell(row, "");
    const areaName = document.createElement("strong");
    areaName.textContent = `${a.area} · RP${a.scenario.return_period_years}`;
    area.append(areaName);
    const ref = document.createElement("div");
    ref.className = "assignment-status";
    ref.textContent = `${a.support_ref}${a.synthetic ? " · synthetic test data" : ""}`;
    area.append(ref);

    GRP.cell(row, resultText(a));
    GRP.cell(row, GRP.formatTime(a.submitted_at));
    GRP.cell(row, SHARING_TEXT[a.sharing_state] || a.sharing_state);

    const action = GRP.cell(row, "");
    const done = a.state === "succeeded";
    // One prominent action per row. Opening the locked result is what a planner does next; the
    // others are demoted so the row reads as a single choice rather than three equal buttons.
    const view = document.createElement("button");
    view.type = "button";
    view.className = done ? "button button--primary" : "button button--secondary";
    view.textContent = done ? "Open result" : "Open";
    view.addEventListener("click", () => {
      setAssessmentUrl(a.assessment_id);
      watch(a.assessment_id);
    });
    action.append(view);

    if (done) {
      const planning = document.createElement("a");
      planning.className = "link-button";
      planning.textContent = "Open in Planning";
      planning.href = `/planning.html?assessment_id=${encodeURIComponent(a.assessment_id)}`;
      action.append(planning);
    }

    if (a.state === "queued" || a.state === "running") {
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "link-button";
      cancel.textContent = "Cancel";
      cancel.addEventListener("click", async () => {
        cancel.disabled = true;
        try {
          await GRP.request(`/api/v1/assessments/${a.assessment_id}/cancel`, { method: "POST" });
        } catch (error) {
          $("[data-submit-status]").textContent = error.message;
        }
        showRecent();
      });
      action.append(cancel);
    }
    return row;
  };

  const showRecent = async () => {
    const payload = await GRP.request(`/api/v1/assessments?hub_code=${encodeURIComponent(hubCode)}`);
    const body = $("[data-recent]");
    const note = $("[data-recent-note]");
    const more = $("[data-recent-more]");
    body.replaceChildren();
    const all = payload.assessments;
    if (!all.length) {
      GRP.emptyRow(body, 5, "No assessments yet. Pick an area above and run one.");
      note.hidden = true;
      more.hidden = true;
      return;
    }
    const visible = recentExpanded ? all : all.slice(0, RECENT_VISIBLE);
    visible.forEach((a) => body.append(recentRow(a)));
    const running = all.filter((a) => a.state === "queued" || a.state === "running").length;
    note.textContent = running
      ? `${all.length} assessment(s) in this Hub · ${running} still running.`
      : `${all.length} assessment(s) in this Hub.`;
    note.hidden = false;
    if (all.length > RECENT_VISIBLE) {
      more.hidden = false;
      more.textContent = recentExpanded
        ? `Show only the latest ${RECENT_VISIBLE}`
        : `Show all ${all.length}`;
    } else {
      more.hidden = true;
    }
  };

  const fillList = (selector, values) => {
    const list = $(selector);
    list.replaceChildren();
    values.forEach((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      list.append(item);
    });
  };

  const showStatus = (status) => {
    $("[data-result-card]").hidden = false;
    if (status.state !== "succeeded") $("[data-open-planning]").hidden = true;
    $("[data-synthetic]").hidden = !status.synthetic;
    const incompatible = $("[data-incompatible]");
    incompatible.hidden = status.input_compatible !== false;
    incompatible.textContent = status.input_warning || "";
    $("[data-result-title]").textContent = `${status.area} · ${status.scenario.return_period_years}-year flood`;
    const pill = $("[data-state-pill]");
    pill.textContent = status.state;
    pill.dataset.state = status.state === "succeeded" ? "active" : status.state === "failed" ? "limit_reached" : "ai_off";
    let meta = `Support reference ${status.support_ref} · method ${status.method.key} ${status.method.version}`;
    if (status.state === "queued" || status.state === "running") meta = `Working in the background… ${meta}`;
    if (status.error_code) meta = `${ERROR_TEXT[status.error_code] || status.error_code} ${meta}`;
    $("[data-result-meta]").textContent = meta;
    if (status.state !== "succeeded") {
      $("[data-totals]").replaceChildren();
      $("[data-trust]").replaceChildren();
      $("[data-centers-table]").replaceChildren();
    }
  };

  const showResult = async (id) => {
    const [result, centers] = await Promise.all([
      GRP.request(`/api/v1/assessments/${id}/result`),
      GRP.request(`/api/v1/assessments/${id}/centers?size=200`),
    ]);
    showStatus(result);
    setAssessmentUrl(id);
    const planningLink = $("[data-open-planning]");
    planningLink.href = `/planning.html?assessment_id=${encodeURIComponent(id)}`;
    planningLink.hidden = false;
    const totals = $("[data-totals]");
    totals.replaceChildren();
    [
      ["Centers in area", result.summary.in_scope],
      ["Potentially exposed", result.summary.potentially_exposed],
      ["Not exposed under this scenario", result.summary.not_exposed_under_scenario],
      ["Unable to assess", result.summary.unable_to_assess],
    ].forEach(([label, value]) => {
      const card = document.createElement("article");
      const name = document.createElement("span");
      const number = document.createElement("strong");
      name.textContent = label;
      number.textContent = String(value);
      card.append(name, number);
      totals.append(card);
    });
    const trust = $("[data-trust]");
    trust.replaceChildren();
    [
      `Scientifically approved: ${result.trust.scientifically_approved ? "yes" : "no"}`,
      `Sharing: ${result.trust.sharing_state}`,
      `Receipt: ${result.trust.receipt_id || "none"}`,
    ].forEach((text) => {
      const pill = document.createElement("span");
      pill.className = "status-pill";
      pill.textContent = text;
      trust.append(pill);
    });

    const table = $("[data-centers-table]");
    table.replaceChildren();
    ensureMap();
    layers.clearLayers();
    const boundary = await areaOutline(result.area_detail);
    let bounds = null;
    if (boundary) {
      const outline = window.L.geoJSON(boundary.geometry, {
        style: { color: "#1b678f", weight: 2, fillColor: "#8db33f", fillOpacity: 0.08 },
      }).addTo(layers);
      bounds = outline.getBounds();
    }
    centers.centers.forEach((c) => {
      const row = document.createElement("tr");
      GRP.cell(row, c.name);
      GRP.cell(row, STATUS_TEXT[c.status]);
      const meaning = (result.reason_codes[c.reason_code] || {}).meaning || c.reason_code;
      GRP.cell(row, meaning);
      GRP.cell(row, c.flood_depth_m === null ? "–" : `${c.flood_depth_m} m`);
      table.append(row);
      window.L.circleMarker([c.lat, c.lon], {
        radius: 8, color: "#fff", weight: 2, fillColor: STATUS_COLOR[c.status], fillOpacity: 0.95,
      })
        .bindPopup(`<strong></strong><br><span></span>`)
        .on("popupopen", (event) => {
          const node = event.popup.getElement();
          node.querySelector("strong").textContent = c.name;
          node.querySelector("span").textContent = STATUS_TEXT[c.status];
        })
        .addTo(layers);
    });
    if (bounds) map.fitBounds(bounds, { padding: [20, 20] });
    window.setTimeout(() => map.invalidateSize(), 50);

    fillList("[data-sources]", result.datasets.map((d) =>
      `${d.role.replace("_", " ")}: ${d.title} · ${d.provider} · sha256 ${d.sha256.slice(0, 12)}…`)
      .concat([`Area: ${result.area_detail.name} (${result.area_detail.source}, ${result.area_detail.edition})`]));
    fillList("[data-gaps]", result.gaps);
    fillList("[data-limits]", result.limits);
  };

  const watch = async (id) => {
    window.clearTimeout(pollTimer);
    try {
      const status = await GRP.request(`/api/v1/assessments/${id}`);
      if (status.state !== "queued" && status.state !== "running") GRP.jobs.done(id);
      if (status.state === "succeeded") {
        await showResult(id);
        showRecent();
        return;
      }
      showStatus(status);
      if (status.state === "queued" || status.state === "running") {
        pollTimer = window.setTimeout(() => watch(id), 5000);
      } else {
        showRecent();
      }
    } catch (error) {
      $("[data-submit-status]").textContent = error.message;
    }
  };

  $("[data-submit-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("[data-submit-button]");
    const status = $("[data-submit-status]");
    button.disabled = true;
    status.textContent = "Submitting…";
    const [key, version] = $("[data-method]").value.split("@");
    try {
      const accepted = await GRP.request("/api/v1/assessments", {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: {
          hub_code: hubCode,
          boundary_id: selectedAreaId(),
          hazard: { type: "flood", return_period_years: hazardYears(), dataset_version_id: $("[data-hazard]").value },
          evacuation_centers_dataset_version_id: $("[data-centers]").value,
          vulnerability_dataset_version_id: null,
          method: { key, version },
        },
      });
      status.textContent =
        `Job accepted (${accepted.support_ref}). It runs in the background; you can leave this page and will be told when it finishes.`;
      GRP.jobs.track({
        id: accepted.assessment_id,
        label: `Assessment ${accepted.support_ref}`,
        statusPath: `/api/v1/assessments/${accepted.assessment_id}`,
        href: "/assessments.html",
        ownerPath: "/assessments.html",
      });
      watch(accepted.assessment_id);
      showRecent();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  $("[data-refresh-recent]").addEventListener("click", () => showRecent());
  $("[data-recent-more]").addEventListener("click", () => {
    recentExpanded = !recentExpanded;
    showRecent();
  });

  GRP.bindSignOut();

  GRP.me()
    .then(async (identity) => {
      const membership = identity.memberships.find((m) => ["ndmo_planner", "hub_expert", "planner", "admin"].includes(m.role));
      if (!membership) {
        $("[data-page-status]").textContent =
          "You need an NDMO Planner, Hub Expert / GIS Specialist, or Hub Admin role in a Hub to run assessments. A Platform Admin role alone is not enough.";
        return;
      }
      hubCode = membership.hub_code;
      $("[data-hub-pill]").textContent = `${membership.hub_name} · ${membership.role}`;
      $("[data-page-status]").textContent =
        "Pick an area, scenario and data, then run. The result shows which centers may be exposed and why.";
      await loadCatalog();
      await showRecent();
      const requestedAssessmentId = new URLSearchParams(window.location.search).get("assessment_id");
      if (requestedAssessmentId) {
        watch(requestedAssessmentId);
        return;
      }
      // A job started here before switching pages: keep following it.
      const pending = GRP.jobs.list().find((job) => job.ownerPath === "/assessments.html");
      if (pending) watch(pending.id);
    })
    .catch((error) => {
      if (error.status === 401 || error.status === 403) {
        window.location.replace("/");
        return;
      }
      $("[data-page-status]").textContent = error.message;
    });
})();
