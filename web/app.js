(() => {
  const parameters = new URLSearchParams(window.location.search);
  const alert = document.querySelector("#auth-alert");
  const title = document.querySelector("[data-auth-alert-title]");
  const message = document.querySelector("[data-auth-alert-message]");
  const state = parameters.get("auth");
  const states = {
    unavailable: {
      title: "Sign-in is temporarily unavailable",
      message: "The SERVIR connection is not configured or cannot be reached. Please contact the platform administrator.",
    },
    failed: {
      title: "Sign-in could not be completed",
      message: "No GRP session was created. Return to SERVIR and try again, or contact the platform administrator.",
    },
    pending: {
      title: "Administrator assignment required",
      message: "Your SERVIR identity was verified, but no active GRP membership was found. An administrator can now assign your Hub and role; retry after they confirm access.",
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
