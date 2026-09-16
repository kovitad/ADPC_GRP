(() => {
  const requestSelect = document.querySelector("[data-request-email]");
  const requestCount = document.querySelector("[data-request-count]");
  const assignmentForm = document.querySelector("[data-assignment-form]");
  const assignmentStatus = document.querySelector("[data-assignment-status]");
  const assignButton = document.querySelector("[data-assign-button]");

  const showPendingRequests = (requests) => {
    requestSelect.replaceChildren();
    requestCount.textContent = String(requests.length);
    requests.forEach((request) => {
      const option = document.createElement("option");
      option.value = request.email;
      option.textContent = request.email;
      requestSelect.append(option);
    });
    if (requests.length === 0) {
      const option = document.createElement("option");
      option.textContent = "No pending requests";
      option.value = "";
      requestSelect.append(option);
    }
    requestSelect.disabled = requests.length === 0;
    assignButton.disabled = requests.length === 0;
  };

  const loadPendingRequests = () =>
    fetch("/api/v1/admin/access-requests", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Could not load pending requests");
        }
        return response.json();
      })
      .then((payload) => showPendingRequests(payload.requests));

  const enableAdminPanel = () => {
    document.querySelector("[data-admin-panel]").hidden = false;
    loadPendingRequests().catch(() => {
      assignmentStatus.textContent = "Pending requests could not be loaded.";
    });
  };

  const showIdentity = (identity) => {
    const displayName = identity.display_name || identity.email;
    document.querySelector("[data-user-name]").textContent = displayName;
    document.querySelector("[data-user-email]").textContent = identity.email;
    document.querySelector("[data-user-initial]").textContent = displayName.slice(0, 1).toUpperCase();

    const adminBadge = document.querySelector("[data-platform-admin]");
    adminBadge.hidden = !identity.is_platform_admin;

    const list = document.querySelector("[data-memberships]");
    list.replaceChildren();
    identity.memberships.forEach((membership) => {
      const item = document.createElement("li");
      item.className = "membership-row";

      const hub = document.createElement("div");
      const name = document.createElement("strong");
      const code = document.createElement("span");
      name.textContent = membership.hub_name;
      code.textContent = membership.hub_code.toUpperCase();
      hub.append(name, code);

      const role = document.createElement("span");
      role.className = "role-badge";
      role.textContent = membership.role;
      item.append(hub, role);
      list.append(item);
    });

    if (identity.memberships.length === 0) {
      const item = document.createElement("li");
      item.className = "membership-row membership-row--empty";
      item.textContent = "Platform-wide administration access; no Hub membership assigned.";
      list.append(item);
    }

    if (identity.is_platform_admin) {
      enableAdminPanel();
    }
  };

  assignmentForm.addEventListener("submit", (event) => {
    event.preventDefault();
    assignmentStatus.textContent = "Assigning membership…";
    assignButton.disabled = true;
    const hubCode = document.querySelector("[data-hub-code]").value.trim().toLowerCase();
    const role = document.querySelector("[data-role]").value;
    fetch(`/api/v1/admin/hubs/${encodeURIComponent(hubCode)}/members`, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ email: requestSelect.value, role }),
    })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Membership could not be assigned");
        }
        assignmentStatus.textContent = payload.message;
        await loadPendingRequests();
      })
      .catch((error) => {
        assignmentStatus.textContent = error.message;
        assignButton.disabled = false;
      });
  });

  fetch("/api/v1/me", { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then((response) => {
      if (response.status === 401 || response.status === 403) {
        window.location.replace("/");
        return null;
      }
      if (!response.ok) {
        throw new Error("Could not load membership");
      }
      return response.json();
    })
    .then((identity) => {
      if (identity) {
        showIdentity(identity);
      }
    })
    .catch(() => {
      document.querySelector("[data-workspace-status]").textContent =
        "Membership could not be loaded. Refresh the page or contact the platform administrator.";
    });
})();
