(() => {
  const parameters = new URLSearchParams(window.location.search);
  const alert = document.querySelector("#auth-alert");

  if (alert && parameters.get("auth") === "unavailable") {
    alert.hidden = false;
    window.history.replaceState({}, "", window.location.pathname);
  }

  const copyButton = document.querySelector("[data-copy-template]");
  const copyStatus = document.querySelector("[data-copy-status]");
  const requestTemplate = document.querySelector("#access-request");

  if (!copyButton || !copyStatus || !requestTemplate) {
    return;
  }

  if (!navigator.clipboard) {
    copyButton.hidden = true;
    copyStatus.textContent = "Select the message to copy it manually.";
    return;
  }

  copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(requestTemplate.textContent.trim());
      copyButton.textContent = "Copied";
      copyStatus.textContent = "Access request copied to your clipboard.";
    } catch {
      copyStatus.textContent = "Could not copy automatically. Select the message and copy it manually.";
    }
  });
})();
