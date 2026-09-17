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
  const planningRoles = new Set(["ndmo_planner", "hub_expert", "planner", "admin"]);
  const roleLabel = (role) => ({
    ndmo_planner: "NDMO Planner",
    hub_expert: "Hub Expert / GIS Specialist",
    planner: "Legacy Planner",
    admin: "Hub Admin",
  }[role] || role);

  const thread = $("[data-thread]");
  const input = $("[data-input]");
  const sendButton = $("[data-send]");

  const state = {
    hubCode: null,
    chatAvailable: false,
    boundaries: [],
    selected: null,
    explicitSelection: false,
    currentPlace: null,
    floodLayers: [],
    centersVersion: null,
    assessmentId: null,
    pollTimer: null,
    busy: false,
    history: [],
  };

  // ---------- keep the conversation when moving between menu pages ----------
  // Stored only in this browser tab (sessionStorage): gone when the tab closes or on sign-out.
  // v2 deliberately starts a fresh local session: v1 restored the synthetic demo as the
  // default map context, which is misleading for real-district SIG lookup.
  const STORE_KEY = "grp.planning.v2";
  const transcript = [];
  let restoring = false;
  let ownerEmail = null;
  let openEvidencePayload = null;

  const saveState = () => {
    if (restoring || !ownerEmail) return;
    try {
      const kept = transcript.slice(-40);
      const evidenceIndex = openEvidencePayload
        ? kept.findIndex((entry) => entry.payload === openEvidencePayload)
        : -1;
      sessionStorage.setItem(STORE_KEY, JSON.stringify({
        owner: ownerEmail,
        transcript: kept,
        selectedId: state.selected ? state.selected.id : null,
        explicitSelection: state.explicitSelection,
        assessmentId: state.assessmentId,
        pendingAssessmentId: state.pendingAssessmentId || null,
        history: state.history.slice(-8),
        evidenceIndex,
      }));
    } catch (_error) {
      // Storage full or blocked: the page still works, it just will not remember.
    }
  };

  // ---------- map ----------
  const map = window.L.map("risk-map", { zoomControl: true }).setView([13.4, 101.0], 6);
  window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  const districtLayer = window.L.featureGroup().addTo(map);
  const centersLayer = window.L.featureGroup().addTo(map);
  const placeLayer = window.L.featureGroup().addTo(map);
  let floodOverlay = null;

  const safeHttps = (value) => {
    try {
      const url = new URL(value);
      return url.protocol === "https:" ? url.href : null;
    } catch (_error) {
      return null;
    }
  };

  // ---------- chat rendering ----------
  const scrollDown = () => {
    thread.scrollTop = thread.scrollHeight;
  };

  const hideWelcome = () => {
    const welcome = $("[data-welcome]");
    if (welcome) welcome.remove();
  };

  const addMessage = (role, text, { label, actions = [], error = false, record = true, confirmation = null } = {}) => {
    hideWelcome();
    if (record && !restoring) {
      transcript.push({ kind: "message", role, text, label: label || null, error, confirmation });
      saveState();
    }
    const row = document.createElement("div");
    row.className = `pw-msg pw-msg--${role}${error ? " pw-msg--error" : ""}`;
    if (role === "assistant") {
      const avatar = document.createElement("span");
      avatar.className = "pw-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = "AI";
      row.append(avatar);
    }
    const bubble = document.createElement("div");
    bubble.className = "pw-bubble";
    bubble.textContent = text;
    if (label) {
      const small = document.createElement("small");
      small.className = "pw-bubble__label";
      small.textContent = label;
      bubble.append(small);
    }
    if (actions.length) {
      const bar = document.createElement("div");
      bar.className = "pw-actions";
      actions.forEach((action) => bar.append(action));
      bubble.append(bar);
    }
    row.append(bubble);
    thread.append(row);
    scrollDown();
    return row;
  };

  // SIG answers: a compact status card, the brief folded underneath, details on the right.
  const addEvidenceMessage = (payload, question) => {
    if (!restoring) {
      transcript.push({ kind: "evidence", payload, question });
      saveState();
    }
    const row = addMessage("assistant", "", {
      label: payload.label,
      record: false,
      actions: [chipButton("Open map & evidence", () => renderEvidence(payload, question))],
    });
    const bubble = row.querySelector(".pw-bubble");
    bubble.classList.add("pw-bubble--evidence");
    bubble.prepend(statusCard(payload, question));
    const brief = document.createElement("details");
    brief.className = "pw-brief";
    const summary = document.createElement("summary");
    summary.textContent = "Read the brief";
    const text = renderBrief(payload.answer, (n) => {
      renderEvidence(payload, question);
      focusCitation(n);
    });
    brief.append(summary, text);
    bubble.querySelector(".pw-bubble__label").before(brief);
    scrollDown();
  };

  const STEP_LABELS = {
    understand_question: "Understood the question",
    assemble_pack: "Gathered SIG flood evidence",
    draft: "Wrote the brief",
    publish_answer: "SIG source check and receipt",
    hazard_map: "Loaded SIG flood map",
  };

  const seconds = (ms) => `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
  const clock = (ms) => {
    const total = Math.floor(ms / 1000);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  };

  // Live progress while one request runs. The API answers in one go, so the steps advance
  // on typical timings and are replaced by the real step durations when the answer arrives.
  const addProgress = ({ publish = false } = {}) => {
    hideWelcome();
    const steps = [
      { label: "Understanding your question", after: 0 },
      { label: "Finding the district and flood evidence on SIG (usually 20–90 s)", after: 4000 },
      { label: "Checking SIG used the real district boundary", after: 30000 },
      { label: "Writing the brief from the evidence", after: 45000 },
    ];
    if (publish) steps.push({ label: "SIG source check, receipt and flood map", after: 60000 });
    const row = document.createElement("div");
    row.className = "pw-msg pw-msg--assistant";
    const avatar = document.createElement("span");
    avatar.className = "pw-avatar";
    avatar.textContent = "AI";
    const bubble = document.createElement("div");
    bubble.className = "pw-bubble pw-progress-card";
    const head = document.createElement("div");
    head.className = "pw-progress-card__head";
    const title = document.createElement("strong");
    title.textContent = "Working on it";
    const timer = document.createElement("span");
    timer.className = "pw-timer";
    timer.textContent = "0:00";
    head.append(title, timer);
    const list = document.createElement("ol");
    list.className = "pw-steps";
    const items = steps.map((step) => {
      const item = document.createElement("li");
      item.textContent = step.label;
      list.append(item);
      return item;
    });
    const bar = document.createElement("div");
    bar.className = "pw-progress";
    bar.append(document.createElement("span"));
    bubble.append(head, list, bar);
    row.append(avatar, bubble);
    thread.append(row);
    scrollDown();
    const started = performance.now();
    const tick = () => {
      const ms = performance.now() - started;
      timer.textContent = clock(ms);
      let current = 0;
      steps.forEach((step, index) => {
        if (ms >= step.after) current = index;
      });
      items.forEach((item, index) => {
        item.className = index < current ? "is-done" : index === current ? "is-active" : "";
      });
    };
    tick();
    const handle = window.setInterval(tick, 500);
    return {
      remove: () => {
        window.clearInterval(handle);
        row.remove();
      },
      elapsed: () => performance.now() - started,
    };
  };

  // Brief as headings and paragraphs; [n] citations open the matching evidence card.
  const renderBrief = (text, onCite) => {
    const box = document.createElement("div");
    box.className = "pw-brief__text";
    let list = null;
    text.split(/\n+/).forEach((raw) => {
      const line = raw.trim();
      if (!line) return;
      const heading = line.match(/^#{1,4}\s+(.*)$/);
      const bullet = line.match(/^[-*]\s+(.*)$/);
      let node;
      if (heading) {
        list = null;
        node = document.createElement("h4");
        appendInline(node, heading[1], onCite);
      } else if (bullet) {
        if (!list) {
          list = document.createElement("ul");
          box.append(list);
        }
        node = document.createElement("li");
        appendInline(node, bullet[1], onCite);
        list.append(node);
        return;
      } else {
        list = null;
        node = document.createElement("p");
        appendInline(node, line, onCite);
      }
      box.append(node);
    });
    return box;
  };

  const appendInline = (parent, text, onCite) => {
    text.split(/(\[\d+\](?:\[\d+\])*|\*\*[^*]+\*\*)/g).forEach((part) => {
      if (!part) return;
      if (/^\[\d+\]/.test(part)) {
        part.match(/\d+/g).forEach((n) => {
          const cite = document.createElement("button");
          cite.type = "button";
          cite.className = "pw-cite";
          cite.textContent = n;
          cite.title = `Open evidence [${n}]`;
          cite.addEventListener("click", () => onCite(Number(n)));
          parent.append(cite);
        });
      } else if (/^\*\*.*\*\*$/.test(part)) {
        const strong = document.createElement("strong");
        strong.textContent = part.slice(2, -2);
        parent.append(strong);
      } else {
        parent.append(document.createTextNode(part));
      }
    });
  };

  const chipButton = (text, onClick, warning = false) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `pw-chip-button${warning ? " is-warning" : ""}`;
    button.textContent = text;
    button.addEventListener("click", () => onClick(button));
    return button;
  };

  const showAllowance = (usage) => {
    const pill = $("[data-allowance]");
    pill.classList.toggle("is-low", GRP.isLow(usage));
    pill.classList.toggle("is-off", usage.status !== "active");
    pill.title = GRP.allowanceMessage(usage);
    pill.textContent =
      usage.status === "active"
        ? `AI ${GRP.tokens(usage.tokens_remaining)} tokens left`
        : usage.status === "limit_reached"
          ? "AI limit reached"
          : "AI off";
  };

  const renderContext = () => {
    const box = $("[data-context]");
    box.replaceChildren();
    if (state.selected) {
      const chip = document.createElement("span");
      chip.textContent = `📍 ${state.selected.name}`;
      box.append(chip);
    }
    if (state.assessmentId) {
      const chip = document.createElement("span");
      chip.textContent = "Result on map";
      box.append(chip);
    }
  };

  const updateSend = () => {
    sendButton.disabled = state.busy || !state.hubCode || !input.value.trim();
  };

  // ---------- welcome ----------
  const renderWelcome = () => {
    const welcome = $("[data-welcome]");
    if (!welcome) return;
    const area = state.selected ? state.selected.name : null;
    welcome.querySelector("h2").textContent = "What decision are you preparing for?";
    const intro = welcome.querySelector("p");
    intro.textContent =
      "For a Thailand district or sub-district and an agreed flood scenario, I can help you " +
      "answer two linked questions: Where could people move? and Which vulnerable people need " +
      "support? Then I can prepare a traceable preparedness investment brief. A red/yellow/green " +
      "risk map is available as further information.";
    const box = $("[data-suggestions]");
    box.replaceChildren();
    [
      area
        ? ["Where could people move?", `Run a 100-year flood assessment for ${area}`,
          `Where could people move if a 100-year flood hits ${area}?`]
        : ["Use my current district", "Find your Thailand district before asking SIG",
          null],
      ["Explain what the map shows", "After a result appears",
        "Explain the result: which evacuation centers may be exposed and why?"],
      ["Check SIG flood exposure", "Schools, hospitals and roads for a Thailand district",
        "Which schools and hospitals in Mueang Nan District, Nan are exposed to flooding?"],
    ].forEach(([title, detail, prompt]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pw-suggestion";
      const strong = document.createElement("strong");
      const span = document.createElement("span");
      strong.textContent = title;
      span.textContent = detail;
      button.append(strong, span);
      button.addEventListener("click", () => {
        if (prompt) send(prompt);
        else useCurrentLocation();
      });
      box.append(button);
    });
    let coming = welcome.querySelector(".pw-coming");
    if (!coming) {
      coming = document.createElement("p");
      coming.className = "pw-coming";
      welcome.append(coming);
    }
    coming.innerHTML = "";
    const strong = document.createElement("strong");
    strong.textContent = "Coming next: ";
    coming.append(
      strong,
      document.createTextNode(
        "vulnerable people who need support (Increment 6), the preparedness investment brief, " +
          "and the red/yellow/green risk map. Today the map shows flood depth and evacuation centers.",
      ),
    );
  };

  // ---------- layers ----------
  const boundaryStyle = (selected) => ({
    color: "#1b678f",
    weight: selected ? 3 : 2,
    dashArray: selected ? null : "4 4",
    fillColor: "#8db33f",
    fillOpacity: selected ? 0.16 : 0.05,
  });

  const drawDistricts = () => {
    districtLayer.clearLayers();
    state.boundaries.forEach((boundary) => {
      const layer = window.L.geoJSON(boundary.geometry, { style: boundaryStyle(false) });
      layer.boundaryId = boundary.id;
      layer.bindTooltip(`${boundary.name}${boundary.synthetic ? " · synthetic" : ""}`, { sticky: true });
      layer.on("click", () => selectBoundary(boundary, { announce: true }));
      districtLayer.addLayer(layer);
    });
  };

  const selectBoundary = (boundary, { announce = false, explicit = announce } = {}) => {
    state.selected = boundary;
    state.explicitSelection = explicit;
    if (explicit) {
      const districtToggle = $('[data-layer="districts"]');
      const floodToggle = $('[data-layer="flood"]');
      const centersToggle = $('[data-layer="centers"]');
      districtToggle.checked = floodToggle.checked = centersToggle.checked = true;
      districtLayer.addTo(map);
      centersLayer.addTo(map);
      if (floodOverlay) floodOverlay.addTo(map);
    }
    placeLayer.clearLayers();
    $("[data-place-chip]").hidden = true;
    districtLayer.eachLayer((layer) => layer.setStyle(boundaryStyle(layer.boundaryId === boundary.id)));
    const layer = districtLayer.getLayers().find((item) => item.boundaryId === boundary.id);
    if (layer) map.flyToBounds(layer.getBounds(), { padding: [60, 60], duration: 0.6 });
    renderContext();
    renderWelcome();
    saveState();
    if (announce && !state.busy) {
      addMessage("assistant", `${boundary.name} is selected. Ask me to run a flood assessment for it, or ask anything else.`, {
        actions: [chipButton("Run 100-year flood assessment", () => send(`Run a 100-year flood assessment for ${boundary.name}`))],
      });
    }
  };

  const loadFloodOverlay = async (layer) => {
    if (floodOverlay) floodOverlay.remove();
    floodOverlay = null;
    if (!layer || !layer.available || !layer.bounds) return;
    const response = await fetch(layer.image_url, { credentials: "same-origin" });
    if (!response.ok) return;
    const url = URL.createObjectURL(await response.blob());
    floodOverlay = window.L.imageOverlay(url, layer.bounds, { opacity: 0.8, interactive: false });
    if ($('[data-layer="flood"]').checked) floodOverlay.addTo(map);
    $("[data-flood-title]").textContent = `Flood depth · ${layer.return_period_years}-year`;
  };

  const drawLegend = (legend) => {
    const box = $("[data-flood-legend]");
    box.replaceChildren();
    [...legend.classes, legend.no_data].forEach((item) => {
      const row = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.className = "pw-swatch";
      swatch.style.background = `rgba(${item.rgba[0]},${item.rgba[1]},${item.rgba[2]},${item.rgba[3] / 255})`;
      row.append(swatch, document.createTextNode(item.label));
      box.append(row);
    });
  };

  const popup = (title, lines) => {
    const node = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = title;
    node.append(strong);
    lines.forEach((line) => {
      node.append(document.createElement("br"), document.createTextNode(line));
    });
    return node;
  };

  const drawPendingCenters = async () => {
    if (!state.centersVersion) return;
    const collection = await GRP.request(state.centersVersion.features_url);
    centersLayer.clearLayers();
    collection.features.forEach((feature) => {
      const [lon, lat] = feature.geometry.coordinates;
      window.L.circleMarker([lat, lon], { radius: 6, color: "#374151", weight: 2, fillColor: "#fff", fillOpacity: 1 })
        .bindPopup(popup(feature.properties.name, ["Evacuation center · not assessed yet"]))
        .addTo(centersLayer);
    });
  };

  const drawResultCenters = (centers, reasons) => {
    centersLayer.clearLayers();
    centers.forEach((center) => {
      const meaning = (reasons[center.reason_code] || {}).meaning || center.reason_code;
      const lines = [STATUS_TEXT[center.status]];
      if (center.flood_depth_m !== null) lines.push(`Flood depth ${center.flood_depth_m} m`);
      lines.push(meaning);
      window.L.circleMarker([center.lat, center.lon], {
        radius: 8, color: "#fff", weight: 2, fillColor: STATUS_COLOR[center.status], fillOpacity: 0.95,
      })
        .bindPopup(popup(center.name, lines))
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

  $("[data-layers-toggle]").addEventListener("click", (event) => {
    const panel = $("[data-layers]");
    panel.hidden = !panel.hidden;
    event.currentTarget.setAttribute("aria-expanded", String(!panel.hidden));
  });

  // ---------- result card ----------
  const resultCard = $("[data-result]");
  $("[data-result-close]").addEventListener("click", () => {
    resultCard.hidden = true;
  });

  const showProgress = (title) => {
    resultCard.hidden = false;
    $("[data-synthetic]").hidden = true;
    $("[data-result-title]").textContent = title;
    $("[data-result-meta]").textContent = "Screening evacuation centers in the background…";
    $("[data-progress]").hidden = false;
    $("[data-stats]").replaceChildren();
    $("[data-result-link]").hidden = true;
  };

  const showResult = async (id, { quiet = false } = {}) => {
    const [result, centers] = await Promise.all([
      GRP.request(`/api/v1/assessments/${id}/result`),
      GRP.request(`/api/v1/assessments/${id}/centers?size=200`),
    ]);
    drawResultCenters(centers.centers, result.reason_codes);
    resultCard.hidden = false;
    $("[data-progress]").hidden = true;
    $("[data-synthetic]").hidden = !result.synthetic;
    $("[data-result-title]").textContent = `${result.area} · ${result.scenario.return_period_years}-year flood`;
    $("[data-result-meta]").textContent =
      `Method ${result.method.key} ${result.method.version}${result.method.status === "approved" ? "" : " (draft)"} · ref ${result.support_ref}`;
    const stats = $("[data-stats]");
    stats.replaceChildren();
    [
      ["", result.summary.in_scope, "Centers in area"],
      ["pw-stat--exposed", result.summary.potentially_exposed, "Potentially exposed"],
      ["pw-stat--not", result.summary.not_exposed_under_scenario, "Not exposed"],
      ["pw-stat--unable", result.summary.unable_to_assess, "Unable to assess"],
    ].forEach(([modifier, value, label]) => {
      const tile = document.createElement("div");
      tile.className = `pw-stat ${modifier}`;
      const strong = document.createElement("strong");
      const span = document.createElement("span");
      strong.textContent = String(value);
      span.textContent = label;
      tile.append(strong, span);
      stats.append(tile);
    });
    $("[data-result-link]").hidden = false;
    state.assessmentId = id;
    state.pendingAssessmentId = null;
    renderContext();
    const boundary = state.boundaries.find((b) => b.id === result.area_detail.id);
    if (boundary) selectBoundary(boundary, { explicit: true });
    saveState();
    if (quiet) return;
    addMessage(
      "assistant",
      `The ${result.scenario.return_period_years}-year flood screening for ${result.area} is on the map. ` +
        `${result.summary.potentially_exposed} of ${result.summary.in_scope} evacuation centers may be exposed, ` +
        `${result.summary.not_exposed_under_scenario} are not exposed under this scenario, and ` +
        `${result.summary.unable_to_assess} could not be assessed.`,
      {
        label: result.synthetic ? "Synthetic test data — not a scientific result." : "From the locked assessment result.",
        actions: [
          chipButton("Where could people move?", () => send("Which evacuation centers are not exposed, where people could move?")),
          chipButton("Why unable to assess?", () => send("Which centers could not be assessed, and why?")),
        ],
      },
    );
  };

  const watch = async (id) => {
    window.clearTimeout(state.pollTimer);
    try {
      const job = await GRP.request(`/api/v1/assessments/${id}`);
      if (job.state === "succeeded") {
        await showResult(id);
      } else if (job.state === "queued" || job.state === "running") {
        state.pollTimer = window.setTimeout(() => watch(id), 5000);
      } else {
        state.pendingAssessmentId = null;
        saveState();
        $("[data-progress]").hidden = true;
        $("[data-result-meta]").textContent = `Assessment ${job.state}. Reference ${job.support_ref}.`;
        addMessage("assistant", `The assessment ${job.state}${job.error_code ? ` (${job.error_code})` : ""}. Reference ${job.support_ref}.`, { error: true });
      }
    } catch (error) {
      addMessage("assistant", error.message, { error: true });
    }
  };

  // ---------- SIG evidence ----------
  const sigPanel = $("[data-sig]");
  $("[data-sig-close]").addEventListener("click", () => {
    sigPanel.hidden = true;
    $("[data-sig-frame]").removeAttribute("src");
  });

  // Evidence panel: what SIG returned, what is missing, how it was produced, downloads.
  const evidencePanel = $("[data-evidence]");
  const sigAreaLayer = window.L.featureGroup().addTo(map);
  let currentEvidence = null;

  const openEvidence = () => {
    evidencePanel.hidden = false;
    document.body.classList.add("has-evidence");
    if (window.matchMedia("(max-width: 860px)").matches) {
      document.body.dataset.view = "map";
    }
    window.setTimeout(() => map.invalidateSize(), 0);
  };

  $("[data-ev-close]").addEventListener("click", () => {
    openEvidencePayload = null;
    saveState();
    evidencePanel.hidden = true;
    document.body.classList.remove("has-evidence");
  });

  document.querySelectorAll("[data-ev-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("[data-ev-tab]").forEach((t) =>
        t.setAttribute("aria-selected", String(t === tab)),
      );
      document.querySelectorAll("[data-ev-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.evPanel !== tab.dataset.evTab;
      });
    });
  });

  const downloadFile = (name, content, type) => {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const slug = (text) =>
    String(text || "evidence").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);

  const traceText = (evidence) => {
    const lines = [
      `Question: ${evidence.question}`,
      `Area: ${evidence.place}`,
      `SIG pack: ${evidence.pack_id || "-"}`,
      `Assembled at: ${evidence.assembled_at || "-"} (${evidence.gather_ms ?? "-"} ms)`,
      `Receipt: ${evidence.receipt ? evidence.receipt.receipt_id : "none (not published)"}`,
      "",
      "SIG platform steps:",
      ...evidence.sig_trace.map((line, i) => `  ${i + 1}. ${line}`),
      "",
      "GRP steps:",
      ...evidence.grp_trace.map((step, i) => `  ${i + 1}. ${step.step}: ${step.detail}`),
      "",
      "Declared gaps:",
      ...evidence.gaps.map((gap) => `  - ${gap}`),
    ];
    return lines.join("\n");
  };

  document.querySelector("[data-ev-download-toggle]").addEventListener("click", (event) => {
    const menu = $("[data-ev-download]");
    menu.hidden = !menu.hidden;
    event.currentTarget.setAttribute("aria-expanded", String(!menu.hidden));
  });

  document.querySelectorAll("[data-download]").forEach((button) => {
    button.addEventListener("click", () => {
      $("[data-ev-download]").hidden = true;
      if (!currentEvidence) return;
      const { evidence, answer } = currentEvidence;
      const base = `grp-${slug(evidence.place)}-${(evidence.pack_id || "pack").slice(0, 8)}`;
      if (button.dataset.download === "brief") {
        const header = `# ${evidence.question}\n\nArea: ${evidence.place}\nSIG pack: ${evidence.pack_id}\n` +
          `Status: ${evidence.receipt ? `receipt ${evidence.receipt.receipt_id}` : "unverified draft (no receipt)"}\n\n` +
          "_SIG generic evidence. Not a GRP assessment and not a decision that any place is safe._\n\n";
        downloadFile(`${base}-brief.md`, header + answer, "text/markdown");
      } else if (button.dataset.download === "evidence") {
        downloadFile(`${base}-evidence.json`, JSON.stringify({ ...evidence, brief: answer }, null, 2), "application/json");
      } else {
        downloadFile(`${base}-trace.txt`, traceText(evidence), "text/plain");
      }
    });
  });

  const outlineSigArea = async (evidence) => {
    sigAreaLayer.clearLayers();
    const name = (evidence.area && evidence.area.sig_place) || evidence.place;
    if (!name) return;
    try {
      const query = /thailand/i.test(evidence.place) ? evidence.place : `${evidence.place}, Thailand`;
      const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&polygon_geojson=1&limit=1&countrycodes=th&q=${encodeURIComponent(query)}`;
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      const [place] = await response.json();
      if (!place || !place.geojson) return;
      const shape = window.L.geoJSON(place.geojson, {
        style: { color: "#1d4ed8", weight: 2.5, fillColor: "#60a5fa", fillOpacity: 0.08 },
      }).bindTooltip(`${name} · outline from OpenStreetMap (orientation only)`, { sticky: true });
      shape.addTo(sigAreaLayer);
      map.flyToBounds(shape.getBounds(), { padding: [60, 60], duration: 0.7 });
    } catch (_error) {
      // Outline is only for orientation; the evidence still shows without it.
    }
  };

  const evidenceCard = (citation) => {
    const card = document.createElement("article");
    card.className = "pw-card";
    const title = document.createElement("h3");
    title.textContent = `[${citation.n}] ${citation.title || citation.source || "Source"}`;
    const source = document.createElement("p");
    source.className = "pw-card__source";
    source.textContent = citation.source || citation.kind || "";
    const tags = document.createElement("div");
    tags.className = "pw-card__tags";
    const retrieval = String(citation.retrieval || "");
    const tagText = retrieval.startsWith("computed") ? "computed" : retrieval.includes("live") ? "pulled live" : citation.kind === "gaps" ? "declared gap" : "archived";
    const tag = document.createElement("span");
    tag.className = `pw-tag pw-tag--${tagText.replace(" ", "-")}`;
    tag.textContent = tagText;
    const validation = document.createElement("span");
    validation.textContent = citation.validation || "";
    tags.append(tag, validation);
    card.append(title, source, tags);
    if (citation.text) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Details";
      const body = document.createElement("p");
      body.textContent = citation.text;
      details.append(summary, body);
      card.append(details);
    }
    return card;
  };

  const focusCitation = (n) => {
    document.querySelector('[data-ev-tab="evidence"]').click();
    const card = $("[data-ev-cards]").children[n - 1];
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.remove("is-focus");
    void card.offsetWidth;
    card.classList.add("is-focus");
    const details = card.querySelector("details");
    if (details) details.open = true;
  };

  const renderEvidence = (payload, message) => {
    const evidence = payload.evidence;
    if (!evidence) return;
    currentEvidence = { evidence, answer: payload.answer, message };
    openEvidencePayload = payload;
    saveState();
    const counts = evidence.summary;
    $("[data-ev-title]").textContent = (evidence.area && evidence.area.sig_place) || evidence.place;
    $("[data-ev-counts]").textContent =
      `${counts.sources} sources · ${counts.pulled_live} pulled live · ${counts.computed} computed · ${counts.declared_gaps} declared gap(s)`;
    const area = $("[data-ev-area]");
    area.textContent = evidence.area && evidence.area.sig_area
      ? `SIG analysis area: ${evidence.area.sig_area}`
      : "";

    const numbers = $("[data-ev-numbers]");
    numbers.replaceChildren();
    Object.entries((evidence.stats && evidence.stats.counts) || {}).forEach(([name, value]) => {
      const tile = document.createElement("div");
      tile.className = "pw-number";
      const strong = document.createElement("strong");
      const span = document.createElement("span");
      strong.textContent = typeof value.exposed === "number"
        ? `${value.exposed} / ${value.total}`
        : `${value.exposed_km ?? 0} / ${value.total_km ?? 0} km`;
      span.textContent = `${name.replaceAll("_", " ")} in flood area`;
      tile.append(strong, span);
      numbers.append(tile);
    });

    const cards = $("[data-ev-cards]");
    cards.replaceChildren(...evidence.citations.map(evidenceCard));

    const gaps = $("[data-ev-gaps]");
    gaps.replaceChildren(...evidence.gaps.map((gap) => {
      const item = document.createElement("li");
      item.textContent = gap;
      return item;
    }));

    const trace = $("[data-ev-trace]");
    trace.replaceChildren(
      ...evidence.sig_trace.map((line) => {
        const item = document.createElement("li");
        item.textContent = line;
        return item;
      }),
      ...evidence.grp_trace.map((step) => {
        const item = document.createElement("li");
        item.className = "is-grp";
        const time = typeof step.duration_ms === "number" ? ` (${seconds(step.duration_ms)})` : "";
        item.textContent = `GRP · ${STEP_LABELS[step.step] || step.step}: ${step.detail}${time}`;
        return item;
      }),
    );
    $("[data-ev-exec]").textContent =
      `Pack ${evidence.pack_id || "-"} assembled ${evidence.assembled_at ? GRP.formatTime(evidence.assembled_at) : "-"} (Bangkok); SIG gathering ${evidence.gather_ms ? seconds(evidence.gather_ms) : "-"}; whole answer ${evidence.total_ms ? seconds(evidence.total_ms) : "-"}.`;

    const mapButton = $("[data-ev-map]");
    const mapUrl = safeHttps(payload.map_url);
    mapButton.disabled = false;
    mapButton.classList.remove("is-warning");
    delete mapButton.dataset.confirm;
    if (evidence.receipt) {
      mapButton.textContent = "Show SIG flood map";
      mapButton.onclick = () => {
        if (!mapUrl) return;
        $("[data-sig-frame]").src = mapUrl;
        sigPanel.hidden = false;
      };
      const receiptUrl = safeHttps(evidence.receipt.public_url);
      $("[data-ev-foot]").textContent = "";
      if (receiptUrl) {
        const link = document.createElement("a");
        link.href = receiptUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = `Public receipt ${evidence.receipt.receipt_id}`;
        $("[data-ev-foot]").append("Passed SIG's source check · ", link);
      }
    } else {
      mapButton.textContent = "Publish receipt & show SIG flood map";
      mapButton.onclick = () => {
        if (mapButton.dataset.confirm !== "yes") {
          mapButton.dataset.confirm = "yes";
          mapButton.textContent = "Confirm: this creates a public record";
          mapButton.classList.add("is-warning");
          return;
        }
        mapButton.disabled = true;
        send(message, { publish: true, echo: false, confirmedPlace: evidence.place });
      };
      $("[data-ev-foot]").textContent =
        "Unverified draft: not yet checked by SIG's source check, no receipt. Evidence only — not a decision that any place is safe.";
    }
    outlineSigArea(evidence);
    openEvidence();
    if (evidence.receipt && mapUrl) {
      $("[data-sig-frame]").src = mapUrl;
      sigPanel.hidden = false;
    }
  };

  const statusCard = (payload, question) => {
    const evidence = payload.evidence;
    const counts = evidence.summary;
    const card = document.createElement("div");
    card.className = "pw-status";
    const title = document.createElement("strong");
    title.textContent = question;
    const line = document.createElement("span");
    line.textContent =
      `${counts.sources} sources · ${counts.pulled_live} pulled live · ${counts.computed} computed · ${counts.declared_gaps} declared gap(s)`;
    const badge = document.createElement("span");
    badge.className = `pw-status__badge${evidence.receipt ? " is-ok" : ""}`;
    badge.textContent = evidence.receipt ? `Receipt ${evidence.receipt.receipt_id}` : "Unverified draft";
    card.append(title);
    if (payload.note) {
      const note = document.createElement("span");
      note.className = "pw-status__note";
      note.textContent = payload.note;
      card.append(note);
    }
    card.append(line);
    const steps = (evidence.grp_trace || []).filter((step) => typeof step.duration_ms === "number");
    if (evidence.total_ms || steps.length) {
      const timing = document.createElement("span");
      timing.className = "pw-status__timing";
      const parts = steps.map((step) => `${STEP_LABELS[step.step] || step.step} ${seconds(step.duration_ms)}`);
      timing.textContent = `Took ${seconds(evidence.total_ms || 0)} · ${parts.join(" · ")}`;
      card.append(timing);
    }
    card.append(badge);
    return card;
  };

  const sigActions = (payload, message) => [
    chipButton("Open map & evidence", () => renderEvidence(payload, message)),
  ];

  const confirmAreaAction = (confirmation) => {
    const { place, message, publish } = confirmation;
    return chipButton(publish ? `Confirm ${place} and publish` : `Confirm ${place}`, async (button) => {
      button.disabled = true;
      try {
        const completed = await send(message, { publish, echo: false, confirmedPlace: place });
        if (completed) {
          confirmation.completed = true;
          button.textContent = "Area confirmed";
          saveState();
        }
      } finally {
        if (!confirmation.completed) button.disabled = false;
      }
    });
  };

  // ---------- sending ----------
  const asksAboutCurrentLocation = (message) => /\b(?:my )?current (?:location|district|area)\b/i.test(message);

  const findThaiPlaceMention = async (message) => {
    if (!/[\u0E00-\u0E7F]/.test(message)) return null;
    try {
      const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&addressdetails=1&limit=1&countrycodes=th&accept-language=en&q=${encodeURIComponent(message)}`;
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      const [place] = await response.json();
      return response.ok && place ? place : null;
    } catch (_error) {
      return null;
    }
  };

  const send = async (text, { publish = false, echo = true, confirmedPlace = null } = {}) => {
    const message = (text ?? input.value).trim();
    if (!message || state.busy || !state.hubCode) return;
    if (!state.chatAvailable) {
      addMessage("assistant", "The chat assistant runs only in the local Docker Desktop test right now.", { error: true });
      return;
    }
    if (!confirmedPlace && asksAboutCurrentLocation(message)) {
      if (!state.currentPlace) {
        if (echo) addMessage("user", message);
        addMessage(
          "assistant",
          "I do not know your current district yet. Use the location button or search for a Thailand district first.",
          { label: "Location needed.", actions: [chipButton("Use my location", useCurrentLocation)] },
        );
        return false;
      }
      confirmedPlace = state.currentPlace;
    }
    if (!confirmedPlace) {
      const candidate = await findThaiPlaceMention(message);
      const candidateName = candidate ? externalPlaceName(candidate) : "";
      if (candidateName) {
        if (echo) addMessage("user", message);
        input.value = "";
        autosize();
        addMessage("assistant", `I found ${candidateName}. Confirm it as your map location before using SIG evidence.`, {
          label: "Confirm your location.",
          actions: [chipButton(`Use ${candidateName} and answer`, async (button) => {
            // Confirming the district is the explicit area choice; then answer the
            // original question for it so the evidence appears on the map at once.
            button.disabled = true;
            pickPlace(candidate);
            const completed = await send(message, { echo: false, confirmedPlace: candidateName });
            button.textContent = completed ? `${candidateName} confirmed` : `Use ${candidateName} and answer`;
            if (!completed) button.disabled = false;
          })],
        });
        return false;
      }
    }
    const requestMessage = confirmedPlace && asksAboutCurrentLocation(message)
      ? message.replace(/\b(?:my )?current (?:location|district|area)\b/i, confirmedPlace)
      : message;
    if (echo) addMessage("user", message);
    input.value = "";
    autosize();
    state.busy = true;
    updateSend();
    const typing = addProgress({ publish });
    try {
      const payload = await GRP.request("/api/v1/planning/chat", {
        method: "POST",
        body: {
          message: requestMessage,
          place: confirmedPlace,
          hub_code: state.hubCode,
          boundary_id: state.explicitSelection && state.selected ? state.selected.id : null,
          assessment_id: state.assessmentId,
          publish_receipt: publish,
          history: state.history.slice(-8),
        },
      });
      typing.remove();
      if (payload.usage) showAllowance(payload.usage);
      let actions = [];
      if (payload.mode === "assessment_started") {
        const boundary = state.boundaries.find((b) => b.id === payload.boundary_id);
        if (boundary) selectBoundary(boundary, { explicit: true });
        state.assessmentId = null;
        await drawPendingCenters();
        showProgress(boundary ? boundary.name : "Assessment");
        state.pendingAssessmentId = payload.assessment_id;
        saveState();
        document.body.dataset.view = window.matchMedia("(max-width: 860px)").matches ? "map" : document.body.dataset.view;
        watch(payload.assessment_id);
      } else if (payload.mode === "sig_evidence") {
        actions = sigActions(payload, message);
      } else if (payload.mode === "needs_area_confirmation" && payload.place) {
        const confirmation = { place: payload.place, message, publish };
        addMessage("assistant", payload.answer, {
          label: payload.label,
          actions: [confirmAreaAction(confirmation)],
          confirmation,
        });
        return;
      }
      if (payload.mode === "sig_evidence" && payload.evidence) {
        addEvidenceMessage(payload, message);
        renderEvidence(payload, message);
      } else {
        addMessage("assistant", payload.answer, {
          label: payload.label,
          actions,
          error: payload.mode === "area_rejected" || payload.mode === "gate_blocked",
        });
      }
      state.history.push({ role: "user", text: message }, { role: "assistant", text: payload.answer.slice(0, 1200) });
      saveState();
      return true;
    } catch (error) {
      typing.remove();
      addMessage("assistant", error.message, { label: error.code, error: true });
      if (error.code === "SIG_REAUTH_REQUIRED") {
        window.setTimeout(() => window.location.assign("/api/v1/auth/login"), 1500);
      }
      GRP.request("/api/v1/me/ai-usage").then(showAllowance).catch(() => {});
      return false;
    } finally {
      state.busy = false;
      updateSend();
      input.focus();
    }
  };

  const autosize = () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  };

  input.addEventListener("input", () => {
    autosize();
    updateSend();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  });
  $("[data-composer]").addEventListener("submit", (event) => {
    event.preventDefault();
    send();
  });

  // ---------- search ----------
  const searchInput = $("[data-search-input]");
  const searchResults = $("[data-search-results]");
  let searchTimer = null;
  let searchToken = 0;

  const searchItem = (title, detail, onPick) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "pw-search__item";
    const strong = document.createElement("strong");
    const span = document.createElement("span");
    strong.textContent = title;
    span.textContent = detail;
    button.append(strong, span);
    button.addEventListener("click", () => {
      searchResults.hidden = true;
      searchInput.value = title;
      onPick();
    });
    return button;
  };

  const externalPlaceName = (place) => {
    const address = place.address || {};
    // SIG needs an administrative district, not a city-wide or neighbourhood
    // label. In Bangkok, `city_district` is the khet (for example Bang Sue);
    // elsewhere in Thailand Nominatim normally uses `county` for the amphoe.
    const district = address.city_district || address.county;
    const province = address.state || address.province;
    if (district) return [...new Set([district, province, "Thailand"].filter(Boolean))].join(", ");
    return null;
  };

  const pickPlace = (place, { currentLocation = false } = {}) => {
    placeLayer.clearLayers();
    const lat = Number(place.lat);
    const lon = Number(place.lon);
    const shape = place.geojson && place.geojson.type !== "Point"
      ? window.L.geoJSON(place.geojson, { style: { color: "#2563eb", weight: 2, fillOpacity: 0.05, dashArray: "6 4" } })
      : null;
    if (shape) {
      shape.addTo(placeLayer);
      map.flyToBounds(shape.getBounds(), { padding: [60, 60], duration: 0.6 });
    } else {
      map.flyTo([lat, lon], 12, { duration: 0.6 });
    }
    window.L.circleMarker([lat, lon], { radius: 6, color: "#2563eb", fillColor: "#2563eb", fillOpacity: 1 }).addTo(placeLayer);
    const name = externalPlaceName(place);
    state.currentPlace = name || null;
    const chip = $("[data-place-chip]");
    chip.replaceChildren();
    if (!name) {
      chip.textContent = "This map location is for orientation only. Choose a Thailand district before requesting SIG evidence.";
      chip.hidden = false;
      return;
    }
    chip.append(document.createTextNode(
      `${currentLocation ? "Your current district" : name} is not a supported GRP assessment area yet. `
    ));
    chip.append(chipButton("Check SIG flood exposure", () => send(
      `Check flood exposure for schools, hospitals and roads in ${name}.`,
      { confirmedPlace: name },
    )));
    chip.hidden = false;
  };

  const useCurrentLocation = async () => {
    const button = $("[data-use-location]");
    if (!navigator.geolocation) {
      addMessage("assistant", "This browser does not provide location access. Search for a Thailand district instead.", { error: true });
      return;
    }
    button.disabled = true;
    button.textContent = "Finding location…";
    try {
      const position = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(
        resolve,
        reject,
        { enableHighAccuracy: false, maximumAge: 300000, timeout: 10000 },
      ));
      const { latitude, longitude } = position.coords;
      const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=14&addressdetails=1&accept-language=en&lat=${encodeURIComponent(latitude)}&lon=${encodeURIComponent(longitude)}`;
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      const place = await response.json();
      if (!response.ok || !place || place.address?.country_code?.toLowerCase() !== "th") {
        throw new Error("CURRENT_LOCATION_NOT_THAILAND");
      }
      if (!externalPlaceName(place)) {
        throw new Error("CURRENT_LOCATION_NO_DISTRICT");
      }
      pickPlace({ ...place, lat: latitude, lon: longitude }, { currentLocation: true });
    } catch (error) {
      const message = error.code === 1
        ? "Location permission was not granted. Search for a Thailand district instead."
        : error.message === "CURRENT_LOCATION_NOT_THAILAND"
        ? "GRP’s current SIG lookup is limited to Thailand districts."
        : error.message === "CURRENT_LOCATION_NO_DISTRICT"
        ? "I found your approximate location but not its administrative district. Search for a Thailand district before using SIG evidence."
        : "I could not identify a district from your location. Search for a Thailand district instead.";
      addMessage("assistant", message, { error: true });
    } finally {
      button.disabled = false;
      button.textContent = "Use my location";
    }
  };

  const runSearch = async (query) => {
    const token = ++searchToken;
    searchResults.replaceChildren();
    const lower = query.toLowerCase();
    const local = state.boundaries.filter((b) => b.name.toLowerCase().includes(lower));
    if (local.length) {
      const group = document.createElement("div");
      group.className = "pw-search__group";
      group.textContent = "Supported assessment areas";
      searchResults.append(group);
      local.slice(0, 5).forEach((boundary) =>
        searchResults.append(searchItem(boundary.name, `${boundary.admin_level}${boundary.synthetic ? " · synthetic test area" : ""}`, () => selectBoundary(boundary, { announce: true }))),
      );
    }
    searchResults.hidden = false;
    if (query.length < 3) return;
    try {
      const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&polygon_geojson=1&addressdetails=1&limit=5&countrycodes=th&q=${encodeURIComponent(query)}`;
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      const places = await response.json();
      if (token !== searchToken) return;
      if (places.length) {
        const group = document.createElement("div");
        group.className = "pw-search__group";
        group.textContent = "Places (OpenStreetMap, for orientation)";
        searchResults.append(group);
        places.forEach((place) =>
          searchResults.append(searchItem(place.display_name.split(",")[0], place.display_name.split(",").slice(1, 3).join(",").trim(), () => pickPlace(place))),
        );
      }
    } catch (_error) {
      // Orientation search is optional; supported areas still work offline.
    }
    if (!searchResults.children.length) {
      const empty = document.createElement("div");
      empty.className = "pw-search__empty";
      empty.textContent = "No matches in Thailand.";
      searchResults.append(empty);
    }
  };

  searchInput.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    const query = searchInput.value.trim();
    if (!query) {
      searchResults.hidden = true;
      return;
    }
    searchTimer = window.setTimeout(() => runSearch(query), 350);
  });
  searchInput.addEventListener("focus", () => {
    if (searchInput.value.trim()) searchResults.hidden = false;
  });
  $("[data-use-location]").addEventListener("click", useCurrentLocation);
  document.addEventListener("click", (event) => {
    if (!$("[data-search]").contains(event.target)) searchResults.hidden = true;
  });

  // ---------- mobile view switch ----------
  document.querySelectorAll("[data-show]").forEach((button) => {
    button.addEventListener("click", () => {
      document.body.dataset.view = button.dataset.show;
      document.querySelectorAll("[data-show]").forEach((b) => b.setAttribute("aria-selected", String(b === button)));
      if (button.dataset.show === "map") window.setTimeout(() => map.invalidateSize(), 0);
    });
  });

  const restoreState = async () => {
    let saved = null;
    try {
      saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null");
    } catch (_error) {
      saved = null;
    }
    if (!saved) return;
    if (saved.owner !== ownerEmail) {
      sessionStorage.removeItem(STORE_KEY);
      return;
    }
    restoring = true;
    try {
      (saved.transcript || []).forEach((entry) => {
        transcript.push(entry);
        if (entry.kind === "evidence") addEvidenceMessage(entry.payload, entry.question);
        else addMessage(entry.role, entry.text, {
          label: entry.label,
          error: entry.error,
          record: false,
          actions: entry.confirmation && !entry.confirmation.completed
            ? [confirmAreaAction(entry.confirmation)] : [],
        });
      });
      state.history = saved.history || [];
      const boundary = state.boundaries.find((b) => b.id === saved.selectedId);
      if (boundary) selectBoundary(boundary, { explicit: Boolean(saved.explicitSelection) });
      if (saved.assessmentId) {
        await showResult(saved.assessmentId, { quiet: true }).catch(() => {});
      }
      if (saved.pendingAssessmentId) {
        state.pendingAssessmentId = saved.pendingAssessmentId;
        showProgress(boundary ? boundary.name : "Assessment");
        watch(saved.pendingAssessmentId);
      }
      const evidence = transcript[saved.evidenceIndex];
      if (evidence && evidence.kind === "evidence") renderEvidence(evidence.payload, evidence.question);
    } finally {
      restoring = false;
      saveState();
    }
  };

  // ---------- start ----------
  GRP.bindSignOut();

  GRP.me()
    .then(async (identity) => {
      const membership = identity.memberships.find((m) => planningRoles.has(m.role));
      const banner = $("[data-banner]");
      if (!membership) {
        banner.textContent = "You need an NDMO Planner, Hub Expert / GIS Specialist, or Hub Admin role in a Hub to plan. A Platform Admin role alone is not enough.";
        banner.hidden = false;
        $("[data-hub-name]").textContent = "No Hub role";
        return;
      }
      state.hubCode = membership.hub_code;
      $("[data-hub-name]").textContent = `${membership.hub_name} · ${roleLabel(membership.role)}`;
      const query = `?hub_code=${encodeURIComponent(state.hubCode)}`;
      const [planning, areas, layers] = await Promise.all([
        GRP.request("/api/v1/planning/status").catch(() => ({ available: false })),
        GRP.request(`/api/v1/catalog/boundaries${query}`),
        GRP.request(`/api/v1/maps/layers${query}`),
      ]);
      state.chatAvailable = Boolean(planning.available);
      if (planning.usage) showAllowance(planning.usage);
      else GRP.request("/api/v1/me/ai-usage").then(showAllowance).catch(() => {});
      if (!planning.available) {
        banner.textContent = "The chat assistant runs only in the local Docker Desktop test right now.";
        banner.hidden = false;
      } else if (!planning.sig_connected) {
        banner.textContent = "SIG evidence needs a fresh sign-in (the server restarted). Assessments and explanations still work.";
        banner.hidden = false;
      }
      state.boundaries = areas.boundaries;
      state.floodLayers = layers.flood;
      state.centersVersion = layers.evacuation_centers[0] || null;
      $("[data-vulnerability-note]").textContent = layers.vulnerability.message;
      drawLegend(layers.flood_legend);
      drawDistricts();
      await Promise.all([loadFloodOverlay(state.floodLayers[0]), drawPendingCenters()]);
      // Synthetic fixtures remain available from Layers for demonstration, but never define
      // the default map or analysis area for a real person.
      districtLayer.remove();
      centersLayer.remove();
      renderWelcome();
      ownerEmail = identity.email;
      await restoreState();
      updateSend();
      input.focus();
    })
    .catch((error) => {
      if (error.status === 401 || error.status === 403) {
        window.location.replace("/");
        return;
      }
      addMessage("assistant", error.message, { error: true });
    });
})();
