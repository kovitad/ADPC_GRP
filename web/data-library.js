(() => {
  "use strict";

  const POLL_MS = 1500;
  const errorBox = document.querySelector("[data-error]");
  const vulnerability = document.querySelector("[data-vulnerability-message]");
  let canImport = false;
  let shelterUploadEnabled = false;

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

  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const renderBootstrap = (bootstrap) => {
    const state = document.querySelector("[data-bootstrap-state]");
    const summary = document.querySelector("[data-bootstrap-summary]");
    const categories = document.querySelector("[data-bootstrap-categories]");
    const next = document.querySelector("[data-bootstrap-next]");
    state.textContent = bootstrap.ready ? "Ready" : "Setup needed";
    state.classList.toggle("status-pill--success", bootstrap.ready);
    summary.textContent = bootstrap.ready
      ? "The supported Thailand baseline is active for new district planning."
      : "One or more supported baseline inputs still need to be imported and activated.";
    categories.replaceChildren();
    const labels = {
      boundary: "District boundaries",
      evacuation_centers: "DDPM shelters",
      hazard: "100-year flood depth",
    };
    Object.entries(bootstrap.categories).forEach(([key, value]) => {
      const item = element("div", `library-bootstrap__item${value.active ? " is-ready" : ""}`);
      item.append(
        element("span", "library-bootstrap__dot", value.active ? "✓" : "—"),
        element("strong", "", labels[key] || key),
        element("small", "", value.active ? `Active · ${value.version_id.slice(0, 8)}` : "Not active"),
      );
      categories.append(item);
    });
    next.textContent = bootstrap.scope_note;
  };

  const sourceKind = (version) => {
    if (version.synthetic) return { label: "Synthetic demo", modifier: "demo" };
    if (version.source_mode === "browser_upload") {
      return { label: "Local upload", modifier: "local" };
    }
    return { label: "Platform baseline", modifier: "platform" };
  };

  const sourceTitle = (version) => {
    if (version.source_mode === "browser_upload") {
      return version.original_filename || "Uploaded shelter dataset";
    }
    return version.dataset_title || "Managed shelter dataset";
  };

  const sourceUse = (version) => {
    if (version.is_current && version.readiness === "assessment_ready") {
      return version.synthetic ? "Used for test district" : "Used for real districts";
    }
    if (version.can_accept) return "Available to select";
    return version.readiness.replaceAll("_", " ");
  };

  const versionCells = (category, version) => {
    if (category === "boundary") return [
      version.edition || "—", version.readiness.replaceAll("_", " "),
      Number(version.feature_count).toLocaleString(), Number(version.file_count).toLocaleString(),
      Number(version.supported_count).toLocaleString(), GRP.formatTime(version.created_at),
    ];
    return [
      version.readiness.replaceAll("_", " "), Number(version.tile_count || 0).toLocaleString(),
      Number(version.file_count).toLocaleString(), "100 years", GRP.formatTime(version.created_at),
    ];
  };

  const acceptShelterVersion = async (version, button) => {
    const nameWarning = version.shelter_names_confirmed === false
      ? "\n\nThis version uses generated centre labels because the source name fields are not yet confirmed."
      : "";
    if (!window.confirm(
      `Use this exact shelter version for new assessments? Existing locked results will not change.${nameWarning}`,
    )) return;
    button.disabled = true;
    errorBox.hidden = true;
    const note = document.querySelector("[data-shelter-upload-note]");
    note.textContent = "Accepting the selected shelter version…";
    try {
      const payload = await GRP.request(
        `/api/v1/data-library/versions/${version.version_id}/accept`,
        { method: "POST" },
      );
      note.textContent = `Ready for new assessments. Reference ${payload.support_ref}.`;
      await load();
    } catch (error) {
      showError(error.message || "The shelter version could not be accepted.");
      button.disabled = false;
    }
  };

  const renderShelterVersions = (versions) => {
    const list = document.querySelector(configs.evacuation_centers.body);
    list.replaceChildren();
    if (!versions.length) {
      list.append(element(
        "p",
        "library-version-empty",
        "No shelter source has been imported yet. Add a local ZIP or import the platform baseline.",
      ));
      return;
    }

    const ordered = [...versions].sort((left, right) =>
      Number(left.synthetic) - Number(right.synthetic)
        || Number(right.is_current) - Number(left.is_current)
        || String(right.created_at).localeCompare(String(left.created_at)),
    );
    ordered.forEach((version) => {
      const kind = sourceKind(version);
      const active = version.is_current && version.readiness === "assessment_ready";
      const card = element("article", "library-version-card");
      if (active) card.classList.add("is-active");
      if (version.synthetic) card.classList.add("is-demo");

      const head = element("div", "library-version-card__head");
      const identity = element("div", "library-version-card__identity");
      identity.append(element(
        "span",
        `library-source-tag library-source-tag--${kind.modifier}`,
        kind.label,
      ));
      identity.append(element("h4", "library-version-card__title", sourceTitle(version)));
      identity.append(element(
        "p",
        "library-version-card__meta",
        `${version.provider || "Unknown provider"} · imported ${GRP.formatTime(version.created_at)}`,
      ));
      const state = element(
        "span",
        `library-use-badge${active ? " is-active" : ""}`,
        sourceUse(version),
      );
      head.append(identity, state);

      const metrics = element("dl", "library-version-card__metrics");
      [
        ["Centres", Number(version.feature_count || 0).toLocaleString()],
        ["District-name differences", Number(version.district_name_mismatch_count || 0).toLocaleString()],
        ["Outside boundary", Number(version.outside_boundary_count || 0).toLocaleString()],
      ].forEach(([label, value]) => {
        const item = element("div");
        item.append(element("dt", "", label), element("dd", "", value));
        metrics.append(item);
      });

      let nameText = "Stored centre names are available.";
      let nameClass = "is-neutral";
      if (version.shelter_names_confirmed === false) {
        nameText = "Centre names are generated because the source name fields have not been confirmed.";
        nameClass = "is-warning";
      } else if (version.shelter_names_confirmed === true) {
        nameText = "Confirmed source centre names are available.";
        nameClass = "is-good";
      }
      const nameNote = element(
        "p",
        `library-version-card__name-note ${nameClass}`,
        nameText,
      );

      const foot = element("div", "library-version-card__foot");
      foot.append(element(
        "span",
        "library-version-card__version",
        `Version ${version.version_id.slice(0, 8)} · ${Number(version.file_count || 0).toLocaleString()} source files`,
      ));
      if (active) {
        const link = element("a", "library-version-card__action", "Use in Planning →");
        link.href = "/planning.html";
        foot.append(link);
      } else if (version.can_accept) {
        const button = element("button", "library-version-card__action", "Use for new assessments");
        button.type = "button";
        button.addEventListener("click", () => acceptShelterVersion(version, button));
        foot.append(button);
      }
      card.append(head, metrics, nameNote, foot);
      list.append(card);
    });
  };

  const renderVersions = (category, versions) => {
    if (category === "evacuation_centers") {
      renderShelterVersions(versions);
      return;
    }
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
    if (category === "evacuation_centers") {
      shelterUploadEnabled = Boolean(data.browser_upload && data.browser_upload.enabled);
      const panel = document.querySelector("[data-shelter-upload-panel]");
      const file = document.querySelector("[data-shelter-upload-file]");
      const upload = document.querySelector("[data-upload-shelters]");
      panel.hidden = !canImport || !shelterUploadEnabled;
      file.disabled = Boolean(data.active_import_id) || Boolean(data.requires_boundaries);
      upload.disabled = file.disabled || !file.files.length;
    }
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
      payload.state === "succeeded" && category === "evacuation_centers"
        ? `${report.message} Review the quality counts, then choose “Use in new assessments”.`
        : payload.state === "succeeded"
          ? report.message
          : `Import stopped. Quote ${payload.support_ref}.`;
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

  const uploadShelters = async () => {
    const picker = document.querySelector("[data-shelter-upload-file]");
    const button = document.querySelector("[data-upload-shelters]");
    const note = document.querySelector("[data-shelter-upload-note]");
    const file = picker.files[0];
    if (!file || !shelterUploadEnabled) return;
    button.disabled = true;
    picker.disabled = true;
    errorBox.hidden = true;
    note.textContent = "Uploading the ZIP into local quarantine…";
    try {
      const started = await GRP.request("/api/v1/uploads/evacuation-centers", {
        method: "POST",
        body: file,
        contentType: "application/zip",
        idempotencyKey: crypto.randomUUID(),
        extraHeaders: { "X-Upload-Filename": file.name },
      });
      note.textContent = `${started.files.length} component file(s) received. Waiting for validation…`;
      GRP.jobs.track({
        id: started.import_id,
        label: "Uploaded evacuation-centre import",
        statusPath: `/api/v1/data-library/imports/${started.import_id}`,
        href: "/data-library.html",
        ownerPath: "/data-library.html",
      });
      poll("evacuation_centers", started.import_id);
    } catch (error) {
      showError(error.message || "The shelter ZIP could not be uploaded.");
      note.textContent = "The upload was not queued.";
      picker.disabled = false;
      button.disabled = !picker.files.length;
    }
  };

  const load = async () => {
    try {
      const payload = await GRP.request("/api/v1/data-library");
      canImport = payload.can_import_platform_baseline;
      renderBootstrap(payload.thailand_bootstrap);
      Object.keys(configs).forEach((category) => renderCategory(category, payload[configs[category].payload]));
      vulnerability.textContent = payload.vulnerability.message;
    } catch (error) {
      showError(error.message || "The data library could not be loaded.");
    }
  };

  Object.entries(configs).forEach(([category, config]) => {
    document.querySelector(config.button).addEventListener("click", () => startImport(category));
  });
  document.querySelector("[data-shelter-upload-file]").addEventListener("change", (event) => {
    const file = event.target.files[0];
    document.querySelector("[data-shelter-file-name]").textContent = file
      ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MB`
      : "No file selected";
    document.querySelector("[data-upload-shelters]").disabled = !file;
  });
  document.querySelector("[data-upload-shelters]").addEventListener("click", uploadShelters);
  load();
})();
