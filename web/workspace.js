(() => {
  const csrfHeaders = () => {
    const match = document.cookie.match(/(?:^|;\s*)grp_csrf=([^;]+)/);
    return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
  };
  const errorMessage = (payload, fallback) =>
    (payload && payload.error && payload.error.message) || fallback;
  const requestInput = document.querySelector("[data-request-email]");
  const assignmentForm = document.querySelector("[data-assignment-form]");
  const assignmentStatus = document.querySelector("[data-assignment-status]");
  const assignButton = document.querySelector("[data-assign-button]");
  const adminMenu = document.querySelector("[data-admin-menu]");
  const hubSelect = document.querySelector("[data-hub-code]");
  const memberList = document.querySelector("[data-member-list]");
  const refreshMembers = document.querySelector("[data-refresh-members]");
  let currentIdentity = null;
  const roleLabel = (role) => ({
    ndmo_planner: "NDMO Planner",
    hub_expert: "Hub Expert / GIS Specialist",
    planner: "Legacy Planner",
    admin: "Hub Admin",
  }[role] || role);
  const memberRoles = ["ndmo_planner", "hub_expert", "admin", "planner"];

  const memberControl = (value, options) => {
    const select = document.createElement("select");
    options.forEach((optionValue) => {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = roleLabel(optionValue);
      option.selected = optionValue === value;
      select.append(option);
    });
    return select;
  };

  const updateMember = async (member, role, access, button) => {
    button.disabled = true;
    assignmentStatus.textContent = `Updating ${member.email}…`;
    try {
      const response = await fetch(
        `/api/v1/admin/hubs/${encodeURIComponent(hubSelect.value)}/members/${encodeURIComponent(member.id)}`,
        {
          method: "PATCH",
          credentials: "same-origin",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            ...csrfHeaders(),
          },
          body: JSON.stringify({ role: role.value, status: access.value }),
        },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(errorMessage(payload, "Membership could not be updated"));
      assignmentStatus.textContent = payload.message;
      await loadMembers();
    } catch (error) {
      assignmentStatus.textContent = error.message;
      button.disabled = false;
    }
  };

  const showMembers = (members) => {
    memberList.replaceChildren();
    members.forEach((member) => {
      const row = document.createElement("tr");
      const personCell = document.createElement("td");
      const name = document.createElement("strong");
      const email = document.createElement("span");
      name.textContent = member.display_name || member.email;
      email.textContent = member.email;
      personCell.append(name, email);
      const roleCell = document.createElement("td");
      const role = memberControl(member.role, memberRoles);
      roleCell.append(role);
      const accessCell = document.createElement("td");
      const access = memberControl(member.status, ["active", "disabled"]);
      accessCell.append(access);
      const actionCell = document.createElement("td");
      const save = document.createElement("button");
      save.type = "button";
      save.className = "button button--secondary";
      save.textContent = "Save";
      save.addEventListener("click", () => updateMember(member, role, access, save));
      actionCell.append(save);
      row.append(personCell, roleCell, accessCell, actionCell);
      memberList.append(row);
    });
    if (members.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 4;
      cell.textContent = "No Hub members found.";
      row.append(cell);
      memberList.append(row);
    }
  };

  const loadMembers = () =>
    fetch(`/api/v1/admin/hubs/${encodeURIComponent(hubSelect.value)}/members`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then((response) => {
        if (!response.ok) throw new Error("Could not load Hub members");
        return response.json();
      })
      .then((payload) => showMembers(payload.members));

  const loadAdminHubs = () =>
    fetch("/api/v1/admin/hubs", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then((response) => {
        if (!response.ok) throw new Error("Could not load administered Hubs");
        return response.json();
      })
      .then((payload) => {
        hubSelect.replaceChildren();
        payload.hubs.forEach((hub) => {
          const option = document.createElement("option");
          option.value = hub.code;
          option.textContent = hub.name;
          hubSelect.append(option);
        });
        if (payload.hubs.length === 0) throw new Error("No administered Hub is available");
      });

  const auditList = document.querySelector("[data-audit-list]");

  const loadAudit = () =>
    GRP.request(
      `/api/v1/admin/audit-events?hub_code=${encodeURIComponent(hubSelect.value)}&limit=50`,
    )
      .then((payload) => {
        auditList.replaceChildren();
        payload.events.forEach((event) => {
          const row = document.createElement("tr");
          GRP.cell(row, GRP.formatTime(event.occurred_at));
          GRP.cell(row, event.actor);
          GRP.cell(row, event.action.replaceAll("_", " "));
          GRP.cell(row, event.result);
          auditList.append(row);
        });
        if (payload.events.length === 0) {
          GRP.emptyRow(auditList, 4, "No security events for this Hub yet.");
        }
      })
      .catch(() => auditList.replaceChildren());

  const loadAllowance = () =>
    GRP.request("/api/v1/me/ai-usage")
      .then((usage) => {
        const message = document.querySelector("[data-ai-message]");
        const pill = document.querySelector("[data-ai-status]");
        message.textContent = GRP.allowanceMessage(usage);
        message.classList.toggle("is-low", GRP.isLow(usage));
        pill.textContent = usage.status.replaceAll("_", " ");
        pill.dataset.state = usage.status;
        const share = usage.token_limit
          ? Math.min(100, (usage.tokens_used / usage.token_limit) * 100)
          : 0;
        document.querySelector("[data-ai-meter]").style.width = `${share}%`;
        document.querySelector("[data-ai-detail]").textContent = usage.token_limit
          ? `${GRP.tokens(usage.tokens_used)} of ${GRP.tokens(usage.token_limit)} tokens used this month. The Platform Admin sets the limit; it resets on the 1st at 00:00 Bangkok time.`
          : "No monthly token limit has been set yet.";
      })
      .catch(() => {
        document.querySelector("[data-ai-message]").textContent =
          "AI is not available right now. Maps, analysis and downloads still work.";
      });

  const enableAdminPanel = (identity) => {
    const adminPanel = document.querySelector("[data-admin-panel]");
    adminPanel.hidden = false;
    adminMenu.hidden = false;
    document.querySelector("[data-refresh-log]").addEventListener("click", () => loadAudit());
    loadAdminHubs().then(() => Promise.all([loadMembers(), loadAudit()])).catch(() => {
      assignmentStatus.textContent = "Hub members could not be loaded.";
    });
    if (window.location.hash === "#admin-panel") {
      window.requestAnimationFrame(() => adminPanel.scrollIntoView({ behavior: "smooth" }));
    }
  };

  const showIdentity = (identity) => {
    currentIdentity = identity;
    const displayName = identity.display_name || identity.email;
    document.querySelector("[data-user-name]").textContent = displayName;
    document.querySelector("[data-user-email]").textContent = identity.email;
    document.querySelector("[data-user-initial]").textContent = displayName.slice(0, 1).toUpperCase();
    document.querySelector("[data-platform-admin]").hidden = !identity.is_platform_admin;
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
      role.textContent = roleLabel(membership.role);
      item.append(hub, role);
      list.append(item);
    });
    if (identity.memberships.length === 0) {
      const item = document.createElement("li");
      item.className = "membership-row membership-row--empty";
      item.textContent = "Platform-wide administration access; no Hub membership assigned.";
      list.append(item);
    }
    document.querySelector("[data-platform-menu]").hidden = !identity.is_platform_admin;
    loadAllowance();
    const isHubAdmin = identity.memberships.some((membership) => membership.role === "admin");
    if (identity.is_platform_admin || isHubAdmin) enableAdminPanel(identity);
  };

  assignmentForm.addEventListener("submit", (event) => {
    event.preventDefault();
    assignmentStatus.textContent = "Assigning membership…";
    assignButton.disabled = true;
    fetch(`/api/v1/admin/hubs/${encodeURIComponent(hubSelect.value)}/members`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            ...csrfHeaders(),
          },
      body: JSON.stringify({
        email: requestInput.value.trim().toLowerCase(),
        role: document.querySelector("[data-role]").value,
      }),
    })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(errorMessage(payload, "Membership could not be assigned"));
        assignmentStatus.textContent = payload.message;
        requestInput.value = "";
        await loadMembers();
      })
      .catch((error) => {
        assignmentStatus.textContent = error.message;
      })
      .finally(() => {
        assignButton.disabled = false;
      });
  });

  hubSelect.addEventListener("change", () => {
    loadMembers();
    loadAudit();
  });
  refreshMembers.addEventListener("click", () => loadMembers());

  GRP.bindSignOut();

  // Reuse the identity the shared top bar already loaded (one /me call per page).
  GRP.me()
    .then((identity) => {
      if (identity) showIdentity(identity);
    })
    .catch((error) => {
      if (error.status === 401 || error.status === 403) {
        window.location.replace("/");
        return;
      }
      document.querySelector("[data-workspace-status]").textContent =
        "Membership could not be loaded. Refresh the page or contact the platform administrator.";
    });
})();
