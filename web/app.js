"use strict";

const app = {
  clients: [],
  events: [],
  settings: null,
  projectAlerts: {},
  muted: localStorage.getItem("ms_muted") === "1",
  pollTimer: null,
  currentDetailId: null,
  currentFilter: "all",
  search: "",
  confirmClient: null,
  pendingAdmin: null,
  currentProject: null,

  init() {
    app.renderBell();
    app.refresh();
    app.pollTimer = setInterval(app.refresh, 15000);
  },

  async api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) {
      const e = new Error(await res.text());
      e.status = res.status;
      throw e;
    }
    return res.json();
  },

  async withAdmin(action) {
    try {
      await action();
      return true;
    } catch (e) {
      if (e.status === 401) {
        app.pendingAdmin = action;
        app.openAdmin();
        return false;
      }
      throw e;
    }
  },

  async refresh() {
    try {
      const [clients, events, settings, projectAlerts] = await Promise.all([
        app.api("/api/clients"),
        app.api("/api/events?limit=200"),
        app.api("/api/settings"),
        app.api("/api/project-alerts"),
      ]);

      const wasCritical = new Set(app.clients.filter((c) => ["critical", "warning"].includes(c.diagnosis)).map((c) => c.id));
      const wasOffline = new Set(app.clients.filter((c) => c.status === "offline").map((c) => c.id));
      app.clients = clients.sort((a, b) => {
        const o = { critical: 0, warning: 1, offline: 1, online: 2, ok: 3 };
        return (o[a.diagnosis] ?? 3) - (o[b.diagnosis] ?? 3);
      });
      app.events = events;
      app.settings = settings;
      app.projectAlerts = projectAlerts || {};
      if (app.settings.report_interval_seconds && document.getElementById("set-interval")) {
        document.getElementById("set-interval").value = app.settings.report_interval_seconds;
      }
      app.renderDashboard();
      if (app.currentDetailId) app.renderDetail(app.currentDetailId);
      if (app.isTab("log")) app.renderLog();

      const nowCritical = new Set(app.clients.filter((c) => ["critical", "warning"].includes(c.diagnosis)).map((c) => c.id));
      const nowOffline = new Set(app.clients.filter((c) => c.status === "offline").map((c) => c.id));
      const newProblems = [...nowCritical].filter((id) => !wasCritical.has(id));
      const newOffline = [...nowOffline].filter((id) => !wasOffline.has(id));
      if (newProblems.length > 0 || newOffline.length > 0) app.playBell();
    } catch (e) {
      if (app.clients.length !== 0) console.error(e);
    }
  },

  isTab(name) {
    return document.querySelector(`.tab[data-tab="${name}"]`).classList.contains("active");
  },

  showTab(name) {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    document.getElementById("dashboard").style.display = name === "dashboard" ? "" : "none";
    document.getElementById("log-view").style.display = name === "log" ? "" : "none";
    document.getElementById("detail-view").style.display = "none";
    if (name === "log") app.renderLog();
    if (name === "dashboard") app.renderDashboard();
  },

  fmtTime(ts) {
    if (!ts) return "never";
    const d = new Date(ts * 1000);
    const ago = Math.floor((Date.now() / 1000 - ts) / 60);
    if (ago < 1) return "just now";
    if (ago < 60) return `${ago}m ago`;
    return d.toLocaleString();
  },

  pct(v) {
    if (v === null || v === undefined) return 0;
    return Math.round(v);
  },

  healthOf(c) {
    if (c.status === "offline") return "offline";
    return ["critical", "warning", "ok"].includes(c.diagnosis) ? c.diagnosis : "ok";
  },

  matchesFilter(c) {
    if (app.search) {
      const hay = `${c.name} ${c.host_ip} ${(c.projects || []).join(" ")} ${c.kind}`.toLowerCase();
      if (!hay.includes(app.search.toLowerCase())) return false;
    }
    if (app.currentFilter === "problems") return ["critical", "warning"].includes(c.diagnosis) || c.status === "offline";
    if (app.currentFilter === "healthy") return c.status !== "offline" && c.diagnosis === "ok";
    if (app.currentFilter === "offline") return c.status === "offline";
    return true;
  },

  renderDashboard() {
    const root = document.getElementById("dashboard");
    const existing = root.querySelector(".dash-static");
    if (!existing) {
      const staticBar = document.createElement("div");
      staticBar.className = "dash-static";
      staticBar.innerHTML = `
        <div class="stat-row" id="dash-stats"></div>
        <div class="inline-controls">
          <input type="search" id="client-search" placeholder="Search by name, IP or project">
        </div>
        <div class="filters" id="dash-filters"></div>
      `;
      staticBar.querySelector("#client-search").addEventListener("input", (e) => {
        app.search = e.target.value;
        app.renderList();
      });
      root.appendChild(staticBar);
    }

    const problems = app.clients.filter((c) => ["critical", "warning"].includes(c.diagnosis) || c.status === "offline");
    document.getElementById("dash-stats").innerHTML = `
      <div class="stat-card"><div class="label">Clients</div><div class="value">${app.clients.length}</div></div>
      <div class="stat-card"><div class="label">Healthy</div><div class="value" style="color:var(--green)">${app.clients.length - problems.length}</div></div>
      <div class="stat-card"><div class="label">Issues</div><div class="value" style="color:${problems.length ? "var(--red)" : "var(--text)"}">${problems.length}</div></div>
    `;

    const chips = [
      ["all", `All (${app.clients.length})`],
      ["problems", `Problems (${app.clients.filter((c) => ["critical", "warning"].includes(c.diagnosis) || c.status === "offline").length})`],
      ["healthy", `Healthy (${app.clients.filter((c) => c.status !== "offline" && c.diagnosis === "ok").length})`],
      ["offline", `Offline (${app.clients.filter((c) => c.status === "offline").length})`],
    ];
    const chipsBox = document.getElementById("dash-filters");
    chipsBox.innerHTML = "";
    chips.forEach(([val, label]) => {
      const b = document.createElement("button");
      b.className = "chip" + (app.currentFilter === val ? " active" : "");
      b.textContent = label;
      b.onclick = () => {
        app.currentFilter = val;
        app.renderDashboard();
      };
      chipsBox.appendChild(b);
    });

    app.renderList();
  },

  renderList() {
    const root = document.getElementById("dashboard");
    let list = root.querySelector(".client-list");
    if (list) list.remove();
    list = document.createElement("div");
    list.className = "client-list";

    const filtered = app.clients.filter((c) => app.matchesFilter(c));

    if (filtered.length === 0) {
      list.innerHTML = '<div class="empty">No clients match the current filters. Run the agent on a machine to register it here.</div>';
    } else {
      const byProject = {};
      filtered.forEach((c) => {
        const projs = (c.projects && c.projects.length ? c.projects : ["Ungrouped"]);
        projs.forEach((proj) => {
          if (!byProject[proj]) byProject[proj] = [];
          byProject[proj].push(c);
        });
      });
      const groupOrder = Object.keys(byProject).sort((a, b) => (a === "Ungrouped" ? 1 : b === "Ungrouped" ? -1 : a.localeCompare(b)));

      groupOrder.forEach((proj) => {
        const clist = byProject[proj];
        const groupHead = document.createElement("div");
        groupHead.className = "group-head";
        const isUngrouped = proj === "Ungrouped";
        const alertCfg = app.projectAlerts[proj];
        const badge = !isUngrouped && alertCfg && (alertCfg.email_to || (alertCfg.webhooks && alertCfg.webhooks.length))
          ? '<span class="alert-badge" title="Project alert configured">●</span>'
          : "";
        groupHead.innerHTML = `<span>${app.esc(proj)} (${clist.length})</span>${badge}` +
          (isUngrouped ? "" : ` <a class="group-alert-link" href="#" onclick="app.openProjectAlerts('${app.esc(proj).replace(/'/g, "\\'")}');return false">alerts</a>`);
        list.appendChild(groupHead);

        clist.forEach((c) => {
          const health = app.healthOf(c);
          const row = document.createElement("div");
          row.className = "client-row";
          row.innerHTML = `
            <span class="dot ${health}"></span>
            <div class="meta">
              <div class="name">${app.esc(c.name)}</div>
              <div class="sub">${c.host_ip} · ${app.fmtTime(c.last_seen)}</div>
            </div>
            <span class="tag">${c.kind}</span>
            <div class="bars">
              ${app.barHtml(c.cpu_percent, "CPU")}
              ${app.barHtml(c.mem_percent, "MEM")}
            </div>
          `;
          row.onclick = () => app.openDetail(c.id);
          list.appendChild(row);
        });
      });
    }
    root.appendChild(list);
  },

