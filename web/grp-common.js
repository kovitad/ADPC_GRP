// Shared helpers for signed-in GRP screens: CSRF header, typed errors, sign-out.
window.GRP = (() => {
  const csrfHeaders = () => {
    const match = document.cookie.match(/(?:^|;\s*)grp_csrf=([^;]+)/);
    return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
  };

  const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  const request = async (
    path,
    { method = "GET", body, idempotencyKey, contentType, extraHeaders = {}, retried = false } = {},
  ) => {
    const headers = { Accept: "application/json", ...csrfHeaders(), ...extraHeaders };
    if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
    const rawBody = body instanceof Blob || body instanceof FormData;
    if (body !== undefined && !(body instanceof FormData)) {
      headers["Content-Type"] = contentType || (rawBody ? body.type : "application/json");
    }
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : rawBody ? body : JSON.stringify(body),
    });
    // Rate limited while loading a page: wait as told (at most 10 s) and read once more.
    if (response.status === 429 && method === "GET" && !retried) {
      const seconds = Math.min(10, Math.max(1, Number(response.headers.get("Retry-After")) || 3));
      await wait(seconds * 1000);
      return request(path, {
        method, body, idempotencyKey, contentType, extraHeaders, retried: true,
      });
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

  // A file from the API (a report, a table): same headers and errors as request(), then saved.
  const download = async (path, { method = "GET", body, fallbackName = "download" } = {}) => {
    const headers = { ...csrfHeaders() };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const error = new Error(
        (payload.error && payload.error.message) || `Download failed (${response.status})`,
      );
      error.status = response.status;
      error.code = payload.error && payload.error.code;
      throw error;
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = match ? match[1] : fallbackName;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const bindSignOut = () => {
    document.querySelectorAll("[data-sign-out]").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          [sessionStorage, localStorage].forEach((store) =>
            Object.keys(store)
              .filter((key) => key.startsWith("grp."))
              .forEach((key) => store.removeItem(key)),
          );
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

  // One top bar for every signed-in page, as a grouped menu (docs/pilot/2026-10-05_Navigation_
  // Live_Feeds_and_Air_Quality_Plan.md): Planning, Assessments, Live, Share data, Admin and the
  // person's own menu. Every item keeps its data attribute, so pages can still show or hide it.
  const NAV_ITEMS = [
    { key: "planning", label: "Planning", href: "/planning.html" },
    { key: "assessments", label: "Assessments", href: "/assessments.html" },
    {
      key: "live", label: "Live", items: [
        // The pilot registry: one entry per pilot. `access` says who may see it.
        { key: "pilot", label: "Bangkok and Nonthaburi flood", note: "live", href: "/flood.html", attr: "data-pilot-menu", access: "flood", hidden: true },
        { key: "river", label: "River Watch (GEOGLOWS)", note: "live", href: "/pilot.html", attr: "data-river-menu", access: "admin", hidden: true },
        { key: "air", label: "Southeast Asia air quality", note: "soon", href: "/air-quality.html", attr: "data-air-menu", access: "admin", hidden: true, soon: true },
      ],
    },
    {
      key: "share", label: "Share data", items: [
        { key: "share", label: "Contribute data (files and tables)", href: "/contribute.html" },
        { key: "share-live", label: "Contribute a live feed", href: "/contribute.html#live-feed" },
        { key: "share-list", label: "My contributions", href: "/contribute.html#cb-list-heading" },
      ],
    },
    {
      key: "admin", label: "Admin", items: [
        { key: "admin", label: "Administration", href: "/workspace.html#admin-panel", attr: "data-admin-menu", hidden: true },
        { key: "data", label: "Source data", href: "/data-inspector.html", attr: "data-data-menu", hidden: true },
        { key: "library", label: "Data library", href: "/data-library.html", attr: "data-library-menu", hidden: true },
        { key: "platform", label: "Platform", href: "/platform.html", attr: "data-platform-menu", hidden: true },
      ],
    },
  ];
  const PAGE_KEYS = {
    "/planning.html": "planning",
    "/assessments.html": "assessments",
    "/contribute.html": "share",
    "/workspace.html": "access",
    "/platform.html": "platform",
    "/data-inspector.html": "data",
    "/data-preview.html": "data",
    "/data-library.html": "library",
    "/pilot.html": "river",
    "/flood.html": "pilot",
    "/air-quality.html": "air",
  };

  let mePromise = null;
  const me = () => {
    mePromise = mePromise || request("/api/v1/me");
    return mePromise;
  };

  const menuLink = (item, current) => {
    const link = document.createElement("a");
    link.href = item.href;
    link.dataset.nav = item.key;
    link.setAttribute("role", "menuitem");
    if (item.attr) link.setAttribute(item.attr, "");
    if (item.hidden) link.hidden = true;
    const label = document.createElement("span");
    label.textContent = item.label;
    link.append(label);
    if (item.note) {
      const note = document.createElement("small");
      note.className = `grp-menu__note${item.soon ? " is-soon" : ""}`;
      note.textContent = item.note;
      link.append(note);
    }
    if (item.key === current) {
      link.classList.add("is-active");
      link.setAttribute("aria-current", "page");
    }
    if (item.soon) {
      // Listed so people know it is coming; not a link until its page exists.
      link.removeAttribute("href");
      link.setAttribute("aria-disabled", "true");
      link.classList.add("is-soon");
    }
    return link;
  };

  // A click-to-open menu: Esc or a click outside closes it, arrow keys move between items.
  const openMenus = new Set();
  const closeMenus = (except = null) => {
    openMenus.forEach((menu) => {
      if (menu === except) return;
      menu.classList.remove("is-open");
      menu.querySelector(".grp-menu__button").setAttribute("aria-expanded", "false");
      openMenus.delete(menu);
    });
  };
  const visibleItems = (menu) => [...menu.querySelectorAll(".grp-menu__panel [role=menuitem]")]
    .filter((item) => !item.hidden);
  const buildMenu = (key, label, items, current) => {
    const menu = document.createElement("div");
    menu.className = "grp-menu";
    menu.dataset.menu = key;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "grp-menu__button";
    button.setAttribute("aria-haspopup", "menu");
    button.setAttribute("aria-expanded", "false");
    button.textContent = label;
    const panel = document.createElement("div");
    panel.className = "grp-menu__panel";
    panel.setAttribute("role", "menu");
    panel.setAttribute("aria-label", label);
    items.forEach((item) => panel.append(item instanceof Node ? item : menuLink(item, current)));
    menu.append(button, panel);
    if (items.some((item) => !(item instanceof Node) && item.key === current)) {
      button.classList.add("is-active");
    }
    const open = (focusFirst) => {
      closeMenus(menu);
      menu.classList.add("is-open");
      button.setAttribute("aria-expanded", "true");
      openMenus.add(menu);
      if (focusFirst) visibleItems(menu)[0]?.focus();
    };
    button.addEventListener("click", () => {
      if (menu.classList.contains("is-open")) closeMenus();
      else open(false);
    });
    button.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open(true);
      }
    });
    panel.addEventListener("keydown", (event) => {
      const list = visibleItems(menu);
      const at = list.indexOf(document.activeElement);
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        list[(at + step + list.length) % list.length]?.focus();
      } else if (event.key === "Escape") {
        closeMenus();
        button.focus();
      }
    });
    return menu;
  };

  // A group with nothing the person may open is hidden, and shows again when a page reveals an
  // item (workspace.js reveals the Administration link after its own access check).
  const syncGroups = (nav) => {
    nav.querySelectorAll(".grp-menu[data-menu]").forEach((menu) => {
      if (menu.dataset.menu === "user") return;
      menu.hidden = visibleItems(menu).length === 0;
    });
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

    const burger = document.createElement("button");
    burger.type = "button";
    burger.className = "grp-topbar__burger";
    burger.setAttribute("aria-label", "Menu");
    burger.setAttribute("aria-expanded", "false");
    burger.textContent = "☰";

    const nav = document.createElement("nav");
    nav.className = "grp-topbar__nav";
    nav.id = "grp-main-menu";
    nav.setAttribute("aria-label", "Main menu");
    burger.setAttribute("aria-controls", nav.id);
    NAV_ITEMS.forEach((item) => {
      if (item.items) {
        nav.append(buildMenu(item.key, item.label, item.items, current));
        return;
      }
      const link = menuLink(item, current);
      link.removeAttribute("role");
      link.classList.add("grp-topbar__link");
      nav.append(link);
    });

    const user = document.createElement("div");
    user.className = "grp-topbar__user";
    const running = document.createElement("a");
    running.className = "grp-topbar__jobs";
    running.dataset.topbarJobs = "";
    running.hidden = true;
    const signOut = document.createElement("button");
    signOut.type = "button";
    signOut.className = "grp-topbar__signout";
    signOut.dataset.signOut = "";
    signOut.setAttribute("role", "menuitem");
    signOut.textContent = "Sign out";
    const userMenu = buildMenu("user", "Account", [
      { key: "access", label: "My access", href: "/workspace.html" },
      signOut,
    ], current);
    const who = userMenu.querySelector(".grp-menu__button");
    who.classList.add("grp-topbar__name");
    who.dataset.topbarName = "";
    user.append(running, userMenu);

    slot.append(brand, burger, nav, user);
    syncGroups(nav);

    burger.addEventListener("click", () => {
      const open = !slot.classList.contains("is-menu-open");
      slot.classList.toggle("is-menu-open", open);
      burger.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (event) => {
      if (![...openMenus].some((menu) => menu.contains(event.target))) closeMenus();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeMenus();
        slot.classList.remove("is-menu-open");
        burger.setAttribute("aria-expanded", "false");
      }
    });
    new MutationObserver(() => syncGroups(nav)).observe(nav, {
      subtree: true, attributes: true, attributeFilter: ["hidden"],
    });

    me()
      .then((identity) => {
        who.textContent = identity.display_name || identity.email;
        who.title = identity.email;
        const isHubAdmin = identity.memberships.some((m) => m.role === "admin");
        const isAdmin = isHubAdmin || identity.is_platform_admin;
        nav.querySelector('[data-nav="admin"]').hidden = !isAdmin;
        nav.querySelector('[data-nav="data"]').hidden = !isAdmin;
        nav.querySelector('[data-nav="library"]').hidden = !isAdmin;
        nav.querySelector('[data-nav="platform"]').hidden = !identity.is_platform_admin;
        // ADR-0036: River Watch is for Admins. ADR-0038: the Bangkok flood view is open to every
        // member of the pilot's Hubs. Pilots marked "soon" show to Admins only.
        nav.querySelectorAll(".grp-menu__panel [data-nav]").forEach((link) => {
          const spec = NAV_ITEMS.flatMap((group) => group.items || []).find((i) => i.key === link.dataset.nav);
          if (spec && spec.access === "admin") link.hidden = !isAdmin;
        });
        const floodLink = nav.querySelector('[data-nav="pilot"]');
        if (isAdmin) {
          floodLink.hidden = false;
        } else if (identity.memberships.length) {
          request("/api/v1/pilot/flood")
            .then((answer) => {
              floodLink.hidden = !(answer.pilots && answer.pilots.length);
            })
            .catch(() => {});
        }
        syncGroups(nav);
      })
      .catch(() => {});
  };

  // Background jobs the person started (assessments, source data checks). The server keeps
  // running them whatever page or tab is open; this remembers them across tabs so any page can say
  // "still running" and announce when one finishes. The page that owns a job shows the result
  // itself, so it is not announced there.
  const JOBS_KEY = "grp.jobs.v1";
  const JOB_POLL_MS = 5000;
  let jobTimer = null;

  const readJobs = () => {
    try {
      return JSON.parse(localStorage.getItem(JOBS_KEY) || "[]");
    } catch (_error) {
      return [];
    }
  };

  const writeJobs = (jobs) => {
    try {
      localStorage.setItem(JOBS_KEY, JSON.stringify(jobs));
    } catch (_error) {
      // Storage blocked: the job still runs, there is just no reminder on other pages.
    }
  };

  const showJobCount = () => {
    const pill = document.querySelector("[data-topbar-jobs]");
    if (!pill) return;
    const jobs = readJobs();
    pill.hidden = jobs.length === 0;
    if (!jobs.length) return;
    pill.textContent = jobs.length === 1 ? `Running: ${jobs[0].label}` : `${jobs.length} jobs running`;
    pill.href = jobs[0].href;
    pill.title = "Still running in the background. You can keep working; you will be told when it finishes.";
  };

  const toastRegion = () => {
    let region = document.querySelector("[data-grp-toasts]");
    if (!region) {
      region = document.createElement("div");
      region.className = "grp-toasts";
      region.dataset.grpToasts = "";
      region.setAttribute("role", "status");
      region.setAttribute("aria-live", "polite");
      document.body.append(region);
    }
    return region;
  };

  const notify = (job, ok, detail) => {
    const toast = document.createElement("div");
    toast.className = `grp-toast${ok ? "" : " is-failed"}`;
    const text = document.createElement("p");
    text.textContent = ok ? `${job.label} is ready.` : `${job.label} stopped${detail ? `: ${detail}` : ""}.`;
    const open = document.createElement("a");
    open.href = job.href;
    open.textContent = ok ? "Open" : "See details";
    const close = document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "×";
    close.addEventListener("click", () => toast.remove());
    toast.append(text, open, close);
    toastRegion().append(toast);
    if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
      try {
        new Notification("Global Risk Platform", { body: text.textContent });
      } catch (_error) {
        // Some browsers allow notifications only from a service worker; the toast is enough.
      }
    }
  };

  // One polling loop per page. track() used to start another timer each time it was called, so
  // two lookups plus the page-load check polled every job three times over.
  let checking = false;
  const scheduleCheck = () => {
    window.clearTimeout(jobTimer);
    jobTimer = window.setTimeout(checkJobs, JOB_POLL_MS);
  };

  const checkJobs = async () => {
    window.clearTimeout(jobTimer);
    if (checking) return;
    checking = true;
    try {
      await checkJobsOnce();
    } finally {
      checking = false;
    }
    if (readJobs().length) scheduleCheck();
  };

  const checkJobsOnce = async () => {
    const jobs = readJobs();
    if (!jobs.length) {
      showJobCount();
      return;
    }
    const finished = new Set();
    await Promise.all(
      jobs.map(async (job) => {
        try {
          const status = await request(job.statusPath);
          if (status.state === "succeeded" || status.state === "failed" || status.state === "cancelled") {
            finished.add(job.id);
            if (window.location.pathname !== job.ownerPath) {
              notify(job, status.state === "succeeded", status.error_code);
            }
          }
        } catch (error) {
          // Gone (404) or no longer allowed: stop watching it. Anything else, try again later.
          if (error.status === 404 || error.status === 403) finished.add(job.id);
        }
      }),
    );
    if (finished.size) writeJobs(readJobs().filter((job) => !finished.has(job.id)));
    showJobCount();
  };

  const jobs = {
    // job: { id, label, statusPath, href, ownerPath }
    track(job) {
      writeJobs([...readJobs().filter((item) => item.id !== job.id), job]);
      showJobCount();
      if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission().catch(() => {});
      }
      scheduleCheck();
    },
    done(id) {
      writeJobs(readJobs().filter((item) => item.id !== id));
      showJobCount();
    },
    list() {
      return readJobs();
    },
  };

  renderTopbar();
  if (document.querySelector("[data-grp-topbar]")) checkJobs();

  return {
    jobs,
    me,
    request,
    download,
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
