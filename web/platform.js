(() => {
  const $ = (selector) => document.querySelector(selector);
  const statusText = $("[data-platform-status]");

  const labels = {
    api: "API",
    database: "Database",
    environment: "Environment",
    ai_feature_enabled: "AI build switch",
    ai_provider_key_present: "AI provider key",
    ai_model: "AI model",
    langfuse_configured: "Langfuse",
    sig_service_login_configured: "SIG service login",
    worker: "Worker",
  };

  const showValue = (value) => {
    if (value === true) return "yes";
    if (value === false) return "no";
    return value === null || value === undefined ? "not set" : String(value);
  };

  const loadHealth = () =>
    GRP.request("/api/v1/platform/health").then((health) => {
      const list = $("[data-health]");
      list.replaceChildren();
      Object.entries(labels).forEach(([key, label]) => {
        const term = document.createElement("dt");
        const detail = document.createElement("dd");
        term.textContent = label;
        detail.textContent = showValue(health[key]);
        detail.dataset.ok = String(health[key] === true || health[key] === "up" || health[key] === "ready");
        list.append(term, detail);
      });
    });

  const loadSetting = () =>
    GRP.request("/api/v1/platform/ai-usage/setting").then((setting) => {
      $("[data-token-limit]").value = setting.token_limit_per_person || 200000;
      $("[data-ai-enabled]").value = String(setting.ai_enabled);
      const pill = $("[data-setting-state]");
      const on = setting.ai_enabled && setting.ai_feature_enabled && setting.token_limit_per_person;
      pill.textContent = on ? "AI on" : "AI off";
      pill.dataset.state = on ? "active" : "ai_off";
      $("[data-setting-changed]").textContent = setting.changed_at
        ? `Last changed ${GRP.formatTime(setting.changed_at)} (Bangkok).`
        : "No token limit has been set. AI stays off until one is set (AI-13).";
      if (!setting.ai_feature_enabled) {
        $("[data-setting-changed]").textContent +=
          " The server build switch AI_FEATURE_ENABLED is false, so AI stays off.";
      }
    });

  const loadRiskRecipe = () =>
    GRP.request("/api/v1/platform/risk-recipe").then((recipe) => {
      $("[data-risk-population]").value = recipe.weights.population * 100;
      $("[data-risk-buildings]").value = recipe.weights.building_density * 100;
      $("[data-risk-roads]").value = recipe.weights.road_distance * 100;
      $("[data-risk-version]").value = recipe.version;
      $("[data-risk-owner]").value = recipe.science_owner;
      $("[data-risk-source]").value = recipe.source_ref;
      $("[data-risk-reason]").value = recipe.change_reason;
      const pill = $("[data-risk-recipe-state]");
      pill.textContent = "Approved";
      pill.dataset.state = "active";
      $("[data-risk-recipe-status]").textContent =
        `Active ${recipe.version} · approved ${GRP.formatTime(recipe.approved_at)} (Bangkok).`;
    });

  const loadPeople = () =>
    GRP.request("/api/v1/platform/ai-usage/people").then((payload) => {
      const body = $("[data-people]");
      body.replaceChildren();
      payload.people.forEach((person) => {
        const row = document.createElement("tr");
        const who = GRP.cell(row, "");
        const name = document.createElement("strong");
        const email = document.createElement("span");
        name.textContent = person.display_name || person.email;
        email.textContent = person.email;
        who.append(name, email);
        GRP.cell(row, GRP.tokens(person.tokens_used));
        GRP.cell(row, person.token_limit ? GRP.tokens(person.tokens_remaining) : "–");
        const status = GRP.cell(row, "");
        const pill = document.createElement("span");
        pill.className = "status-pill";
        pill.dataset.state = person.status;
        pill.textContent = person.status.replaceAll("_", " ");
        status.append(pill);
        GRP.cell(row, GRP.formatDate(person.reset_at));
        const action = GRP.cell(row, "");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "button button--secondary";
        button.textContent = "Reset now";
        button.disabled = person.tokens_used === 0;
        button.addEventListener("click", async () => {
          button.disabled = true;
          try {
            const result = await GRP.request(
              `/api/v1/platform/ai-usage/people/${encodeURIComponent(person.user_id)}/reset`,
              { method: "POST" },
            );
            $("[data-people-status]").textContent =
              `Reset ${person.email}: ${GRP.tokens(result.tokens_used_before)} tokens cleared for this month.`;
            await Promise.all([loadPeople(), loadLog()]);
          } catch (error) {
            $("[data-people-status]").textContent = error.message;
            button.disabled = false;
          }
        });
        action.append(button);
        body.append(row);
      });
      if (payload.people.length === 0) GRP.emptyRow(body, 6, "No active people.");
    });

  const loadHubs = () =>
    GRP.request("/api/v1/platform/hubs").then((payload) => {
      const body = $("[data-hubs]");
      body.replaceChildren();
      payload.hubs.forEach((hub) => {
        const row = document.createElement("tr");
        const who = GRP.cell(row, "");
        const name = document.createElement("strong");
        const code = document.createElement("span");
        name.textContent = hub.name;
        code.textContent = hub.code;
        who.append(name, code);
        GRP.cell(row, hub.status);
        GRP.cell(row, String(hub.active_members));
        const action = GRP.cell(row, "");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "button button--secondary";
        const closing = hub.status === "active";
        button.textContent = closing ? "Close Hub" : "Reopen Hub";
        button.addEventListener("click", async () => {
          button.disabled = true;
          try {
            const result = await GRP.request(`/api/v1/platform/hubs/${encodeURIComponent(hub.code)}`, {
              method: "PATCH",
              body: { status: closing ? "closed" : "active" },
            });
            $("[data-hub-status]").textContent = `${hub.code}: ${result.message}`;
            await Promise.all([loadHubs(), loadLog()]);
          } catch (error) {
            $("[data-hub-status]").textContent = error.message;
            button.disabled = false;
          }
        });
        action.append(button);
        body.append(row);
      });
    });

  const loadLog = () =>
    GRP.request("/api/v1/admin/audit-events?limit=100").then((payload) => {
      const body = $("[data-log]");
      body.replaceChildren();
      payload.events.forEach((event) => {
        const row = document.createElement("tr");
        GRP.cell(row, GRP.formatTime(event.occurred_at));
        GRP.cell(row, event.actor);
        GRP.cell(row, event.action.replaceAll("_", " "));
        GRP.cell(row, event.result);
        body.append(row);
      });
      if (payload.events.length === 0) GRP.emptyRow(body, 4, "No security events yet.");
    });

  $("[data-setting-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = $("[data-setting-status]");
    status.textContent = "Saving…";
    try {
      await GRP.request("/api/v1/platform/ai-usage/setting", {
        method: "PUT",
        body: {
          token_limit_per_person: Number($("[data-token-limit]").value),
          ai_enabled: $("[data-ai-enabled]").value === "true",
        },
      });
      status.textContent = "AI setting saved. It applies from the next AI request.";
      await Promise.all([loadSetting(), loadPeople(), loadLog(), loadHealth()]);
    } catch (error) {
      status.textContent = error.message;
    }
  });

  $("[data-risk-recipe-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = $("[data-risk-recipe-status]");
    const button = event.submitter;
    if (button) button.disabled = true;
    status.textContent = "Saving approved recipe…";
    try {
      await GRP.request("/api/v1/platform/risk-recipe", {
        method: "PUT",
        body: {
          version: $("[data-risk-version]").value.trim(),
          population_weight: Number($("[data-risk-population]").value) / 100,
          building_density_weight: Number($("[data-risk-buildings]").value) / 100,
          road_distance_weight: Number($("[data-risk-roads]").value) / 100,
          science_owner: $("[data-risk-owner]").value.trim(),
          source_ref: $("[data-risk-source]").value.trim(),
          change_reason: $("[data-risk-reason]").value.trim(),
        },
      });
      await Promise.all([loadRiskRecipe(), loadLog()]);
      status.textContent += " New SIG evidence requests will pin this version.";
    } catch (error) {
      status.textContent = error.message;
    } finally {
      if (button) button.disabled = false;
    }
  });

  $("[data-activate-mvp1]").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const status = $("[data-activation-status]");
    button.disabled = true;
    status.textContent = "Activating the approved baseline…";
    try {
      const result = await GRP.request("/api/v1/platform/mvp1/activate", { method: "POST" });
      status.textContent =
        `Activated RP100 for ${result.supported_districts.toLocaleString()} districts. ` +
        "No-data cells remain Unable to assess.";
      await loadLog();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

  $("[data-test-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = $("[data-test-status]");
    const reply = $("[data-test-reply]");
    const button = event.submitter;
    if (button) button.disabled = true;
    status.textContent = "Calling the AI gateway…";
    reply.hidden = true;
    try {
      const result = await GRP.request("/api/v1/ai/test-call", {
        method: "POST",
        body: { message: $("[data-test-message]").value.trim() },
      });
      reply.textContent = result.answer;
      reply.hidden = false;
      status.textContent = `${result.label} Model ${result.model}: ${GRP.tokens(result.input_tokens)} input + ${GRP.tokens(result.output_tokens)} output tokens. ${GRP.allowanceMessage(result.usage)}`;
      await Promise.all([loadPeople(), loadLog()]);
    } catch (error) {
      status.textContent = error.message;
    } finally {
      if (button) button.disabled = false;
    }
  });

  $("[data-hub-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await GRP.request("/api/v1/platform/hubs", {
        method: "POST",
        body: { code: $("[data-hub-code]").value.trim().toLowerCase(), name: $("[data-hub-name]").value.trim() },
      });
      $("[data-hub-status]").textContent = result.message;
      event.target.reset();
      await Promise.all([loadHubs(), loadLog()]);
    } catch (error) {
      $("[data-hub-status]").textContent = error.message;
    }
  });

  $("[data-refresh-health]").addEventListener("click", () => loadHealth());
  $("[data-refresh-people]").addEventListener("click", () => loadPeople());
  $("[data-refresh-log]").addEventListener("click", () => loadLog());

  GRP.bindSignOut();

  GRP.me()
    .then((identity) => {
      if (!identity.is_platform_admin) {
        statusText.textContent = "Platform Admin access is required for this page.";
        return;
      }
      statusText.textContent = `Signed in as ${identity.email}. Changes here are written to the security log.`;
      $("[data-platform-content]").hidden = false;
      return Promise.all([
        loadHealth(), loadRiskRecipe(), loadSetting(), loadPeople(), loadHubs(), loadLog(),
      ]);
    })
    .catch((error) => {
      if (error.status === 401 || error.status === 403) {
        window.location.replace("/admin-login.html");
        return;
      }
      statusText.textContent = error.message;
    });
})();
