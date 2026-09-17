// Shared helpers for signed-in GRP screens: CSRF header, typed errors, sign-out.
window.GRP = (() => {
  const csrfHeaders = () => {
    const match = document.cookie.match(/(?:^|;\s*)grp_csrf=([^;]+)/);
    return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
  };

  const request = async (path, { method = "GET", body, idempotencyKey } = {}) => {
    const headers = { Accept: "application/json", ...csrfHeaders() };
    if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
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
    brand.setAttribute("aria-label", "SERVIR GRP home");
    const mark = document.createElement("span");
    mark.className = "brand-mark";
    mark.setAttribute("aria-hidden", "true");
    for (let i = 0; i < 4; i += 1) mark.append(document.createElement("span"));
    const name = document.createElement("span");
    name.textContent = "SERVIR GRP";
    brand.append(mark, name);

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
