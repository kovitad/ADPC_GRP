(() => {
  const account = document.querySelector("[data-account-name]");
  const hubLabel = document.querySelector("[data-hub-name]");
  const status = document.querySelector("[data-status]");
  const list = document.querySelector("[data-run-list]");
  const empty = document.querySelector("[data-empty]");
  const refresh = document.querySelector("[data-refresh]");
  const profile = document.querySelector("[data-profile]");
  const siteName = document.querySelector("[data-site-name]");
  const finish = document.querySelector("[data-finish-area]");
  const reset = document.querySelector("[data-reset-area]");
  const check = document.querySelector("[data-check-coverage]");
  const runButton = document.querySelector("[data-run]");
  const form = document.querySelector("[data-assessment-form]");
  const builderStatus = document.querySelector("[data-builder-status]");
  const coveragePanel = document.querySelector("[data-coverage]");
  const progress = document.querySelector("[data-progress]");
  const stepsPanel = document.querySelector("[data-steps]");
  const resultPanel = document.querySelector("[data-result]");
  const resultTitle = document.querySelector("[data-result-title]");
  const resultState = document.querySelector("[data-result-state]");
  const resultDownload = document.querySelector("[data-result-download]");
  const resultSummary = document.querySelector("[data-result-summary]");
  const resultTabs = document.querySelectorAll("[data-result-view]");
  const viewExplanation = document.querySelector("[data-view-explanation]");
  const mapNotice = document.querySelector("[data-map-notice]");

  const state = {
    hubCode: null,
    points: [],
    shape: null,
    finished: false,
    coverage: null,
    runId: null,
    resultMap: null,
    result: null,
    zoneLayers: [],
    candidateLayers: [],
    resultBounds: null,
  };
  const presets = {
    KE: { center: [-2.18, 40.87], zoom: 11, country: "KE" },
    ID: { center: [-2.7, 105.3], zoom: 8, country: "ID" },
  };
  const colors = {
    1: "#146c43", 2: "#36a269", 3: "#85c88a", 5: "#a83b35", 6: "#c6a465",
    7: "#8e67ad", 8: "#d8c98a", 9: "#737b78", 10: "#4b9fbd", 11: "#0b574f",
    12: "#e18b45", 13: "#bc5a3c",
  };

  const map = L.map("mangrove-map", { preferCanvas: true }).setView(
    presets.KE.center,
    presets.KE.zoom,
  );
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  const vertexLayer = L.layerGroup().addTo(map);

  const date = (value) =>
    new Date(value).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });

  const geometry = () => ({
    type: "Polygon",
    coordinates: [[...state.points.map((point) => [point.lng, point.lat]), [state.points[0].lng, state.points[0].lat]]],
  });

  const redraw = () => {
    if (state.shape) map.removeLayer(state.shape);
    vertexLayer.clearLayers();
    state.shape = null;
    if (!state.points.length) return;
    state.shape = state.finished
      ? L.polygon(state.points, { color: "#123f3a", weight: 3, fillOpacity: 0.18 }).addTo(map)
      : L.polyline(state.points, { color: "#297c78", weight: 3, dashArray: "6 5" }).addTo(map);
    state.points.forEach((point) =>
      L.circleMarker(point, { radius: 4, color: "#123f3a", fillColor: "#fff", fillOpacity: 1 }).addTo(vertexLayer),
    );
  };

  const resetArea = () => {
    if (state.shape) map.removeLayer(state.shape);
    vertexLayer.clearLayers();
    state.shape = null;
    state.points = [];
    state.finished = false;
    state.coverage = null;
    finish.disabled = true;
    check.disabled = true;
    runButton.disabled = false;
    coveragePanel.hidden = true;
    resultPanel.hidden = true;
    builderStatus.textContent = "Click the map to start drawing your area.";
  };

  map.on("click", (event) => {
    if (state.finished) return;
    state.points.push(event.latlng);
    finish.disabled = state.points.length < 3;
    builderStatus.textContent = `${state.points.length} point${state.points.length === 1 ? "" : "s"} selected.`;
    redraw();
  });

  finish.addEventListener("click", () => {
    if (state.points.length < 3) return;
    state.finished = true;
    redraw();
    check.disabled = false;
    finish.disabled = true;
    builderStatus.textContent = "Area selected. Check live evidence before running.";
    map.fitBounds(state.shape.getBounds(), { padding: [20, 20] });
  });
  reset.addEventListener("click", resetArea);
  profile.addEventListener("change", () => {
    resetArea();
    const selected = presets[profile.value];
    map.setView(selected.center, selected.zoom);
  });

  const showBuilderError = (error) => {
    builderStatus.replaceChildren();
    builderStatus.append(document.createTextNode(error.message || "The request could not be completed."));
    if (error.status === 401 || ["NOT_SIGNED_IN", "SIG_REAUTH_REQUIRED"].includes(error.code)) {
      const link = document.createElement("a");
      link.href = "/api/v1/auth/login";
      link.textContent = " Sign in with SERVIR again.";
      builderStatus.append(link);
    }
  };

  const showCoverage = (answer) => {
    coveragePanel.replaceChildren();
    const headline = document.createElement("strong");
    headline.textContent = `${answer.area_km2.toLocaleString()} km² · ${answer.layer_names.length} governed layers`;
    const detail = document.createElement("p");
    detail.textContent = `${answer.estimated_tiles} planned tile area(s). ${answer.gaps.length} declared evidence gap(s).`;
    coveragePanel.append(headline, detail);
    if (answer.gaps.length) {
      const firstGap = document.createElement("p");
      firstGap.textContent = `First declared gap: ${answer.gaps[0]}`;
      coveragePanel.append(firstGap);
    }
    coveragePanel.hidden = false;
  };

  check.addEventListener("click", async () => {
    if (!state.finished || !state.hubCode) return;
    check.disabled = true;
    runButton.disabled = true;
    builderStatus.textContent = "Checking live governed evidence. This can take up to a minute…";
    try {
      state.coverage = await GRP.request("/api/v1/coastal-zoning/coverage", {
        method: "POST",
        body: {
          hub_code: state.hubCode,
          country: presets[profile.value].country,
          aoi: { type: "Feature", geometry: geometry(), properties: { source: "drawn" } },
        },
      });
      showCoverage(state.coverage);
      runButton.disabled = false;
      builderStatus.textContent = state.coverage.ready
        ? "Coverage is ready. Review the declared gaps, then run the assessment."
        : "Required evidence is not available for this area.";
    } catch (error) {
      showBuilderError(error);
      runButton.disabled = false;
    } finally {
      check.disabled = false;
    }
  });

  const renderSteps = (steps) => {
    stepsPanel.replaceChildren();
    steps.forEach((step) => {
      const row = document.createElement("div");
      row.className = "m360-step";
      const label = document.createElement("span");
      label.textContent = step.summary || step.label;
      const value = document.createElement("span");
      value.textContent = step.status;
      row.append(label, value);
      stepsPanel.append(row);
    });
  };

  const addResultCard = (title, lines) => {
    const card = document.createElement("article");
    card.className = "m360-result-card";
    const heading = document.createElement("h3");
    heading.textContent = title;
    card.append(heading);
    const ul = document.createElement("ul");
    lines.forEach((line) => {
      const li = document.createElement("li");
      li.textContent = line;
      ul.append(li);
    });
    card.append(ul);
    resultSummary.append(card);
  };

  const applyResultView = (view) => {
    if (!state.resultMap || !state.result) return;
    const configurations = {
      zones: {
        explanation: "Showing every mapped zoning class. Select another view to highlight its locations.",
        kinds: [],
      },
      winwin: {
        explanation: "Highlighting all unranked opportunity areas. Bright outlines show exactly where they occur on the map.",
        kinds: ["coastal", "inland", "restoration"],
      },
      resort: {
        explanation: "Highlighting coastal and inland resort candidates. These are map-grid screening locations, not building approvals.",
        kinds: ["coastal", "inland"],
      },
      restoration: {
        explanation: "Highlighting mapped restoration and planting/reconnection candidates in bright green.",
        kinds: ["restoration"],
      },
    };
    const selected = configurations[view] || configurations.zones;
    viewExplanation.textContent = selected.explanation;
    state.zoneLayers.forEach(({ layer }) => {
      layer.setStyle({ fillOpacity: view === "zones" ? 0.72 : 0.13 });
    });
    const visible = [];
    state.candidateLayers.forEach(({ kind, layer }) => {
      const show = view !== "zones" && selected.kinds.includes(kind);
      if (show) {
        if (!state.resultMap.hasLayer(layer)) layer.addTo(state.resultMap);
        visible.push(layer);
      } else if (state.resultMap.hasLayer(layer)) {
        state.resultMap.removeLayer(layer);
      }
    });
    if (view === "zones") {
      mapNotice.hidden = true;
      state.resultMap.fitBounds(state.resultBounds, { padding: [15, 15] });
    } else if (visible.length) {
      mapNotice.hidden = true;
      const bounds = L.latLngBounds([]);
      visible.forEach((layer) => bounds.extend(layer.getBounds()));
      state.resultMap.fitBounds(bounds, { padding: [45, 45], maxZoom: 14 });
    } else {
      mapNotice.textContent = `No ${view === "winwin" ? "opportunity" : view} candidate locations were identified in this selected area.`;
      mapNotice.hidden = false;
      state.resultMap.fitBounds(state.resultBounds, { padding: [15, 15] });
    }
  };

  const renderResultSummary = (view) => {
    const answer = state.result;
    if (!answer) return;
    applyResultView(view);
    resultSummary.replaceChildren();
    resultTabs.forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.resultView === view)));
    if (view === "zones") {
      addResultCard(
        "Map key",
        Object.entries(answer.cell_counts)
          .filter(([code]) => code !== "0")
          .map(([code, cells]) => `${answer.zone_legend[code] || `Zone ${code}`}: ${cells} map cells`),
      );
    } else {
      const wanted = view === "restoration"
        ? ["restoration"]
        : view === "resort"
          ? ["coastal", "inland"]
          : ["coastal", "inland", "restoration"];
      const candidates = answer.candidates.filter((candidate) => wanted.includes(candidate.kind));
      addResultCard(
        view === "winwin" ? "Unranked opportunities" : `${view[0].toUpperCase()}${view.slice(1)} candidates`,
        candidates.length
          ? candidates.map((candidate) => `${candidate.zone_id} · ${candidate.name} · ${candidate.area_km2} km² · map-grid estimate`)
          : ["No candidate component met the deterministic rules in this view."],
      );
    }
    addResultCard("Important limits", answer.limits);
    const gaps = answer.evidence.gaps || [];
    addResultCard("Declared evidence gaps", gaps.length ? gaps.slice(0, 6) : ["No gap was declared by this pack."]);
  };

  resultTabs.forEach((tab) => tab.addEventListener("click", () => renderResultSummary(tab.dataset.resultView)));

  const showResult = (answer) => {
    state.result = answer;
    resultPanel.hidden = false;
    resultTitle.textContent = answer.site_name;
    resultState.textContent = "Map-grid estimate · unverified";
    resultDownload.href = `/api/v1/coastal-zoning/runs/${answer.run_id}/result`;
    resultDownload.download = `${answer.site_name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-result.json`;
    resultSummary.replaceChildren();
    if (state.resultMap) state.resultMap.remove();
    state.zoneLayers = [];
    state.candidateLayers = [];
    state.resultMap = L.map("mangrove-result-map", { preferCanvas: true });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(state.resultMap);
    const grid = answer.grid;
    const [west, south, east, north] = grid.bounds;
    const dx = (east - west) / grid.w;
    const dy = (north - south) / grid.h;
    grid.codes.forEach((row, rowIndex) =>
      row.forEach((code, colIndex) => {
        if (!colors[code]) return;
        const bounds = [
          [north - (rowIndex + 1) * dy, west + colIndex * dx],
          [north - rowIndex * dy, west + (colIndex + 1) * dx],
        ];
        const layer = L.rectangle(bounds, {
          stroke: false,
          fillColor: colors[code],
          fillOpacity: 0.72,
        }).bindTooltip(answer.zone_legend[String(code)] || `Zone ${code}`).addTo(state.resultMap);
        state.zoneLayers.push({ code, layer });
      }),
    );
    const candidateColors = { coastal: "#f06b35", inland: "#8e44ad", restoration: "#16a765" };
    answer.candidates.forEach((candidate) => {
      const color = candidateColors[candidate.kind] || "#f06b35";
      const layer = L.geoJSON(candidate.geometry, {
        style: { color, weight: 3, fillColor: color, fillOpacity: 0.68 },
      }).bindTooltip(candidate.zone_id, {
        permanent: true,
        direction: "center",
        className: "m360-candidate-label",
      });
      const popup = document.createElement("div");
      const popupTitle = document.createElement("strong");
      popupTitle.textContent = `${candidate.zone_id}: ${candidate.name}`;
      const popupDetail = document.createElement("p");
      popupDetail.textContent = `${candidate.area_km2} km² · map-grid estimate · unranked`;
      popup.append(popupTitle, popupDetail);
      layer.bindPopup(popup);
      state.candidateLayers.push({ kind: candidate.kind, layer });
    });
    state.resultBounds = [[south, west], [north, east]];
    const legend = L.control({ position: "bottomright" });
    legend.onAdd = () => {
      const panel = L.DomUtil.create("div", "m360-map-legend");
      const heading = document.createElement("strong");
      heading.textContent = "Visible map colors";
      panel.append(heading);
      Object.entries(answer.cell_counts)
        .filter(([code, cells]) => code !== "0" && cells > 0 && colors[code])
        .forEach(([code]) => {
          const row = document.createElement("div");
          const swatch = document.createElement("span");
          swatch.style.backgroundColor = colors[code];
          row.append(swatch, document.createTextNode(answer.zone_legend[code] || `Zone ${code}`));
          panel.append(row);
        });
      return panel;
    };
    legend.addTo(state.resultMap);
    renderResultSummary("zones");
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const pollRun = async () => {
    const answer = await GRP.request(`/api/v1/coastal-zoning/runs/${state.runId}`);
    renderSteps(answer.steps);
    if (answer.status === "succeeded") {
      builderStatus.textContent = "Assessment completed.";
      showResult(await GRP.request(`/api/v1/coastal-zoning/runs/${state.runId}/result`));
      runButton.disabled = false;
      loadRuns();
      return;
    }
    if (["failed", "cancelled"].includes(answer.status)) {
      builderStatus.textContent = answer.error?.message || `Assessment ${answer.status}.`;
      runButton.disabled = false;
      loadRuns();
      return;
    }
    window.setTimeout(() => pollRun().catch((error) => {
      builderStatus.textContent = error.message;
    }), 3000);
  };

  const runAssessment = async () => {
    if (!state.hubCode) {
      showBuilderError({ status: 401, message: "Sign in before running an assessment." });
      return;
    }
    if (!state.finished) {
      builderStatus.textContent = "Draw and finish an area before running the assessment.";
      return;
    }
    if (!state.coverage?.ready) {
      builderStatus.textContent = "Check live evidence successfully before running the assessment.";
      return;
    }
    if (!siteName.value.trim()) {
      builderStatus.textContent = "Enter an assessment name before running.";
      siteName.focus();
      return;
    }
    runButton.disabled = true;
    builderStatus.textContent = "Queueing the deterministic assessment…";
    try {
      const answer = await GRP.request("/api/v1/coastal-zoning/runs", {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: {
          hub_code: state.hubCode,
          coverage_id: state.coverage.coverage_id,
          aoi: {
            type: "Feature",
            geometry: geometry(),
            properties: { name: siteName.value.trim(), source: "drawn" },
          },
          site_name: siteName.value.trim(),
          country: presets[profile.value].country,
          params: state.coverage.defaults,
          language: "en",
        },
      });
      state.runId = answer.run_id;
      progress.hidden = false;
      builderStatus.textContent = "Assessment queued. You may leave this page and return later.";
      await pollRun();
    } catch (error) {
      showBuilderError(error);
      runButton.disabled = false;
    }
  };

  runButton.addEventListener("click", runAssessment);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    runAssessment();
  });

  const loadRuns = async () => {
    refresh.disabled = true;
    status.hidden = false;
    status.textContent = "Loading assessments…";
    list.hidden = true;
    empty.hidden = true;
    try {
      const answer = await GRP.request("/api/v1/coastal-zoning/runs");
      const runs = answer.runs || [];
      list.replaceChildren();
      if (!runs.length) {
        status.hidden = true;
        empty.hidden = false;
        return;
      }
      runs.forEach((run) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "m360-run";
        row.setAttribute("aria-label", `Open ${run.site_name}`);
        const title = document.createElement("div");
        const strong = document.createElement("strong");
        strong.textContent = run.site_name;
        const owner = document.createElement("small");
        owner.textContent = run.review_state === "reviewed" ? "Reviewed" : "Draft";
        title.append(strong, owner);
        const runState = document.createElement("span");
        runState.className = "m360-run__state";
        runState.textContent = run.status.replaceAll("_", " ");
        const created = document.createElement("small");
        created.textContent = date(run.created_at);
        row.append(title, runState, created);
        row.addEventListener("click", async () => {
          state.runId = run.run_id;
          progress.hidden = false;
          const detail = await GRP.request(`/api/v1/coastal-zoning/runs/${run.run_id}`);
          renderSteps(detail.steps);
          if (detail.status === "succeeded") {
            showResult(await GRP.request(`/api/v1/coastal-zoning/runs/${run.run_id}/result`));
          } else if (["queued", "running"].includes(detail.status)) {
            builderStatus.textContent = "Watching this assessment's progress…";
            pollRun().catch((error) => { builderStatus.textContent = error.message; });
          } else {
            builderStatus.textContent = detail.error?.message || `Assessment ${detail.status}.`;
          }
        });
        list.append(row);
      });
      status.textContent = `${runs.length} assessment${runs.length === 1 ? "" : "s"} shown.`;
      list.hidden = false;
    } catch (error) {
      if (error.status === 401) {
        window.location.assign("/");
        return;
      }
      status.textContent = error.status === 404
        ? "Mangrove 360 is not enabled in this environment."
        : error.message;
    } finally {
      refresh.disabled = false;
    }
  };

  GRP.me()
    .then((identity) => {
      account.textContent = identity.display_name || identity.email;
      const membership = identity.memberships[0];
      state.hubCode = membership?.hub_code || null;
      hubLabel.textContent = membership ? membership.hub_name : "Platform";
      if (!state.hubCode) builderStatus.textContent = "A Hub membership is required.";
    })
    .catch((error) => {
      if (error.status === 401) window.location.assign("/");
      else account.textContent = "Account unavailable";
    });

  refresh.addEventListener("click", loadRuns);
  GRP.bindSignOut();
  loadRuns();
})();
