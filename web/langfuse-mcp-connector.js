(() => {
  "use strict";

  const MCP_URL = "https://langfuse-risk-servir.adpc.net/api/public/mcp";
  const localHosts = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);
  const isLocal = window.location.protocol === "file:" || localHosts.has(window.location.hostname);
  const form = document.querySelector("[data-connector-form]");
  const publicKeyInput = document.querySelector("#langfuse-public-key");
  const secretKeyInput = document.querySelector("#langfuse-secret-key");
  const status = document.querySelector("[data-status]");
  const localState = document.querySelector("[data-local-state]");
  const copyUrlButton = document.querySelector("[data-copy-url]");
  const generateButton = document.querySelector("[data-generate]");
  const clearButton = document.querySelector("[data-clear]");

  const setStatus = (message, kind = "") => {
    status.textContent = message;
    status.dataset.kind = kind;
  };

  const clearKeys = () => {
    publicKeyInput.value = "";
    secretKeyInput.value = "";
  };

  const copyText = async (value) => {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return;
    }

    const temporary = document.createElement("textarea");
    temporary.value = value;
    temporary.setAttribute("readonly", "");
    temporary.setAttribute("aria-hidden", "true");
    temporary.className = "connector-copy-buffer";
    document.body.append(temporary);
    temporary.select();
    const copied = document.execCommand("copy");
    temporary.remove();
    if (!copied) {
      throw new Error("Clipboard copy was rejected");
    }
  };

  const validateKey = (value, prefix, label) => {
    if (!value.startsWith(prefix)) {
      throw new Error(`${label} must start with ${prefix}`);
    }
    if (/[:\s]/u.test(value)) {
      throw new Error(`${label} must not contain spaces, line breaks, or a colon`);
    }
  };

  if (!isLocal) {
    localState.textContent =
      "Unavailable: open this utility on localhost or as a local file. Keys are refused on deployed hosts.";
    localState.dataset.kind = "blocked";
    setStatus("No key processing is available on this host.", "error");
    return;
  }

  for (const control of [publicKeyInput, secretKeyInput, copyUrlButton, generateButton, clearButton]) {
    control.disabled = false;
  }
  localState.textContent =
    "Local mode confirmed. This page makes no network requests and does not store either key.";
  localState.dataset.kind = "safe";

  copyUrlButton.addEventListener("click", async () => {
    try {
      await copyText(MCP_URL);
      setStatus("MCP URL copied.", "success");
    } catch (_error) {
      setStatus("The browser could not copy the MCP URL. Copy it from the connection details.", "error");
    }
  });

  form.addEventListener("reset", () => {
    window.setTimeout(() => {
      clearKeys();
      setStatus("Keys cleared from the form.", "success");
      publicKeyInput.focus();
    }, 0);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setStatus("");

    const publicKey = publicKeyInput.value.trim();
    const secretKey = secretKeyInput.value.trim();

    try {
      validateKey(publicKey, "pk-lf-", "Public key");
      validateKey(secretKey, "sk-lf-", "Secret key");
      const authorization = `Basic ${window.btoa(`${publicKey}:${secretKey}`)}`;
      await copyText(authorization);
      clearKeys();
      setStatus(
        "Authorization value copied and both form fields cleared. Paste it into Claude, save the connector, then overwrite your clipboard.",
        "success",
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The value could not be generated.", "error");
      secretKeyInput.value = "";
      secretKeyInput.focus();
    }
  });
})();
