(() => {
  const parameters = new URLSearchParams(window.location.search);
  const alert = document.querySelector("#registration-alert");
  const title = document.querySelector("[data-registration-title]");
  const message = document.querySelector("[data-registration-message]");
  const state = parameters.get("registration");
  const states = {
    unavailable: {
      title: "Registration is temporarily unavailable",
      message: "The SERVIR connection is not configured or cannot be reached. Contact the platform administrator.",
    },
    failed: {
      title: "Existing Global Risk account could not be verified",
      message: "No access request was created. Try again with your existing SERVIR account.",
    },
    pending: {
      title: "Registration request received",
      message: "Your SERVIR identity was verified. A Platform Admin can now assign your Hub and role; return to sign in after approval.",
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
