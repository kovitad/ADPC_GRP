// ADR-0032: send a Hub's data to Global Risk as a contribution, and follow it until it lands.
(() => {
  const $ = (selector) => document.querySelector(selector);
  const planningRoles = new Set(["ndmo_planner", "hub_expert", "planner", "admin"]);

  // Field notes follow Global Risk's own gate (28 Sep 2026) and the runbook. type: text (default),
  // area, select, map (a JSON mapping), list (comma separated), weights.
  const VALIDATION = ["unvalidated", "single-agency", "official-statistic", "peer-reviewed", "multi-agency-consensus"];
  const F = {
    url: {
      label: "File link",
      help: "Paste the Google Drive share link of the file (not a folder). Set sharing to 'Anyone with the link'. GRP turns it into the direct-download form Global Risk needs. Drive shows a virus-scan page for files over about 100 MB: host those on GitHub or a web server.",
      placeholder: "https://drive.google.com/file/d/…/view",
    },
    title: { label: "Title", help: "What it is, in a few words." },
    description: { label: "Description", type: "area", help: "What one record or pixel means, how it was made, and what it leaves out." },
    source: { label: "Source", help: "Who made it, and from what. For example: Thailand DDPM, compiled by ADPC." },
    license: { label: "Licence", help: "For example CC-BY-4.0. If it is genuinely unknown write 'unstated'; leaving it blank is not accepted." },
    vintage: { label: "Vintage", help: "When it was produced or last updated, as YYYY-MM.", placeholder: "2026-09" },
    usage_notes: { label: "Usage notes", type: "area", optional: true, help: "A few lines every analyst reads when citing it (at most 500 characters)." },
    countries: { label: "Countries", type: "list", optional: true, help: "Comma separated.", placeholder: "Thailand" },
    validation: { label: "Validation", type: "select", options: VALIDATION, help: "Say 'unvalidated' rather than guess." },
    pack: { label: "Pack", type: "select", options: ["risk", "food-security"], help: "Which part of Global Risk may cite it." },
  };
  const KINDS = {
    vector: {
      label: "Point layer",
      help: "A GeoJSON file of points (longitude, latitude), such as evacuation centres. Global Risk counts them against the flood layer beside hospitals and schools. GRP reads the file first and refuses it if it has contact fields (phone, fax, email).",
      fields: [
        ["layer", { label: "Layer name", help: "Short snake_case name the risk pack counts under, 3 to 40 characters, e.g. evacuation_centres.", placeholder: "evacuation_centres" }],
        ["url"], ["title"], ["description"], ["source"], ["license"], ["vintage"], ["countries"],
        ["name_field", { label: "Name field", optional: true, help: "The property holding each point's name, if any.", placeholder: "name" }],
        ["usage_notes"],
      ],
    },
    raster: {
      label: "Raster",
      help: "A GeoTIFF in EPSG:4326. Hazard and vulnerability layers must already be classes 0-5 (0 = none). A population count grid stays as people per pixel and needs no legend.",
      fields: [
        ["layer", { label: "Layer name", help: "Starts with hazard_, risk_, vulnerability_ or population_ (a count grid), 3 to 40 characters, e.g. hazard_flood_thailand_rp100.", placeholder: "vulnerability_vulnerable_people" }],
        ["url"], ["title"], ["description"], ["source"], ["license"], ["vintage"],
        ["legend", { label: "Legend", type: "map", help: "Class number to label. Not needed for population_ layers.", placeholder: "{\"1\": \"Very low\", \"2\": \"Low\", \"3\": \"Moderate\", \"4\": \"High\", \"5\": \"Very high\"}" }],
        ["declared", { label: "Declared contract", type: "map", help: "What the file is: dtype, valid_min, valid_max, and nodata if any. Global Risk checks the file against it.", placeholder: "{\"dtype\": \"uint8\", \"valid_min\": 0, \"valid_max\": 5, \"nodata\": 0}" }],
        ["usage_notes"],
      ],
    },
    table: {
      label: "Table",
      help: "A CSV such as a depth-damage table. Paste it, or link to it. It becomes a feed Global Risk can query and cite.",
      fields: [
        ["dataset", { label: "Dataset name", help: "snake_case; it becomes the feed name, e.g. flood_depth_damage_th.", placeholder: "flood_depth_damage_th" }],
        ["title"], ["description"], ["source"], ["validation"], ["license"], ["vintage"],
        ["cadence", { label: "Cadence", type: "select", options: ["irregular", "monthly", "daily", "annual"] }],
        ["columns", { label: "Columns", type: "map", help: "Output field to CSV column header.", placeholder: "{\"depth_m\": \"Depth_m\", \"residential\": \"Residential\"}" }],
        ["units", { label: "Units", help: "Units of the numeric columns, in words." }],
        ["csv_text", { label: "CSV", type: "area", optional: true, help: "Header row first, up to 200 KB. Or give a link below instead." }],
        ["url", { label: "CSV link", optional: true, help: "Instead of pasting: a public link to the CSV." }],
        ["pack"], ["as_of_field", { label: "Date field", optional: true, help: "The output field holding each row's date." }],
        ["usage_notes"],
      ],
    },
    document: {
      label: "Document",
      help: "A report or guideline (PDF). Global Risk archives it and cites passages from it.",
      fields: [
        ["pack"], ["url", { label: "Document link", help: "A public link to the file itself (a Google Drive file link is converted)." }],
        ["source", { label: "Publisher", help: "For example: Thailand DDPM." }], ["title"],
        ["pub_date", { label: "Published", help: "YYYY-MM or YYYY-MM-DD.", placeholder: "2025-11" }],
        ["temporal", { label: "Looks", type: "select", options: ["retrospective", "forecast"], help: "Only a forecast may be cited for an outlook." }],
        ["validation"], ["countries"],
        ["doc_type", { label: "Type", optional: true, placeholder: "bulletin" }],
        ["usage_notes"],
      ],
    },
    feed: {
      label: "Live feed",
      help: "A JSON feed Global Risk fetches itself and serves through feeds_query and its risk answers, such as GRP's Bangkok flood feed or an agency's live API. Global Risk keeps a copy for up to six hours.",
      fields: [
        ["dataset", { label: "Feed name", help: "snake_case; it becomes the feed's name on Global Risk, e.g. bangkok_flood_districts_live.", placeholder: "bangkok_flood_districts_live" }],
        ["title"], ["description"], ["source"], ["validation"],
        ["cadence", { label: "How often it changes", help: "In words, e.g. every 10 minutes.", placeholder: "every 10 minutes" }],
        ["url", { label: "Feed address", help: "An http or https address anyone can open, that will stay up. Not a temporary tunnel.", placeholder: "https://grp.example.org/api/v1/public/flood/bangkok/feed.json" }],
        ["records_path", { label: "Record list", help: "Where the list of records is, as a dot path, e.g. districts or data.rows.", placeholder: "districts" }],
        ["fields", { label: "Fields to keep", type: "map", help: "Output name to the path inside each record. A list position is a number, e.g. values.0.", placeholder: "{\"district\": \"district_name_en\", \"active\": \"active_incidents\", \"as_of\": \"as_of\"}" }],
        ["as_of_field", { label: "Date field", optional: true, help: "One of the output names above that holds each record's time, so Global Risk returns the newest records.", placeholder: "as_of" }],
        ["pack"],
        ["hazards", { label: "Hazards", type: "list", optional: true, help: "Comma separated. A risk answer cites the feed only for these hazards.", placeholder: "flood, flashflood" }],
        ["countries"], ["license"], ["usage_notes"],
      ],
    },
    weights: {
      label: "Risk weights",
      help: "Changes how the flood risk level is computed from vulnerability layers. It affects the risk levels every Global Risk user sees, for every place.",
      fields: [
        ["hazard", { label: "Hazard", help: "The base hazard the recipe belongs to, e.g. flood.", placeholder: "flood" }],
        ["weights", { label: "Weights", type: "map", help: "Vulnerability layer to weight; they must add up to 1.0. A population_ count grid cannot be weighted.", placeholder: "{\"vulnerability_pop_all_total\": 0.4, \"vulnerability_reclass_blddensity\": 0.35, \"vulnerability_reclass_road\": 0.25}" }],
        ["rationale", { label: "Rationale", type: "area", help: "Why these weights. It is the only evidence the numbers rest on." }],
      ],
    },
  };

  const STATUS = {
    submitting: ["Sending", "is-running"],
    checking: ["Checking whether it arrived", "is-running"],
    staged: ["Waiting for a Global Risk reviewer", "is-waiting"],
    approved: ["Live on Global Risk", "is-ok"],
    declined: ["Declined: fix and resend", "is-bad"],
    rejected: ["Rejected by a reviewer", "is-bad"],
    withdrawn: ["Withdrawn", "is-muted"],
    failed: ["Not sent", "is-bad"],
  };

  const startKind = window.location.hash === "#live-feed" ? "feed" : "vector";
  const state = { hubCode: null, kind: startKind, values: {}, checked: null, rows: [], timer: null, servir: false, feedTab: "platform", platformFeeds: null };

  const kindButtons = () => {
    const box = $("[data-kinds]");
    Object.entries(KINDS).forEach(([kind, spec]) => {
      const label = document.createElement("label");
      label.className = "cb-kind";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "kind";
      input.value = kind;
      input.checked = kind === state.kind;
      input.addEventListener("change", () => {
        collect();
        state.kind = kind;
        renderFields({});
      });
      const span = document.createElement("span");
      span.textContent = spec.label;
      label.append(input, span);
      box.append(label);
    });
  };

  const fieldSpec = ([key, own]) => ({ key, ...(F[key] || {}), ...(own || {}) });

  const renderFields = (problems) => {
    const spec = KINDS[state.kind];
    $("[data-kind-help]").textContent = spec.help;
    const isFeed = state.kind === "feed";
    $("[data-feed]").hidden = !isFeed;
    $("[data-feed-test]").hidden = !isFeed;
    if (!isFeed) $("[data-feed-result]").hidden = true;
    if (isFeed) renderFeedSource();
    const box = $("[data-fields]");
    box.replaceChildren();
    spec.fields.map(fieldSpec).forEach((field) => {
      const wrap = document.createElement("label");
      wrap.className = `cb-field${field.type === "area" || field.type === "map" ? " cb-field--wide" : ""}`;
      const name = document.createElement("span");
      name.className = "cb-field__name";
      name.textContent = field.label + (field.optional ? " (optional)" : "");
      let control;
      if (field.type === "select") {
        control = document.createElement("select");
        field.options.forEach((option) => {
          const item = document.createElement("option");
          item.value = option;
          item.textContent = option;
          control.append(item);
        });
      } else if (field.type === "area" || field.type === "map") {
        control = document.createElement("textarea");
        control.rows = field.type === "map" ? 3 : 4;
      } else {
        control = document.createElement("input");
        control.type = field.key === "url" ? "url" : "text";
      }
      control.name = field.key;
      if (field.placeholder) control.placeholder = field.placeholder;
      const value = state.values[field.key];
      if (value !== undefined) {
        control.value = typeof value === "object" && !Array.isArray(value)
          ? JSON.stringify(value)
          : Array.isArray(value) ? value.join(", ") : String(value);
      }
      wrap.append(name, control);
      if (field.help) {
        const help = document.createElement("small");
        help.textContent = field.help;
        wrap.append(help);
      }
      const problem = problems[field.key];
      if (problem) {
        wrap.classList.add("is-invalid");
        control.setAttribute("aria-invalid", "true");
        const error = document.createElement("strong");
        error.className = "cb-field__error";
        error.textContent = problem;
        wrap.append(error);
      }
      box.append(wrap);
    });
    const first = box.querySelector(".is-invalid textarea, .is-invalid input, .is-invalid select");
    if (first) first.focus();
  };

  const collect = () => {
    $("[data-fields]").querySelectorAll("[name]").forEach((control) => {
      state.values[control.name] = control.value;
    });
  };

  const manifestFromForm = () => {
    collect();
    const manifest = {};
    KINDS[state.kind].fields.map(fieldSpec).forEach((field) => {
      const raw = String(state.values[field.key] ?? "").trim();
      if (!raw) return;
      if (field.type === "map") {
        try {
          manifest[field.key] = JSON.parse(raw);
        } catch (_error) {
          manifest[field.key] = raw; // the server names the problem on the right field
        }
      } else {
        manifest[field.key] = raw;
      }
    });
    return manifest;
  };

  // ADR-0052: a live feed from this GRP (filled from its registry) or from another source.
  const flattenFeed = (manifest) => {
    const { fetch = {}, adapter: _adapter, ...rest } = manifest;
    return { ...rest, url: fetch.url || "", records_path: fetch.records_path, fields: fetch.fields, as_of_field: fetch.as_of_field };
  };

  const renderFeedSource = () => {
    document.querySelectorAll("[data-feed-tab]").forEach((tab) => {
      tab.setAttribute("aria-selected", String(tab.dataset.feedTab === state.feedTab));
    });
    $("[data-feed-other]").hidden = state.feedTab !== "other";
    const box = $("[data-feed-platform]");
    box.hidden = state.feedTab !== "platform";
    if (state.feedTab !== "platform") return;
    box.replaceChildren();
    if (!state.platformFeeds) {
      box.textContent = "Loading this GRP's feeds…";
      return;
    }
    if (!state.platformFeeds.length) {
      box.textContent = "This GRP has no feeds to share.";
      return;
    }
    state.platformFeeds.forEach((feed) => {
      const card = document.createElement("div");
      card.className = `cb-feed__card${feed.available ? "" : " is-unavailable"}`;
      const title = document.createElement("strong");
      title.textContent = feed.label;
      const name = document.createElement("code");
      name.textContent = feed.dataset;
      const summary = document.createElement("p");
      summary.textContent = feed.summary;
      card.append(title, name, summary);
      if (feed.reason) {
        const why = document.createElement("p");
        why.className = "cb-feed__reason";
        why.textContent = `Not ready to send: ${feed.reason}`;
        card.append(why);
      }
      const use = document.createElement("button");
      use.type = "button";
      use.className = "button button--secondary";
      use.textContent = feed.available ? "Use this feed" : "Fill the form anyway";
      use.addEventListener("click", () => {
        state.values = flattenFeed(feed.manifest);
        state.feedTab = "other";
        renderFields({});
        showBanner(feed.available
          ? "The form is filled from this GRP's feed. Test it, then check and send."
          : "The form is filled, but this feed cannot be sent until the reason shown is fixed.", feed.available ? "info" : "bad");
      });
      card.append(use);
      box.append(card);
    });
  };

  const loadPlatformFeeds = async () => {
    if (!state.hubCode) return;
    try {
      const result = await GRP.request(`/api/v1/contributions/platform-feeds?hub_code=${encodeURIComponent(state.hubCode)}`);
      state.platformFeeds = result.feeds || [];
    } catch (error) {
      state.platformFeeds = [];
      showBanner(error.message, "bad");
    }
    if (state.kind === "feed") renderFeedSource();
  };

  const showFeedResult = (result) => {
    const box = $("[data-feed-result]");
    box.replaceChildren();
    box.hidden = false;
    box.className = `cb-feed-result ${result.ok ? "is-ok" : "is-bad"}`;
    const head = document.createElement("strong");
    head.textContent = result.ok
      ? `Global Risk would read ${result.count} records and return the last ${result.returned_by_default} by default.`
      : `Global Risk could not use this feed: ${result.problem}`;
    box.append(head);
    if (!result.ok) return;
    const facts = document.createElement("dl");
    facts.append(detail("Order", result.order));
    if (result.as_of) facts.append(detail("Newest record", result.as_of));
    box.append(facts);
    (result.notes || []).forEach((note) => {
      const p = document.createElement("p");
      p.textContent = note;
      box.append(p);
    });
    const sample = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "The records a default query returns";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(result.last, null, 2);
    sample.append(summary, pre);
    box.append(sample);
  };

  const testFeed = async () => {
    const manifest = manifestFromForm();
    let fields = manifest.fields;
    if (typeof fields === "string") {
      showFeedResult({ ok: false, problem: "Fields to keep must be a mapping, for example {\"name\": \"name\"}." });
      return;
    }
    if (!manifest.url || !manifest.records_path || !fields) {
      showFeedResult({ ok: false, problem: "Give the feed address, the record list and the fields to keep first." });
      return;
    }
    const button = $("[data-feed-test]");
    button.disabled = true;
    button.textContent = "Testing…";
    try {
      fields = Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, String(v)]));
      showFeedResult(await GRP.request("/api/v1/contributions/feed-check", {
        method: "POST",
        body: { hub_code: state.hubCode, url: manifest.url, records_path: manifest.records_path, fields, as_of_field: manifest.as_of_field || null },
      }));
    } catch (error) {
      showFeedResult({ ok: false, problem: error.message });
    } finally {
      button.disabled = false;
      button.textContent = "Test the feed";
    }
  };

  const showBanner = (text, kind = "info") => {
    const banner = $("[data-banner]");
    banner.textContent = text;
    banner.className = `cb-banner is-${kind}`;
    banner.hidden = !text;
  };

  // A layer or dataset name Global Risk already holds cannot be sent again (ADR-0032 amendment):
  // contributions never overwrite. Say so in a dialog, never a browser alert.
  const showDuplicate = (duplicate) => {
    if (!duplicate) return;
    const dialog = $("[data-duplicate]");
    $("[data-duplicate-name]").textContent = duplicate.name;
    $("[data-duplicate-text]").textContent = duplicate.message;
    const facts = $("[data-duplicate-facts]");
    facts.replaceChildren();
    if (duplicate.state) facts.append(detail("State in GRP", duplicate.state));
    if (duplicate.contribution_id) facts.append(detail("Global Risk ID", duplicate.contribution_id));
    if (duplicate.submitted_at) facts.append(detail("Sent", GRP.formatTime(duplicate.submitted_at)));
    facts.hidden = !facts.childNodes.length;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  };

  const check = async () => {
    const manifest = manifestFromForm();
    $("[data-confirm]").hidden = true;
    const result = await GRP.request("/api/v1/contributions", {
      method: "POST",
      body: { hub_code: state.hubCode, kind: state.kind, manifest, preview: true },
    });
    renderFields(result.problems || {});
    if (result.duplicate) {
      showBanner(result.duplicate.message, "bad");
      showDuplicate(result.duplicate);
      return;
    }
    if (Object.keys(result.problems || {}).length) {
      showBanner("Fix the marked fields, then check again.", "bad");
      return;
    }
    showBanner("");
    state.checked = result;
    const notes = $("[data-notes]");
    notes.replaceChildren(...(result.notes || []).map((note) => {
      const item = document.createElement("li");
      item.textContent = note;
      return item;
    }));
    $("[data-manifest]").textContent = JSON.stringify(result.manifest, null, 2);
    // Worded to stay true whether Global Risk auto-approves (as on 30 Sep 2026) or reviews first.
    $("[data-warning]").textContent = state.kind === "feed"
      ? "Global Risk approves contributions at once on this server: the feed will be live for every Global Risk user, and only a Global Risk reviewer can remove it. It fetches the address again on later reads, so the address must stay up."
      : state.kind === "weights"
      ? "This changes the flood risk levels every Global Risk user sees, everywhere. Global Risk may apply it as soon as it arrives. The reply says whether it was approved or is waiting for a reviewer. An approved contribution may only be removable by a Global Risk reviewer."
      : "Global Risk may publish this to every Global Risk user as soon as it arrives. The reply says whether it was approved or is waiting for a reviewer. An approved contribution may only be removable by a Global Risk reviewer.";
    $("[data-agree-text]").textContent = state.kind === "weights"
      ? "I understand Global Risk may change risk levels for every Global Risk user, and that I may not be able to take it back."
      : "I understand Global Risk may make this available to every Global Risk user, and that I may not be able to take it back.";
    $("[data-agree]").checked = false;
    $("[data-send]").disabled = true;
    $("[data-confirm]").hidden = false;
    $("[data-confirm]").scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const send = async () => {
    if (!state.checked) return;
    const button = $("[data-send]");
    button.disabled = true;
    try {
      const result = await GRP.request("/api/v1/contributions", {
        method: "POST",
        body: { hub_code: state.hubCode, kind: state.kind, manifest: state.checked.manifest, preview: false },
      });
      if (!result.sent) {
        renderFields(result.problems || {});
        $("[data-confirm]").hidden = true;
        if (result.duplicate) {
          showBanner(result.duplicate.message, "bad");
          showDuplicate(result.duplicate);
        }
        return;
      }
      const row = result.contribution;
      GRP.jobs.track({
        id: `contribution-${row.id}`,
        label: `Global Risk contribution "${row.title || row.name}"`,
        statusPath: `/api/v1/contributions/${row.id}`,
        href: "/contribute.html",
        ownerPath: "/contribute.html",
      });
      $("[data-confirm]").hidden = true;
      state.checked = null;
      showBanner("Sent. Global Risk is downloading and checking the file; this can take a few minutes. You can leave this page: the top bar will tell you when it lands.", "info");
      await loadList();
    } catch (error) {
      showBanner(error.message, "bad");
      if (error.code === "SIG_REAUTH_REQUIRED") {
        window.setTimeout(() => window.location.assign("/api/v1/auth/login"), 1500);
      }
    } finally {
      button.disabled = !$("[data-agree]").checked;
    }
  };

  const tryQuestion = (row) => {
    const name = (row.response && row.response.layer) || row.name;
    if (row.kind === "raster" && String(name).startsWith("population_")) {
      return "How many people in Bang Sue District, Bangkok live in the 100-year flood zone, by severity?";
    }
    if (row.kind === "vector") {
      return `How many ${String(name).replace(/_/g, " ")} in Bang Sue District, Bangkok would be at risk in a 100-year flood?`;
    }
    return "Show the available flood information for Bang Sue District, Bangkok.";
  };

  const detail = (label, value) => {
    const row = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    row.append(dt, dd);
    return row;
  };

  const renderList = () => {
    const list = $("[data-list]");
    list.replaceChildren();
    $("[data-empty]").hidden = state.rows.length > 0;
    state.rows.forEach((row) => {
      const [statusText, statusClass] = STATUS[row.status] || [row.status, ""];
      const item = document.createElement("li");
      item.className = "cb-item";
      const head = document.createElement("div");
      head.className = "cb-item__head";
      const title = document.createElement("strong");
      title.textContent = row.title || row.name || "(untitled)";
      const pill = document.createElement("span");
      pill.className = `cb-status ${statusClass}`;
      pill.textContent = statusText;
      head.append(title, pill);
      const meta = document.createElement("p");
      meta.className = "cb-item__meta";
      meta.textContent = [
        (KINDS[row.kind] || {}).label || row.kind,
        row.name,
        row.mine ? "sent by you" : "sent by a colleague",
        row.created_at ? GRP.formatTime(row.created_at) : "",
      ].filter(Boolean).join(" · ");
      item.append(head, meta);

      const facts = document.createElement("dl");
      facts.className = "cb-facts";
      if (row.contribution_id) facts.append(detail("Global Risk ID", row.contribution_id));
      if (row.feature_count) facts.append(detail("Points checked by GRP", row.feature_count.toLocaleString()));
      if (row.file_sha256) facts.append(detail("File SHA-256", `${row.file_sha256.slice(0, 16)}…`));
      const response = row.response || {};
      if (response.observed && response.observed.features) {
        facts.append(detail("Global Risk read", `${response.observed.features.toLocaleString()} features`));
      }
      if (response.reviewer_label) facts.append(detail("Review", response.reviewer_label));
      if (response.decision_note) facts.append(detail("Decision", response.decision_note));
      if (facts.childNodes.length) item.append(facts);

      if (row.error) {
        const error = document.createElement("p");
        error.className = "cb-item__error";
        error.textContent = row.error;
        item.append(error);
      }
      if (row.problems && row.problems.length) {
        const problems = document.createElement("ul");
        problems.className = "cb-item__problems";
        row.problems.forEach((problem) => {
          const li = document.createElement("li");
          li.textContent = problem;
          problems.append(li);
        });
        item.append(problems);
      }
      if (row.status === "approved" && response.how_to_test) {
        const how = document.createElement("p");
        how.className = "cb-item__how";
        how.textContent = `How Global Risk says to test it: ${response.how_to_test}`;
        item.append(how);
      }

      const actions = document.createElement("div");
      actions.className = "cb-item__actions";
      const canRefresh = row.mine && (
        ["submitting", "checking", "staged", "approved"].includes(row.status)
        || row.error_code === "SUBMIT_UNCONFIRMED"
      );
      if (canRefresh) {
        const refresh = document.createElement("button");
        refresh.type = "button";
        refresh.className = "button button--secondary button--compact";
        refresh.textContent = "Check on Global Risk";
        refresh.addEventListener("click", async () => {
          refresh.disabled = true;
          try {
            await GRP.request(`/api/v1/contributions/${row.id}/refresh`, { method: "POST" });
            await loadList();
          } catch (error) {
            showBanner(error.message, "bad");
            refresh.disabled = false;
          }
        });
        actions.append(refresh);
      }
      if (["declined", "failed", "rejected"].includes(row.status)) {
        const fix = document.createElement("button");
        fix.type = "button";
        fix.className = "button button--secondary button--compact";
        fix.textContent = "Fix and send again";
        fix.addEventListener("click", () => {
          state.kind = row.kind;
          state.values = { ...row.manifest };
          document.querySelectorAll("[data-kinds] input").forEach((input) => {
            input.checked = input.value === row.kind;
          });
          renderFields(row.field_problems || {});
          $("[data-confirm]").hidden = true;
          $("[data-form]").scrollIntoView({ behavior: "smooth", block: "start" });
        });
        actions.append(fix);
      }
      if (row.status === "approved" && row.kind !== "weights") {
        const use = document.createElement("a");
        use.className = "button button--primary button--compact";
        use.href = `/planning.html?ask=${encodeURIComponent(tryQuestion(row))}`;
        use.textContent = "Try it in Planning";
        actions.append(use);
      }
      if (actions.childNodes.length) item.append(actions);
      list.append(item);
    });
  };

  const loadList = async () => {
    if (!state.hubCode) return;
    const result = await GRP.request(`/api/v1/contributions?hub_code=${encodeURIComponent(state.hubCode)}`);
    state.rows = result.contributions || [];
    renderList();
    window.clearTimeout(state.timer);
    if (state.rows.some((row) => row.state === "running")) {
      state.timer = window.setTimeout(() => loadList().catch(() => {}), 4000);
    }
  };

  // Everything this SERVIR sign-in sent to Global Risk, from this page or any other app.
  const cell = (text, className) => {
    const td = document.createElement("td");
    if (className) td.className = className;
    td.textContent = text;
    return td;
  };

  const loadGlobalRisk = async () => {
    const button = $("[data-gr-reload]");
    const empty = $("[data-gr-empty]");
    button.disabled = true;
    $("[data-gr-checked]").textContent = "Asking Global Risk…";
    try {
      const result = await GRP.request(`/api/v1/contributions/on-global-risk?hub_code=${encodeURIComponent(state.hubCode)}`);
      const rows = result.contributions || [];
      const body = $("[data-gr-rows]");
      body.replaceChildren();
      rows.forEach((row) => {
        const tr = document.createElement("tr");
        const layer = document.createElement("td");
        const name = document.createElement("code");
        name.textContent = row.name || "(unnamed)";
        layer.append(name);
        if (row.is_test) {
          const tag = document.createElement("span");
          tag.className = "cb-tag is-test";
          tag.textContent = "TEST";
          tag.title = "A test copy: not for decisions";
          layer.append(" ", tag);
        }
        if (row.title) {
          const title = document.createElement("small");
          title.textContent = row.title;
          layer.append(title);
        }
        const [statusText, statusClass] = STATUS[row.status] || [row.status || "unknown", ""];
        const status = document.createElement("td");
        const pill = document.createElement("span");
        pill.className = `cb-status ${statusClass}`;
        pill.textContent = statusText;
        status.append(pill);
        tr.append(
          layer,
          status,
          cell(row.live ? "Yes" : "No", row.live ? "is-live" : ""),
          cell(row.features != null ? Number(row.features).toLocaleString() : "—"),
          cell(row.sent_from === "grp" ? "This page (GRP)" : "Another app or agent"),
          cell(row.auto_approved ? "Auto-approved, no human review" : (row.decision_note || "—")),
          cell(row.created_at ? GRP.formatTime(row.created_at) : "—"),
          cell(row.contribution_id || "—", "cb-mono"),
        );
        body.append(tr);
      });
      $("[data-gr-wrap]").hidden = rows.length === 0;
      empty.hidden = rows.length > 0;
      empty.textContent = "Your SERVIR account has not contributed anything to Global Risk yet.";
      $("[data-gr-checked]").textContent = `Checked ${GRP.formatTime(result.checked_at)}. ${rows.length} contribution${rows.length === 1 ? "" : "s"}, ${rows.filter((row) => row.live).length} used in answers.`;
    } catch (error) {
      $("[data-gr-checked]").textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };

  const checkServir = async () => {
    const pill = $("[data-servir]");
    try {
      const status = await GRP.request("/api/v1/planning/status");
      state.servir = Boolean(status.sig_connected);
      if (status.sig_connected) {
        pill.textContent = "SERVIR signed in";
        pill.className = "status-pill";
      } else {
        pill.textContent = "";
        const link = document.createElement("a");
        link.href = "/api/v1/auth/login";
        link.textContent = "Sign in with SERVIR to send";
        pill.append(link);
        pill.className = "status-pill is-warning";
      }
    } catch (_error) {
      pill.textContent = "SERVIR status unknown";
    }
  };

  $("[data-form]").addEventListener("submit", (event) => {
    event.preventDefault();
    check().catch((error) => showBanner(error.message, "bad"));
  });
  $("[data-reset]").addEventListener("click", () => {
    state.values = {};
    $("[data-confirm]").hidden = true;
    renderFields({});
  });
  $("[data-agree]").addEventListener("change", (event) => {
    $("[data-send]").disabled = !event.currentTarget.checked;
  });
  $("[data-send]").addEventListener("click", () => send());
  $("[data-feed-test]").addEventListener("click", () => testFeed());
  document.querySelectorAll("[data-feed-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      collect();
      state.feedTab = tab.dataset.feedTab;
      renderFeedSource();
    });
  });
  $("[data-edit]").addEventListener("click", () => {
    $("[data-confirm]").hidden = true;
  });
  $("[data-reload]").addEventListener("click", () => loadList().catch((error) => showBanner(error.message, "bad")));
  $("[data-gr-reload]").addEventListener("click", () => loadGlobalRisk());

  GRP.bindSignOut();
  kindButtons();
  renderFields({});
  GRP.me()
    .then(async (identity) => {
      const membership = identity.memberships.find((m) => planningRoles.has(m.role));
      if (!membership) {
        showBanner("You need a planning role in a Hub to share data with Global Risk. A Platform Admin role alone is not enough.", "bad");
        $("[data-check]").disabled = true;
        $("[data-hub-name]").textContent = "No Hub role";
        return;
      }
      state.hubCode = membership.hub_code;
      loadPlatformFeeds();
      $("[data-hub-name]").textContent = membership.hub_name;
      await Promise.all([checkServir(), loadList()]);
      if (state.servir) {
        await loadGlobalRisk();
      } else {
        $("[data-gr-checked]").textContent = "Sign in with SERVIR to see what your account has on Global Risk.";
      }
    })
    .catch((error) => {
      if (error.status === 401 || error.status === 403) {
        window.location.replace("/");
        return;
      }
      if (error.status === 404) {
        showBanner("Sharing with Global Risk runs only where the planning assistant runs (local development for now).", "bad");
        $("[data-check]").disabled = true;
      } else {
        showBanner(error.message, "bad");
      }
    });
})();
