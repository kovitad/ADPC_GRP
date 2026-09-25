(() => {
  const $ = (selector) => document.querySelector(selector);
  const STATUS_TEXT = {
    not_assessed: "Not assessed yet",
    potentially_exposed: "Potentially exposed under this scenario",
    not_exposed_under_scenario: "Lower mapped flood exposure",
    // Shown as N/A: the stored status stays unable_to_assess, which is the method's approved value
    // and the key the API and golden cases use. Only the wording a planner reads changes.
    unable_to_assess: "N/A",
  };
  const STATUS_COLOR = {
    not_assessed: "#64748b",
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
  const requestedAssessmentId = new URLSearchParams(window.location.search).get("assessment_id");

  const state = {
    hubCode: null,
    chatAvailable: false,
    boundaries: [],
    selected: null,
    explicitSelection: false,
    currentPlace: null,
    floodLayers: [],
    floodScenarios: [],
    centerVersions: [],
    supportingLayers: [],
    vulnerabilityLayers: [],
    localContext: null,
    // The selected area's GRP figures, fetched once and reused by the popup and the People tab.
    // null means "loading or none for this area"; undefined means "not asked for yet".
    areaProfile: null,
    // Which area areaProfile belongs to, so a first selection is not mistaken for a cached one.
    areaProfileId: null,
    // idle | loading | ready | none | error. The People tab renders from this rather than from
    // whatever the last caller happened to pass, so it cannot contradict itself (backlog U1).
    areaProfileState: "idle",
    // Population returned by the current SIG evidence pack, shown beside GRP's, never instead.
    sigPopulation: null,
    sigPopulationSource: "",
    // SIG answers already obtained this session, keyed by place. A SIG lookup costs minutes, so
    // re-selecting a district offers the answer we already have instead of asking to run it again.
    sigAnswers: new Map(),
    areaLevel: "district",
    centersVersion: null,
    methods: [],
    centerRows: [],
    centerSource: null,
    activeCenterId: null,
    assessmentId: null,
    assessmentBoundaryId: null,
    pendingAssessmentId: null,
    sigConnected: false,
    pollTimer: null,
    busy: false,
    runBusy: false,
    history: [],
  };

  // ---------- keep the conversation when moving between menu pages ----------
  // Stored only in this browser tab (sessionStorage): gone when the tab closes or on sign-out.
  // v5 discards tab state created before centre sources and assessment rows shared one district scope.
  const STORE_KEY = "grp.planning.v5";
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
  const supportingMapLayers = new Map();
  const supportingCollections = new Map();
  const vulnerabilityMapLayers = new Map();
  // ADR-0030: explicit panes, because image overlays and vectors otherwise share overlayPane and
  // stack by insertion order, which would let the district mask dim the flood layer and the pins.
  map.createPane("grpSensitivity").style.zIndex = "350";
  map.createPane("grpSensitivityMask").style.zIndex = "380";
  map.getPane("grpSensitivityMask").style.pointerEvents = "none";
  let sensitivityMask = null;
  const centerRenderer = window.L.canvas({ padding: 0.35 });
  const centerMarkers = new Map();
  let centerFilter = "all";
  let centerLoadRevision = 0;
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

  // The assistant speaks for Global Risk, so its avatar is a globe rather than the letters "AI".
  const SVG_NS = "http://www.w3.org/2000/svg";
  const globeIcon = () => {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    [
      ["circle", { cx: "12", cy: "12", r: "9" }],
      ["ellipse", { cx: "12", cy: "12", rx: "4", ry: "9" }],
      ["path", { d: "M3 12h18M4.6 7.5h14.8M4.6 16.5h14.8" }],
    ].forEach(([tag, attributes]) => {
      const shape = document.createElementNS(SVG_NS, tag);
      Object.entries(attributes).forEach(([name, value]) => shape.setAttribute(name, value));
      svg.append(shape);
    });
    return svg;
  };
  const globeAvatar = () => {
    const avatar = document.createElement("span");
    avatar.className = "pw-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.append(globeIcon());
    return avatar;
  };

  const addMessage = (role, text, { label, actions = [], error = false, record = true, confirmation = null } = {}) => {
    hideWelcome();
    if (record && !restoring) {
      transcript.push({ kind: "message", role, text, label: label || null, error, confirmation });
      saveState();
    }
    const row = document.createElement("div");
    row.className = `pw-msg pw-msg--${role}${error ? " pw-msg--error" : ""}`;
    if (role === "assistant") row.append(globeAvatar());
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
    const packId = String((payload.evidence && payload.evidence.pack_id) || "");
    if (payload.receipt && packId) {
      const prior = Array.from(thread.children).find(
        (node) => node.dataset.packId === packId && node.dataset.receipt === "no",
      );
      if (prior) prior.remove();
    }
    if (!restoring) {
      const priorIndex = payload.receipt && packId
        ? transcript.findIndex((entry) => entry.kind === "evidence"
          && entry.payload.evidence.pack_id === packId && !entry.payload.receipt)
        : -1;
      if (priorIndex >= 0) transcript.splice(priorIndex, 1);
      transcript.push({ kind: "evidence", payload, question });
      saveState();
    }
    const row = addMessage("assistant", "", {
      label: payload.label,
      record: false,
      actions: [chipButton(payload.map_url ? "Open summary, map & evidence" : "Open planning summary", () => renderEvidence(payload, question))],
    });
    const bubble = row.querySelector(".pw-bubble");
    row.dataset.packId = packId;
    row.dataset.receipt = payload.receipt ? "yes" : "no";
    bubble.classList.add("pw-bubble--evidence");
    bubble.prepend(statusCard(payload, question));
    if (payload.answer && payload.answer.trim()) {
      const brief = document.createElement("details");
      brief.className = "pw-brief";
      brief.open = payload.answer_source === "deterministic_fallback";
      const summary = document.createElement("summary");
      summary.textContent = payload.answer_source === "deterministic_fallback"
        ? "Key findings from Global Risk evidence"
        : "Read the brief";
      const text = renderBrief(payload.answer, (n) => {
        renderEvidence(payload, question);
        focusCitation(n);
      });
      brief.append(summary, text);
      bubble.querySelector(".pw-bubble__label").before(brief);
    }
    if (restoring && !state.sigConnected) {
      const restored = document.createElement("p");
      restored.className = "pw-draft-warning";
      restored.textContent =
        "Restored from your conversation. Global Risk is disconnected: you can keep asking about this area while its evidence is under an hour old, but sign in again to gather it anew.";
      bubble.querySelector(".pw-bubble__label").before(restored);
    }
    scrollDown();
  };

  const STEP_LABELS = {
    understand_question: "Understood the question",
    assemble_pack: "Gathered Global Risk flood evidence",
    assemble_pack_reused: "Reused Global Risk evidence",
    grp_baseline_evidence: "Added GRP figures",
    draft: "Wrote the brief",
    publish_answer: "Global Risk source check and receipt",
    hazard_map: "Loaded Global Risk flood map",
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
    const steps = publish
      ? [
          { label: "Checking the exact brief you reviewed", after: 0 },
          { label: "Creating the public receipt if Global Risk accepts it", after: 5000 },
          { label: "Loading Global Risk's receipt-bound hazard map", after: 12000 },
        ]
      : [
          { label: "Understanding your question", after: 0 },
          { label: "Finding the district and flood evidence on Global Risk (usually 20–90 s)", after: 4000 },
          { label: "Checking Global Risk used the real district boundary", after: 30000 },
          { label: "Writing the brief from the evidence", after: 45000 },
        ];
    const row = document.createElement("div");
    row.className = "pw-msg pw-msg--assistant";
    const avatar = globeAvatar();
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
      if (!line || /^#{1,6}\s*$/.test(line)) return;
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
    if (!box.childNodes.length) {
      const fallback = document.createElement("p");
      fallback.textContent = "No formatted brief was returned. Review the evidence cards instead.";
      box.append(fallback);
    }
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
    const text = usage.status === "active"
      ? `${GRP.tokens(usage.tokens_remaining)} tokens left`
      : usage.status === "limit_reached"
        ? "Limit reached"
        : "Off";
    // A globe, like the assistant's avatar, instead of the word "AI"; the spoken label keeps it.
    pill.replaceChildren(globeIcon(), document.createTextNode(text));
    pill.setAttribute("aria-label", `AI allowance: ${text}`);
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
    welcome.querySelector("h2").textContent = "Explore the available flood information";
    const intro = welcome.querySelector("p");
    intro.textContent =
      "District boundaries, the available RP100 flood layer and evacuation-centre locations are " +
      "shown immediately. Ask in your own words for Global Risk flood, risk or population information.";
    const box = $("[data-suggestions]");
    box.replaceChildren();
    [
      area
        ? ["Show information for this district", `Flood, centres and Global Risk evidence for ${area}`,
          `Show the available flood and population information for ${area}.`]
        : ["Use my current district", "Find your Thailand district before asking Global Risk",
          null],
      ["Explain what the map shows", "Use the visible layers and their sources",
        "Explain the flood and evacuation-centre data shown on the map."],
      ["Check Global Risk flood exposure", "Schools, hospitals and roads for a Thailand district",
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
    coming.replaceChildren();
    const strong = document.createElement("strong");
    strong.textContent = "Available data: ";
    coming.append(
      strong,
      document.createTextNode(
        "Thailand district boundaries, RP100 flood depth, evacuation-centre locations, and Global Risk " +
          "hazard, risk and population values when Global Risk returns them.",
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
      layer.on("click", (event) => {
        window.L.DomEvent.stop(event);
        selectBoundary(boundary, { announce: true });
        showAreaProfile(boundary, layer);
      });
      districtLayer.addLayer(layer);
    });
  };

  const canonicalSigPlace = (boundary) => {
    // The country comes from the boundary delivery, matching api/planning.py. With none recorded
    // the short label is sent unchanged and the exact-area gate decides, as it does server side.
    const country = String(boundary.country_name || "").trim();
    if (!country) return String(boundary.name || "").trim();
    let name = String(boundary.name || "").trim();
    if (boundary.admin_level === "district" && !/district/i.test(name)) name += " District";
    if (boundary.admin_level === "subdistrict" && !/subdistrict/i.test(name)) name += " Subdistrict";
    return [name, boundary.province_name, country].filter(Boolean).join(", ");
  };

  // ---------- area profile popup ----------
  const areaProfiles = new Map();

  const numberText = (value) =>
    value === null || value === undefined ? "unknown" : Number(value).toLocaleString();

  const areaProfileHtml = (boundary, profile) => {
    const levelLabel = boundary.admin_level === "subdistrict" ? "Sub-district" : "District";
    const title = [boundary.name, boundary.name_th].filter(Boolean).join(" · ");
    const province = [boundary.province_name, boundary.province_name_th]
      .filter(Boolean)
      .join(" · ");
    const head =
      `<strong>${title}</strong><br><span class="pw-area-pop__level">${levelLabel}` +
      (province ? ` · ${province}` : "") +
      `</span>`;
    // Recorded evacuation centres by kind of place. Shown even when population is missing,
    // because the two come from different deliveries and either can be absent alone.
    const centers = profile && profile.evacuation_centers;
    const centerRows =
      centers && centers.total
        ? `<p class="pw-area-pop__level">Recorded evacuation centres: ` +
          `${numberText(centers.total)}</p>` +
          `<table class="pw-area-pop__table"><tbody>` +
          centers.by_type
            .map(
              (item) =>
                `<tr><th scope="row">${item.label}</th><td>${numberText(item.count)}</td></tr>`,
            )
            .join("") +
          `</tbody></table>` +
          `<p class="pw-area-pop__caveat">${centers.caveat || ""}</p>`
        : centers
          ? `<p class="pw-area-pop__none">No evacuation centres are recorded for this area.</p>`
          : "";
    // People inside the modelled flood extent. Absent means the exposure job has not run for
    // these dataset versions, which is not the same as nobody being exposed, so nothing is shown.
    const exposure = profile && profile.flood_exposure;
    const exposureRows = exposure
      ? `<p class="pw-area-pop__level">Inside the RP` +
        `${numberText(exposure.return_period_years)} modelled flood extent</p>` +
        `<table class="pw-area-pop__table"><tbody>` +
        `<tr><th scope="row">Villages</th><td>${numberText(exposure.villages_in_zone)}</td></tr>` +
        `<tr><th scope="row">People</th><td>${numberText(exposure.people_in_zone)}</td></tr>` +
        `<tr><th scope="row">Households</th>` +
        `<td>${numberText(exposure.households_in_zone)}</td></tr>` +
        `</tbody></table>` +
        (exposure.no_data_village_count
          ? `<p class="pw-area-pop__note">${numberText(exposure.no_data_village_count)} ` +
            `village(s) carry no modelled depth: dry, or outside the layer. Not confirmed ` +
            `safe.</p>`
          : "") +
        (exposure.villages_in_zone_without_population
          ? `<p class="pw-area-pop__note">` +
            `${numberText(exposure.villages_in_zone_without_population)} village(s) inside the ` +
            `extent have no usable population figure, so People is an undercount.</p>`
          : "") +
        `<p class="pw-area-pop__caveat">${exposure.caveat || ""}</p>`
      : "";
    // A headline the popup can always show without covering the map. Everything else folds away:
    // three stacked tables made the popup taller than the viewport on a district click.
    const headline = [];
    if (profile && profile.population) {
      headline.push(`${numberText(profile.population.total_population)} people`);
      headline.push(`${numberText(profile.population.village_count)} villages`);
    }
    if (exposure) {
      headline.push(`${numberText(exposure.people_in_zone)} in the RP`
        + `${numberText(exposure.return_period_years)} extent`);
    }
    if (centers && centers.total) {
      headline.push(`${numberText(centers.total)} centres`);
    }
    const headlineRow = headline.length
      ? `<p class="pw-area-pop__headline">${headline.join(" · ")}</p>`
      : "";
    const fold = (body) => (body
      ? `<details class="pw-area-pop__more"><summary>Detail and caveats</summary>${body}</details>`
      : "");
    const tail = `<p class="pw-area-pop__foot">Full figures stay in the People tab.</p>`;
    if (!profile || !profile.population) {
      return (
        `<div class="pw-area-pop">${head}${headlineRow}` +
        `<p class="pw-area-pop__none">No population record for this area.</p>` +
        `${fold(`${exposureRows}${centerRows}`)}${tail}</div>`
      );
    }
    const p = profile.population;
    const source = profile.source || {};
    const rows = [
      ["Villages", numberText(p.village_count)],
      ["People", numberText(p.total_population)],
      ["Male", numberText(p.male)],
      ["Female", numberText(p.female)],
      ["Households", numberText(p.households)],
    ]
      .map(
        ([label, value]) =>
          `<tr><th scope="row">${label}</th><td>${value}</td></tr>`,
      )
      .join("");
    const excluded = Number(p.excluded_village_count || 0);
    const note = excluded
      ? `<p class="pw-area-pop__note">${numberText(excluded)} village(s) excluded: the source ` +
        `figures do not add up or are implausible.</p>`
      : "";
    const detail =
      `<table class="pw-area-pop__table"><tbody>${rows}</tbody></table>${note}` +
      `<p class="pw-area-pop__caveat">${source.label || "Registered village population"}` +
      (source.edition ? ` · edition ${source.edition}` : "") +
      `. ${source.caveat || ""}</p>${exposureRows}${centerRows}`;
    return `<div class="pw-area-pop">${head}${headlineRow}${fold(detail)}${tail}</div>`;
  };

  const profileHasFigures = (profile) => Boolean(
    profile && (profile.population || profile.flood_exposure
      || (profile.evacuation_centers && profile.evacuation_centers.total)),
  );

  // Fetched once per area and reused by the popup and the People tab. Idempotent and safe to call
  // from every panel render: a cached area resolves without a request but still re-renders, which
  // is what stopped the tab reverting to the raster page on a later render (backlog U1).
  const ensureAreaProfile = async (boundary) => {
    if (!boundary) return null;
    const cached = areaProfiles.get(boundary.id);
    const mine = () => state.selected && state.selected.id === boundary.id;
    if (cached !== undefined) {
      if (mine()) {
        state.areaProfile = cached;
        state.areaProfileId = boundary.id;
        state.areaProfileState = cached === null
          ? "error"
          : profileHasFigures(cached) ? "ready" : "none";
        renderVulnerablePeople();
      }
      return cached;
    }
    if (mine()) {
      state.areaProfileId = boundary.id;
      state.areaProfileState = "loading";
      state.areaProfile = null;
      renderVulnerablePeople();
    }
    let profile = null;
    try {
      profile = await GRP.request(`/api/v1/catalog/areas/${boundary.id}/profile`);
    } catch (error) {
      profile = null;
    }
    areaProfiles.set(boundary.id, profile);
    if (mine()) {
      state.areaProfile = profile;
      state.areaProfileState = profile === null
        ? "error"
        : profileHasFigures(profile) ? "ready" : "none";
      renderVulnerablePeople();
    }
    return profile;
  };

  const showAreaProfile = async (boundary, layer) => {
    layer
      .bindPopup(`<div class="pw-area-pop"><strong>${boundary.name}</strong><br>Loading…</div>`)
      .openPopup();
    layer.setPopupContent(areaProfileHtml(boundary, await ensureAreaProfile(boundary)));
  };

  const selectBoundary = (
    boundary,
    { announce = false, explicit = announce, preserveAssessment = false } = {},
  ) => {
    const changed = Boolean(state.selected && state.selected.id !== boundary.id);
    if (changed && !preserveAssessment) {
      state.assessmentId = null;
      state.assessmentBoundaryId = null;
      const url = new URL(window.location.href);
      url.searchParams.delete("assessment_id");
      window.history.replaceState({}, "", url);
      resultCard.hidden = true;
    }
    state.selected = boundary;
    state.explicitSelection = explicit;
    if (state.areaProfileId !== boundary.id) {
      // Clear first so the People tab cannot show the previous area's numbers, then fill. SIG's
      // population belongs to the answer for the previous area, so it goes too.
      state.areaProfile = null;
      state.areaProfileState = "loading";
      state.areaProfileId = boundary.id;
      state.sigPopulation = null;
      state.sigPopulationSource = "";
    }
    ensureAreaProfile(boundary);
    if (
      !state.centersVersion
      || Boolean(state.centersVersion.synthetic) !== Boolean(boundary.synthetic)
    ) {
      state.centersVersion = state.centerVersions.find(
        (version) => Boolean(version.synthetic) === Boolean(boundary.synthetic) && version.is_current,
      ) || state.centerVersions.find(
        (version) => Boolean(version.synthetic) === Boolean(boundary.synthetic),
      ) || null;
    }
    if (explicit) {
      const districtToggle = $('[data-layer="districts"]');
      const centersToggle = $('[data-layer="centers"]');
      districtToggle.checked = centersToggle.checked = true;
      districtLayer.addTo(map);
      centersLayer.addTo(map);
    }
    placeLayer.clearLayers();
    $("[data-place-chip]").hidden = true;
    districtLayer.eachLayer((layer) => layer.setStyle(boundaryStyle(layer.boundaryId === boundary.id)));
    syncSensitivityView();
    const layer = districtLayer.getLayers().find((item) => item.boundaryId === boundary.id);
    if (layer) map.flyToBounds(layer.getBounds(), { padding: [60, 60], duration: 0.6 });
    renderContext();
    renderWelcome();
    saveState();
    if (!preserveAssessment && (!state.assessmentId || changed)) {
      drawPendingCenters({ openPanel: announce }).catch((error) => {
        addMessage("assistant", error.message, { error: true });
      });
    }
    if (announce && !state.busy) {
      // Name what the planner gets, not the system it comes from. "Show SIG information" described
      // a call; these describe an answer, and the first two need no SIG lookup at all.
      const place = canonicalSigPlace(boundary);
      const askSig = (question) => () => send(question, { confirmedPlace: place });
      addMessage(
        "assistant",
        `${boundary.name} is selected. Its flood and evacuation-centre layers are on the map, and `
        + "its population and centre counts are in the People tab. Ask a question, or pick one:",
        {
          actions: [
            chipButton("How many people live here?", askSig(
              `How many people live in ${place}, and how many are inside the flood extent?`,
            )),
            chipButton("What evacuation centres are here?", askSig(
              `What evacuation centres are recorded in ${place}, and what kind of places are they?`,
            )),
            chipButton("What does Global Risk add?", askSig(
              `Show the available Global Risk flood, risk and population information for ${place}.`,
            )),
          ],
        },
      );
    }
    syncRunPanel();
  };

  // ---------- resizable assistant panel ----------
  // The chat was a fixed 360-440px. A planner reading a long brief wants it wider; one studying the
  // map wants it out of the way. Drag or arrow-key the divider; the width is remembered per browser.
  const CHAT_WIDTH_KEY = "grp.planning.chatWidth";
  const shell = document.querySelector(".pw-shell");

  const setChatWidth = (px, { remember = true } = {}) => {
    const width = Math.round(Math.min(Math.max(px, 300), window.innerWidth * 0.6));
    shell.style.setProperty("--pw-chat-width", `${width}px`);
    if (remember) {
      try {
        window.localStorage.setItem(CHAT_WIDTH_KEY, String(width));
      } catch (error) {
        // A browser with storage blocked still resizes; it just will not remember.
      }
    }
    // Leaflet measures its container once, so it must be told the viewport changed.
    if (map) map.invalidateSize();
  };

  const initChatResize = () => {
    const handle = $("[data-chat-resize]");
    if (!handle || !shell) return;
    try {
      const saved = Number(window.localStorage.getItem(CHAT_WIDTH_KEY));
      if (saved) setChatWidth(saved, { remember: false });
    } catch (error) {
      // No stored width: the CSS default applies.
    }
    const onMove = (event) => setChatWidth(event.clientX - shell.getBoundingClientRect().left);
    const stop = () => {
      document.body.classList.remove("is-resizing");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", stop);
    };
    handle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      document.body.classList.add("is-resizing");
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", stop);
    });
    handle.addEventListener("keydown", (event) => {
      const step = { ArrowLeft: -32, ArrowRight: 32 }[event.key];
      if (!step) return;
      event.preventDefault();
      setChatWidth(document.querySelector(".pw-chat").getBoundingClientRect().width + step);
    });
    handle.addEventListener("dblclick", () => setChatWidth(400));
  };

  const selectedFloodLayer = () => {
    const selectedId = $("[data-flood-scenario]").value;
    return state.floodLayers.find((layer) => layer.id === selectedId) || null;
  };

  // Show the same return period the assessment was run against, so the depth on the map and the
  // numbers in the panel describe one scenario (backlog U5). Silent when that scenario is not
  // imported: the locked result stays valid either way.
  const alignFloodScenario = (returnPeriodYears) => {
    const scenario = state.floodScenarios.find(
      (item) => item.return_period_years === returnPeriodYears && item.available,
    );
    if (!scenario) return false;
    const select = $("[data-flood-scenario]");
    if (select.value === scenario.layer_id) return true;
    select.value = scenario.layer_id;
    loadFloodOverlay(selectedFloodLayer());
    return true;
  };

  // The assessment's area may not be in the list currently loaded: the level selector may be on
  // districts while the result is for a sub-district, or the other way round. Look in memory, then
  // fetch that one area, switching the level list so the outline can actually be drawn.
  const resolveAssessmentArea = async (detail) => {
    if (!detail || !detail.id) return null;
    const known = state.boundaries.find((item) => item.id === detail.id);
    if (known) return known;
    const level = detail.admin_level === "subdistrict" ? "subdistrict" : "district";
    const params = new URLSearchParams({ hub_code: state.hubCode, level });
    if (level === "subdistrict") {
      params.set("parent_admin_code", String(detail.admin_code).slice(0, 4));
    }
    try {
      const payload = await GRP.request(`/api/v1/catalog/boundaries?${params}`);
      const found = payload.boundaries.find((item) => item.id === detail.id);
      if (!found) return null;
      // Replace the visible list so the level selector, the map and the panel agree.
      state.areaLevel = level;
      state.boundaries = payload.boundaries;
      const levelSelect = $("[data-area-level]");
      if (levelSelect) levelSelect.value = level;
      drawDistricts();
      return found;
    } catch (error) {
      return null;
    }
  };

  const configureFloodScenarios = (scenarios) => {
    state.floodScenarios = scenarios || [];
    const select = $("[data-flood-scenario]");
    select.replaceChildren();
    state.floodScenarios.forEach((scenario) => {
      const option = document.createElement("option");
      option.value = scenario.layer_id || `rp-${scenario.return_period_years}`;
      option.textContent = `${scenario.label} · ${scenario.available ? "available" : "not imported"}`;
      option.disabled = !scenario.available;
      select.append(option);
    });
    const preferred = state.floodScenarios.find((scenario) => scenario.return_period_years === 100 && scenario.available)
      || state.floodScenarios.find((scenario) => scenario.available);
    select.disabled = !preferred;
    if (preferred) select.value = preferred.layer_id;
    $("[data-flood-scenario-note]").textContent = preferred
      ? "Choose a return period, then check Flood depth to draw it. RP20 and RP50 stay disabled until their source versions are imported."
      : "No flood-depth scenario has been imported.";
  };

  const loadFloodOverlay = async (layer) => {
    if (floodOverlay) floodOverlay.remove();
    floodOverlay = null;
    if (!layer || layer.available === false || !layer.bounds) return;
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

  const statusDetail = (center) => {
    // A bare "N/A" under a centre's name read as a broken record to planners. The grey pin, the
    // legend, the filter and the result summary already mark these centres as N/A,
    // so the row and popup say nothing about it rather than repeat it on every one.
    const lines = center.status === "unable_to_assess"
      ? []
      : [STATUS_TEXT[center.status] || center.status];
    if (center.flood_depth_m !== null && center.flood_depth_m !== undefined) {
      lines.push(`Mapped flood depth ${center.flood_depth_m} m`);
    }
    // The method's reason text spells out why a centre has no depth. On a map pin, where most
    // centres in a district share the same reason, repeating it on every one is noise. Kept for
    // the two statuses where it adds something.
    if (center.reason_meaning && center.status !== "unable_to_assess") {
      lines.push(center.reason_meaning);
    }
    if (center.capacity !== null && center.capacity !== undefined) {
      lines.push(`Reported capacity ${Number(center.capacity).toLocaleString()} people`);
    }
    if (center.supporting_unit) lines.push(`Supporting unit ${center.supporting_unit}`);
    if (center.village) lines.push(`Village ${center.village}`);
    if (center.subdistrict) lines.push(`Sub-district ${center.subdistrict}`);
    return lines;
  };

  const activateCenter = (featureId, { moveMap = true } = {}) => {
    state.activeCenterId = featureId;
    const center = state.centerRows.find((item) => item.feature_id === featureId);
    const marker = centerMarkers.get(featureId);
    if (moveMap && center && marker) {
      map.flyTo([center.lat, center.lon], Math.max(map.getZoom(), 15), { duration: 0.45 });
      marker.openPopup();
    }
    const rows = Array.from($("[data-centre-list]").children);
    rows.forEach((row) => row.classList.toggle("is-active", row.dataset.featureId === featureId));
    const active = rows.find((row) => row.dataset.featureId === featureId);
    if (active) active.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  // An answer that names centres should be able to point at them. The server resolves the model's
  // reference markers against the ids it issued and returns that list, so this is an exact id
  // lookup rather than the name matching it replaced: a truncated or reworded name no longer
  // breaks the link, and a reference GRP did not issue never arrives here at all.
  const centresNamedIn = (payload) => {
    const ids = payload && payload.focus && Array.isArray(payload.focus.centers)
      ? payload.focus.centers
      : [];
    if (!ids.length) return [];
    const byId = new Map(state.centerRows.map((center) => [center.feature_id, center]));
    return ids.map((id) => byId.get(id)).filter(Boolean);
  };

  const showCentresOnMap = (centres) => {
    if (!centres.length) return;
    centersLayer.addTo(map);
    $('[data-layer="centers"]').checked = true;
    const points = centres
      .filter((center) => typeof center.lat === "number" && typeof center.lon === "number")
      .map((center) => [center.lat, center.lon]);
    if (points.length === 1) {
      activateCenter(centres[0].feature_id);
      return;
    }
    if (points.length) {
      map.fitBounds(window.L.latLngBounds(points), { padding: [50, 50], maxZoom: 14 });
    }
    // Flag them in the centre list too, so the panel and the map agree on what is being discussed.
    const named = new Set(centres.map((center) => center.feature_id));
    Array.from($("[data-centre-list]").children).forEach((row) => {
      row.classList.toggle("is-named", named.has(row.dataset.featureId));
    });
    document.body.dataset.view = window.matchMedia("(max-width: 860px)").matches
      ? "map"
      : document.body.dataset.view;
  };

  const renderCenterList = () => {
    const query = $("[data-centre-search]").value.trim().toLocaleLowerCase();
    const visible = state.centerRows.filter((center) =>
      (centerFilter === "all" || center.status === centerFilter)
      && (!query || center.name.toLocaleLowerCase().includes(query)),
    );
    $("[data-centre-count]").textContent = state.centerRows.length
      ? `(${state.centerRows.length.toLocaleString()})`
      : "";
    $("[data-centre-list-count]").textContent = state.centerRows.length
      ? `Showing ${visible.length.toLocaleString()} of ${state.centerRows.length.toLocaleString()} centre records.`
      : "No centre records are available for this district.";
    const list = $("[data-centre-list]");
    list.replaceChildren(...visible.map((center) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "pw-centre-row";
      row.dataset.featureId = center.feature_id;
      row.classList.toggle("is-active", state.activeCenterId === center.feature_id);
      const dot = document.createElement("span");
      dot.className = "pw-centre-row__dot";
      dot.style.background = STATUS_COLOR[center.status] || STATUS_COLOR.not_assessed;
      const text = document.createElement("span");
      text.className = "pw-centre-row__text";
      const name = document.createElement("strong");
      const detail = document.createElement("span");
      name.textContent = center.name;
      detail.textContent = statusDetail(center).join(" · ");
      text.append(name);
      if (detail.textContent) text.append(detail);
      const view = document.createElement("span");
      view.className = "pw-centre-row__view";
      view.textContent = "View";
      row.append(dot, text, view);
      row.addEventListener("click", () => activateCenter(center.feature_id));
      return row;
    }));
  };

  const setCenterRows = (rows, source) => {
    state.centerRows = rows;
    state.centerSource = source;
    state.activeCenterId = null;
    $("[data-centre-intro]").textContent = rows.length
      ? "Select a row to locate the same centre on the map. Repeated names are kept as separate source records."
      : "No evacuation-centre records were returned for this district.";
    $("[data-centre-source]").textContent = source || "";
    renderCenterList();
  };

  const drawCenterMarkers = (centers) => {
    centersLayer.clearLayers();
    centerMarkers.clear();
    centers.forEach((center) => {
      const assessed = center.status !== "not_assessed";
      const marker = window.L.circleMarker([center.lat, center.lon], {
        renderer: assessed ? undefined : centerRenderer,
        radius: assessed ? 8 : 5,
        color: assessed ? "#fff" : "#374151",
        weight: assessed ? 2 : 1,
        fillColor: assessed ? STATUS_COLOR[center.status] : "#fff",
        fillOpacity: 0.95,
      })
        .bindPopup(popup(center.name, statusDetail(center)))
        .on("click", () => activateCenter(center.feature_id, { moveMap: false }))
        .addTo(centersLayer);
      centerMarkers.set(center.feature_id, marker);
    });
  };

  const drawPendingCenters = async ({ openPanel = false } = {}) => {
    const revision = ++centerLoadRevision;
    if (!state.centersVersion || !state.selected) {
      drawCenterMarkers([]);
      setCenterRows([], "Select a supported district to load its managed source records.");
      return;
    }
    const url = new URL(state.centersVersion.features_url, window.location.origin);
    url.searchParams.set("boundary_id", state.selected.id);
    if (state.hubCode) url.searchParams.set("hub_code", state.hubCode);
    const collection = await GRP.request(`${url.pathname}${url.search}`);
    if (revision !== centerLoadRevision || state.selected?.id !== collection.boundary?.id) return;
    const centers = collection.features.map((feature) => {
      const [lon, lat] = feature.geometry.coordinates;
      return {
        feature_id: feature.properties.feature_id || feature.id,
        name: feature.properties.name,
        lon,
        lat,
        status: "not_assessed",
        reason_code: null,
        reason_meaning: null,
        flood_depth_m: null,
        capacity: feature.properties.capacity,
        supporting_unit: feature.properties.supporting_unit,
        subdistrict: feature.properties.subdistrict,
        village: feature.properties.village,
      };
    });
    setCenterRows(
      centers,
      `${collection.source.title} · ${collection.source.provider} · ${collection.boundary.name}`,
    );
    drawCenterMarkers(centers);
    await loadLocalContext(state.selected.id);
    await enableRecommendedSupportingLayers();
    renderSourceSummary(collection);
    if (openPanel) document.querySelector('[data-ev-tab="centres"]').click();
  };

  const supportingColour = (role) => ({
    volunteer_centers: "#7c3aed",
    early_warning_resources: "#d97706",
    village_locations: "#475569",
  }[role] || "#475569");

  const loadSupportingLayer = async (source) => {
    let group = supportingMapLayers.get(source.version_id);
    if (!group) {
      group = window.L.featureGroup();
      supportingMapLayers.set(source.version_id, group);
    }
    group.clearLayers();
    if (!state.selected) return;
    const collection = await getSupportingCollection(source, state.selected.id);
    collection.features.forEach((feature) => {
      const [lon, lat] = feature.geometry.coordinates;
      const properties = feature.properties;
      window.L.circleMarker([lat, lon], {
        radius: source.role === "village_locations" ? 3 : 5,
        color: "#fff",
        weight: 1,
        fillColor: supportingColour(source.role),
        fillOpacity: 0.9,
      }).bindPopup(popup(properties.name, [source.title_th || source.title])).addTo(group);
    });
    const toggle = document.querySelector(`[data-supporting-version="${source.version_id}"]`);
    if (toggle?.checked) group.addTo(map);
  };

  const getSupportingCollection = async (source, boundaryId) => {
    const cacheKey = `${source.version_id}:${boundaryId}`;
    if (supportingCollections.has(cacheKey)) return supportingCollections.get(cacheKey);
    const url = new URL(source.features_url, window.location.origin);
    url.searchParams.set("boundary_id", boundaryId);
    url.searchParams.set("hub_code", state.hubCode);
    const collection = await GRP.request(`${url.pathname}${url.search}`);
    supportingCollections.set(cacheKey, collection);
    return collection;
  };

  const loadLocalContext = async (boundaryId) => {
    const supporting = await Promise.all(state.supportingLayers.map(async (source) => {
      try {
        const collection = await getSupportingCollection(source, boundaryId);
        return { ...source, count: collection.total };
      } catch (_error) {
        return { ...source, count: null };
      }
    }));
    state.localContext = {
      boundaryId,
      supporting,
      // A withheld indicator (ADR-0030) is not counted as available to the planner.
      vulnerability: state.vulnerabilityLayers.filter(
        (item) => item.available && item.planner_status !== "withheld",
      ),
    };
    return state.localContext;
  };

  const enableRecommendedSupportingLayers = async () => {
    const recommended = state.supportingLayers.filter(
      (source) => source.role === "volunteer_centers" || source.role === "early_warning_resources",
    );
    await Promise.all(recommended.map(async (source) => {
      const toggle = document.querySelector(`[data-supporting-version="${source.version_id}"]`);
      if (toggle) toggle.checked = true;
      try {
        await loadSupportingLayer(source);
      } catch (_error) {
        if (toggle) toggle.checked = false;
      }
    }));
  };

  const loadEnabledSupportingLayers = async () => {
    await Promise.all(state.supportingLayers.map(async (source) => {
      const toggle = document.querySelector(`[data-supporting-version="${source.version_id}"]`);
      if (toggle?.checked) await loadSupportingLayer(source);
    }));
  };

  const buildSupplementalLayerControls = () => {
    const supporting = $("[data-supporting-layer-controls]");
    supporting.replaceChildren();
    state.supportingLayers.forEach((source) => {
      const label = document.createElement("label");
      label.className = "pw-toggle";
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.dataset.supportingVersion = source.version_id;
      const title = document.createElement("span");
      title.textContent = `${source.title_th ? `${source.title_th} / ` : ""}${source.title}`;
      toggle.addEventListener("change", async () => {
        if (toggle.checked) await loadSupportingLayer(source);
        else supportingMapLayers.get(source.version_id)?.remove();
      });
      label.append(toggle, title);
      supporting.append(label);
    });

    const vulnerability = $("[data-vulnerability-layer-controls]");
    vulnerability.replaceChildren();
    state.vulnerabilityLayers.forEach((source) => {
      if (source.planner_status === "withheld") {
        const withheld = document.createElement("p");
        withheld.className = "pw-muted pw-withheld";
        withheld.textContent = `${source.title}: ${source.withheld_reason}`;
        vulnerability.append(withheld);
        return;
      }
      const label = document.createElement("label");
      label.className = "pw-toggle";
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.dataset.vulnerabilityVersion = source.version_id;
      const title = document.createElement("span");
      title.textContent = `${source.title_th ? `${source.title_th} / ` : ""}${source.title}`;
      toggle.addEventListener("change", async () => {
        let overlay = vulnerabilityMapLayers.get(source.version_id);
        if (toggle.checked && !overlay) {
          const response = await fetch(source.image_url, { credentials: "same-origin" });
          if (!response.ok) return;
          overlay = window.L.imageOverlay(URL.createObjectURL(await response.blob()), source.bounds, {
            opacity: 0.62,
            interactive: false,
            pane: "grpSensitivity",
          });
          vulnerabilityMapLayers.set(source.version_id, overlay);
        }
        if (toggle.checked) overlay?.addTo(map);
        else overlay?.remove();
        syncSensitivityView();
      });
      label.append(toggle, title);
      vulnerability.append(label);
    });
  };

  const sensitivityShown = () =>
    Array.from(vulnerabilityMapLayers.values()).some((overlay) => map.hasLayer(overlay));

  // Each outer ring of the selected area becomes a hole in a world-sized polygon, so everything
  // outside the district is dimmed and the relative pattern inside it reads on its own.
  const selectedRings = () => {
    if (!state.selected) return [];
    const layer = districtLayer.getLayers().find((item) => item.boundaryId === state.selected.id);
    if (!layer || typeof layer.getLatLngs !== "function") return [];
    const latlngs = layer.getLatLngs();
    const parts = window.L.LineUtil.isFlat(latlngs[0]) ? [latlngs] : latlngs;
    return parts.map((part) => part[0]).filter((ring) => ring && ring.length > 2);
  };

  const syncSensitivityView = () => {
    const shown = sensitivityShown();
    $("[data-sensitivity-legend]").hidden = !shown;
    if (sensitivityMask) {
      sensitivityMask.remove();
      sensitivityMask = null;
    }
    const rings = shown ? selectedRings() : [];
    if (!rings.length) return;
    const world = [[-89, -179.9], [-89, 179.9], [89, 179.9], [89, -179.9]];
    sensitivityMask = window.L.polygon([world, ...rings], {
      pane: "grpSensitivityMask",
      stroke: false,
      fillColor: "#f4f6f5",
      fillOpacity: 0.72,
      interactive: false,
    }).addTo(map);
  };

  $("[data-centre-search]").addEventListener("input", renderCenterList);
  document.querySelectorAll("[data-centre-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      centerFilter = button.dataset.centreFilter;
      document.querySelectorAll("[data-centre-filter]").forEach((item) => {
        item.setAttribute("aria-pressed", String(item === button));
      });
      renderCenterList();
    });
  });

  $("[data-flood-scenario]").addEventListener("change", async () => {
    await loadFloodOverlay(selectedFloodLayer());
    syncRunPanel();
  });

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

  $("[data-area-level]").addEventListener("change", async (event) => {
    const nextLevel = event.currentTarget.value;
    const priorDistrict = state.selected?.admin_level === "district" ? state.selected : null;
    if (nextLevel === "subdistrict" && !priorDistrict) {
      event.currentTarget.value = "district";
      addMessage("assistant", "Select a district first, then choose Sub-district in Layers.", { error: true });
      return;
    }
    const params = new URLSearchParams({ hub_code: state.hubCode, level: nextLevel });
    if (priorDistrict) params.set("parent_admin_code", priorDistrict.admin_code);
    const payload = await GRP.request(`/api/v1/catalog/boundaries?${params}`);
    state.areaLevel = nextLevel;
    state.boundaries = payload.boundaries;
    state.selected = null;
    // Nothing is selected at the new level, so the People tab must go back to its prompt rather
    // than keep the previous level's figures on screen (backlog U1).
    state.areaProfile = null;
    state.areaProfileId = null;
    state.areaProfileState = "idle";
    renderVulnerablePeople();
    drawDistricts();
    $("[data-boundary-layer-title]").textContent = nextLevel === "subdistrict"
      ? `Sub-district boundaries in ${priorDistrict.name}`
      : "District boundaries";
    $("[data-search-input]").placeholder = `Search a ${nextLevel === "subdistrict" ? "sub-district" : "district"} in Thailand`;
    if (districtLayer.getLayers().length) {
      map.fitBounds(districtLayer.getBounds(), { padding: [40, 40] });
    }
    syncRunPanel();
  });

  // ---------- configure and run ----------
  const runPanel = $("[data-run]");
  const runToggle = $("[data-run-toggle]");
  const runHazard = $("[data-run-hazard]");
  const runCenters = $("[data-run-centers]");
  const runSubmit = $("[data-run-submit]");

  const assessmentMethod = () =>
    state.methods.find((method) => method.status === "approved") || state.methods[0] || null;

  const centerVersionsForArea = () => state.centerVersions.filter((version) =>
    version.readiness === "assessment_ready"
    && (!state.selected || Boolean(version.synthetic) === Boolean(state.selected.synthetic))
  );

  const centerSourceKind = (version) => {
    if (version.synthetic) return "Synthetic demo";
    if (version.source_mode === "browser_upload") return "Local upload";
    return "Platform baseline";
  };

  const centerSourceName = (version) => {
    if (version.source_mode === "browser_upload") {
      return version.original_filename || "Uploaded shelter dataset";
    }
    return version.title;
  };

  const centerSourceOption = (version) => [
    version.is_current ? "Recommended · Ready" : "Previous version · Ready",
    version.title_th ? `${version.title_th} / ${centerSourceName(version)}` : centerSourceName(version),
    `${Number(version.feature_count || 0).toLocaleString()} centres`,
    centerSourceKind(version),
    `v${version.version_id.slice(0, 8)}`,
  ].filter(Boolean).join(" · ");

  const setRunPanelOpen = (open) => {
    runPanel.hidden = !open;
    runToggle.setAttribute("aria-expanded", String(open));
    if (open) {
      $("[data-layers]").hidden = true;
      $("[data-layers-toggle]").setAttribute("aria-expanded", "false");
      syncRunPanel();
    }
  };

  const syncRunPanel = () => {
    $("[data-run-area]").textContent = state.selected
      ? `${state.selected.name}${state.selected.province_name ? ` · ${state.selected.province_name}` : ""}`
      : "Select a district on the map";

    const selectedHazardId = runHazard.value || $("[data-flood-scenario]").value;
    runHazard.replaceChildren();
    state.floodScenarios.forEach((scenario) => {
      const option = document.createElement("option");
      option.value = scenario.layer_id || `rp-${scenario.return_period_years}`;
      option.textContent = `${scenario.label} · ${scenario.available ? "available" : "not imported"}`;
      option.disabled = !scenario.available;
      runHazard.append(option);
    });
    const preferredHazard = [...runHazard.options].find((option) => option.value === selectedHazardId)
      || [...runHazard.options].find((option) => !option.disabled);
    if (preferredHazard) runHazard.value = preferredHazard.value;
    runHazard.disabled = !preferredHazard;

    const versions = centerVersionsForArea().sort(
      (left, right) => Number(right.is_current) - Number(left.is_current)
        || String(right.created_at).localeCompare(String(left.created_at)),
    );
    const selectedCenterId = runCenters.value || state.centersVersion?.version_id;
    runCenters.replaceChildren();
    [true, false].forEach((isCurrent) => {
      const matching = versions.filter((version) => Boolean(version.is_current) === isCurrent);
      if (!matching.length) return;
      const group = document.createElement("optgroup");
      group.label = isCurrent ? "Recommended dataset" : "Previous versions";
      matching.forEach((version) => {
        const option = document.createElement("option");
        option.value = version.version_id;
        option.textContent = centerSourceOption(version);
        group.append(option);
      });
      runCenters.append(group);
    });
    const preferredCenter = versions.find((version) => version.version_id === selectedCenterId)
      || versions.find((version) => version.is_current)
      || versions[0];
    if (preferredCenter) runCenters.value = preferredCenter.version_id;
    runCenters.disabled = !preferredCenter;
    const centerNote = $("[data-run-centers-note]");
    centerNote.textContent = preferredCenter
      ? `${centerSourceKind(preferredCenter)} selected · ${Number(preferredCenter.feature_count || 0).toLocaleString()} centres · version ${preferredCenter.version_id.slice(0, 8)}. The exact version will be saved with the result.${preferredCenter.shelter_names_confirmed === false ? " Centre labels are generated; source names are not confirmed." : ""}`
      : "No accepted shelter dataset matches this area. Ask a Platform Admin to select one in Data library.";
    centerNote.classList.toggle(
      "is-warning",
      Boolean(preferredCenter && preferredCenter.shelter_names_confirmed === false),
    );

    const method = assessmentMethod();
    $("[data-run-method]").textContent = method
      ? `${method.key} ${method.version}${method.status === "approved" ? " · approved" : " · draft"}`
      : "No method available";
    const ready = Boolean(state.selected && preferredHazard && preferredCenter && method);
    runSubmit.disabled = !ready || state.runBusy;
    if (!state.runBusy) {
      $("[data-run-status]").textContent = ready
        ? "Ready. The exact versions above will be saved with the result."
        : "Select a supported district and available inputs to begin.";
    }
  };

  const renderRunTrace = (payload) => {
    const section = $("[data-run-trace-section]");
    section.hidden = false;
    const badge = $("[data-run-state]");
    badge.textContent = payload.state;
    badge.className = payload.state === "succeeded"
      ? "is-complete"
      : ["failed", "cancelled"].includes(payload.state) ? "is-failed" : "";
    $("[data-run-reference]").textContent = `Support reference ${payload.support_ref}`;
    const list = $("[data-run-trace]");
    list.replaceChildren(...(payload.steps || []).map((step) => {
      const item = document.createElement("li");
      item.className = `pw-run-step is-${step.state}`;
      const mark = document.createElement("span");
      mark.className = "pw-run-step__mark";
      mark.textContent = step.state === "completed" ? "✓" : step.state === "failed" ? "!" : "";
      const text = document.createElement("div");
      const strong = document.createElement("strong");
      const detail = document.createElement("small");
      strong.textContent = step.label;
      detail.textContent = step.detail || (step.state === "queued" ? "Waiting" : "In progress");
      text.append(strong, detail);
      item.append(mark, text);
      return item;
    }));
  };

  const runAssessment = async () => {
    const hazard = state.floodLayers.find((layer) => layer.id === runHazard.value);
    const centerVersion = state.centerVersions.find(
      (version) => version.version_id === runCenters.value,
    );
    const method = assessmentMethod();
    if (!state.selected || !hazard || !centerVersion || !method || state.runBusy) return;
    state.runBusy = true;
    syncRunPanel();
    $("[data-run-status]").textContent = "Recording the request and pinning the selected data versions…";
    try {
      state.centersVersion = centerVersion;
      await drawPendingCenters();
      const started = await GRP.request("/api/v1/assessments", {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: {
          hub_code: state.hubCode,
          boundary_id: state.selected.id,
          hazard: {
            type: "flood",
            return_period_years: hazard.return_period_years,
            dataset_version_id: hazard.version_id,
          },
          evacuation_centers_dataset_version_id: centerVersion.version_id,
          vulnerability_dataset_version_id: null,
          method: { key: method.key, version: method.version },
        },
      });
      state.assessmentId = null;
      state.pendingAssessmentId = started.assessment_id;
      showProgress(state.selected.name);
      GRP.jobs.track({
        id: started.assessment_id,
        label: `Shelter screening for ${state.selected.name}`,
        statusPath: `/api/v1/assessments/${started.assessment_id}`,
        href: `/planning.html?assessment_id=${encodeURIComponent(started.assessment_id)}`,
        ownerPath: "/planning.html",
      });
      saveState();
      await watch(started.assessment_id);
    } catch (error) {
      state.runBusy = false;
      $("[data-run-status]").textContent = error.message;
      syncRunPanel();
      addMessage("assistant", error.message, { label: error.code, error: true });
    }
  };

  runToggle.addEventListener("click", () => setRunPanelOpen(runPanel.hidden));
  $("[data-run-close]").addEventListener("click", () => setRunPanelOpen(false));
  runHazard.addEventListener("change", async () => {
    $("[data-flood-scenario]").value = runHazard.value;
    await loadFloodOverlay(selectedFloodLayer());
    syncRunPanel();
  });
  runCenters.addEventListener("change", async () => {
    const chosen = state.centerVersions.find((version) => version.version_id === runCenters.value);
    if (!chosen) return;
    state.centersVersion = chosen;
    state.assessmentId = null;
    state.assessmentBoundaryId = null;
    resultCard.hidden = true;
    await drawPendingCenters();
    syncRunPanel();
  });
  runSubmit.addEventListener("click", runAssessment);

  // ---------- result card ----------
  const resultCard = $("[data-result]");
  $("[data-result-close]").addEventListener("click", () => {
    resultCard.hidden = true;
  });

  const showProgress = (title) => {
    resultCard.hidden = false;
    $("[data-synthetic]").hidden = true;
    $("[data-incompatible-result]").hidden = true;
    $("[data-result-title]").textContent = title;
    $("[data-result-meta]").textContent = "Screening evacuation centers in the background…";
    $("[data-progress]").hidden = false;
    $("[data-stats]").replaceChildren();
    $("[data-result-summary]").hidden = true;
    $("[data-result-context]").hidden = true;
    $("[data-result-link]").hidden = true;
  };

  const loadAssessmentCenters = async (id) => {
    const first = await GRP.request(`/api/v1/assessments/${id}/centers?size=1000`);
    const centers = [...first.centers];
    const pages = Math.ceil(first.total / first.size);
    for (let page = 2; page <= pages; page += 1) {
      const next = await GRP.request(
        `/api/v1/assessments/${id}/centers?size=1000&page=${page}`,
      );
      centers.push(...next.centers);
    }
    return { ...first, centers };
  };

  const showResult = async (id, { quiet = false } = {}) => {
    centerLoadRevision += 1;
    const [result, centers] = await Promise.all([
      GRP.request(`/api/v1/assessments/${id}/result`),
      loadAssessmentCenters(id),
    ]);
    const assessedCenters = centers.centers.map((center) => ({
      ...center,
      reason_meaning:
        (result.reason_codes[center.reason_code] || {}).meaning || center.reason_code || null,
    }));
    await loadLocalContext(result.area_detail.id);
    setCenterRows(
      assessedCenters,
      `Locked assessment ${result.support_ref} · ${result.area} · RP${result.scenario.return_period_years}`,
    );
    drawCenterMarkers(assessedCenters);
    $("[data-assessment-legend]").hidden = false;
    const centersToggle = $('[data-layer="centers"]');
    centersToggle.checked = true;
    centersLayer.addTo(map);
    if (result.map) {
      let matchingLayer = state.floodLayers.find(
        (layer) => layer.version_id === result.map.version_id,
      );
      if (!matchingLayer) {
        matchingLayer = {
          ...result.map,
          id: `assessment-${result.map.version_id}`,
          title: `Flood depth RP${result.map.return_period_years} · assessment input`,
          available: true,
        };
        state.floodLayers.push(matchingLayer);
      }
      const scenarioSelect = $("[data-flood-scenario]");
      if (![...scenarioSelect.options].some((option) => option.value === matchingLayer.id)) {
        const pinnedOption = document.createElement("option");
        pinnedOption.value = matchingLayer.id;
        pinnedOption.textContent = `RP${result.map.return_period_years} · pinned assessment input`;
        scenarioSelect.append(pinnedOption);
      }
      scenarioSelect.value = matchingLayer.id;
      const floodToggle = $('[data-layer="flood"]');
      floodToggle.checked = true;
      await loadFloodOverlay({ ...result.map, available: true });
    }
    resultCard.hidden = false;
    $("[data-progress]").hidden = true;
    $("[data-synthetic]").hidden = !result.synthetic;
    const incompatible = $("[data-incompatible-result]");
    incompatible.hidden = result.input_compatible !== false;
    incompatible.textContent = result.input_warning || "";
    $("[data-result-title]").textContent = `${result.area} · ${result.scenario.return_period_years}-year flood`;
    $("[data-result-meta]").textContent =
      `Method ${result.method.key} ${result.method.version}${result.method.status === "approved" ? "" : " (draft)"} · ref ${result.support_ref}`;
    const stats = $("[data-stats]");
    stats.replaceChildren();
    [
      ["", result.summary.in_scope, "Centers in area"],
      ["pw-stat--exposed", result.summary.potentially_exposed, "Potentially exposed"],
      ["pw-stat--not", result.summary.not_exposed_under_scenario, "Not exposed"],
      ["pw-stat--unable", result.summary.unable_to_assess, "N/A"],
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
    const summaryButton = $("[data-result-summary]");
    summaryButton.hidden = false;
    summaryButton.onclick = () => renderAssessmentSummary(result, assessedCenters);
    const resultLink = $("[data-result-link]");
    resultLink.href = `/assessments.html?assessment_id=${encodeURIComponent(id)}`;
    resultLink.hidden = false;
    const contextButton = $("[data-result-context]");
    contextButton.hidden = !state.chatAvailable;
    contextButton.onclick = () => {
      const boundary = state.boundaries.find((item) => item.id === result.area_detail.id);
      const place = boundary ? canonicalSigPlace(boundary) : [
        result.area,
        result.area_detail.province_name,
        "Thailand",
      ].filter(Boolean).join(", ");
      return send(
        `Show supporting Global Risk flood, population, schools, hospitals and roads information for ${place}.`,
        { confirmedPlace: place },
      );
    };
    state.assessmentId = id;
    state.assessmentBoundaryId = result.area_detail.id;
    state.pendingAssessmentId = null;
    const url = new URL(window.location.href);
    url.searchParams.set("assessment_id", id);
    window.history.replaceState({}, "", url);
    renderContext();
    const boundary = await resolveAssessmentArea(result.area_detail);
    if (boundary) {
      selectBoundary(boundary, { explicit: true, preserveAssessment: true });
      alignFloodScenario(result.scenario.return_period_years);
      await enableRecommendedSupportingLayers();
    } else {
      // Never leave a different district selected while the panel describes this result. Clearing
      // is worse than useless only if we say nothing, so say it (backlog U5).
      state.selected = null;
      state.explicitSelection = false;
      state.areaProfile = null;
      state.areaProfileId = null;
      state.areaProfileState = "idle";
      renderVulnerablePeople();
      drawDistricts();
      addMessage(
        "assistant",
        `This result is for ${result.area}, which is not in the area list currently loaded, so its `
        + "outline is not on the map. The locked numbers below are unaffected.",
        { label: "Area outline unavailable.", error: true },
      );
    }
    saveState();
    if (quiet) return;
    renderAssessmentSummary(result, assessedCenters);
    addMessage(
      "assistant",
      `The ${result.scenario.return_period_years}-year flood screening for ${result.area} ` +
        `(${result.support_ref}) is on the map, and the area and scenario above now match it. ` +
        `${result.summary.potentially_exposed} of ${result.summary.in_scope} evacuation centers may be exposed, ` +
        `${result.summary.not_exposed_under_scenario} are not exposed under this scenario, and ` +
        `${result.summary.unable_to_assess} are N/A: the flood layer has no depth there.`,
      {
        label: result.synthetic ? "Synthetic test data — not a scientific result." : "From the locked assessment result.",
        actions: [
          chipButton("Where could people move?", () => send("Which evacuation centers are not exposed, where people could move?")),
          chipButton("Why N/A?", () => send("Which centers are N/A, and why?")),
        ],
      },
    );
  };

  const watch = async (id) => {
    window.clearTimeout(state.pollTimer);
    try {
      const [job, trace] = await Promise.all([
        GRP.request(`/api/v1/assessments/${id}`),
        GRP.request(`/api/v1/assessments/${id}/trace`),
      ]);
      renderRunTrace(trace);
      if (job.state !== "queued" && job.state !== "running") GRP.jobs.done(id);
      if (job.state === "succeeded") {
        state.runBusy = false;
        $("[data-run-status]").textContent = "Completed. Opening the mapped shelter result…";
        setRunPanelOpen(false);
        await showResult(id);
      } else if (job.state === "queued" || job.state === "running") {
        $("[data-result-title]").textContent = `${job.area} · ${job.scenario.return_period_years}-year flood`;
        $("[data-result-meta]").textContent = `Working in the background… ref ${job.support_ref}`;
        $("[data-run-status]").textContent = "The background worker is running. You can leave this panel open or continue using the map.";
        state.pollTimer = window.setTimeout(() => watch(id), 1500);
      } else {
        state.runBusy = false;
        state.pendingAssessmentId = null;
        saveState();
        $("[data-progress]").hidden = true;
        $("[data-result-meta]").textContent = `Assessment ${job.state}. Reference ${job.support_ref}.`;
        syncRunPanel();
        addMessage("assistant", `The assessment ${job.state}${job.error_code ? ` (${job.error_code})` : ""}. Reference ${job.support_ref}.`, { error: true });
      }
    } catch (error) {
      state.runBusy = false;
      state.pendingAssessmentId = null;
      $("[data-progress]").hidden = true;
      $("[data-result-meta]").textContent = error.message;
      syncRunPanel();
      saveState();
      addMessage("assistant", error.message, { error: true });
    }
  };

  // ---------- SIG evidence ----------
  const sigPanel = $("[data-sig]");
  const sigFrame = $("[data-sig-frame]");
  const showSigMap = (mapUrl, evidence, mapKind) => {
    sigFrame.src = mapUrl;
    const place = (evidence.area && evidence.area.sig_place) || evidence.place || "Confirmed area";
    const receiptId = evidence.receipt && evidence.receipt.receipt_id;
    $("[data-sig-meta]").textContent = `${place}${receiptId ? ` · receipt ${receiptId}` : ""}`;
    const risk = mapKind === "sig_vulnerability_weighted_flood_risk";
    $("[data-sig-title]").textContent = risk
      ? "Global Risk vulnerability-weighted flood risk"
      : "Flood hazard and asset exposure";
    $("[data-sig-help]").textContent = risk
      ? "Shows Global Risk's risk classes calculated with the approved recipe recorded below. It supports screening and does not certify that a location is safe."
      : "Shows assets intersecting mapped flood-hazard classes. It is not a vulnerability-weighted risk score and does not certify that a location is safe.";
    sigPanel.hidden = false;
  };
  $("[data-sig-close]").addEventListener("click", () => {
    sigPanel.hidden = true;
    sigFrame.removeAttribute("src");
  });

  // Evidence panel: what SIG returned, what is missing, how it was produced, downloads.
  const evidencePanel = $("[data-evidence]");
  const publishConfirm = $("[data-publish-confirm]");
  const publishConfirmButton = $("[data-publish-confirm-button]");
  const hidePublishConfirm = () => {
    publishConfirm.hidden = true;
    publishConfirmButton.disabled = false;
  };
  $("[data-publish-cancel]").addEventListener("click", hidePublishConfirm);
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

  const setPanelMode = (mode) => {
    const previous = document.querySelector('[data-ev-tab][aria-selected="true"]');
    evidencePanel.dataset.mode = mode;
    $("[data-ev-actions]").hidden = mode !== "sig";
    $("[data-ev-foot]").hidden = mode !== "sig";
    document.querySelectorAll("[data-ev-tab]").forEach((tab) => {
      tab.hidden = (tab.dataset.evTab === "evidence" || tab.dataset.evTab === "trace")
        && mode !== "sig";
    });
    // Keep the tab the planner chose if it still applies. Forcing Summary on every panel render
    // threw them off People mid-read, which looked like the tab losing its contents (backlog U1).
    const keep = previous && !previous.hidden ? previous : null;
    (keep || document.querySelector('[data-ev-tab="summary"]')).click();
  };

  const summaryNotice = (title, text, modifier = "") => {
    const card = document.createElement("article");
    card.className = `pw-decision-notice ${modifier}`.trim();
    const strong = document.createElement("strong");
    const body = document.createElement("p");
    strong.textContent = title;
    body.textContent = text;
    card.append(strong, body);
    return card;
  };

  const renderCoverage = (items) => {
    const box = $("[data-summary-coverage]");
    box.replaceChildren(...items.map(({ label, status, detail }) => {
      const row = document.createElement("div");
      row.className = `pw-coverage__row is-${status}`;
      const dot = document.createElement("span");
      dot.className = "pw-coverage__dot";
      const text = document.createElement("div");
      const strong = document.createElement("strong");
      const small = document.createElement("span");
      strong.textContent = label;
      small.textContent = detail;
      text.append(strong, small);
      row.append(dot, text);
      return row;
    }));
  };

  const renderGaps = (items) => {
    $("[data-ev-gaps]").replaceChildren(...items.map((gap) => {
      const item = document.createElement("li");
      item.textContent = gap;
      return item;
    }));
  };

  const peopleStatGrid = (cards) => {
    const grid = document.createElement("div");
    grid.className = "pw-people-grid";
    cards.forEach(([value, label]) => {
      const card = document.createElement("article");
      card.className = "pw-people-stat";
      const strong = document.createElement("strong");
      const span = document.createElement("span");
      strong.textContent = value === null || value === undefined
        ? "unknown"
        : Number(value).toLocaleString();
      span.textContent = label;
      card.append(strong, span);
      grid.append(card);
    });
    return grid;
  };

  const peopleNote = (text) => {
    const note = document.createElement("p");
    note.className = "pw-people-note";
    note.textContent = text;
    return note;
  };

  // Renders only from state, so every panel mode shows the same thing for the same area and a
  // later re-render cannot replace real figures with the indicator-map fallback (backlog U1).
  const renderVulnerablePeople = () => {
    const box = $("[data-vulnerable-content]");
    box.replaceChildren();
    const heading = document.createElement("h3");
    heading.textContent = "Vulnerable people";
    box.append(heading);

    const profile = state.areaProfile;
    const indicators = state.localContext?.vulnerability || [];

    if (state.areaProfileState === "loading") {
      box.append(peopleNote("Loading this area's figures from the GRP data library…"));
      return;
    }

    if (state.areaProfileState === "ready" && profile) {
      const area = profile.area || {};
      const where = [area.name, area.name_th].filter(Boolean).join(" · ")
        + (area.province_name ? `, ${area.province_name}` : "");
      const intro = document.createElement("p");
      intro.textContent = `${where} — from the GRP data library, no Global Risk lookup needed.`;
      box.append(intro);

      if (profile.population) {
        const p = profile.population;
        box.append(peopleStatGrid([
          [p.total_population, "people (registered)"],
          [p.male, "male"],
          [p.female, "female"],
          [p.households, "households"],
          [p.village_count, "villages"],
        ]));
        if (profile.source) {
          box.append(peopleNote(`${profile.source.label}. ${profile.source.caveat}`));
        }
      } else {
        box.append(peopleNote("No registered population record is held for this area."));
      }

      if (profile.flood_exposure) {
        const e = profile.flood_exposure;
        const sub = document.createElement("h4");
        sub.textContent = `Inside the RP${e.return_period_years} modelled flood extent`;
        box.append(sub, peopleStatGrid([
          [e.people_in_zone, "people"],
          [e.villages_in_zone, "villages"],
          [e.households_in_zone, "households"],
        ]));
        box.append(peopleNote(e.caveat));
      }

      const centres = profile.evacuation_centers;
      if (centres && centres.total) {
        const sub = document.createElement("h4");
        sub.textContent = "Recorded evacuation centres";
        box.append(sub, peopleStatGrid(
          [[centres.total, "recorded centres"]].concat(
            centres.by_type.map((item) => [item.count, item.label.toLowerCase()]),
          ),
        ));
        box.append(peopleNote(centres.caveat));
      }
    } else if (state.areaProfileState === "none") {
      box.append(peopleNote(
        "The GRP data library holds no population, flood-exposure or evacuation-centre record for "
        + "this area. That is a gap in the delivered data, not a count of zero.",
      ));
    } else if (state.areaProfileState === "error") {
      box.append(peopleNote(
        "This area's figures could not be read. It may not be a supported area. Choose a district "
        + "or sub-district from the area list and try again.",
      ));
    } else {
      box.append(peopleNote(
        "Select a district or sub-district on the map to see its registered population, the people "
        + "inside the modelled flood extent, and the evacuation centres recorded for it.",
      ));
    }

    // SIG's own population is shown beside GRP's, never instead of it.
    const sigValues = Object.entries(state.sigPopulation || {})
      .filter(([, value]) => typeof value === "number");
    if (sigValues.length) {
      const sub = document.createElement("h4");
      sub.textContent = "Global Risk district population evidence";
      box.append(sub);
      if (state.sigPopulationSource) box.append(peopleNote(state.sigPopulationSource));
      box.append(peopleStatGrid(
        sigValues.map(([name, value]) => [value, name.replaceAll("_", " ")]),
      ));
      box.append(peopleNote(
        "These are cited district-level aggregates from Global Risk. They are not linked to a specific "
        + "evacuation centre, household or map point, and categories may overlap.",
      ));
    }

    // Always last, and always one line: map context, never a substitute for the figures above.
    if (indicators.length) {
      box.append(peopleNote(
        `${indicators.length} source-native vulnerability indicator map(s) can be turned on in `
        + "Layers for spatial pattern. They are rasters, not people counts, and are not part of "
        + "the locked flood calculation.",
      ));
    }
  };

  const localCoverage = () => {
    const context = state.localContext;
    if (!context) return [];
    const labels = {
      volunteer_centers: "Civil-defence volunteer centres",
      early_warning_resources: "Early-warning resources",
      village_locations: "Village locations",
    };
    const rows = context.supporting.map((item) => ({
      label: labels[item.role] || item.title,
      status: item.count === null ? "missing" : "available",
      detail: item.count === null
        ? "Could not load this layer for the selected area"
        : `${Number(item.count).toLocaleString()} record(s) in this area`,
    }));
    if (context.vulnerability.length) {
      rows.push({
        label: "Vulnerability indicator maps",
        status: "available",
        detail: `${context.vulnerability.length} display-only indicator(s) available in Layers`,
      });
    }
    return rows;
  };

  const renderSourceSummary = (collection) => {
    setPanelMode("source");
    const hero = $("[data-summary-hero]");
    const movementSection = $("[data-summary-movement-section]");
    const fundingSection = $("[data-summary-funding-section]");
    const briefSection = $("[data-summary-brief-section]");
    hero.after(movementSection);
    movementSection.after(fundingSection);
    fundingSection.after(briefSection);
    briefSection.querySelector("h3").textContent = "Important limitation";
    currentEvidence = null;
    openEvidencePayload = null;
    $("[data-ev-eyebrow]").textContent = "Available district source data";
    $("[data-ev-title]").textContent = collection.boundary.name;
    $("[data-ev-counts]").textContent =
      `${collection.total.toLocaleString()} evacuation-centre record(s) · not assessed`;
    $("[data-ev-area]").textContent =
      `${collection.source.title} · ${collection.source.provider}`;
    $("[data-summary-status]").textContent = "Source records — no assessment run";
    $("[data-summary-title]").textContent = "Available evacuation-centre locations";
    $("[data-summary-lead]").textContent =
      "The complete district-scoped source list is on the Centres tab and uses the same records as the map markers. No flood status, capacity, route or safety conclusion has been added.";
    $("[data-summary-movement-title]").textContent = "What a planner can do now";
    $("[data-summary-movement]").replaceChildren(summaryNotice(
      "Review named centre records",
      "Open the Centres tab, search by name, and select a row to locate that exact source record on the map.",
    ));
    $("[data-summary-caveat]").hidden = true;
    $("[data-summary-coverage-title]").textContent = "Available information";
    $("[data-summary-coverage-intro]").textContent =
      "Only managed source facts are shown before an assessment.";
    renderCoverage([
      { label: "District boundary", status: "available", detail: collection.boundary.name },
      { label: "Evacuation-centre locations", status: "available", detail: `${collection.total} source record(s)` },
      ...localCoverage(),
      { label: "Flood status by centre", status: "missing", detail: "Run an assessment to classify these same records" },
      { label: "Capacity, services and routes", status: "missing", detail: "No approved centre-level source is linked" },
      { label: "Vulnerable people counts", status: "missing", detail: "Indicator maps are available, but no approved count method is linked" },
    ]);
    $("[data-summary-brief]").replaceChildren(summaryNotice(
      "No safety claim",
      "A point on the map is an available source record. It is not evidence that the centre is suitable, accessible, open or safe.",
    ));
    renderGaps([
      "Centre capacity and essential services are not included in this source.",
      "Route accessibility and travel safety have not been assessed.",
      "District population evidence, when available from Global Risk, is not tied to individual centres.",
    ]);
    ensureAreaProfile(state.selected);
    renderVulnerablePeople();
    openEvidence();
  };

  const renderAssessmentSummary = (result, centers) => {
    setPanelMode("assessment");
    setCenterRows(
      centers,
      `Locked assessment ${result.support_ref} · ${result.area} · RP${result.scenario.return_period_years}`,
    );
    renderGaps([
      ...(result.gaps || []),
      ...(result.limits || []),
      "Local preparedness points and vulnerability maps are current planning context; they are not pinned inputs to this locked centre-flood result.",
    ]);
    ensureAreaProfile(state.selected);
    renderVulnerablePeople();
    const hero = $("[data-summary-hero]");
    const movementSection = $("[data-summary-movement-section]");
    const fundingSection = $("[data-summary-funding-section]");
    const briefSection = $("[data-summary-brief-section]");
    hero.after(movementSection);
    movementSection.after(fundingSection);
    fundingSection.after(briefSection);
    briefSection.querySelector("h3").textContent = "Plain-language brief";
    $("[data-summary-movement-title]").textContent = "Where people could move";
    $("[data-summary-caveat]").hidden = false;
    $("[data-summary-coverage-title]").textContent = "Preparedness funding case";
    $("[data-summary-coverage-intro]").textContent =
      "Use available evidence now and treat missing checks as preparation or funding gaps.";
    currentEvidence = null;
    openEvidencePayload = null;
    $("[data-ev-eyebrow]").textContent = "GRP decision summary";
    $("[data-ev-title]").textContent = result.area;
    $("[data-ev-counts]").textContent =
      `${result.summary.in_scope} centres · RP${result.scenario.return_period_years} · locked result`;
    $("[data-ev-area]").textContent =
      `${result.synthetic ? "Synthetic demonstration" : "Assessment"} · ${result.method.key} ${result.method.version}`;
    $("[data-summary-status]").textContent = result.synthetic
      ? "Synthetic demonstration — not a scientific result"
      : "Locked assessment result";
    $("[data-summary-title]").textContent = "Movement options under this flood scenario";
    $("[data-summary-lead]").textContent =
      `${result.summary.potentially_exposed} centre(s) may be exposed, ` +
      `${result.summary.not_exposed_under_scenario} have lower mapped exposure, and ` +
      `${result.summary.unable_to_assess} are N/A. Red shading on the map shows ` +
      "flood depth from lighter to deeper red; it is not a risk or safety rating.";

    const candidates = centers.filter(
      (center) => center.status === "not_exposed_under_scenario",
    );
    const exposed = centers.filter((center) => center.status === "potentially_exposed");
    const unable = centers.filter((center) => center.status === "unable_to_assess");
    const movement = $("[data-summary-movement]");
    movement.replaceChildren();
    if (!candidates.length) {
      movement.append(summaryNotice(
        "No candidate movement options from this result",
        "Do not infer a destination from the map. Review exposed and unable-to-assess centres and resolve the missing evidence.",
        "is-blocked",
      ));
    } else {
      const list = document.createElement("div");
      list.className = "pw-candidates";
      candidates.slice(0, 6).forEach((center) => {
        const item = document.createElement("article");
        item.className = "pw-candidate";
        const marker = document.createElement("span");
        marker.className = "pw-candidate__marker";
        marker.style.background = STATUS_COLOR.not_exposed_under_scenario;
        const text = document.createElement("div");
        const name = document.createElement("strong");
        const detail = document.createElement("span");
        name.textContent = center.name;
        detail.textContent = center.flood_depth_m === null
          ? "Not exposed under this scenario"
          : `Flood depth ${center.flood_depth_m} m · not exposed under this scenario`;
        text.append(name, detail);
        item.append(marker, text);
        list.append(item);
      });
      movement.append(list);
      if (candidates.length > 6) {
        const more = document.createElement("p");
        more.className = "pw-decision-intro";
        more.textContent = `Plus ${candidates.length - 6} more candidate centre(s) in the complete Centres tab.`;
        movement.append(more);
      }
    }
    const centerNames = (items) => {
      const visible = items.slice(0, 3).map((center) => center.name).join(", ");
      return items.length > 3 ? `${visible}, and ${items.length - 3} more` : visible;
    };
    const cautions = document.createElement("div");
    cautions.className = "pw-status-breakdown";
    if (exposed.length) {
      cautions.append(summaryNotice(
        `${exposed.length} potentially exposed centre(s)`,
        centerNames(exposed),
        "is-exposed",
      ));
    }
    if (unable.length) {
      cautions.append(summaryNotice(
        `${unable.length} centre(s) N/A`,
        centerNames(unable),
        "is-unable",
      ));
    }
    if (cautions.childElementCount) movement.append(cautions);

    renderCoverage([
      { label: "Flood hazard", status: "available", detail: `RP${result.scenario.return_period_years} locked input` },
      { label: "Evacuation-centre locations", status: "available", detail: `${result.summary.in_scope} centres screened` },
      { label: "Movement screening", status: candidates.length ? "available" : "blocked", detail: candidates.length ? `${candidates.length} lower-exposure candidate(s)` : "No candidate from this result" },
      ...localCoverage(),
      { label: "Reported centre capacity", status: centers.some((item) => item.capacity != null) ? "available" : "missing", detail: centers.some((item) => item.capacity != null) ? "Shown per centre where supplied; not a suitability check" : "No capacity value supplied for these centres" },
      { label: "Essential services", status: "missing", detail: "No approved service-readiness source is linked" },
      { label: "Accessibility and routes", status: "missing", detail: "Travel safety has not been assessed" },
      { label: "Vulnerable people calculation", status: "missing", detail: "Display maps are loaded; an approved calculation still waits on DEP-07" },
      { label: "Interventions and costs", status: "missing", detail: "Waits on approved DEP-12 template" },
    ]);
    $("[data-summary-brief]").replaceChildren(summaryNotice(
      "What a planner can say now",
      candidates.length
        ? `${candidates.length} centre(s) are candidate movement options because they have lower mapped exposure in this scenario. Check capacity, accessibility, services, routes and other hazards before making a movement decision.`
        : "This screening does not identify a lower-exposure candidate. Resolve the unable-to-assess and missing-evidence items before making a movement decision.",
    ));
    openEvidence();
  };

  const renderSigSummary = (payload) => {
    const evidence = payload.evidence;
    const hasRisk = Boolean(evidence.risk_recipe);
    setPanelMode("sig");
    const hero = $("[data-summary-hero]");
    const movementSection = $("[data-summary-movement-section]");
    const fundingSection = $("[data-summary-funding-section]");
    const briefSection = $("[data-summary-brief-section]");
    hero.after(briefSection);
    briefSection.after(movementSection);
    movementSection.after(fundingSection);
    briefSection.querySelector("h3").textContent = payload.answer_source === "deterministic_fallback"
      ? "Key findings from the evidence"
      : "Evidence-based brief";
    $("[data-summary-movement-title]").textContent = "Available map layers";
    $("[data-summary-caveat]").hidden = true;
    $("[data-summary-coverage-title]").textContent = "Available information";
    $("[data-summary-coverage-intro]").textContent =
      "The map and evidence panel show each available source directly.";
    $("[data-ev-eyebrow]").textContent = "Planning summary · Global Risk screening";
    $("[data-summary-status]").textContent = evidence.receipt
      ? `Source-checked · receipt ${evidence.receipt.receipt_id}`
      : payload.answer_source === "deterministic_fallback"
        ? "Deterministic evidence summary · not publishable"
        : "Unverified screening draft";
    $("[data-summary-title]").textContent = hasRisk
      ? "Global Risk flood-risk information"
      : "Global Risk flood information";
    $("[data-summary-lead]").textContent = payload.answer_source === "deterministic_fallback"
      ? "The AI brief failed formatting checks, so GRP is showing only numbered findings copied from the structured evidence pack."
      : hasRisk
        ? `Global Risk returned hazard, exposure and vulnerability-weighted risk using recipe ${evidence.risk_recipe.version}.`
        : "Global Risk returned flood-hazard and asset-exposure information for the confirmed district.";
    $("[data-summary-movement]").replaceChildren(summaryNotice(
      "Flood and evacuation-centre layers are visible",
      "Use Layers to turn the national RP100 flood layer, district boundaries and evacuation-centre locations on or off.",
    ));
    renderCoverage([
      { label: "Flood hazard and exposure", status: "available", detail: `${evidence.summary.computed} computed evidence item(s)` },
      { label: "Evacuation-centre locations", status: state.centersVersion ? "available" : "missing", detail: state.centersVersion ? state.centersVersion.title : "No managed layer available" },
      {
        label: "Vulnerability-weighted risk",
        status: hasRisk ? "available" : "partial",
        detail: hasRisk
          ? `Global Risk recipe ${evidence.risk_recipe.version}; exact source values remain in Evidence`
          : "Global Risk generic screening may be present; no approved recipe is recorded",
      },
      ...(Object.keys((evidence.stats && evidence.stats.population_by_age) || {}).length
        ? [{ label: "Population by age", status: "available", detail: "Values are shown in the Evidence tab" }]
        : []),
      ...(evidence.warnings || []).map((warning) => ({
        label: "Global Risk metadata consistency",
        status: "blocked",
        detail: warning,
      })),
    ]);
    const brief = $("[data-summary-brief]");
    brief.replaceChildren();
    if (payload.answer && payload.answer.trim()) {
      brief.append(renderBrief(payload.answer, (n) => focusCitation(n)));
    } else {
      brief.append(summaryNotice(
        "Brief unavailable",
        "The structured source cards and values remain available in the Evidence tab.",
      ));
    }
  };

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
      `Evidence pack: ${evidence.pack_id || "-"}`,
      `Assembled at: ${evidence.assembled_at || "-"} (${evidence.gather_ms ?? "-"} ms)`,
      `Receipt: ${evidence.receipt ? evidence.receipt.receipt_id : "none (not published)"}`,
      "",
      "Global Risk platform steps:",
      ...evidence.sig_trace.map((line, i) => `  ${i + 1}. ${line}`),
      "",
      "GRP steps:",
      ...evidence.grp_trace.map((step, i) => `  ${i + 1}. ${step.step}: ${step.detail}`),
      "",
      "Evidence contract warnings:",
      ...(evidence.warnings || []).map((warning) => `  - ${warning}`),
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
        const answerStatus = evidence.receipt
          ? `receipt ${evidence.receipt.receipt_id}`
          : openEvidencePayload?.answer_source === "deterministic_fallback"
            ? "deterministic evidence summary (not publishable)"
            : "unverified draft (no receipt)";
        const header = `# ${evidence.question}\n\nArea: ${evidence.place}\nEvidence pack: ${evidence.pack_id}\n` +
          `Status: ${answerStatus}\n\n` +
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
    renderSigSummary(payload);
    const counts = evidence.summary;
    $("[data-ev-title]").textContent = (evidence.area && evidence.area.sig_place) || evidence.place;
    $("[data-ev-counts]").textContent =
      `${counts.sources} sources · ${counts.pulled_live} pulled live · ${counts.computed} computed · ${counts.declared_gaps} declared gap(s)`;
    const area = $("[data-ev-area]");
    area.textContent = evidence.area && evidence.area.sig_area
      ? `Global Risk analysis area: ${evidence.area.sig_area}`
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
      span.textContent = `${name.replaceAll("_", " ")} exposed to mapped flood hazard`;
      tile.append(strong, span);
      numbers.append(tile);
    });
    Object.entries((evidence.stats && evidence.stats.population_by_age) || {}).forEach(([name, value]) => {
      if (typeof value !== "number") return;
      const tile = document.createElement("div");
      tile.className = "pw-number";
      const strong = document.createElement("strong");
      const span = document.createElement("span");
      strong.textContent = value.toLocaleString();
      span.textContent = `${name.replaceAll("_", " ")} · Global Risk demographic evidence`;
      tile.append(strong, span);
      numbers.append(tile);
    });
    state.sigPopulation = (evidence.stats && evidence.stats.population_by_age) || null;
    state.sigPopulationSource =
      "Population values returned by the current Global Risk district evidence pack.";
    ensureAreaProfile(state.selected);
    renderVulnerablePeople();
    if (evidence.risk_recipe) {
      const tile = document.createElement("div");
      tile.className = "pw-number";
      const strong = document.createElement("strong");
      const span = document.createElement("span");
      const weights = evidence.risk_recipe.weights;
      strong.textContent = evidence.risk_recipe.version;
      span.textContent = `Approved Global Risk recipe · population ${Math.round(weights.population * 100)}% · buildings ${Math.round(weights.building_density * 100)}% · roads ${Math.round(weights.road_distance * 100)}%`;
      tile.append(strong, span);
      numbers.append(tile);
    }

    const cards = $("[data-ev-cards]");
    cards.replaceChildren(...evidence.citations.map(evidenceCard));

    const gapItems = [
      ...(evidence.warnings || []).map((warning) => `Evidence contract warning: ${warning}`),
      ...evidence.gaps,
    ];
    renderGaps(gapItems);

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
      `Pack ${evidence.pack_id || "-"} assembled ${evidence.assembled_at ? GRP.formatTime(evidence.assembled_at) : "-"} (Bangkok); Global Risk gathering ${evidence.gather_ms ? seconds(evidence.gather_ms) : "-"}; whole answer ${evidence.total_ms ? seconds(evidence.total_ms) : "-"}.`;

    const mapButton = $("[data-ev-map]");
    const mapUrl = safeHttps(payload.map_url);
    hidePublishConfirm();
    mapButton.disabled = false;
    mapButton.classList.remove("is-warning");
    delete mapButton.dataset.confirm;
    if (evidence.receipt) {
      mapButton.textContent = mapUrl
        ? payload.map_kind === "sig_vulnerability_weighted_flood_risk"
          ? "Show Global Risk's risk map"
          : "Show hazard & exposure map"
        : "Global Risk embedded map unavailable";
      mapButton.disabled = !mapUrl;
      mapButton.onclick = () => mapUrl && showSigMap(mapUrl, evidence, payload.map_kind);
      const receiptUrl = safeHttps(evidence.receipt.public_url);
      $("[data-ev-foot]").textContent = "";
      if (receiptUrl) {
        const link = document.createElement("a");
        link.href = receiptUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = `Public receipt ${evidence.receipt.receipt_id}`;
        $("[data-ev-foot]").append("Passed Global Risk's source check · ", link);
      }
      if (!mapUrl) {
        $("[data-ev-foot]").append(
          `${receiptUrl ? " · " : ""}${payload.map_note || "The answer is available, but Global Risk did not return a verified flood-hazard map."}`,
        );
      }
    } else {
      const publishToken = livePublishToken(payload);
      if (publishToken) {
        mapButton.textContent = "Verify & create public receipt";
        mapButton.onclick = () => { publishConfirm.hidden = false; };
        publishConfirmButton.onclick = () => {
          publishConfirmButton.disabled = true;
          send(message, {
            publish: true,
            publishToken,
            echo: false,
            confirmedPlace: evidence.place,
          });
        };
        $("[data-ev-foot]").textContent =
          "Unverified draft: not yet checked by Global Risk. Publishing checks this exact text and creates a shareable public receipt only if it passes.";
      } else if (needsFreshEvidence(payload)) {
        mapButton.textContent = "Gather fresh evidence to publish";
        mapButton.onclick = () => send(message, {
          echo: false, confirmedPlace: evidence.place, refresh: true,
        });
        $("[data-ev-foot]").textContent =
          `This brief uses Global Risk evidence gathered ${evidenceGathered(payload) || "earlier"}. A public receipt needs evidence gathered in the last 5 minutes, so gather it again from Global Risk first. That takes a few minutes.`;
      } else {
        mapButton.textContent = "Retry AI brief";
        mapButton.onclick = () => send(message, {
          echo: false, confirmedPlace: evidence.place, refresh: true,
        });
        $("[data-ev-foot]").textContent = payload.answer_source === "deterministic_fallback"
          ? "The evidence lookup succeeded. GRP generated the visible summary deterministically because the AI brief failed formatting checks. It cannot be published; retry asks for a fresh AI brief."
          : "The evidence lookup succeeded, but no publishable brief is available. Retry asks for a fresh AI brief.";
      }
    }
    outlineSigArea(evidence);
    openEvidence();
    if (evidence.receipt && mapUrl) {
      showSigMap(mapUrl, evidence, payload.map_kind);
    }
  };

  // ADR-0029: evidence is reused for an hour, so any card that is not freshly gathered says when
  // it was, beside the "pulled live" count that would otherwise read as live now.
  const evidenceGathered = (payload) => {
    const at = payload.evidence_assembled_at ? new Date(payload.evidence_assembled_at) : null;
    if (!at || Number.isNaN(at.getTime())) return "";
    const minutes = Math.max(0, Math.round((Date.now() - at.getTime()) / 60000));
    const sameDay = at.toDateString() === new Date().toDateString();
    const when = sameDay
      ? at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : at.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
    if (minutes < 1) return `${when}, just now`;
    if (minutes < 120) return `${when}, ${minutes} min ago`;
    return when;
  };

  // Mirrors PACK_PUBLISH_MAX_AGE_SECONDS. A card left open keeps its token for 15 minutes, but the
  // evidence it would certify may only be 5 minutes old; the server refuses anything older.
  const PUBLISH_MAX_AGE_MS = 5 * 60 * 1000;
  const livePublishToken = (payload) => {
    if (!payload.publish_token) return null;
    const at = payload.evidence_assembled_at ? new Date(payload.evidence_assembled_at) : null;
    if (at && !Number.isNaN(at.getTime()) && Date.now() - at.getTime() > PUBLISH_MAX_AGE_MS) {
      return null;
    }
    return payload.publish_token;
  };
  const needsFreshEvidence = (payload) =>
    Boolean(payload.publish_needs_fresh_evidence || (payload.publish_token && !livePublishToken(payload)));

  const gatherAgain = (payload, question, text = "Gather again from Global Risk") => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "link-button pw-status__again";
    button.textContent = text;
    button.addEventListener("click", () => send(question, {
      echo: false,
      confirmedPlace: payload.area?.requested || payload.evidence?.place,
      refresh: true,
    }));
    return button;
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
    badge.textContent = evidence.receipt
      ? `Receipt ${evidence.receipt.receipt_id}`
      : payload.answer_source === "deterministic_fallback"
        ? "Deterministic summary · not publishable"
        : livePublishToken(payload)
          ? "Unverified draft"
          : needsFreshEvidence(payload) ? "Gather again to publish" : "Evidence only";
    card.append(title);
    if (payload.note) {
      const note = document.createElement("span");
      note.className = "pw-status__note";
      note.textContent = payload.note;
      card.append(note);
    }
    card.append(line);
    if (counts.pulled_live === 0) {
      const sourceNote = document.createElement("span");
      sourceNote.className = "pw-status__source-note";
      sourceNote.textContent =
        "No source was pulled live in this run; computed exposure is not a report of current flooding.";
      card.append(sourceNote);
    }
    const steps = (evidence.grp_trace || []).filter((step) => typeof step.duration_ms === "number");
    if (payload.cached) {
      const timing = document.createElement("span");
      timing.className = "pw-status__timing";
      timing.textContent = "Answered immediately: you asked this earlier in this sign-in.";
      card.append(timing);
    } else if (evidence.total_ms || steps.length) {
      const timing = document.createElement("span");
      timing.className = "pw-status__timing";
      const parts = steps.map((step) => `${STEP_LABELS[step.step] || step.step} ${seconds(step.duration_ms)}`);
      timing.textContent = `Took ${seconds(evidence.total_ms || 0)} · ${parts.join(" · ")}`;
      card.append(timing);
    }
    const gathered = evidenceGathered(payload);
    const reused = payload.evidence_reused || payload.cached;
    if (gathered && (reused || restoring)) {
      const reuse = document.createElement("span");
      reuse.className = "pw-status__reuse";
      reuse.append(reused
        ? `Global Risk evidence gathered ${gathered} · reused, no new Global Risk lookup.`
        : `Global Risk evidence gathered ${gathered}.`);
      reuse.append(gatherAgain(payload, question));
      card.append(reuse);
    }
    card.append(badge);
    return card;
  };

  const sigActions = (payload, message) => [
    chipButton(payload.map_url ? "Open map & evidence" : "Open evidence", () => renderEvidence(payload, message)),
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

  const placeKey = (name) => String(name || "").trim().toLowerCase().replace(/\s+/g, " ");

  const rememberSigAnswer = (payload, question) => {
    const name = payload.area?.requested || payload.area?.sig_place || state.currentPlace;
    if (!name) return;
    // Keep only the most recent few: an evidence pack is large and this is session memory only.
    state.sigAnswers.set(placeKey(name), { payload, question });
    while (state.sigAnswers.size > 5) {
      state.sigAnswers.delete(state.sigAnswers.keys().next().value);
    }
  };

  const storedSigAnswer = (name) => state.sigAnswers.get(placeKey(name)) || null;

  const showStoredSigAnswer = (name) => {
    const stored = storedSigAnswer(name);
    if (!stored) return;
    addEvidenceMessage(stored.payload, stored.question);
    renderEvidence(stored.payload, stored.question);
  };

  const send = async (text, {
    publish = false, publishToken = null, echo = true, confirmedPlace = null, refresh = false,
  } = {}) => {
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
          "I do not know your district yet. Use my location, click your district on the map, or name it in your message (for example \"Bang Bua Thong, Nonthaburi\").",
          {
            label: "Location needed.",
            actions: [
              chipButton("Use my location", useCurrentLocation),
              chipButton("Show me the map", () => {
                document.body.dataset.view = "map";
                window.setTimeout(() => map.invalidateSize(), 0);
              }),
            ],
          },
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
        addMessage("assistant", `I found ${candidateName}. Confirm it as your map location before using Global Risk evidence.`, {
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
      const payload = await askPlanning({
        message: requestMessage,
        place: confirmedPlace,
        hub_code: state.hubCode,
        boundary_id: state.explicitSelection && state.selected ? state.selected.id : null,
        assessment_id: state.assessmentId,
        publish_receipt: publish,
        publish_token: publishToken,
        refresh,
        echo,
        history: state.history.slice(-8),
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
        state.runBusy = true;
        syncRunPanel();
        saveState();
        GRP.jobs.track({
          id: payload.assessment_id,
          label: `Assessment for ${boundary ? boundary.name : "the chosen area"}`,
          statusPath: `/api/v1/assessments/${payload.assessment_id}`,
          href: "/planning.html",
          ownerPath: "/planning.html",
        });
        document.body.dataset.view = window.matchMedia("(max-width: 860px)").matches ? "map" : document.body.dataset.view;
        watch(payload.assessment_id);
      } else if (payload.mode === "sig_evidence") {
        actions = sigActions(payload, message);
      } else if (payload.mode === "explain_result") {
        // The answer names centres; offer to show exactly those on the map, which is what a
        // planner asks next when a brief lists seven places they cannot locate.
        const named = centresNamedIn(payload);
        if (named.length) {
          actions = [chipButton(
            named.length === 1
              ? `Show ${named[0].name} on the map`
              : `Show these ${named.length} centres on the map`,
            () => showCentresOnMap(named),
          )];
        }
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
        rememberSigAnswer(payload, message);
        addEvidenceMessage(payload, message);
        renderEvidence(payload, message);
      } else {
        if (payload.mode === "gate_blocked") {
          hidePublishConfirm();
          const mapButton = $("[data-ev-map]");
          mapButton.textContent = "Retry brief generation";
          mapButton.onclick = () => send(message, { echo: false, confirmedPlace: payload.area?.requested });
          $("[data-ev-foot]").textContent =
            "Global Risk refused this draft. No public receipt or live map was created. Review the reason in chat, then retry.";
        }
        addMessage("assistant", payload.answer, {
          label: payload.label,
          actions,
          error: payload.mode === "area_rejected" || payload.mode === "gate_blocked",
        });
      }
      if (!publish) {
        state.history.push({ role: "user", text: message });
        if (payload.answer?.trim()) {
          state.history.push({ role: "assistant", text: payload.answer.slice(0, 1200) });
        }
        saveState();
      }
      return true;
    } catch (error) {
      typing.remove();
      addMessage("assistant", error.message, { label: error.code, error: true });
      if (error.code === "PUBLISH_NEEDS_FRESH_EVIDENCE") hidePublishConfirm();
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

  // A SIG gather for a Thai district has been measured at over a minute, so the answer comes
  // back as a job rather than as a held-open request (ADR-0025). The top-bar pill shows it
  // running, so a planner can switch pages and be told when it lands.
  const LOOKUP_POLL_MS = 2000;
  const LOOKUP_GIVE_UP_MS = 10 * 60 * 1000;

  const askPlanning = async (body) => {
    const started = await GRP.request("/api/v1/planning/lookups", { method: "POST", body });
    const statusPath = `/api/v1/planning/lookups/${started.job_id}`;
    GRP.jobs.track({
      id: started.job_id,
      label: "Global Risk evidence lookup",
      statusPath,
      href: "/planning.html",
      ownerPath: "/planning.html",
    });
    const deadline = Date.now() + LOOKUP_GIVE_UP_MS;
    try {
      for (;;) {
        const status = await GRP.request(statusPath);
        if (status.state === "succeeded") return status.answer;
        if (status.state === "failed") {
          const failure = new Error(status.error || "The Global Risk lookup could not be completed.");
          failure.code = status.error_code;
          throw failure;
        }
        if (Date.now() > deadline) {
          const timeout = new Error(
            "This lookup is taking longer than expected. The top bar keeps watching it.",
          );
          timeout.code = "LOOKUP_STILL_RUNNING";
          timeout.keepWatching = true;
          throw timeout;
        }
        await new Promise((resolve) => window.setTimeout(resolve, LOOKUP_POLL_MS));
      }
    } catch (error) {
      // Stop watching only what has actually ended. A lookup this page gave up polling is
      // still running on the server, and the top bar is then the only thing tracking it.
      if (!error.keepWatching) GRP.jobs.done(started.job_id);
      throw error;
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
    // OpenStreetMap keeps the Thai district (amphoe, or khet in Bangkok) in different
    // fields: `county` outside Bangkok, `suburb` inside it. `city_district` is often the
    // sub-district (tambon), so accept a value only when it reads as a district.
    const isDistrict = (value) =>
      typeof value === "string"
      && !/sub-?district/i.test(value)
      && !/^ตำบล|^แขวง/.test(value)
      && (/district$/i.test(value.trim()) || /^อำเภอ|^เขต/.test(value));
    const district = [
      address.county,
      address.suburb,
      address.city_district,
      address.state_district,
      address.district,
    ].find(isDistrict);
    const province = address.province || address.state || (district ? address.city : null);
    if (district) return [...new Set([district, province, "Thailand"].filter(Boolean))].join(", ");
    return null;
  };

  const normalizeAreaName = (value) => String(value || "")
    .toLowerCase()
    .replace(/\b(?:district|amphoe|khet|thailand)\b/g, "")
    .replace(/[^a-z0-9\u0E00-\u0E7F]+/g, " ")
    .trim();

  const localBoundaryForPlace = (name) => {
    const [district, province] = String(name || "").split(",").map(normalizeAreaName);
    const matches = state.boundaries.filter((boundary) =>
      normalizeAreaName(boundary.name) === district
      && (!province || !boundary.province_name
        || normalizeAreaName(boundary.province_name) === province));
    return matches.length === 1 ? matches[0] : null;
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
      chip.textContent = "This map location is for orientation only. Choose a Thailand district before requesting Global Risk evidence.";
      chip.hidden = false;
      return;
    }
    const localBoundary = localBoundaryForPlace(name);
    if (localBoundary) selectBoundary(localBoundary, { explicit: true });
    chip.append(document.createTextNode(
      `${currentLocation ? `Your current district is ${name}.` : `${name} selected.`} Available map layers are shown. `
    ));
    if (storedSigAnswer(name)) {
      chip.append(chipButton("Show the Global Risk evidence I already have", () =>
        showStoredSigAnswer(name)));
    }
    chip.append(chipButton(
      storedSigAnswer(name) ? "Gather it again from Global Risk" : "Check Global Risk flood exposure",
      () => send(
        `Check flood exposure for schools, hospitals and roads in ${name}.`,
        { confirmedPlace: name, refresh: Boolean(storedSigAnswer(name)) },
      ),
    ));
    chip.hidden = false;
  };

  // Nominatim returns the district field at different zooms depending on the address,
  // so try the administrative levels from district outwards before giving up.
  const reverseDistrict = async (lat, lon) => {
    for (const zoom of [10, 12, 14, 8]) {
      try {
        const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=${zoom}&addressdetails=1&accept-language=en&lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`;
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        if (!response.ok) continue;
        const place = await response.json();
        if (!place || place.error) continue;
        if (place.address?.country_code?.toLowerCase() !== "th") {
          return { outsideThailand: true };
        }
        if (externalPlaceName(place)) return { place: { ...place, lat, lon } };
      } catch (_error) {
        // Try the next zoom level; the caller reports a single clear failure.
      }
    }
    return {};
  };

  // Clicking bare map (not a supported area outline) offers that district for SIG evidence.
  const useMapPoint = async (lat, lon) => {
    const chip = $("[data-place-chip]");
    chip.replaceChildren();
    chip.textContent = "Finding the district for that point…";
    chip.hidden = false;
    const { place, outsideThailand } = await reverseDistrict(lat, lon);
    if (place) {
      const name = externalPlaceName(place);
      // Clicking the same district again used to repeat the identical prompt in the chat, which
      // read as the assistant forgetting what it had just been told. The place chip already shows
      // the selection, so re-selecting is silent.
      const already = state.currentPlace === name;
      pickPlace(place);
      if (!already) {
        const reuse = storedSigAnswer(name);
        addMessage(
          "assistant",
          reuse
            ? `${name} is selected. Global Risk evidence for this district was already gathered in this `
              + "session, so it can be shown again without another lookup."
            : `${name} is selected from the map for Global Risk flood evidence.`,
          {
            label: reuse ? "Already gathered this session." : "Map location selected.",
            actions: [
              ...(reuse
                ? [chipButton("Show the Global Risk evidence I already have", () =>
                    showStoredSigAnswer(name))]
                : []),
              chipButton(
                reuse ? "Gather it again from Global Risk" : "Check Global Risk flood exposure",
                () => send(
                  `Check flood exposure for schools, hospitals and roads in ${name}.`,
                  { confirmedPlace: name, refresh: Boolean(reuse) },
                ),
              ),
            ],
          },
        );
      }
      return;
    }
    chip.textContent = outsideThailand
      ? "GRP's Global Risk lookup covers Thailand districts only. Click inside Thailand or search for a district."
      : "No administrative district was found for that point. Click nearer a town, or search for a district by name.";
  };

  let mapClickBusy = false;
  map.on("click", async (event) => {
    if (mapClickBusy) return;
    mapClickBusy = true;
    try {
      await useMapPoint(event.latlng.lat, event.latlng.lng);
    } finally {
      mapClickBusy = false;
    }
  });

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
      const { place, outsideThailand } = await reverseDistrict(latitude, longitude);
      if (outsideThailand) throw new Error("CURRENT_LOCATION_NOT_THAILAND");
      if (!place) throw new Error("CURRENT_LOCATION_NO_DISTRICT");
      pickPlace(place, { currentLocation: true });
      const name = externalPlaceName(place);
      addMessage("assistant", `Your district is ${name}. Available local map layers are shown, and Global Risk information can be added.`, {
        label: "Current district confirmed.",
        actions: [chipButton("Check Global Risk flood exposure", () => send(
          `Check flood exposure for schools, hospitals and roads in ${name}.`,
          { confirmedPlace: name },
        ))],
      });
    } catch (error) {
      const message = error.code === 1
        ? "Location permission was not granted. Search for a Thailand district instead."
        : error.message === "CURRENT_LOCATION_NOT_THAILAND"
        ? "GRP’s current Global Risk lookup is limited to Thailand districts."
        : error.message === "CURRENT_LOCATION_NO_DISTRICT"
        ? "I found your position but no administrative district there. Click your district on the map, or search for it by name."
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
      group.textContent = "Thailand districts";
      searchResults.append(group);
      local.slice(0, 5).forEach((boundary) =>
        searchResults.append(searchItem(
          boundary.name,
          `${boundary.province_name ? `${boundary.province_name} · ` : ""}${boundary.admin_level}${boundary.synthetic ? " · synthetic test area" : ""}`,
          () => selectBoundary(boundary, { announce: true }),
        )),
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

  // A new tab, a closed tab or a new sign-in has nothing in sessionStorage. The server keeps the
  // conversation (ADR-0029), so it is drawn from there rather than starting blank.
  const conversationPath = () =>
    `/api/v1/planning/conversation?hub_code=${encodeURIComponent(state.hubCode)}`;

  const restoreConversation = async () => {
    if (!state.chatAvailable || !state.hubCode) return;
    let stored = null;
    try {
      stored = await GRP.request(conversationPath());
    } catch (_error) {
      return;
    }
    if (!stored.messages || !stored.messages.length) return;
    restoring = true;
    try {
      stored.messages.forEach((entry) => {
        if (entry.kind === "evidence" && entry.payload && entry.payload.evidence) {
          const record = { kind: "evidence", payload: entry.payload, question: entry.question || "" };
          transcript.push(record);
          addEvidenceMessage(record.payload, record.question);
        } else {
          transcript.push({
            kind: "message", role: entry.role, text: entry.text, label: entry.label || null, error: false,
          });
          addMessage(entry.role, entry.text, { label: entry.label, record: false });
        }
      });
      state.history = stored.history || [];
    } finally {
      restoring = false;
      saveState();
    }
  };

  const welcomeTemplate = $("[data-welcome]").cloneNode(true);
  let clearArmed = null;

  const startOver = async (button) => {
    // Two clicks, not a browser dialog: the first says what will be forgotten.
    if (!clearArmed) {
      button.textContent = "Forget chat and evidence?";
      clearArmed = window.setTimeout(() => {
        clearArmed = null;
        button.textContent = "New conversation";
      }, 4000);
      return;
    }
    window.clearTimeout(clearArmed);
    clearArmed = null;
    button.disabled = true;
    try {
      await GRP.request(conversationPath(), { method: "DELETE" });
      transcript.length = 0;
      state.history = [];
      state.sigAnswers.clear();
      openEvidencePayload = null;
      thread.replaceChildren(welcomeTemplate.cloneNode(true));
      renderWelcome();
      saveState();
    } catch (error) {
      addMessage("assistant", error.message, { label: error.code, error: true, record: false });
    } finally {
      button.disabled = false;
      button.textContent = "New conversation";
    }
  };

  const restoreState = async ({ skipAssessment = false } = {}) => {
    let saved = null;
    try {
      saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null");
    } catch (_error) {
      saved = null;
    }
    if (saved && saved.owner !== ownerEmail) {
      sessionStorage.removeItem(STORE_KEY);
      saved = null;
    }
    if (!saved) {
      await restoreConversation();
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
      if (saved.assessmentId && !skipAssessment) {
        await showResult(saved.assessmentId, { quiet: true }).catch(() => {});
      }
      if (saved.pendingAssessmentId && !skipAssessment) {
        state.pendingAssessmentId = saved.pendingAssessmentId;
        state.runBusy = true;
        syncRunPanel();
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
  // The server renews the SIG token on its own while a refresh token lasts, so this only
  // reports what is left and offers the one action that helps: sign in again.
  const SIG_EXPIRY_WARNING_SECONDS = 15 * 60;

  const signInAgainLink = () => {
    const link = document.createElement("a");
    link.href = "/api/v1/auth/login";
    link.textContent = "Sign in again";
    return link;
  };

  const showSigConnectionNotice = (planning) => {
    const banner = $("[data-banner]");
    const connected = Boolean(planning.sig_connected);
    const remaining = Number(planning.sig_expires_in_seconds);
    const expiringSoon =
      connected && Number.isFinite(remaining) && remaining <= SIG_EXPIRY_WARNING_SECONDS;
    if (connected && !expiringSoon) {
      if (banner.dataset.notice === "sig-connection") {
        banner.hidden = true;
        delete banner.dataset.notice;
      }
      return;
    }
    banner.textContent = expiringSoon
      ? `Global Risk evidence stays connected for about ${Math.max(1, Math.round(remaining / 60))} more minutes. `
      : "Global Risk evidence needs a fresh sign-in. Existing evidence may be restored from this browser tab, but a new lookup cannot run. ";
    banner.append(signInAgainLink());
    banner.dataset.notice = "sig-connection";
    banner.hidden = false;
  };

  const refreshSigConnection = async () => {
    if (!state.hubCode || !state.chatAvailable) return;
    try {
      const planning = await GRP.request("/api/v1/planning/status");
      state.sigConnected = Boolean(planning.sig_connected);
      showSigConnectionNotice(planning);
    } catch (_error) {
      // The next request will show the normal API error; do not replace another banner here.
    }
  };

  window.addEventListener("focus", refreshSigConnection);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshSigConnection();
  });

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
      const [planning, areas, layers, methods] = await Promise.all([
        GRP.request("/api/v1/planning/status").catch(() => ({ available: false })),
        GRP.request(`/api/v1/catalog/boundaries${query}`),
        GRP.request(`/api/v1/maps/layers${query}`),
        GRP.request(`/api/v1/catalog/methods${query}`),
      ]);
      state.chatAvailable = Boolean(planning.available);
      state.sigConnected = Boolean(planning.sig_connected);
      if (planning.usage) showAllowance(planning.usage);
      else GRP.request("/api/v1/me/ai-usage").then(showAllowance).catch(() => {});
      if (!planning.available) {
        banner.textContent = "The chat assistant runs only in the local Docker Desktop test right now.";
        banner.dataset.notice = "planning-unavailable";
        banner.hidden = false;
      } else {
        showSigConnectionNotice(planning);
      }
      state.boundaries = areas.boundaries;
      state.floodLayers = layers.flood;
      state.methods = methods.methods || [];
      configureFloodScenarios(layers.flood_scenarios);
      state.centerVersions = layers.evacuation_centers || [];
      state.supportingLayers = layers.supporting_points || [];
      state.vulnerabilityLayers = layers.vulnerability || [];
      state.centersVersion = state.centerVersions.find((layer) => layer.is_current && !layer.synthetic)
        || state.centerVersions.find((layer) => !layer.synthetic)
        || state.centerVersions[0]
        || null;
      if (state.centersVersion) {
        $("[data-centers-title]").textContent = "Evacuation centers";
      }
      const mapPreview = state.floodLayers[0]?.preview_only || state.centersVersion?.preview_only;
      const floodToggle = $('[data-layer="flood"]');
      const centersToggle = $('[data-layer="centers"]');
      const districtToggle = $('[data-layer="districts"]');
      // Display-first MVP 1: flood and boundaries can load immediately. Evacuation centres
      // load only after a district is selected so the browser never downloads the national set.
      floodToggle.checked = Boolean(selectedFloodLayer());
      centersToggle.checked = false;
      districtToggle.checked = state.boundaries.length > 0;
      const previewNote = $("[data-map-preview-note]");
      previewNote.hidden = !mapPreview;
      previewNote.textContent = mapPreview
        ? "Source preview — the available flood and evacuation-centre data is shown directly."
        : "";
      $("[data-vulnerability-note]").textContent = state.vulnerabilityLayers.length
        ? "Source-native display indicators only; GRP does not combine them into a risk score."
        : "No vulnerability indicator is active.";
      buildSupplementalLayerControls();
      drawLegend(layers.flood_legend);
      drawDistricts();
      syncRunPanel();
      await loadFloodOverlay(selectedFloodLayer());
      if (districtToggle.checked) districtLayer.addTo(map);
      if (centersToggle.checked) centersLayer.addTo(map);
      if (floodOverlay && floodToggle.checked) floodOverlay.addTo(map);
      renderWelcome();
      initChatResize();
      ownerEmail = identity.email;
      const clearButton = $("[data-clear-chat]");
      clearButton.hidden = !state.chatAvailable;
      clearButton.addEventListener("click", () => startOver(clearButton));
      await restoreState({ skipAssessment: Boolean(requestedAssessmentId) });
      if (requestedAssessmentId) {
        // Arriving from Flood assessment. restoreState has just re-selected whatever area this
        // browser last used, which is usually not the assessment's, so drop it rather than show a
        // different district while the assessment loads (backlog U5).
        state.selected = null;
        state.explicitSelection = false;
        state.areaProfile = null;
        state.areaProfileId = null;
        state.areaProfileState = "idle";
        state.assessmentId = null;
        state.pendingAssessmentId = requestedAssessmentId;
        state.runBusy = true;
        syncRunPanel();
        renderVulnerablePeople();
        showProgress("Loading assessment");
        saveState();
        watch(requestedAssessmentId);
      }
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