esc(s) {
    return String(s || "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  },

  barHtml(v, label) {
    const val = app.pct(v);
    const cls = val >= 90 ? " crit" : val >= 70 ? " hi" : "";
    return `<div class="bar" title="${label} ${val}%"><i class="${cls}" style="width:${val}%"></i></div>`;
  },

  openDetail(id) {
    app.currentDetailId = id;
    app.showTab("dashboard");
    document.getElementById("dashboard").style.display = "none";
    document.getElementById("log-view").style.display = "none";
    app.renderDetail(id);
  },

  async renderDetail(id) {
    const data = await app.api(`/api/clients/${id}`);
    const c = data.client;
    const snap = data.snapshot ? data.snapshot.payload : {};
    const health = app.healthOf(c);
    const diag = data.diagnosis;

    const box = document.getElementById("detail-view");
    box.style.display = "";
    const messages = diag.messages || [];
    const msgHtml = messages.length
      ? messages.map((m) => `<div>• ${app.esc(m.message)}</div>`).join("")
      : (health === "offline" ? "<div>No signal received.</div>" : "<div>Everything looks healthy.</div>");

    const cpu = snap.cpu_percent || 0;
    const mem = snap.mem_percent || 0;
    let diskHtml = "<div class='hint'>No disk data</div>";
    if (snap.disks && snap.disks.length) {
      diskHtml = snap.disks.map((d) => `
        <div class="flex-between"><span class="mono">${app.esc(d.mount)}</span><span>${app.pct(d.percent)}%</span></div>
        <div class="bar" style="width:100%;margin:4px 0"><i class="${d.percent >= 90 ? "crit" : ""}" style="width:${app.pct(d.percent)}%"></i></div>
      `).join("");
    }

    box.innerHTML = `
      <button class="back" onclick="app.backToList()">← Back</button>
      <div class="card">
        <div class="flex-between">
          <div>
            <h2 style="margin:0">${app.esc(c.name)} <span class="tag">${c.kind}</span></h2>
            <div class="hint">${app.esc(c.host_ip)} · seen ${app.fmtTime(c.last_seen)}</div>
          </div>
          <button class="btn danger" onclick="app.openConfirm(${c.id}, '${app.esc(c.name).replace(/'/g, "\\'")}')">Remove client</button>
        </div>
        <div class="flex-between" style="margin-top:12px">
          <span class="hint">Projects (comma separated, e.g. Web, SRE):</span>
          <div style="display:flex;gap:8px">
            <input id="detail-projects" value="${app.esc((c.projects || []).join(", "))}" placeholder="Web, SRE"/>
            <button class="btn" onclick="app.saveProjects(${c.id})">Save</button>
          </div>
        </div>
      </div>

      <div class="diag-box ${diag.level}">
        <h3>Diagnosis: ${diag.level}</h3>
        ${msgHtml}
      </div>

      <div class="stat-row">
        <div class="stat-card"><div class="label">CPU</div><div class="value">${Math.round(cpu)}%</div></div>
        <div class="stat-card"><div class="label">Memory</div><div class="value">${Math.round(mem)}%</div></div>
        <div class="stat-card"><div class="label">Uptime</div><div class="value">${app.uptime(snap.uptime_seconds)}</div></div>
      </div>

      <div class="card"><h2>Disks</h2>${diskHtml}</div>

      <div class="card">
        <h2>Events</h2>
        <div>${app.eventList(data.events)}</div>
      </div>
    `;
  },

async saveProjects(id) {
    const projects = document.getElementById("detail-projects")
      .value.split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    await app.withAdmin(async () => {
      await app.api(`/api/clients/${id}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projects }),
      });
    });
    app.refresh();
  },

  uptime(s) {
    if (!s) return "?";
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    return d > 0 ? `${d}d ${h}h` : `${h}h`;
  },

  backToList() {
    app.currentDetailId = null;
    document.getElementById("detail-view").style.display = "none";
    document.getElementById("dashboard").style.display = "";
    app.renderDashboard();
  },

  eventList(events, showClient = false) {
    if (!events || events.length === 0) return '<div class="empty">No events</div>';
    return events.map((e) => `
      <div class="event">
        <span class="when">${app.fmtTime(e.ts)}</span>
        <span class="dot ${e.level}" style="display:inline-block;vertical-align:middle;margin:0 6px"></span>
        <span class="msg">${showClient ? `<b>${app.esc(e.client_name)}</b> · ` : ""}${app.esc(e.message)}</span>
      </div>
    `).join("");
  },

  renderLog() {
    const search = (document.getElementById("log-search").value || "").toLowerCase();
    const level = document.getElementById("log-level").value;
    let list = app.events;
    if (level === "ok") {
      list = app.events.filter((e) => e.message.includes("healthy"));
    } else if (level) {
      list = app.events.filter((e) => e.level === level);
    }
    if (search) {
      list = list.filter((e) => `${e.client_name} ${e.message}`.toLowerCase().includes(search));
    }
    document.getElementById("log-list").innerHTML =
      list.length === 0
        ? '<div class="empty">No events match</div>'
        : app.eventList(list, true);
  },

openSettings() {
    const s = app.settings;
    document.getElementById("set-email-enabled").checked = s.email_enabled;
    document.getElementById("set-email-to").value = s.email_to || "";
    document.getElementById("set-email-smtp").value = s.email_smtp || "";
    document.getElementById("set-email-user").value = s.email_user || "";
    document.getElementById("set-email-password").value = "";
    document.getElementById("set-webhooks").value = (s.webhooks || []).join("\n");
    document.getElementById("set-interval").value = s.report_interval_seconds || 300;
    const t = s.thresholds || {};
    document.getElementById("thr-disk-warning").value = t.disk_warning ?? 90;
    document.getElementById("thr-disk-critical").value = t.disk_critical ?? 98;
    document.getElementById("thr-cpu-warning").value = t.cpu_warning ?? 90;
    document.getElementById("thr-cpu-critical").value = t.cpu_critical ?? 95;
    document.getElementById("thr-mem-warning").value = t.mem_warning ?? 90;
    document.getElementById("thr-mem-critical").value = t.mem_critical ?? 95;
    app.renderProjectAlertsList(document.getElementById("project-alerts-list"));
    document.getElementById("settings-modal").style.display = "flex";
  },

  closeSettings() {
    document.getElementById("settings-modal").style.display = "none";
  },

  async saveSettings() {
    await app.withAdmin(async () => {
      const webhooks = document
        .getElementById("set-webhooks")
        .value.split("\n")
        .map((s) => s.trim())
        .filter(Boolean);

      await app.api("/api/settings/notify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email_enabled: document.getElementById("set-email-enabled").checked,
          email_to: document.getElementById("set-email-to").value,
          email_smtp: document.getElementById("set-email-smtp").value,
          email_user: document.getElementById("set-email-user").value,
          email_password: document.getElementById("set-email-password").value,
          webhooks,
        }),
      });

      const interval = parseInt(document.getElementById("set-interval").value, 10);
      if (interval >= 10) {
        await app.api("/api/settings/report-interval", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ report_interval_seconds: interval }),
        });
      }

      let needsRefresh = false;
      const thresholds = {};
      ["disk", "cpu", "mem"].forEach((m) => {
        const w = parseFloat(document.getElementById(`thr-${m}-warning`).value);
        const c = parseFloat(document.getElementById(`thr-${m}-critical`).value);
        if (w >= 0 && w <= 100 && c >= 0 && c <= 100 && (w !== 0 || c !== 0)) {
          thresholds[`${m}_warning`] = w;
          thresholds[`${m}_critical`] = c;
          needsRefresh = true;
        }
      });
      if (needsRefresh) {
        await app.api("/api/settings/thresholds", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(thresholds),
        });
      }
    });

    app.closeSettings();
    app.refresh();
  },

  async testEmail() {
    await app.withAdmin(async () => {
      await app.api("/api/test/email", { method: "POST" });
    });
    alert("Test email requested. Check the inbox.");
  },

  async testWebhooks() {
    const urls = document
      .getElementById("set-webhooks")
      .value.split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    await app.withAdmin(async () => {
      for (const u of urls) {
        await app.api("/api/test/webhook", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: u }) });
      }
    });
    alert("Test messages sent to all webhooks.");
  },

  copyToken() {
    navigator.clipboard.writeText(app.settings.token).then(() => alert("Token copied"));
  },

  openProjectAlerts(project) {
    app.currentProject = project;
    const cfg = app.projectAlerts[project] || {};
    document.getElementById("project-modal-title").textContent = `Project alerts: ${project}`;
    document.getElementById("project-email").value = cfg.email_to || "";
    document.getElementById("project-webhooks").value = (cfg.webhooks || []).join("\n");
    document.getElementById("project-modal").style.display = "flex";
  },

  closeProject() {
    document.getElementById("project-modal").style.display = "none";
  },

  async saveProjectAlerts() {
    await app.withAdmin(async () => {
      await app.api(`/api/project-alerts/${encodeURIComponent(app.currentProject)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email_to: document.getElementById("project-email").value.trim(),
          webhooks: document.getElementById("project-webhooks").value.split("\n").map((s) => s.trim()).filter(Boolean),
        }),
      });
    });
    app.closeProject();
    app.refresh();
  },

  async testProject() {
    await app.withAdmin(async () => {
      await app.api(`/api/project-alerts/${encodeURIComponent(app.currentProject)}/test`, { method: "POST" });
    });
    alert("Test alert sent to this project.");
  },

  renderProjectAlertsList(container) {
    const projects = [...new Set(app.clients.flatMap((c) => c.projects || []))].sort();
    if (projects.length === 0) {
      container.innerHTML = '<p class="hint">Assign a project to a client first (open a client, edit Project, Save).</p>';
      return;
    }
    container.innerHTML = "";
    projects.forEach((proj) => {
      const cfg = app.projectAlerts[proj] || {};
      const row = document.createElement("div");
      row.className = "project-alert-row";
      row.innerHTML = `
        <div class="pa-main">
          <span class="pa-name">${app.esc(proj)}</span>
          <span class="pa-status">${cfg.email_to ? `📧 ${app.esc(cfg.email_to)}` : "no email"}${cfg.webhooks && cfg.webhooks.length ? ` · ${cfg.webhooks.length} webhook(s)` : ""}</span>
        </div>
        <button class="btn" onclick="app.openProjectAlerts('${app.esc(proj).replace(/'/g, "\\'")}')">Configure</button>
      `;
      container.appendChild(row);
    });
  },

  openConfirm(id, name) {
    app.confirmClient = { id, name };
    document.getElementById("confirm-text").textContent = `Remove "${name}" from monitoring? This does not touch the machine itself. Type the name to confirm.`;
    document.getElementById("confirm-input").value = "";
    document.getElementById("confirm-modal").style.display = "flex";
  },

  openAdmin() {
    document.getElementById("admin-password").value = "";
    document.getElementById("admin-modal").style.display = "flex";
    setTimeout(() => document.getElementById("admin-password").focus(), 50);
  },

  closeAdmin() {
    app.pendingAdmin = null;
    document.getElementById("admin-modal").style.display = "none";
  },

  async submitAdmin() {
    const password = document.getElementById("admin-password").value;
    try {
      await app.api("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      document.getElementById("admin-modal").style.display = "none";
      const fn = app.pendingAdmin;
      app.pendingAdmin = null;
      if (fn) await fn();
    } catch (e) {
      alert("Wrong password.");
    }
  },

  closeConfirm() {
    document.getElementById("confirm-modal").style.display = "none";
  },

  async doDelete() {
    const input = document.getElementById("confirm-input").value;
    if (!app.confirmClient || input !== app.confirmClient.name) {
      alert("Name does not match. Nothing was removed.");
      return;
    }
    const id = app.confirmClient.id;
    const name = app.confirmClient.name;
    await app.withAdmin(async () => {
      await app.api(`/api/clients/${id}?confirm=${encodeURIComponent(name)}`, { method: "DELETE" });
    });
    app.closeConfirm();
    app.backToList();
    app.refresh();
  },

  renderBell() {
    document.getElementById("bell").textContent = app.muted ? "🔕" : "🔔";
    if (app.muted) document.getElementById("bell").style.opacity = "0.5";
    else document.getElementById("bell").style.opacity = "1";
  },

  playBell() {
    if (app.muted) return;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = app.audioCtx || (app.audioCtx = new Ctx());
      const now = ctx.currentTime;
      [880, 660].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = freq;
        osc.type = "sine";
        gain.gain.setValueAtTime(0.0001, now + i * 0.18);
        gain.gain.exponentialRampToValueAtTime(0.15, now + i * 0.18 + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.18 + 0.16);
        osc.connect(gain).connect(ctx.destination);
        osc.start(now + i * 0.18);
        osc.stop(now + i * 0.18 + 0.18);
      });
    } catch (e) {}
  },
};

document.getElementById("bell").addEventListener("click", () => {
  app.muted = !app.muted;
  localStorage.setItem("ms_muted", app.muted ? "1" : "0");
  app.renderBell();
});

app.init();