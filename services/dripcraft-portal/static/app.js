const state = {
  config: null,
  token: sessionStorage.getItem("dripcraftPortalToken") || "",
};

const els = {
  authPanel: document.getElementById("authPanel"),
  portalToken: document.getElementById("portalToken"),
  saveTokenButton: document.getElementById("saveTokenButton"),
  refreshButton: document.getElementById("refreshButton"),
  syncButton: document.getElementById("syncButton"),
  createForm: document.getElementById("createForm"),
  createButton: document.getElementById("createButton"),
  craftyLink: document.getElementById("craftyLink"),
  craftyStatus: document.getElementById("craftyStatus"),
  kubeStatus: document.getElementById("kubeStatus"),
  portPool: document.getElementById("portPool"),
  serverRows: document.getElementById("serverRows"),
  serverCount: document.getElementById("serverCount"),
  toast: document.getElementById("toast"),
};

function headers() {
  const result = { "Content-Type": "application/json" };
  if (state.token) result["X-Portal-Token"] = state.token;
  return result;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...headers(),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload.message || payload.error || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload.data;
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => els.toast.classList.add("hidden"), 4200);
}

function statusText(node, ok, enabledText, disabledText) {
  node.textContent = ok ? enabledText : disabledText;
  node.className = ok ? "status-ok" : "status-bad";
}

function fqdnFor(hostname) {
  if (!hostname) return "";
  if (!state.config?.tailnetDomain) return `${hostname}.<tailnet>.ts.net`;
  return `${hostname}.${state.config.tailnetDomain}`;
}

