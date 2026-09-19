/* Keep the dashboard and its controls in place while data changes. */
(() => {
  "use strict";

  const updateStatus = document.getElementById("update-status");
  const actionStatus = document.getElementById("action-status");
  const startButton = document.getElementById("pump-start");
  const startLabel = document.getElementById("pump-start-label");
  const regions = Array.from(document.querySelectorAll("[data-live-region]"));
  const busyForms = new Set();
  let timer;
  let polling;
  let revision = 0;
  let latestAction = 0;
  let fresh = true;

  function updateControls() {
    const allowed = document.getElementById("pump-status").dataset.startAllowed === "true";
    startButton.disabled = !fresh || !allowed || busyForms.size > 0;
    startLabel.textContent = !fresh ? "Waiting for connection" :
      (!allowed ? "Sensor unavailable" : "Start pump");
    document.getElementById("override-banner").hidden =
      document.getElementById("override-status").dataset.active !== "true";
  }

  // Update text/attributes in place. Existing table scroll containers and
  // unchanged elements survive; forms/buttons are outside these regions.
  function patchNode(current, incoming) {
    if (current.isEqualNode(incoming)) return;
    if (current.nodeType !== incoming.nodeType || current.nodeName !== incoming.nodeName) {
      current.replaceWith(incoming.cloneNode(true));
      return;
    }
    if (current.nodeType !== Node.ELEMENT_NODE) {
      current.nodeValue = incoming.nodeValue;
      return;
    }
    for (const attr of Array.from(current.attributes)) {
      if (!incoming.hasAttribute(attr.name)) current.removeAttribute(attr.name);
    }
    for (const attr of incoming.attributes) {
      if (current.getAttribute(attr.name) !== attr.value) {
        current.setAttribute(attr.name, attr.value);
      }
    }
    const oldChildren = Array.from(current.childNodes);
    const newChildren = Array.from(incoming.childNodes);
    newChildren.forEach((child, index) => {
      if (oldChildren[index]) patchNode(oldChildren[index], child);
      else current.appendChild(child.cloneNode(true));
    });
    oldChildren.slice(newChildren.length).forEach(child => child.remove());
  }

  function applyUpdates(html) {
    const incoming = new DOMParser().parseFromString(html, "text/html");
    const updates = regions.map(region => incoming.getElementById(region.id));
    if (updates.some(region => !region || !region.hasAttribute("data-live-region"))) {
      throw new Error("Incomplete dashboard update");
    }
    regions.forEach((region, index) => patchNode(region, updates[index]));
  }

  function schedule(delay = 5000) {
    clearTimeout(timer);
    if (!document.hidden && busyForms.size === 0) timer = setTimeout(refresh, delay);
  }

  function cancelPoll() {
    revision += 1;
    clearTimeout(timer);
    if (polling) polling.abort();
    polling = null;
  }

  async function refresh() {
    if (document.hidden || busyForms.size || polling) return;
    const version = revision;
    const controller = new AbortController();
    polling = controller;
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(document.body.dataset.updatesUrl, {
        headers: {Accept: "text/html"},
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("Dashboard unavailable");
      const html = await response.text();
      // A response requested before a control click must not overwrite it.
      if (version !== revision) return;
      applyUpdates(html);
      fresh = true;
      updateStatus.textContent = "Live · updated " + new Date().toLocaleTimeString();
      updateStatus.classList.remove("red-text");
    } catch (error) {
      if (version !== revision) return;
      fresh = false;
      updateStatus.textContent = "Updates unavailable · showing last received values · retrying";
      updateStatus.classList.add("red-text");
    } finally {
      clearTimeout(timeout);
      if (polling === controller) polling = null;
      updateControls();
      if (version === revision) schedule();
    }
  }

  document.addEventListener("submit", async event => {
    const form = event.target.closest("form[data-dashboard-action]");
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector("button[type='submit'], button:not([type])");
    if (busyForms.has(form) || button.disabled) return;

    const action = ++latestAction;
    busyForms.add(form);
    button.setAttribute("aria-busy", "true");
    // Do not disable Stop while a Start request or data update is pending.
    // The busy set prevents repeated submissions of the same command.
    cancelPoll();
    updateControls();
    actionStatus.textContent = "Sending command...";
    actionStatus.classList.remove("red-text");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: {Accept: "application/json"},
        body: new URLSearchParams(new FormData(form)),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("Command response unavailable");
      const result = await response.json();
      if (typeof result.ok !== "boolean" || typeof result.reason !== "string") {
        throw new Error("Unexpected command response");
      }
      if (action === latestAction) {
        actionStatus.textContent = result.reason;
        actionStatus.classList.toggle("red-text", !result.ok);
      }
    } catch (error) {
      if (action === latestAction) {
        actionStatus.textContent = "Could not confirm the command. Check pump status; it was not resent.";
        actionStatus.classList.add("red-text");
      }
    } finally {
      clearTimeout(timeout);
      busyForms.delete(form);
      button.removeAttribute("aria-busy");
      // Keep Start blocked until a fresh snapshot confirms the current state.
      fresh = false;
      updateControls();
      schedule(0);
    }
  });

  document.addEventListener("visibilitychange", () => {
    cancelPoll();
    if (document.hidden) {
      fresh = false;
      updateControls();
    } else {
      schedule(0);
    }
  });

  updateControls();
  schedule(0);
})();
