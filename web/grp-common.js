// Shared helpers for signed-in GRP screens: CSRF header, typed errors, sign-out.
window.GRP = (() => {
  const csrfHeaders = () => {
    const match = document.cookie.match(/(?:^|;\s*)grp_csrf=([^;]+)/);
    return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
  };

  const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  const request = async (path, { method = "GET", body, idempotencyKey, retried = false } = {}) => {
    const headers = { Accept: "application/json", ...csrfHeaders() };
    if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    // Rate limited while loading a page: wait as told (at most 10 s) and read once more.
    if (response.status === 429 && method === "GET" && !retried) {
      const seconds = Math.min(10, Math.max(1, Number(response.headers.get("Retry-After")) || 3));
      await wait(seconds * 1000);
      return request(path, { method, body, idempotencyKey, retried: true });
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(
        (payload.error && payload.error.message) || `Request failed (${response.status})`,
      );
      error.status = response.status;
      error.code = payload.error && payload.error.code;
      throw error;
    }
    return payload;
  };

  const bindSignOut = () => {
    document.querySelectorAll("[data-sign-out]").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          Object.keys(sessionStorage)
            .filter((key) => key.startsWith("grp."))
            .forEach((key) => sessionStorage.removeItem(key));
        } catch (_error) {
          // Nothing stored or storage blocked.
        }
        try {
          await request("/api/v1/auth/logout", { method: "POST" });
        } finally {
          window.location.assign("/");
        }
      });
    });
  };

  const formatDate = (iso) =>
    new Date(iso).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "long",
      year: "numeric",
      timeZone: "Asia/Bangkok",
    });

  const formatTime = (iso) =>
    new Date(iso).toLocaleString("en-GB", { timeZone: "Asia/Bangkok", hour12: false });

  const tokens = (value) => Number(value || 0).toLocaleString("en-GB");

  // Exact Section 10.6 wording.
  const allowanceMessage = (usage) => {
    const reset = formatDate(usage.reset_at);
    if (usage.status === "ai_off") {
      return "AI features are turned off. Maps, analysis and downloads still work.";
    }
    if (usage.status === "limit_reached") {
      return `You have used your AI allowance for this month. It resets on ${reset}. Maps, analysis and downloads still work.`;
    }
    return `AI allowance: ${tokens(usage.tokens_remaining)} tokens left. Resets on ${reset}.`;
  };

  const isLow = (usage) =>
    usage.status === "active" &&
    Boolean(usage.token_limit) &&
    usage.tokens_remaining <= usage.token_limit * 0.1;

  const cell = (row, value) => {
    const td = document.createElement("td");
    td.textContent = value;
    row.append(td);
    return td;
  };

  const emptyRow = (body, columns, text) => {
    const row = document.createElement("tr");
    const td = cell(row, text);
    td.colSpan = columns;
    body.append(row);
  };

  // One top bar for every signed-in page: same items, same order, always left-aligned.
  const NAV_ITEMS = [
    { key: "planning", label: "Planning", href: "/planning.html" },
    { key: "assessments", label: "Assessments", href: "/assessments.html" },
    { key: "access", label: "My access", href: "/workspace.html" },
    { key: "admin", label: "Administration", href: "/workspace.html#admin-panel", attr: "data-admin-menu", hidden: true },
    { key: "platform", label: "Platform", href: "/platform.html", attr: "data-platform-menu", hidden: true },
  ];
  const PAGE_KEYS = {
    "/planning.html": "planning",
    "/assessments.html": "assessments",
    "/workspace.html": "access",
    "/platform.html": "platform",
  };

  let mePromise = null;
  const me = () => {
    mePromise = mePromise || request("/api/v1/me");
    return mePromise;
  };

  const renderTopbar = () => {
    const slot = document.querySelector("[data-grp-topbar]");
    if (!slot) return;
    const current = PAGE_KEYS[window.location.pathname] || "";
    slot.className = "grp-topbar";
    slot.replaceChildren();

    const brand = document.createElement("a");
    brand.className = "grp-topbar__brand";
    brand.href = "/planning.html";
    brand.setAttribute("aria-label", "SERVIR Global Risk Platform home");
    const logo = document.createElement("img");
    logo.className = "grp-topbar__logo";
    logo.src = "/assets/servir-global-collaborative.png";
    logo.alt = "SERVIR Global Collaborative";
    logo.width = 217;
    logo.height = 30;
    const name = document.createElement("span");
    name.className = "grp-topbar__product";
    name.textContent = "Global Risk Platform";
    brand.append(logo, name);

    const nav = document.createElement("nav");
    nav.className = "grp-topbar__nav";
    nav.setAttribute("aria-label", "Main menu");
    NAV_ITEMS.forEach((item) => {
      const link = document.createElement("a");
      link.href = item.href;
      link.textContent = item.label;
      link.dataset.nav = item.key;
      if (item.attr) link.setAttribute(item.attr, "");
      if (item.hidden) link.hidden = true;
      if (item.key === current) {
        link.classList.add("is-active");
        link.setAttribute("aria-current", "page");
      }
      nav.append(link);
    });

    const user = document.createElement("div");
    user.className = "grp-topbar__user";
    const who = document.createElement("span");
    who.className = "grp-topbar__name";
    who.dataset.topbarName = "";
    const signOut = document.createElement("button");
    signOut.type = "button";
    signOut.className = "grp-topbar__signout";
    signOut.dataset.signOut = "";
    signOut.textContent = "Sign out";
    user.append(who, signOut);

    slot.append(brand, nav, user);

    me()
      .then((identity) => {
        who.textContent = identity.display_name || identity.email;
        who.title = identity.email;
        const isHubAdmin = identity.memberships.some((m) => m.role === "admin");
        nav.querySelector('[data-nav="admin"]').hidden = !(isHubAdmin || identity.is_platform_admin);
        nav.querySelector('[data-nav="platform"]').hidden = !identity.is_platform_admin;
      })
      .catch(() => {});
  };

  renderTopbar();

  return {
    me,
    request,
    bindSignOut,
    formatDate,
    formatTime,
    tokens,
    allowanceMessage,
    isLow,
    cell,
    emptyRow,
  };
})();
