(() => {
  "use strict";

  const POLL_MS = 1500;
  const errorBox = document.querySelector("[data-error]");
  const vulnerability = document.querySelector("[data-vulnerability-message]");
  let canImport = false;

  const configs = {
    boundary: {
      payload: "boundary", endpoint: "boundaries", button: "[data-import-boundaries]",
      state: "[data-boundary-state]", source: "[data-source-note]",
      body: "[data-boundary-versions]", progress: "[data-import-progress]",
      fill: "[data-import-fill]", text: "[data-import-text]",
      label: "Thailand district-boundary import",
    },
    evacuation_centers: {
      payload: "evacuation_centers", endpoint: "evacuation-centers", button: "[data-import-shelters]",
      state: "[data-shelter-state]", source: "[data-shelter-source-note]",
      body: "[data-shelter-versions]", progress: "[data-shelter-progress]",
      fill: "[data-shelter-fill]", text: "[data-shelter-progress-text]",
      label: "DDPM evacuation-centre import",
    },
    hazard: {
      payload: "hazard", endpoint: "hazard-rp100", button: "[data-import-hazard]",
      state: "[data-hazard-state]", source: "[data-hazard-source-note]",
      body: "[data-hazard-versions]", progress: "[data-hazard-progress]",
      fill: "[data-hazard-fill]", text: "[data-hazard-progress-text]",
      label: "100-year flood-depth import",
    },
  };

  const cell = (row, text, title) => {
    const td = document.createElement("td");
    td.textContent = text;
    if (title) td.title = title;
    row.append(td);
  };

  const showError = (message) => {
    errorBox.textContent = message;
    errorBox.hidden = false;
  };

  const versionCells = (category, version) => {
    if (category === "boundary") return [
      version.edition || "—", version.readiness.replaceAll("_", " "),
      Number(version.feature_count).toLocaleString(), Number(version.file_count).toLocaleString(),
      Number(version.supported_count).toLocaleString(), GRP.formatTime(version.created_at),
    ];
    if (category === "evacuation_centers") return [
      version.readiness.replaceAll("_", " "), Number(version.feature_count).toLocaleString(),
      Number(version.file_count).toLocaleString(),
      Number(version.district_name_mismatch_count || 0).toLocaleString(),
      Number(version.outside_boundary_count || 0).toLocaleString(), GRP.formatTime(version.created_at),
    ];
    return [
      version.readiness.replaceAll("_", " "), Number(version.tile_count || 0).toLocaleString(),
      Number(version.file_count).toLocaleString(), "100 years", GRP.formatTime(version.created_at),
    ];
  };

  const renderVersions = (category, versions) => {
    const config = configs[category];
    const body = document.querySelector(config.body);
    body.replaceChildren();
    if (!versions.length) {
      const row = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = category === "hazard" ? 6 : 7;
      td.textContent = "No managed version yet.";
      row.append(td);
      body.append(row);
      return;
    }
    versions.forEach((version) => {
      const row = document.createElement("tr");
      versionCells(category, version).forEach((value) => cell(row, value));
      cell(row, version.version_id.slice(0, 8), version.version_id);
      body.append(row);
    });
  };

  const renderCategory = (category, data) => {
    const config = configs[category];
    const button = document.querySelector(config.button);
    document.querySelector(config.state).textContent = data.versions.length ? "Imported" : "Not imported";
    let sourceText = data.source_available
      ? `Ready: ${data.required_files.length} required source item(s) are available.`
      : "The accepted source files are not available on this server.";
    if (data.requires_boundaries) sourceText = "Import district boundaries first.";
    document.querySelector(config.source).textContent = sourceText;
    renderVersions(category, data.versions);
    button.hidden = !canImport;
    button.disabled = !canImport || !data.source_available || Boolean(data.active_import_id) || Boolean(data.requires_boundaries);
    if (data.active_import_id) poll(category, data.active_import_id);
  };

  const poll = async (category, importId) => {
    const config = configs[category];
    let payload;
    try {
      payload = await GRP.request(`/api/v1/data-library/imports/${importId}`);
    } catch (error) {
      showError(error.message || "The import status could not be read.");
      return;
    }
    document.querySelector(config.progress).hidden = false;
    document.querySelector(config.fill).style.width = `${payload.progress}%`;
    const report = payload.report || {};
    document.querySelector(config.text).textContent =
      payload.state === "queued" ? "Waiting for the import worker…" :
      payload.state === "running" ? `Validating and publishing (${payload.progress}%)…` :
      payload.state === "succeeded" ? report.message : `Import stopped. Quote ${payload.support_ref}.`;
    if (payload.state === "queued" || payload.state === "running") {
      window.setTimeout(() => poll(category, importId), POLL_MS);
      return;
    }
    GRP.jobs.done(importId);
    if (payload.state === "failed") showError(`${payload.error_code || "IMPORT_FAILED"}. Quote ${payload.support_ref}.`);
    await load();
  };

  const startImport = async (category) => {
    const config = configs[category];
    const button = document.querySelector(config.button);
    button.disabled = true;
    errorBox.hidden = true;
    try {
      const started = await GRP.request(`/api/v1/data-library/imports/${config.endpoint}`, {
        method: "POST", idempotencyKey: crypto.randomUUID(),
      });
      GRP.jobs.track({
        id: started.import_id, label: config.label,
        statusPath: `/api/v1/data-library/imports/${started.import_id}`,
        href: "/data-library.html", ownerPath: "/data-library.html",
      });
      poll(category, started.import_id);
    } catch (error) {
      showError(error.message || "The import could not be started.");
      button.disabled = false;
    }
  };

  const load = async () => {
    try {
      const payload = await GRP.request("/api/v1/data-library");
      canImport = payload.can_import_platform_baseline;
      Object.keys(configs).forEach((category) => renderCategory(category, payload[configs[category].payload]));
      vulnerability.textContent = payload.vulnerability.message;
    } catch (error) {
      showError(error.message || "The data library could not be loaded.");
    }
  };

  Object.entries(configs).forEach(([category, config]) => {
    document.querySelector(config.button).addEventListener("click", () => startImport(category));
  });
  load();
})();
