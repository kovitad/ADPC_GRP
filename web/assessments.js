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
  let pollTimer = null;
  let map = null;
  let layers = null;

  const option = (select, value, text) => {
    const item = document.createElement("option");
    item.value = value;
    item.textContent = text;
    select.append(item);
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

  const loadCatalog = async () => {
    const query = `?hub_code=${encodeURIComponent(hubCode)}`;
    const [areas, datasets, methods] = await Promise.all([
      GRP.request(`/api/v1/catalog/boundaries${query}`),
      GRP.request(`/api/v1/catalog/datasets${query}`),
      GRP.request(`/api/v1/catalog/methods${query}`),
    ]);
    boundaries = areas.boundaries;
    const boundarySelect = $("[data-boundary]");
    boundaries.forEach((b) =>
      option(boundarySelect, b.id, `${b.name} (${b.admin_level}${b.synthetic ? ", synthetic" : ""})`),
    );
    datasets.datasets
      .filter((d) => d.type === "hazard")
      .forEach((d) => option($("[data-hazard]"), d.version_id,
        `RP${d.return_period_years} · ${d.title} (${d.provider})`));
    const centers = $("[data-centers]");
    ["platform", "hub_local"].forEach((owner) => {
      const group = document.createElement("optgroup");
      group.label = owner === "platform" ? "Platform data" : "Saved local data";
      datasets.datasets
        .filter((d) => d.type === "evacuation_centers" && d.owner_kind === owner)
        .forEach((d) => option(group, d.version_id, `${d.title} (${d.provider})`));
      if (group.children.length) centers.append(group);
    });
    methods.methods.forEach((m) => option($("[data-method]"), `${m.key}@${m.version}`,
      `${m.key} ${m.version}${m.status === "approved" ? "" : " (draft, not approved)"}`));
    $("[data-new-card]").hidden = false;
    $("[data-recent-card]").hidden = false;
  };

  const hazardYears = () => {
    const text = $("[data-hazard]").selectedOptions[0]?.textContent || "";
    return Number((text.match(/RP(\d+)/) || [])[1]);
  };

  const showRecent = async () => {
    const payload = await GRP.request(`/api/v1/assessments?hub_code=${encodeURIComponent(hubCode)}`);
    const body = $("[data-recent]");
    body.replaceChildren();
    payload.assessments.forEach((a) => {
      const row = document.createElement("tr");
      GRP.cell(row, GRP.formatTime(a.submitted_at));
      GRP.cell(row, `${a.area} · RP${a.scenario.return_period_years}`);
      GRP.cell(row, a.state);
      GRP.cell(row, a.support_ref);
      const action = GRP.cell(row, "");
      const view = document.createElement("button");
      view.type = "button";
      view.className = "button button--secondary";
      view.textContent = "Open";
      view.addEventListener("click", () => watch(a.assessment_id));
      action.append(view);
      if (a.state === "queued" || a.state === "running") {
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "button button--secondary";
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
      body.append(row);
    });
    if (payload.assessments.length === 0) GRP.emptyRow(body, 5, "No assessments yet.");
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
    $("[data-synthetic]").hidden = !status.synthetic;
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
    const boundary = boundaries.find((b) => b.id === result.area_detail.id);
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
          boundary_id: $("[data-boundary]").value,
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
