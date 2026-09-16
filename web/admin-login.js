(() => {
  const parameters = new URLSearchParams(window.location.search);
  const alert = document.querySelector("#admin-auth-alert");
  const title = document.querySelector("[data-admin-alert-title]");
  const message = document.querySelector("[data-admin-alert-message]");
  const state = parameters.get("auth");
  const states = {
    unavailable: {
      title: "Administrator sign-in is unavailable",
      message: "The SIG authentication service is not configured or cannot be reached.",
    },
    failed: {
      title: "Administrator identity could not be verified",
      message: "No GRP administrator session was created. Please try SIG sign-in again.",
    },
    pending: {
      title: "GRP administrator provisioning required",
      message: "SIG verified this email, but it has not been provisioned for GRP access.",
    },
    not_admin: {
      title: "Administrator authority required",
      message: "This GRP account is active but is not a Hub Admin or Platform Admin.",
    },
  };

  if (!alert || !title || !message || !state || !states[state]) {
    return;
  }

  title.textContent = states[state].title;
  message.textContent = states[state].message;
  alert.hidden = false;
  window.history.replaceState({}, "", window.location.pathname);
})();
