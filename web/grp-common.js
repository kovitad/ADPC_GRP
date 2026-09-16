// Shared helpers for signed-in GRP screens: CSRF header, typed errors, sign-out.
window.GRP = (() => {
  const csrfHeaders = () => {
    const match = document.cookie.match(/(?:^|;\s*)grp_csrf=([^;]+)/);
    return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
  };

  const request = async (path, { method = "GET", body } = {}) => {
    const headers = { Accept: "application/json", ...csrfHeaders() };
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

  return {
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
