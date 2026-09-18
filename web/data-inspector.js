/* Admin data inspector (ADR-0006).
 *
 * Shows what is in the read-only source folder, what is wrong with it and what is missing.
 * Everything here describes unapproved files: it is never a GRP result.
 */
(() => {
  "use strict";

  const STATE_KEY = "grp.datainspector.v1";
  const POLL_MS = 1500;
  const POLL_LIMIT = 120;

  const $ = (selector) => document.querySelector(selector);
  const folderList = $("[data-folders]");
  const pickIntro = $("[data-pick-intro]");
  const rootPill = $("[data-root-pill]");
  const progressCard = $("[data-progress-card]");
  const progressPill = $("[data-progress-pill]");
  const progressText = $("[data-progress-text]");
  const progressFill = $("[data-progress-fill]");
  const reportCard = $("[data-report-card]");
  const reportScope = $("[data-report-scope]");
  const cachePill = $("[data-cache-pill]");
  const tally = $("[data-tally]");
  const findingsBox = $("[data-findings]");
  const crossNote = $("[data-cross-note]");
  const mapBox = $("[data-map]");
  const mapLegend = $("[data-map-legend]");
  const layersBody = $("[data-layers]");
  const columnsBox = $("[data-columns]");
  const filesBody = $("[data-files]");
  const fingerprintNote = $("[data-fingerprint-note]");
  const errorBox = $("[data-error]");

  let map = null;
  let markers = null;
  let pollCount = 0;
  let pollTimer = null;

  const readState = () => {
    try {
      return JSON.parse(sessionStorage.getItem(STATE_KEY) || "{}");
    } catch (_) {
      return {};
    }
  };

  const writeState = (value) => {
    try {
      sessionStorage.setItem(STATE_KEY, JSON.stringify(value));
    } catch (_) {
      /* a private window is fine; the page just does not remember the folder */
    }
  };

  const showError = (message) => {
    errorBox.textContent = message;
    errorBox.hidden = false;
  };

  const clearError = () => {
    errorBox.hidden = true;
    errorBox.textContent = "";
  };

  const bytes = (value) => {
    if (value === null || value === undefined) return "—";
    const units = ["B", "KB", "MB", "GB"];
    let size = value;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
      size /= 1024;
      unit += 1;
    }
    return `${size < 10 && unit > 0 ? size.toFixed(1) : Math.round(size)} ${units[unit]}`;
  };

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  /* ---------- step 1: folders ---------- */

  const renderFolders = (payload) => {
    rootPill.textContent = payload.root_label || "Source folder";
    pickIntro.textContent =
      "Pick a folder to read. Choosing “All source data” also checks the points against the " +
      "boundaries, which is the check that finds misplaced points.";
    folderList.replaceChildren();
    payload.folders.forEach((folder) => {
      const button = el("button", "inspector-folder");
      button.type = "button";
      button.setAttribute("role", "listitem");
      button.style.marginInlineStart = `${Math.min(folder.depth, 3) * 1.25}rem`;
      button.dataset.folder = folder.path;
      const name = el("span", "inspector-folder__name", folder.name);
      const meta = el(
        "span",
        "inspector-folder__meta",
        `${folder.file_count} file${folder.file_count === 1 ? "" : "s"} · ${bytes(folder.size_bytes)}`
      );
      button.append(name, meta);
      if (!folder.has_data_files) button.classList.add("is-plain");
      button.addEventListener("click", () => inspect(folder.path));
      folderList.append(button);
    });
  };

  /* ---------- step 2: run or reuse ---------- */

  const setProgress = (state, text, fraction) => {
    progressCard.hidden = false;
    progressPill.textContent = state;
    progressText.textContent = text;
    progressFill.style.width = `${Math.round(fraction * 100)}%`;
  };

  const inspect = async (folder) => {
    clearError();
    window.clearTimeout(pollTimer);
    pollCount = 0;
    reportCard.hidden = true;
    setProgress("Checking", "Fingerprinting the files so an unchanged folder is not read twice…", 0.15);
    try {
      const started = await GRP.request("/api/v1/data-inspector/inspections", {
        method: "POST",
        body: { folder },
      });
      writeState({ folder, inspection_id: started.inspection_id });
      if (started.from_cache) {
        setProgress("Cached", "These files have not changed, so the stored report is reused.", 1);
      } else {
        setProgress("Queued", "The worker will open each layer. Large rasters are sampled.", 0.3);
      }
      poll(started.inspection_id);
    } catch (error) {
      progressCard.hidden = true;
      showError(error.message || "The folder could not be read.");
    }
  };

  const poll = async (inspectionId) => {
    let payload;
    try {
      payload = await GRP.request(`/api/v1/data-inspector/inspections/${inspectionId}`);
    } catch (error) {
      progressCard.hidden = true;
      showError(error.message || "The report could not be read.");
      return;
    }
    if (payload.state === "succeeded") {
      setProgress("Done", "Every layer in this folder was read.", 1);
      window.setTimeout(() => {
        progressCard.hidden = true;
      }, 900);
      render(payload);
      return;
    }
    if (payload.state === "failed") {
      progressCard.hidden = true;
      showError(
        `The inspection stopped: ${payload.error_code || "unknown"}. Quote ${payload.support_ref}.`
      );
      return;
    }
    pollCount += 1;
    if (pollCount > POLL_LIMIT) {
      progressCard.hidden = true;
      showError("The inspection is taking longer than expected. Check that the worker is running.");
      return;
    }
    const share = Math.min(0.3 + pollCount * 0.03, 0.92);
    setProgress(
      payload.state === "running" ? "Reading" : "Queued",
      payload.state === "running"
        ? "Opening each layer and sampling the rasters…"
        : "Waiting for the worker to pick this up…",
      share
    );
    pollTimer = window.setTimeout(() => poll(inspectionId), POLL_MS);
  };

  /* ---------- step 3: the report ---------- */

  const GRADE_LABELS = {
    blocker: "Blocker",
    problem: "Problem",
    known: "Known already",
  };

  const renderTally = (counts) => {
    tally.replaceChildren();
    ["blocker", "problem", "known"].forEach((grade) => {
      const box = el("div", `inspector-tally__item is-${grade}`);
      box.append(el("strong", null, String(counts[grade] ?? 0)));
      box.append(el("span", null, GRADE_LABELS[grade]));
      tally.append(box);
    });
  };

  const renderFindings = (findings) => {
    findingsBox.replaceChildren();
    if (!findings.length) {
      findingsBox.append(el("p", "inspector-note", "Nothing to report for this folder."));
      return;
    }
    findings.forEach((finding) => {
      const card = el("article", `inspector-finding is-${finding.grade}`);
      const head = el("div", "inspector-finding__head");
      head.append(el("span", "inspector-finding__grade", GRADE_LABELS[finding.grade]));
      head.append(el("h4", null, finding.title));
      card.append(head);
      card.append(el("p", null, finding.detail));
      if (finding.action) {
        card.append(el("p", "inspector-finding__action", `What to do: ${finding.action}`));
      }
      if (finding.affects) {
        card.append(el("p", "inspector-finding__affects", finding.affects));
      }
      findingsBox.append(card);
    });
  };

  const renderCross = (cross) => {
    if (!cross) {
      crossNote.textContent =
        "This folder does not hold both boundaries and points, so nothing was cross-checked. " +
        "Pick “All source data” to run it.";
      mapBox.hidden = true;
      mapLegend.hidden = true;
      return;
    }
    const parts = [
      `${cross.points.toLocaleString()} points checked against ${cross.areas.toLocaleString()} areas`,
      `${cross.outside_every_area.toLocaleString()} fall outside every area`,
    ];
    if (cross.compared_names) {
      parts.push(`${cross.mismatched.toLocaleString()} are not in the area they name`);
    } else {
      parts.push("no usable area name to compare, so only position was checked");
    }
    parts.push(`${cross.areas_without_points.toLocaleString()} areas hold no points`);
    crossNote.textContent = `${parts.join("; ")}. Boundaries used: ${cross.area_layer}.`;
    drawMap(cross);
  };

  const COLOURS = { inside: "#2f8f4e", mismatched: "#c2410c", outside: "#98243a" };

  const drawMap = (cross) => {
    const points = cross.preview || [];
    if (!points.length || typeof L === "undefined") {
      mapBox.hidden = true;
      mapLegend.hidden = true;
      return;
    }
    mapBox.hidden = false;
    mapLegend.hidden = false;
    if (!map) {
      map = L.map(mapBox, { scrollWheelZoom: false });
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors",
        maxZoom: 18,
      }).addTo(map);
      markers = L.layerGroup().addTo(map);
    }
    markers.clearLayers();
    const bounds = [];
    points.forEach((point) => {
      bounds.push([point.lat, point.lon]);
      L.circleMarker([point.lat, point.lon], {
        radius: point.status === "inside" ? 3 : 5,
        color: COLOURS[point.status] || COLOURS.outside,
        weight: point.status === "inside" ? 1 : 2,
        fillOpacity: 0.7,
      })
        .bindTooltip(
          point.status === "inside"
            ? "In the area it names"
            : point.status === "mismatched"
              ? "In a different area from the one it names"
              : "Outside every area"
        )
        .addTo(markers);
    });
    map.fitBounds(bounds, { padding: [24, 24] });
    window.setTimeout(() => map.invalidateSize(), 60);
  };

  const renderLayers = (layers) => {
    layersBody.replaceChildren();
    layers.forEach((layer) => {
      const row = document.createElement("tr");
      row.append(el("td", null, layer.path));
      row.append(el("td", null, layer.kind));
      row.append(
        el("td", null, layer.crs_epsg ? `EPSG:${layer.crs_epsg}` : layer.crs || "none declared")
      );
      row.append(
        el(
          "td",
          null,
          layer.kind === "raster"
            ? `${layer.width} × ${layer.height} px · ~${layer.pixel_size_m} m`
            : `${(layer.feature_count ?? 0).toLocaleString()} ${layer.geometry_type || ""}`
        )
      );
      let values = "—";
      if (layer.kind === "raster") {
        values =
          layer.value_min === null || layer.value_min === undefined
            ? "no values in the sample"
            : `${layer.value_min} to ${layer.value_max}` +
              (layer.nodata_share !== null && layer.nodata_share !== undefined
                ? ` · ${Math.round(layer.nodata_share * 100)}% no data`
                : "");
      } else if (layer.fields) {
        values = `${layer.fields.length} columns`;
      }
      if (!layer.readable) values = layer.note || "could not be read";
      row.append(el("td", null, values));
      layersBody.append(row);
    });
  };

  const renderColumns = (layers) => {
    columnsBox.replaceChildren();
    layers
      .filter((layer) => layer.kind === "vector" && layer.fields && layer.fields.length)
      .forEach((layer) => {
        const details = el("details", "inspector-columns");
        details.append(el("summary", null, `${layer.path} — ${layer.fields.length} columns`));
        const table = el("table", "data-table inspector-table");
        const head = document.createElement("thead");
        const headRow = document.createElement("tr");
        ["Column", "Filled", "Empty", "Sample values"].forEach((label) => {
          const th = document.createElement("th");
          th.scope = "col";
          th.textContent = label;
          headRow.append(th);
        });
        head.append(headRow);
        const body = document.createElement("tbody");
        layer.fields.forEach((column) => {
          const row = document.createElement("tr");
          const name = el("td", null, column.name);
          if (column.possibly_truncated) {
            name.append(el("span", "inspector-flag", "cut short"));
          }
          row.append(name);
          row.append(el("td", null, column.filled.toLocaleString()));
          row.append(el("td", null, column.empty.toLocaleString()));
          row.append(el("td", null, column.samples.join(" · ") || "—"));
          body.append(row);
        });
        table.append(head, body);
        details.append(table);
        columnsBox.append(details);
      });
  };

  const renderFiles = (report) => {
    filesBody.replaceChildren();
    (report.files || []).forEach((file) => {
      const row = document.createElement("tr");
      row.append(el("td", null, file.path));
      row.append(el("td", null, bytes(file.size_bytes)));
      const print = el("td", null, `${file.fingerprint.slice(0, 12)}…`);
      if (!file.fully_fingerprinted) print.append(el("span", "inspector-flag", "head and tail"));
      row.append(print);
      filesBody.append(row);
    });
    const key = report.fingerprint ? ` Folder fingerprint ${report.fingerprint.slice(0, 12)}…` : "";
    fingerprintNote.textContent = (report.partly_fingerprinted
      ? "The stored report is reused only while these files are unchanged. Files too large to " +
        "hash whole are fingerprinted at their head and tail, marked below; a change in the " +
        "middle of one of those would not be noticed."
      : "The stored report is reused only while these files are unchanged. Every file here was " +
        "hashed whole.") + key;
  };

  const render = (payload) => {
    const report = payload.report || {};
    reportCard.hidden = false;
    reportScope.textContent = report.folder ? `Report · ${report.folder}` : "Report · all source data";
    cachePill.hidden = !payload.completed_at || payload.state !== "succeeded";
    cachePill.textContent = `Read ${new Date(payload.completed_at).toLocaleString()}`;
    renderTally(report.counts || {});
    renderFindings(report.findings || []);
    renderCross(report.cross_check);
    renderLayers(report.layers || []);
    renderColumns(report.layers || []);
    renderFiles(report);
  };

  /* ---------- start ---------- */

  GRP.request("/api/v1/data-inspector/folders")
    .then((payload) => {
      renderFolders(payload);
      const saved = readState();
      if (saved.folder !== undefined) inspect(saved.folder);
    })
    .catch((error) => {
      pickIntro.textContent = "";
      showError(
        error.message ||
          "The source data folder is not available. It is mounted only on Docker Desktop."
      );
    });
})();
