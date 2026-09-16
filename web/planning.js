(() => {
  const $ = (selector) => document.querySelector(selector);
  const form = $("[data-question-form]");
  const placeInput = $("[data-place]");
  const questionInput = $("[data-question]");
  const publishInput = $("[data-publish-receipt]");
  const runButton = $("[data-run-button]");
  const status = $("[data-planning-status]");
  const chatHistory = $("[data-chat-history]");
  const conversation = $(".assistant-conversation");
  const sigMap = $("[data-sig-map]");
  const showOsm = $("[data-show-osm]");
  const mapState = $("[data-map-state]");
  const history = [];
  let hubCode = null;
  let outline = null;

  const map = window.L.map("risk-map", { zoomControl: true }).setView([15.2, 101.0], 6);
  window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const safeHttps = (value) => {
    try {
      const url = new URL(value);
      return url.protocol === "https:" ? url.href : null;
    } catch (_error) {
      return null;
    }
  };

  const showAllowance = (usage) => {
    const line = $("[data-allowance]");
    line.textContent = GRP.allowanceMessage(usage);
    line.classList.toggle("is-low", GRP.isLow(usage));
  };

  const setBusy = (busy, text = "Thinking…") => {
    runButton.disabled = busy;
    questionInput.disabled = busy;
    runButton.textContent = busy ? text : "Send message";
  };

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

  const fillList = (list, values, format) => {
    list.replaceChildren();
    (values || []).forEach((value) => {
      const item = document.createElement("li");
      item.textContent = format(value);
      list.append(item);
    });
  };

  // Orientation only: outline from OpenStreetMap search. SIG's analysis area is stated in text.
  const outlinePlace = async (place) => {
    const url = `https://nominatim.openstreetmap.org/search?format=geojson&polygon_geojson=1&limit=1&countrycodes=th&q=${encodeURIComponent(place)}`;
    try {
      const response = await fetch(url, { headers: { Accept: "application/geo+json" } });
      const data = await response.json();
      if (outline) outline.remove();
      if (!data.features || data.features.length === 0) return false;
      outline = window.L.geoJSON(data.features[0], {
        style: { color: "#0b453d", weight: 2, fillColor: "#b8e063", fillOpacity: 0.18 },
      }).addTo(map);
      map.fitBounds(outline.getBounds(), { padding: [24, 24] });
      return true;
    } catch (_error) {
      return false;
    }
  };

  const showOsmMap = () => {
    sigMap.hidden = true;
    sigMap.removeAttribute("src");
    showOsm.hidden = true;
    window.setTimeout(() => map.invalidateSize(), 0);
  };

  const showEvidence = async (payload) => {
    $("[data-map-place]").textContent = (payload.area && payload.area.sig_place) || placeInput.value;
    const evidence = $("[data-map-evidence]");
    evidence.hidden = false;
    const area = payload.area || {};
    $("[data-area]").textContent = area.sig_area
      ? `SIG analysis area: ${area.sig_area}. ${area.reason}.`
      : area.reason || "";
    const metrics = $("[data-metrics]");
    metrics.replaceChildren();
    const counts = (payload.stats && payload.stats.counts) || {};
    Object.entries(counts).forEach(([name, value]) => {
      const card = document.createElement("article");
      const label = document.createElement("span");
      const total = document.createElement("strong");
      label.textContent = `${name.replaceAll("_", " ")} exposed`;
      total.textContent =
        typeof value.exposed === "number"
          ? `${value.exposed} / ${value.total}`
          : `${value.exposed_km || 0} / ${value.total_km || 0} km`;
      card.append(label, total);
      metrics.append(card);
    });
    fillList($("[data-citations]"), payload.citations, (c) => `[${c.n}] ${c.title}: ${c.text}`);
    fillList($("[data-trace]"), payload.trace, (t) => `${t.step}: ${t.detail}`);
    fillList($("[data-gaps]"), payload.gaps, (gap) => `Gap: ${gap}`);

    const mapUrl = safeHttps(payload.map_url);
    const outlined = await outlinePlace((area.sig_place || placeInput.value) + ", Thailand");
    if (mapUrl) {
      sigMap.src = mapUrl;
      sigMap.hidden = false;
      showOsm.hidden = false;
      mapState.textContent = "SIG receipt hazard map";
    } else {
      showOsmMap();
      mapState.textContent = outlined
        ? "OSM outline for orientation · tick Publish to see SIG's hazard map"
        : "No outline found · tick Publish to see SIG's hazard map";
    }
  };

  const clearEvidence = (text) => {
    showOsmMap();
    $("[data-map-evidence]").hidden = true;
    mapState.textContent = text;
  };

  document.querySelectorAll("[data-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      questionInput.value = button.dataset.suggestion;
      questionInput.focus();
    });
  });
  showOsm.addEventListener("click", () => {
    showOsmMap();
    mapState.textContent = "OpenStreetMap";
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = questionInput.value.trim();
    if (!message || !hubCode) return;
    const publish = publishInput.checked;
    const priorHistory = history.slice(-8);
    appendMessage("user", message);
    questionInput.value = "";
    setBusy(true, publish ? "Checking and publishing…" : "Thinking…");
    status.textContent = "Asking the assistant…";
    try {
      const payload = await GRP.request("/api/v1/planning/chat", {
        method: "POST",
        body: {
          message,
          place: placeInput.value.trim() || null,
          hub_code: hubCode,
          publish_receipt: publish,
          history: priorHistory,
        },
      });
      appendMessage("assistant", payload.answer, payload);
      history.push({ role: "user", text: message }, { role: "assistant", text: payload.answer.slice(0, 1200) });
      if (payload.usage) showAllowance(payload.usage);
      if (payload.mode === "sig_evidence") {
        await showEvidence(payload);
        status.textContent = payload.receipt
          ? `Public SIG receipt ${payload.receipt.receipt_id} issued. Review before acting.`
          : "Unverified draft from SIG evidence: not gate-checked, no receipt.";
      } else if (payload.mode === "area_rejected") {
        clearEvidence("Stopped: area not confirmed");
        status.textContent = "Stopped safely: SIG could not confirm the district boundary.";
      } else if (payload.mode === "gate_blocked") {
        clearEvidence("Blocked by SIG evidence gate");
        status.textContent = "SIG's gate refused the draft; nothing was published.";
      } else {
        status.textContent = payload.label;
      }
    } catch (error) {
      appendMessage("assistant", error.message, { label: error.code || "Error" });
      if (error.code === "SIG_REAUTH_REQUIRED") {
        status.textContent = "Signing in with SERVIR again to reconnect SIG…";
        window.setTimeout(() => window.location.assign("/api/v1/auth/login"), 1200);
        return;
      }
      status.textContent = error.message;
      GRP.request("/api/v1/me/ai-usage").then(showAllowance).catch(() => {});
    } finally {
      setBusy(false);
    }
  });

  GRP.bindSignOut();

  Promise.all([GRP.request("/api/v1/me"), GRP.request("/api/v1/planning/status")])
    .then(([identity, planning]) => {
      $("[data-user-name]").textContent = identity.display_name || identity.email;
      showAllowance(planning.usage);
      const banner = $("[data-banner]");
      if (!planning.available) {
        banner.textContent = "The planning chat is only available in the local Docker Desktop test.";
      } else if (!planning.can_plan) {
        banner.textContent =
          "You need a Planner or Hub Admin role in a Hub to use planning. A Platform Admin role alone is not enough.";
      } else {
        hubCode = planning.hubs[0].hub_code;
        $("[data-hub-name]").textContent = `${planning.hubs[0].hub_name} · ${planning.hubs[0].role}`;
        if (!planning.sig_connected) {
          banner.textContent =
            "SIG is not connected for this session (the server restarted). General chat works; sign out and in again for flood evidence.";
        }
      }
      banner.hidden = !banner.textContent;
      runButton.disabled = !hubCode;
    })
    .catch((error) => {
      if (error.status === 401 || error.status === 403) {
        window.location.replace("/");
        return;
      }
      status.textContent = error.message;
    });
})();
