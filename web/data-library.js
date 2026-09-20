(() => {
  "use strict";

  const POLL_MS = 1500;
  const button = document.querySelector("[data-import-boundaries]");
  const statePill = document.querySelector("[data-boundary-state]");
  const sourceNote = document.querySelector("[data-source-note]");
  const versionsBody = document.querySelector("[data-boundary-versions]");
  const progressBox = document.querySelector("[data-import-progress]");
  const progressFill = document.querySelector("[data-import-fill]");
  const progressText = document.querySelector("[data-import-text]");
  const errorBox = document.querySelector("[data-error]");
  const vulnerability = document.querySelector("[data-vulnerability-message]");
  let activeImport = null;
  let canImport = false;

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

  const renderVersions = (versions) => {
    versionsBody.replaceChildren();
    if (!versions.length) {
      const row = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 7;
      td.textContent = "No managed boundary version yet.";
      row.append(td);
      versionsBody.append(row);
      return;
    }
    versions.forEach((version) => {
      const row = document.createElement("tr");
      cell(row, version.edition || "—");
      cell(row, version.readiness.replaceAll("_", " "));
      cell(row, Number(version.feature_count).toLocaleString());
      cell(row, Number(version.file_count).toLocaleString());
      cell(row, Number(version.supported_count).toLocaleString());
      cell(row, GRP.formatTime(version.created_at));
      cell(row, version.version_id.slice(0, 8), version.version_id);
      versionsBody.append(row);
    });
  };

  const renderLibrary = (payload) => {
    const boundary = payload.boundary;
    canImport = payload.can_import_platform_baseline;
    statePill.textContent = boundary.versions.length ? "Imported" : "Not imported";
    sourceNote.textContent = boundary.source_available
      ? `Ready: ${boundary.required_files.length} required source files are available.`
      : "The accepted source files are not available on this server.";
    renderVersions(boundary.versions);
    vulnerability.textContent = payload.vulnerability.message;
    activeImport = boundary.active_import_id;
    button.hidden = !canImport;
    button.disabled = !canImport || !boundary.source_available || Boolean(activeImport);
    button.textContent = boundary.versions.length
      ? "Import a new boundary version"
      : "Import accepted boundary baseline";
    if (activeImport) poll(activeImport);
  };

  const poll = async (importId) => {
    let payload;
    try {
      payload = await GRP.request(`/api/v1/data-library/imports/${importId}`);
    } catch (error) {
      showError(error.message || "The import status could not be read.");
      return;
    }
    progressBox.hidden = false;
    progressFill.style.width = `${payload.progress}%`;
    progressText.textContent =
      payload.state === "queued"
        ? "Waiting for the import worker…"
        : payload.state === "running"
          ? `Validating and publishing the boundary collection (${payload.progress}%)…`
          : payload.state === "succeeded"
            ? `${payload.report.message} ${payload.version.feature_count.toLocaleString()} districts and ${payload.version.file_count} immutable files are now registered.`
            : `Import stopped. Quote ${payload.support_ref}.`;
    if (payload.state === "queued" || payload.state === "running") {
      window.setTimeout(() => poll(importId), POLL_MS);
      return;
    }
    GRP.jobs.done(importId);
    activeImport = null;
    if (payload.state === "failed") {
      showError(`${payload.error_code || "IMPORT_FAILED"}. Quote ${payload.support_ref}.`);
    }
    await load();
  };

  const startImport = async () => {
    button.disabled = true;
    errorBox.hidden = true;
    try {
      const idempotencyKey = crypto.randomUUID();
      const started = await GRP.request("/api/v1/data-library/imports/boundaries", {
        method: "POST",
        idempotencyKey,
      });
      activeImport = started.import_id;
      GRP.jobs.track({
        id: activeImport,
        label: "Thailand district-boundary import",
        statusPath: `/api/v1/data-library/imports/${activeImport}`,
        href: "/data-library.html",
        ownerPath: "/data-library.html",
      });
      poll(activeImport);
    } catch (error) {
      showError(error.message || "The boundary import could not be started.");
      button.disabled = false;
    }
  };

  const load = async () => {
    try {
      renderLibrary(await GRP.request("/api/v1/data-library"));
    } catch (error) {
      showError(error.message || "The data library could not be loaded.");
    }
  };

  button.addEventListener("click", startImport);
  load();
})();