function deriveHostname(name) {
  return String(name || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

function formPayload(form) {
  const data = new FormData(form);
  return {
    name: String(data.get("name") || "").trim(),
    hostname: String(data.get("hostname") || "").trim() || deriveHostname(data.get("name")),
    version: String(data.get("version") || "").trim(),
    jarType: String(data.get("jarType") || "Paper"),
    memMin: Number(data.get("memMin") || 1),
    memMax: Number(data.get("memMax") || 4),
    autostart: data.get("autostart") === "on",
    agreeToEula: data.get("agreeToEula") === "on",
    redirect: data.get("redirect") === "on",
  };
}

function renderRows(servers) {
  els.serverRows.innerHTML = "";
  els.serverCount.textContent = String(servers.length);
  if (!servers.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="4" class="muted">No Crafty servers</td>`;
    els.serverRows.appendChild(row);
    return;
  }
  for (const server of servers) {
    const row = document.createElement("tr");
    const exposure = server.exposure;
    const tailnet = exposure?.fqdn || "";
    row.innerHTML = `
      <td>
        <strong>${escapeHtml(server.name || "unknown")}</strong>
        <div class="muted">${escapeHtml(server.id || "")}</div>
      </td>
      <td>${server.port || ""}</td>
      <td>${tailnet ? `<span>${escapeHtml(tailnet)}</span>` : `<span class="muted">not exposed</span>`}</td>
      <td>
        <div class="row-actions">
          ${
            exposure
              ? `<button class="button secondary" data-action="unexpose" data-id="${escapeAttr(server.id)}">Unexpose</button>`
              : `<button class="button secondary" data-action="expose" data-id="${escapeAttr(server.id)}" data-name="${escapeAttr(server.name)}" data-port="${escapeAttr(server.port || "")}">Expose</button>`
          }
          <button class="button danger" data-action="delete" data-id="${escapeAttr(server.id)}">Delete</button>
        </div>
      </td>
    `;
    els.serverRows.appendChild(row);
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/'/g, "&#39;");
}

async function loadConfig() {
  const config = await api("/api/config");
  state.config = config;
  els.craftyLink.href = config.craftyPanelUrl || "#";
  els.portPool.textContent = `${config.portRangeStart}-${config.portRangeEnd}`;
  els.authPanel.classList.toggle("hidden", !config.authRequired || Boolean(state.token));
  const versionInput = els.createForm.elements.version;
  if (config.defaultMinecraftVersion && !versionInput.value) {
    versionInput.value = config.defaultMinecraftVersion;
  }
  els.createForm.elements.memMin.value = config.defaultMemMin || 1;
  els.createForm.elements.memMax.value = config.defaultMemMax || 4;
}

async function refresh() {
  if (state.config?.authRequired && !state.token) return;
  const data = await api("/api/servers");
  statusText(els.craftyStatus, data.craftyConfigured, "ready", "missing secret");
  statusText(els.kubeStatus, data.kubernetesConfigured, "ready", "not in cluster");
  renderRows(data.servers || []);
}

async function createServer(event) {
  event.preventDefault();
  const payload = formPayload(els.createForm);
  els.createButton.disabled = true;
  try {
    const result = await api("/api/servers", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showToast(`${result.name} exposed as ${result.exposure?.fqdn || fqdnFor(payload.hostname)}`);
    await refresh();
    if (payload.redirect && result.craftyPanelUrl && result.autoRedirect) {
      window.setTimeout(() => {
        window.location.href = result.craftyPanelUrl;
      }, 900);
    }
  } catch (error) {
    showToast(error.message);
  } finally {
    els.createButton.disabled = false;
  }
}

async function syncExisting() {
  els.syncButton.disabled = true;
  try {
    const result = await api("/api/sync", {
      method: "POST",
    });
    showToast(`Synced ${result.createdCount || 0}; skipped ${result.skippedCount || 0}`);
    await refresh();
  } catch (error) {
    showToast(error.message);
  } finally {
    els.syncButton.disabled = false;
  }
}

async function rowAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const action = button.dataset.action;
  const id = button.dataset.id;
  button.disabled = true;
  try {
    if (action === "expose") {
      const name = button.dataset.name || id;
      const port = Number(button.dataset.port || 0);
      const hostname = window.prompt("Tailnet host", deriveHostname(name));
      if (!hostname) return;
      await api("/api/exposures", {
        method: "POST",
        body: JSON.stringify({ serverId: id, name, hostname, port }),
      });
      showToast(`${name} exposed as ${fqdnFor(deriveHostname(hostname))}`);
    }
    if (action === "unexpose") {
      await api(`/api/exposures/${encodeURIComponent(id)}`, { method: "DELETE" });
      showToast("Tailnet service removed");
    }
    if (action === "delete") {
      const removeFiles = window.confirm("Delete server files too?");
      const confirmed = window.confirm(removeFiles ? "Delete Crafty server and files?" : "Delete Crafty server from panel?");
      if (!confirmed) return;
      await api(`/api/servers/${encodeURIComponent(id)}?files=${removeFiles ? "true" : "false"}`, {
        method: "DELETE",
      });
      showToast("Server deleted");
    }
    await refresh();
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

els.saveTokenButton.addEventListener("click", async () => {
  state.token = els.portalToken.value;
  sessionStorage.setItem("dripcraftPortalToken", state.token);
  els.authPanel.classList.add("hidden");
  try {
    await refresh();
  } catch (error) {
    sessionStorage.removeItem("dripcraftPortalToken");
    state.token = "";
    els.authPanel.classList.remove("hidden");
    showToast(error.message);
  }
});

els.refreshButton.addEventListener("click", () => refresh().catch((error) => showToast(error.message)));
els.syncButton.addEventListener("click", () => syncExisting());
els.createForm.addEventListener("submit", createServer);
els.serverRows.addEventListener("click", rowAction);
els.createForm.elements.name.addEventListener("input", (event) => {
  const hostInput = els.createForm.elements.hostname;
  if (!hostInput.dataset.touched) hostInput.value = deriveHostname(event.target.value);
});
els.createForm.elements.hostname.addEventListener("input", (event) => {
  event.target.dataset.touched = "true";
});

loadConfig()
  .then(refresh)
  .catch((error) => showToast(error.message));
