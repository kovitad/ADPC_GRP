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
    pending: "#ffffff",
  };

  const form = $("[data-question-form]");
  const questionInput = $("[data-question]");
  const placeInput = $("[data-place]");
  const runButton = $("[data-run-button]");
  const status = $("[data-planning-status]");
  const chatHistory = $("[data-chat-history]");
  const conversation = $(".assistant-conversation");
  const mapState = $("[data-map-state]");
  const sigMap = $("[data-sig-map]");

  const state = {
    hubCode: null,
    chatAvailable: false,
    boundaries: [],
    selected: null,
    floodLayers: [],
    centersVersion: null,
    method: null,
    assessmentId: null,
    pollTimer: null,
    history: { result: [], sig: [] },
  };

  const map = window.L.map("risk-map", { zoomControl: true }).setView([13.4, 101.0], 6);
  window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  const districtLayer = window.L.featureGroup().addTo(map);
  const centersLayer = window.L.featureGroup().addTo(map);
  let floodOverlay = null;
  let floodBlobUrl = null;

  const mode = () => ($("[data-mode-result]").checked ? "result" : "sig");

  const safeHttps = (value) => {
    try {
      const url = new URL(value);
      return url.protocol === "https:" ? url.href : null;
    } catch (_error) {
      return null;
    }
  };

  // ---------- chat ----------
  const appendMessage = (role, text, extras = {}) => {
    const article = document.createElement("article");
    article.className = `assistant-message assistant-message--${role === "user" ? "user" : "result"}`;
    const avatar = document.createElement("span");
    avatar.className = "assistant-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = role === "user" ? "You" : "AI";
    const bubble = document.createElement("div");
    const copy = document.createElement("p");
    copy.className = "result-copy";
    copy.textContent = text;
    bubble.append(copy);
    if (extras.label) {
      const label = document.createElement("small");
      label.className = "result-label";
      label.textContent = extras.label;
      bubble.append(label);
    }
    const receiptUrl = extras.receipt && safeHttps(extras.receipt.public_url);
    if (receiptUrl) {
      const link = document.createElement("a");
      link.href = receiptUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = `Open public SIG receipt ${extras.receipt.receipt_id}`;
      bubble.append(link);
    }
    article.append(avatar, bubble);
    chatHistory.append(article);
    conversation.scrollTop = conversation.scrollHeight;
  };

  const showAllowance = (usage) => {
    const line = $("[data-allowance]");
    line.textContent = GRP.allowanceMessage(usage);
    line.classList.toggle("is-low", GRP.isLow(usage));
  };

  const setPrompts = () => {
    const box = $("[data-prompts]");
    box.replaceChildren();
    const prompts = mode() === "result"
      ? [
          ["Summarise the result", "Summarise this result for a planning meeting."],
          ["Why unable to assess?", "Which centers could not be assessed, and why?"],
          ["Deepest flooding", "Which centers have the deepest flood depth?"],
        ]
      : [
          ["Explain a concept", "What is the difference between flood hazard, exposure and risk?"],
          ["SIG exposure", "Which schools and hospitals are exposed to flooding, and at what severity?"],
        ];
    prompts.forEach(([title, text]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = title;
      button.addEventListener("click", () => {
        questionInput.value = text;
        questionInput.focus();
      });
      box.append(button);
    });
    const sig = mode() === "sig";
    $("[data-place-row]").hidden = !sig;
    $("[data-publish-row]").hidden = !sig;
    runButton.disabled = !state.hubCode || (sig && !state.chatAvailable);
  };

  document.querySelectorAll('input[name="chat-mode"]').forEach((input) =>
    input.addEventListener("change", setPrompts),
  );

  // ---------- layers ----------
  const drawDistricts = () => {
    districtLayer.clearLayers();
    state.boundaries.forEach((boundary) => {
      const layer = window.L.geoJSON(boundary.geometry, {
        style: { color: "#0b453d", weight: 2, fillColor: "#b8e063", fillOpacity: 0.06 },
      });
      layer.bindTooltip(`${boundary.name}${boundary.synthetic ? " (synthetic)" : ""}`, { sticky: true });
      layer.on("click", () => selectBoundary(boundary));
      districtLayer.addLayer(layer);
    });
  };

  const selectBoundary = (boundary) => {
    state.selected = boundary;
    districtLayer.eachLayer((layer) => {
      layer.setStyle({ fillOpacity: 0.06, weight: 2 });
    });
    const index = state.boundaries.indexOf(boundary);
    const chosen = districtLayer.getLayers()[index];
    if (chosen) {
      chosen.setStyle({ fillOpacity: 0.16, weight: 3 });
      map.fitBounds(chosen.getBounds(), { padding: [30, 30] });
    }
    $("[data-area-name]").textContent =
      `${boundary.name}${boundary.synthetic ? " · synthetic test area" : ""}`;
    placeInput.value = boundary.synthetic ? placeInput.value : `${boundary.name}, Thailand`;
    $("[data-run-assessment]").disabled = !state.floodLayers.length || !state.centersVersion;
    mapState.textContent = "Ready to run";
  };

  const loadFloodOverlay = async (layer) => {
    if (floodOverlay) floodOverlay.remove();
    if (floodBlobUrl) URL.revokeObjectURL(floodBlobUrl);
    floodOverlay = null;
    if (!layer || !layer.available || !layer.bounds) return;
    const response = await fetch(layer.image_url, { credentials: "same-origin" });
    if (!response.ok) return;
    floodBlobUrl = URL.createObjectURL(await response.blob());
    floodOverlay = window.L.imageOverlay(floodBlobUrl, layer.bounds, { opacity: 0.85 });
    if ($('[data-layer="flood"]').checked) floodOverlay.addTo(map);
    $("[data-flood-title]").textContent = layer.title;
  };

  const drawLegend = (legend) => {
    const box = $("[data-flood-legend]");
    box.replaceChildren();
    [...legend.classes, legend.no_data].forEach((item) => {
      const row = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.className = "swatch";
      swatch.style.background = `rgba(${item.rgba[0]},${item.rgba[1]},${item.rgba[2]},${item.rgba[3] / 255})`;
      row.append(swatch, document.createTextNode(` ${item.label}`));
      box.append(row);
    });
  };

  const markerPopup = (name, text) => {
    const node = document.createElement("div");
    const title = document.createElement("strong");
    const body = document.createElement("span");
    title.textContent = name;
    body.textContent = text;
    node.append(title, document.createElement("br"), body);
    return node;
  };

  const drawPendingCenters = async () => {
    if (!state.centersVersion) return;
    const collection = await GRP.request(state.centersVersion.features_url);
    centersLayer.clearLayers();
    collection.features.forEach((feature) => {
      const [lon, lat] = feature.geometry.coordinates;
      window.L.circleMarker([lat, lon], {
        radius: 7, color: "#374151", weight: 2, fillColor: STATUS_COLOR.pending, fillOpacity: 1,
      })
        .bindPopup(markerPopup(feature.properties.name, "Not assessed yet"))
        .addTo(centersLayer);
    });
  };

  const drawResultCenters = (centers, reasons) => {
    centersLayer.clearLayers();
    centers.forEach((center) => {
      const meaning = (reasons[center.reason_code] || {}).meaning || center.reason_code;
      const depth = center.flood_depth_m === null ? "" : ` · depth ${center.flood_depth_m} m`;
      window.L.circleMarker([center.lat, center.lon], {
        radius: 8, color: "#ffffff", weight: 2, fillColor: STATUS_COLOR[center.status], fillOpacity: 0.95,
      })
        .bindPopup(markerPopup(center.name, `${STATUS_TEXT[center.status]}${depth}. ${meaning}`))
        .addTo(centersLayer);
    });
  };

  document.querySelectorAll("[data-layer]").forEach((toggle) => {
    toggle.addEventListener("change", () => {
      const layer = { districts: districtLayer, centers: centersLayer, flood: floodOverlay }[toggle.dataset.layer];
      if (!layer) return;
      if (toggle.checked) layer.addTo(map);
      else layer.remove();
    });
  });

  $("[data-scenario]").addEventListener("change", (event) => {
    loadFloodOverlay(state.floodLayers.find((l) => l.version_id === event.target.value));
  });

  $("[data-show-osm]").addEventListener("click", () => {
    sigMap.hidden = true;
    sigMap.removeAttribute("src");
    $("[data-show-osm]").hidden = true;
    window.setTimeout(() => map.invalidateSize(), 0);
  });

  // ---------- assessment ----------
  const showResult = async (id) => {
    const [result, centers] = await Promise.all([
      GRP.request(`/api/v1/assessments/${id}/result`),
      GRP.request(`/api/v1/assessments/${id}/centers?size=200`),
    ]);
    drawResultCenters(centers.centers, result.reason_codes);
    $("[data-result-panel]").hidden = false;
    $("[data-synthetic]").hidden = !result.synthetic;
    $("[data-result-meta]").textContent =
      `${result.area} · ${result.scenario.return_period_years}-year flood · ${result.method.key} ${result.method.version}` +
      ` (${result.method.status}) · ref ${result.support_ref}`;
    const metrics = $("[data-metrics]");
    metrics.replaceChildren();
    [
      ["In area", result.summary.in_scope],
      ["Potentially exposed", result.summary.potentially_exposed],
      ["Not exposed under scenario", result.summary.not_exposed_under_scenario],
      ["Unable to assess", result.summary.unable_to_assess],
    ].forEach(([label, value]) => {
      const card = document.createElement("article");
      const name = document.createElement("span");
      const number = document.createElement("strong");
      name.textContent = label;
      number.textContent = String(value);
      card.append(name, number);
      metrics.append(card);
    });
    state.assessmentId = id;
    state.history.result = [];
    const resultMode = $("[data-mode-result]");
    resultMode.disabled = false;
    resultMode.checked = true;
    $("[data-mode-result-label]").textContent = `(${result.area}, RP${result.scenario.return_period_years})`;
    setPrompts();
    mapState.textContent = "Result ready";
    appendMessage(
      "assistant",
      `The ${result.area} assessment is ready: ${result.summary.potentially_exposed} of ` +
        `${result.summary.in_scope} centers may be exposed under the ${result.scenario.return_period_years}-year flood, ` +
        `${result.summary.unable_to_assess} could not be assessed. Ask me about it.`,
      { label: result.synthetic ? "Synthetic test data." : "From the locked result." },
    );
  };

  const watch = async (id) => {
    window.clearTimeout(state.pollTimer);
    try {
      const job = await GRP.request(`/api/v1/assessments/${id}`);
      mapState.textContent = `Assessment ${job.state}`;
      if (job.state === "succeeded") {
        await showResult(id);
      } else if (job.state === "queued" || job.state === "running") {
        state.pollTimer = window.setTimeout(() => watch(id), 2500);
      } else {
        appendMessage("assistant", `The assessment ${job.state}${job.error_code ? ` (${job.error_code})` : ""}. Reference ${job.support_ref}.`);
      }
    } catch (error) {
      mapState.textContent = error.message;
    }
  };

  $("[data-run-assessment]").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const scenario = state.floodLayers.find((l) => l.version_id === $("[data-scenario]").value);
    if (!state.selected || !scenario) return;
    button.disabled = true;
    mapState.textContent = "Submitting…";
    try {
      const accepted = await GRP.request("/api/v1/assessments", {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: {
          hub_code: state.hubCode,
          boundary_id: state.selected.id,
          hazard: { type: "flood", return_period_years: scenario.return_period_years, dataset_version_id: scenario.version_id },
          evacuation_centers_dataset_version_id: state.centersVersion.version_id,
          vulnerability_dataset_version_id: null,
          method: state.method,
        },
      });
      $("[data-result-link]").href = "/assessments.html";
      await drawPendingCenters();
      watch(accepted.assessment_id);
    } catch (error) {
      mapState.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

  // ---------- SIG evidence display (general/SIG mode) ----------
  const showSigEvidence = (payload) => {
    const panel = $("[data-map-evidence]");
    panel.hidden = false;
    const area = payload.area || {};
    $("[data-area]").textContent = area.sig_area ? `SIG analysis area: ${area.sig_area}. ${area.reason}.` : area.reason || "";
    const metrics = $("[data-sig-metrics]");
    metrics.replaceChildren();
    Object.entries((payload.stats && payload.stats.counts) || {}).forEach(([name, value]) => {
      const card = document.createElement("article");
      const label = document.createElement("span");
      const total = document.createElement("strong");
      label.textContent = `${name.replaceAll("_", " ")} exposed (SIG)`;
      total.textContent = typeof value.exposed === "number" ? `${value.exposed} / ${value.total}` : `${value.exposed_km || 0} / ${value.total_km || 0} km`;
      card.append(label, total);
      metrics.append(card);
    });
    const fill = (selector, values, format) => {
      const list = $(selector);
      list.replaceChildren();
      (values || []).forEach((value) => {
        const item = document.createElement("li");
        item.textContent = format(value);
        list.append(item);
      });
    };
    fill("[data-citations]", payload.citations, (c) => `[${c.n}] ${c.title}: ${c.text}`);
    fill("[data-trace]", payload.trace, (t) => `${t.step}: ${t.detail}`);
    fill("[data-gaps]", payload.gaps, (gap) => `Gap: ${gap}`);
    const mapUrl = safeHttps(payload.map_url);
    if (mapUrl) {
      sigMap.src = mapUrl;
      sigMap.hidden = false;
      $("[data-show-osm]").hidden = false;
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = questionInput.value.trim();
    if (!message || !state.hubCode) return;
    const current = mode();
    appendMessage("user", message);
    questionInput.value = "";
    runButton.disabled = true;
    status.textContent = current === "result" ? "Explaining the stored result…" : "Asking the assistant…";
    try {
      let payload;
      if (current === "result") {
        payload = await GRP.request(`/api/v1/assessments/${state.assessmentId}/explain`, {
          method: "POST",
          body: { question: message, history: state.history.result.slice(-6) },
        });
      } else {
        payload = await GRP.request("/api/v1/planning/chat", {
          method: "POST",
          body: {
            message,
            place: placeInput.value.trim() || null,
            hub_code: state.hubCode,
            publish_receipt: $("[data-publish-receipt]").checked,
            history: state.history.sig.slice(-8),
          },
        });
        if (payload.mode === "sig_evidence") showSigEvidence(payload);
      }
      appendMessage("assistant", payload.answer, payload);
      state.history[current].push({ role: "user", text: message }, { role: "assistant", text: payload.answer.slice(0, 1200) });
      if (payload.usage) showAllowance(payload.usage);
      status.textContent = payload.label || "";
    } catch (error) {
      appendMessage("assistant", error.message, { label: error.code || "Error" });
      status.textContent = error.message;
      if (error.code === "SIG_REAUTH_REQUIRED") {
        window.setTimeout(() => window.location.assign("/api/v1/auth/login"), 1200);
      }
      GRP.request("/api/v1/me/ai-usage").then(showAllowance).catch(() => {});
    } finally {
      setPrompts();
    }
  });

  // ---------- start ----------
  GRP.bindSignOut();

  GRP.request("/api/v1/me")
    .then(async (identity) => {
      $("[data-user-name]").textContent = identity.display_name || identity.email;
      const membership = identity.memberships.find((m) => m.role === "planner" || m.role === "admin");
      const banner = $("[data-banner]");
      if (!membership) {
        banner.textContent = "You need a Planner or Hub Admin role in a Hub. A Platform Admin role alone is not enough.";
        banner.hidden = false;
        mapState.textContent = "No Hub role";
        return;
      }
      state.hubCode = membership.hub_code;
      $("[data-hub-name]").textContent = `${membership.hub_name} · ${membership.role}`;
      const query = `?hub_code=${encodeURIComponent(state.hubCode)}`;
      const [planning, areas, layers, methods] = await Promise.all([
        GRP.request("/api/v1/planning/status").catch(() => ({ available: false })),
        GRP.request(`/api/v1/catalog/boundaries${query}`),
        GRP.request(`/api/v1/maps/layers${query}`),
        GRP.request(`/api/v1/catalog/methods${query}`),
      ]);
      state.chatAvailable = Boolean(planning.available);
      if (planning.usage) showAllowance(planning.usage);
      else GRP.request("/api/v1/me/ai-usage").then(showAllowance).catch(() => {});
      if (!planning.available) {
        banner.textContent = "General and SIG chat run only in the local Docker Desktop test. Result explanations still work.";
        banner.hidden = false;
      } else if (!planning.sig_connected) {
        banner.textContent = "SIG is not connected for this session. Sign out and in again to use SIG evidence.";
        banner.hidden = false;
      }

      state.boundaries = areas.boundaries;
      state.floodLayers = layers.flood;
      state.centersVersion = layers.evacuation_centers[0] || null;
      const method = methods.methods[0];
      state.method = method ? { key: method.key, version: method.version } : null;
      $("[data-vulnerability-note]").textContent = layers.vulnerability.message;

      const scenario = $("[data-scenario]");
      state.floodLayers.forEach((layer) => {
        const option = document.createElement("option");
        option.value = layer.version_id;
        option.textContent = `${layer.return_period_years}-year flood`;
        scenario.append(option);
      });
      drawLegend(layers.flood_legend);
      drawDistricts();
      await Promise.all([loadFloodOverlay(state.floodLayers[0]), drawPendingCenters()]);
      if (districtLayer.getLayers().length) map.fitBounds(districtLayer.getBounds(), { padding: [40, 40] });
      mapState.textContent = state.boundaries.length ? "Click a district to select it" : "No supported areas yet";
      if (state.boundaries.length === 1) selectBoundary(state.boundaries[0]);
      setPrompts();
    })
    .catch((error) => {
      if (error.status === 401 || error.status === 403) {
        window.location.replace("/");
        return;
      }
      status.textContent = error.message;
    });
})();
