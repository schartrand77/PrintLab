from __future__ import annotations

import json
from pathlib import Path

from app.runtime import service_or_404

dashboard_html_template = (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")
static_dir = Path(__file__).with_name("static")


def render_gallery_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta id="themeColorMeta" name="theme-color" content="#cfe2f7">
  <title>PrintLab - Printers</title>
  <script>
    (function() {
      const theme = localStorage.getItem("printlab-theme") === "dark" ? "dark" : "light";
      document.documentElement.dataset.theme = theme;
    })();
  </script>
  <style>
    :root {
      --bg: #e6f0fb;
      --text: #213245;
      --panel: linear-gradient(180deg, #f4f8fc 0%, #eaf2fb 100%);
      --panel-border: #cfe0f3;
      --panel-shadow: 18px 0 30px rgba(21,50,80,.18);
      --overlay: rgba(18,34,52,.36);
      --card: #fff;
      --card-shadow: 0 10px 30px rgba(42,90,138,.16);
      --muted: #5d738a;
      --button-bg: #1f4f7b;
      --button-text: #fff;
      --tab-bg: #edf4fb;
      --tab-border: #bdd2e8;
      --tab-text: #375a79;
      --tab-hover: #e3eef9;
      --toggle-bg: #dbe9f7;
      --toggle-text: #244563;
      --toggle-hover: #c6dbef;
      --close-text: #365877;
      --theme-color: #cfe2f7;
    }
    :root[data-theme="dark"] {
      --bg: #0e1723;
      --text: #edf5ff;
      --panel: linear-gradient(180deg, #132131 0%, #0f1b2a 100%);
      --panel-border: #24384d;
      --panel-shadow: 18px 0 36px rgba(1,6,14,.48);
      --overlay: rgba(4,10,18,.68);
      --card: #162231;
      --card-shadow: 0 14px 34px rgba(1,6,14,.32);
      --muted: #9db5cf;
      --button-bg: #2c6aa0;
      --button-text: #f5faff;
      --tab-bg: #172536;
      --tab-border: #2a4158;
      --tab-text: #d7e7f8;
      --tab-hover: #203247;
      --toggle-bg: #1f3146;
      --toggle-text: #d9ebfd;
      --toggle-hover: #28415d;
      --close-text: #d0e4f8;
      --theme-color: #0e1723;
    }
    * { box-sizing:border-box; }
    html { color-scheme: light; }
    :root[data-theme="dark"] { color-scheme: dark; }
    body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; margin:0; background:var(--bg); color:var(--text); }
    .wrap { max-width:1100px; margin:0 auto; padding:24px 16px 40px; }
    .top-row { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:14px; }
    .title-block { display:grid; gap:8px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:16px; }
    .card { background:var(--card); border-radius:18px; box-shadow:var(--card-shadow); overflow:hidden; }
    .card a { color:inherit; text-decoration:none; display:grid; gap:12px; padding:14px; min-width:0; }
    .printer-media {
      position:relative;
      border-radius:14px;
      overflow:hidden;
      background:linear-gradient(160deg, rgba(245,250,255,.92), rgba(217,231,245,.88));
      min-height:170px;
    }
    .printer-art { width:100%; height:170px; object-fit:contain; display:block; }
    .printer-media::after {
      content:"";
      position:absolute;
      inset:auto 0 0 0;
      height:54px;
      background:linear-gradient(180deg, rgba(15,27,42,0), rgba(15,27,42,.24));
      pointer-events:none;
    }
    .status-stack {
      position:absolute;
      left:10px;
      right:10px;
      bottom:10px;
      display:flex;
      justify-content:space-between;
      gap:8px;
      align-items:flex-end;
    }
    .status-badges {
      display:flex;
      flex-wrap:wrap;
      gap:6px;
    }
    .badge {
      display:inline-flex;
      align-items:center;
      gap:6px;
      padding:5px 9px;
      border-radius:999px;
      font-size:12px;
      font-weight:700;
      backdrop-filter:blur(8px);
      -webkit-backdrop-filter:blur(8px);
    }
    .badge.ok { background:rgba(229,247,238,.92); color:#2f8b56; }
    .badge.bad { background:rgba(253,236,235,.94); color:#a0413b; }
    .badge.info { background:rgba(237,244,251,.94); color:#375a79; }
    .badge.warning { background:rgba(255,242,215,.96); color:#926125; }
    .name-row { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; flex-wrap:wrap; }
    .name-block { min-width:0; flex:1 1 180px; }
    .name { margin:0; font-size:21px; line-height:1.1; }
    .meta { color:var(--muted); font-size:13px; }
    .health-chip {
      border-radius:999px;
      padding:6px 10px;
      background:var(--tab-bg);
      border:1px solid var(--tab-border);
      color:var(--tab-text);
      font-size:12px;
      font-weight:700;
      white-space:nowrap;
      flex:0 0 auto;
      max-width:100%;
    }
    .job-shell { display:grid; gap:8px; }
    .job-title {
      font-size:16px;
      font-weight:700;
      line-height:1.2;
      min-height:38px;
      min-width:0;
      overflow-wrap:anywhere;
    }
    .job-subtitle {
      color:var(--muted);
      font-size:13px;
      min-height:18px;
      min-width:0;
      overflow-wrap:anywhere;
    }
    .progress-track {
      height:8px;
      border-radius:999px;
      overflow:hidden;
      background:rgba(31,79,123,.12);
    }
    .progress-fill {
      height:100%;
      width:0;
      border-radius:999px;
      background:linear-gradient(90deg, #2fa5ff, #56ce8a);
    }
    .card-stats {
      display:grid;
      grid-template-columns:repeat(3, minmax(0, 1fr));
      gap:8px;
    }
    .card-stat {
      border-radius:12px;
      background:var(--tab-bg);
      border:1px solid var(--tab-border);
      padding:8px 10px;
      display:grid;
      gap:4px;
    }
    .card-stat-label {
      color:var(--muted);
      font-size:11px;
      text-transform:uppercase;
      letter-spacing:.3px;
    }
    .card-stat-value {
      font-size:16px;
      font-weight:800;
      line-height:1.1;
    }
    .card-note {
      color:var(--muted);
      font-size:12px;
      line-height:1.35;
      min-height:32px;
      overflow-wrap:anywhere;
    }
    .hamburger { border:0; border-radius:10px; background:var(--button-bg); color:var(--button-text); cursor:pointer; width:42px; height:34px; display:grid; place-items:center; box-shadow:0 8px 22px rgba(22,54,86,.34); }
    .hamburger-lines { width:16px; height:12px; position:relative; }
    .hamburger-lines::before, .hamburger-lines::after, .hamburger-lines span { content:""; position:absolute; left:0; right:0; height:2px; background:currentColor; border-radius:2px; }
    .hamburger-lines::before { top:0; }
    .hamburger-lines span { top:5px; }
    .hamburger-lines::after { top:10px; }
    .sidebar-backdrop { position:fixed; inset:0; background:var(--overlay); display:none; z-index:40; }
    .sidebar-backdrop.open { display:block; }
    .sidebar { position:fixed; z-index:41; top:0; left:0; height:100vh; width:320px; max-width:85vw; background:var(--panel); border-right:1px solid var(--panel-border); box-shadow:var(--panel-shadow); transform:translateX(-101%); transition:transform .18s ease; padding:18px 14px 16px; overflow:auto; }
    .sidebar.open { transform:translateX(0); }
    .sidebar-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
    .sidebar-head-actions { display:flex; align-items:center; gap:8px; }
    .theme-toggle { border:0; border-radius:999px; background:var(--toggle-bg); color:var(--toggle-text); cursor:pointer; padding:6px 10px; font-size:12px; font-weight:600; }
    .theme-toggle:hover { background:var(--toggle-hover); }
    .sidebar-close { border:0; background:transparent; color:var(--close-text); cursor:pointer; font-size:20px; line-height:1; padding:2px 4px; }
    .sidebar h2 { margin:0; font-size:20px; }
    .sidebar p { color:var(--muted); font-size:13px; line-height:1.4; }
    .sidebar-tabs { display:grid; gap:8px; margin:0 0 12px; }
    .sidebar-tab { display:block; text-decoration:none; border:1px solid var(--tab-border); background:var(--tab-bg); color:var(--tab-text); border-radius:999px; padding:6px 10px; font-size:12px; font-weight:600; text-align:left; }
    .sidebar-tab:hover { background:var(--tab-hover); }
    @media (max-width: 720px) {
      .grid { grid-template-columns:1fr; }
      .card-stats { grid-template-columns:1fr 1fr; }
      .health-chip { order:2; }
      .name-block { flex-basis:100%; }
    }
    @media (max-width: 420px) {
      .wrap { padding-left:12px; padding-right:12px; }
      .card-stats { grid-template-columns:1fr; }
    }
  </style>
</head>
<body>
  <div id="sidebarBackdrop" class="sidebar-backdrop" onclick="closeSidebar()"></div>
  <aside id="sidebar" class="sidebar" aria-hidden="true">
    <div class="sidebar-head">
      <h2>Menu</h2>
      <div class="sidebar-head-actions">
        <button id="themeToggle" class="theme-toggle" type="button" aria-label="Switch color theme">Dark</button>
        <button class="sidebar-close" type="button" aria-label="Close menu" onclick="closeSidebar()">&times;</button>
      </div>
    </div>
    <p>Use the sidebar for navigation.</p>
    <div class="sidebar-tabs">
      <a class="sidebar-tab" href="/">Dashboard</a>
      <a class="sidebar-tab" href="/makerworks">MakerWorks</a>
      <a class="sidebar-tab" href="/add-printer">Add Printer</a>
    </div>
  </aside>
  <div class="wrap">
    <div class="top-row">
      <div class="title-block">
        <button class="hamburger" type="button" aria-label="Open menu" onclick="openSidebar()"><div class="hamburger-lines"><span></span></div></button>
        <div>
          <h1>PrintLab</h1>
          <p>Select a printer to open the dashboard.</p>
        </div>
      </div>
    </div>
    <div class="grid" id="cards"></div>
  </div>
  <script>
    const cards = document.getElementById('cards');
    const sidebar = document.getElementById('sidebar');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');
    const themeStorageKey = 'printlab-theme';
    const nativeFetch = window.fetch.bind(window);

    function readCookie(name) {
      const prefix = `${name}=`;
      return document.cookie.split(';').map((item) => item.trim()).find((item) => item.startsWith(prefix))?.slice(prefix.length) || '';
    }

    window.fetch = function(input, init = {}) {
      const next = { ...init, credentials: 'same-origin' };
      const method = String(next.method || 'GET').toUpperCase();
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        const headers = new Headers(next.headers || {});
        const csrf = readCookie('printlab_csrf');
        if (csrf && !headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', csrf);
        next.headers = headers;
      }
      return nativeFetch(input, next);
    };

    function applyTheme(theme) {
      const nextTheme = theme === 'dark' ? 'dark' : 'light';
      document.documentElement.dataset.theme = nextTheme;
      localStorage.setItem(themeStorageKey, nextTheme);
      const toggle = document.getElementById('themeToggle');
      if (toggle) toggle.textContent = nextTheme === 'dark' ? 'Light' : 'Dark';
      const meta = document.getElementById('themeColorMeta');
      if (meta) meta.setAttribute('content', nextTheme === 'dark' ? '#0e1723' : '#cfe2f7');
    }

    function toggleTheme() {
      const current = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
      applyTheme(current === 'dark' ? 'light' : 'dark');
    }

    function openSidebar() {
      sidebar.classList.add('open');
      sidebarBackdrop.classList.add('open');
      sidebar.setAttribute('aria-hidden', 'false');
    }

    function closeSidebar() {
      sidebar.classList.remove('open');
      sidebarBackdrop.classList.remove('open');
      sidebar.setAttribute('aria-hidden', 'true');
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>\"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '\"': '&quot;',
        \"'\": '&#39;'
      }[char]));
    }

    function formatRemainingMinutes(value) {
      const minutes = Number(value);
      if (!Number.isFinite(minutes) || minutes < 0) return '-';
      if (minutes < 1) return '<1m';
      const rounded = Math.round(minutes);
      const hours = Math.floor(rounded / 60);
      const mins = rounded % 60;
      if (hours <= 0) return `${mins}m`;
      if (mins === 0) return `${hours}h`;
      return `${hours}h ${mins}m`;
    }

    function busyState(raw) {
      const state = String(raw || '').toUpperCase();
      if (!state) return false;
      return !['IDLE', 'FINISH', 'COMPLETE', 'FAILED', 'STOP'].some((marker) => state.includes(marker));
    }

    function statusTone(item) {
      if (!item.connected) return 'bad';
      if (item.active_alert_count) return 'warning';
      return 'ok';
    }

    function statusLabel(item) {
      if (!item.connected) return 'Offline';
      const state = String(item.job?.state || '').trim();
      if (state) return state;
      return 'Ready';
    }

    function currentJobName(item) {
      const subtask = String(item.job?.subtask_name || '').trim();
      if (subtask) return subtask;
      const file = String(item.job?.file || '').trim();
      if (file) {
        const parts = file.split('/');
        return parts[parts.length - 1] || file;
      }
      return item.connected ? 'No active print' : 'Waiting for printer';
    }

    function currentJobSubtitle(item) {
      if (!item.connected) {
        return item.last_error ? `Last error: ${item.last_error}` : 'Printer is offline.';
      }
      if (busyState(item.job?.state)) {
        const layers = Number(item.job?.current_layer);
        const totalLayers = Number(item.job?.total_layers);
        const layerText = Number.isFinite(layers) && Number.isFinite(totalLayers) && totalLayers > 0
          ? `Layer ${layers}/${totalLayers}`
          : 'Print in progress';
        const remaining = formatRemainingMinutes(item.job?.remaining_minutes);
        return remaining === '-' ? layerText : `${layerText} • ${remaining} left`;
      }
      if ((item.queue?.count || 0) > 0) {
        return `${item.queue.count} queued job${item.queue.count === 1 ? '' : 's'} waiting`;
      }
      return 'Ready for the next print.';
    }

    function renderPrinterCard(item) {
      const tone = statusTone(item);
      const preview = item.job?.thumbnail_url || '/static/printers/x1c.jpg';
      const progress = Math.max(0, Math.min(100, Number(item.job?.progress_percent ?? 0)));
      const queueCount = Number(item.queue?.count ?? 0);
      const healthScore = item.health?.score ?? '-';
      const remaining = busyState(item.job?.state) ? formatRemainingMinutes(item.job?.remaining_minutes) : 'Ready';
      return `
        <article class="card">
          <a href="/printer/${encodeURIComponent(item.id)}">
            <div class="printer-media">
              <img class="printer-art" src="${escapeHtml(preview)}" alt="${escapeHtml(item.name)} preview" onerror="this.onerror=null;this.src='/static/printers/x1c.jpg'">
              <div class="status-stack">
                <div class="status-badges">
                  <span class="badge ${tone}">${escapeHtml(statusLabel(item))}</span>
                  ${queueCount > 0 ? `<span class="badge info">${queueCount} queued</span>` : ''}
                  ${item.active_alert_count ? `<span class="badge warning">${item.active_alert_count} alert${item.active_alert_count === 1 ? '' : 's'}</span>` : ''}
                </div>
              </div>
            </div>
            <div class="name-row">
              <div class="name-block">
                <h2 class="name">${escapeHtml(item.name)}</h2>
                <div class="meta">${escapeHtml(item.device_type || 'Unknown device')}</div>
              </div>
              <div class="health-chip">Health ${escapeHtml(String(healthScore))}</div>
            </div>
            <div class="job-shell">
              <div class="job-title">${escapeHtml(currentJobName(item))}</div>
              <div class="job-subtitle">${escapeHtml(currentJobSubtitle(item))}</div>
              <div class="progress-track"><div class="progress-fill" style="width:${progress}%"></div></div>
            </div>
            <div class="card-stats">
              <div class="card-stat">
                <div class="card-stat-label">Progress</div>
                <div class="card-stat-value">${escapeHtml(`${Math.round(progress)}%`)}</div>
              </div>
              <div class="card-stat">
                <div class="card-stat-label">Remaining</div>
                <div class="card-stat-value">${escapeHtml(remaining)}</div>
              </div>
              <div class="card-stat">
                <div class="card-stat-label">Queue</div>
                <div class="card-stat-value">${escapeHtml(String(queueCount))}</div>
              </div>
            </div>
            <div class="card-note">${escapeHtml(item.serial || item.last_error || 'Open the printer card for controls and full telemetry.')}</div>
          </a>
        </article>
      `;
    }

    async function loadPrinters() {
      try {
        const response = await fetch('/api/printers');
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data?.detail || `HTTP ${response.status}`);
        }
        const items = data.items || [];
        cards.innerHTML = items.map((item) => renderPrinterCard(item)).join('');
        if (!items.length) {
          cards.innerHTML = "<div class='meta'>No printers configured yet.</div>";
        }
      } catch (error) {
        cards.innerHTML = `<div class='meta'>Failed to load printers: ${escapeHtml(String(error?.message || error))}</div>`;
      }
    }

    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
      themeToggle.addEventListener('click', toggleTheme);
    }
    applyTheme(document.documentElement.dataset.theme);
    loadPrinters();
    setInterval(loadPrinters, 4000);
  </script>
</body>
</html>"""


def render_add_printer_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta id="themeColorMeta" name="theme-color" content="#cfe2f7">
  <title>PrintLab - Add Printer</title>
  <script>
    (function() {
      const theme = localStorage.getItem("printlab-theme") === "dark" ? "dark" : "light";
      document.documentElement.dataset.theme = theme;
    })();
  </script>
  <style>
    :root {
      --bg: #e6f0fb;
      --text: #213245;
      --panel: linear-gradient(180deg, #f4f8fc 0%, #eaf2fb 100%);
      --panel-border: #cfe0f3;
      --panel-shadow: 18px 0 30px rgba(21,50,80,.18);
      --overlay: rgba(18,34,52,.36);
      --card: #fff;
      --card-shadow: 0 10px 30px rgba(42,90,138,.16);
      --muted: #5d738a;
      --button-bg: #1f4f7b;
      --button-text: #fff;
      --tab-bg: #edf4fb;
      --tab-border: #bdd2e8;
      --tab-text: #375a79;
      --tab-active-bg: #1f4f7b;
      --tab-active-border: #1f4f7b;
      --tab-active-text: #fff;
      --toggle-bg: #dbe9f7;
      --toggle-text: #244563;
      --toggle-hover: #c6dbef;
      --close-text: #365877;
      --field-bg: #fff;
      --field-border: #c4d9ee;
      --item-bg: #f9fcff;
      --item-border: #d6e4f2;
    }
    :root[data-theme="dark"] {
      --bg: #0e1723;
      --text: #edf5ff;
      --panel: linear-gradient(180deg, #132131 0%, #0f1b2a 100%);
      --panel-border: #24384d;
      --panel-shadow: 18px 0 36px rgba(1,6,14,.48);
      --overlay: rgba(4,10,18,.68);
      --card: #162231;
      --card-shadow: 0 14px 34px rgba(1,6,14,.32);
      --muted: #9db5cf;
      --button-bg: #2c6aa0;
      --button-text: #f5faff;
      --tab-bg: #172536;
      --tab-border: #2a4158;
      --tab-text: #d7e7f8;
      --tab-active-bg: #2c6aa0;
      --tab-active-border: #2c6aa0;
      --tab-active-text: #f5faff;
      --toggle-bg: #1f3146;
      --toggle-text: #d9ebfd;
      --toggle-hover: #28415d;
      --close-text: #d0e4f8;
      --field-bg: #0f1b2a;
      --field-border: #2a4158;
      --item-bg: #122031;
      --item-border: #29425a;
    }
    * { box-sizing:border-box; }
    html { color-scheme: light; }
    :root[data-theme="dark"] { color-scheme: dark; }
    body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; margin:0; background:var(--bg); color:var(--text); }
    .wrap { max-width:1100px; margin:0 auto; padding:24px 16px 40px; }
    .top-row { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:14px; }
    .title-block { display:grid; gap:8px; }
    .hamburger { border:0; border-radius:10px; background:var(--button-bg); color:var(--button-text); cursor:pointer; width:42px; height:34px; display:grid; place-items:center; box-shadow:0 8px 22px rgba(22,54,86,.34); }
    .hamburger-lines { width:16px; height:12px; position:relative; }
    .hamburger-lines::before, .hamburger-lines::after, .hamburger-lines span { content:""; position:absolute; left:0; right:0; height:2px; background:currentColor; border-radius:2px; }
    .hamburger-lines::before { top:0; }
    .hamburger-lines span { top:5px; }
    .hamburger-lines::after { top:10px; }
    .sidebar-backdrop { position:fixed; inset:0; background:var(--overlay); display:none; z-index:40; }
    .sidebar-backdrop.open { display:block; }
    .sidebar { position:fixed; z-index:41; top:0; left:0; height:100vh; width:320px; max-width:85vw; background:var(--panel); border-right:1px solid var(--panel-border); box-shadow:var(--panel-shadow); transform:translateX(-101%); transition:transform .18s ease; padding:18px 14px 16px; overflow:auto; }
    .sidebar.open { transform:translateX(0); }
    .sidebar-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
    .sidebar-head-actions { display:flex; align-items:center; gap:8px; }
    .theme-toggle { border:0; border-radius:999px; background:var(--toggle-bg); color:var(--toggle-text); cursor:pointer; padding:6px 10px; font-size:12px; font-weight:600; }
    .theme-toggle:hover { background:var(--toggle-hover); }
    .sidebar-close { border:0; background:transparent; color:var(--close-text); cursor:pointer; font-size:20px; line-height:1; padding:2px 4px; }
    .sidebar h2 { margin:0; font-size:20px; }
    .sidebar p { color:var(--muted); font-size:13px; line-height:1.4; }
    .sidebar-tabs { display:grid; gap:8px; margin:0 0 12px; }
    .sidebar-tab { display:block; text-decoration:none; border:1px solid var(--tab-border); background:var(--tab-bg); color:var(--tab-text); border-radius:999px; padding:6px 10px; font-size:12px; font-weight:600; text-align:left; }
    .sidebar-tab.active { background:var(--tab-active-bg); border-color:var(--tab-active-border); color:var(--tab-active-text); }
    .layout { display:grid; gap:16px; }
    .panel { background:var(--card); border-radius:16px; padding:18px; box-shadow:var(--card-shadow); }
    .panel h2 { margin:0 0 8px; }
    .panel p { margin:0 0 14px; color:var(--muted); }
    .panel-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
    .form-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px; }
    .field label { display:block; font-size:12px; color:#496986; margin-bottom:4px; }
    .field input { width:100%; box-sizing:border-box; border:1px solid var(--field-border); border-radius:10px; padding:10px; font-size:14px; background:var(--field-bg); color:var(--text); }
    .field input[readonly] { opacity:.72; cursor:not-allowed; }
    .check-row { display:flex; gap:14px; flex-wrap:wrap; margin-top:6px; }
    .check { display:flex; align-items:center; gap:8px; font-size:13px; color:#2f4f6d; }
    .actions { display:flex; gap:8px; margin-top:14px; }
    .btn { border:0; border-radius:10px; padding:10px 14px; cursor:pointer; font-weight:600; }
    .btn-primary { background:var(--button-bg); color:var(--button-text); }
    .btn-light { background:var(--toggle-bg); color:var(--toggle-text); }
    .btn-danger { background:#b8433b; color:#fff; }
    .btn-danger[disabled] { opacity:.55; cursor:not-allowed; }
    .status { min-height:18px; margin-top:10px; color:#496986; font-size:12px; }
    .status.error { color:#8f3d36; }
    .printer-list { display:grid; gap:10px; margin-top:14px; }
    .printer-item { border:1px solid var(--item-border); border-radius:12px; padding:12px; background:var(--item-bg); }
    .printer-item-head { display:flex; justify-content:space-between; gap:8px; align-items:flex-start; }
    .printer-item-actions { display:flex; gap:8px; align-items:center; margin-top:10px; }
    .printer-name { margin:0; font-size:18px; }
    .printer-meta { color:var(--muted); font-size:13px; margin-top:4px; }
    .printer-note { color:var(--muted); font-size:12px; margin-top:8px; }
    .badge { display:inline-block; padding:4px 8px; border-radius:999px; font-size:12px; }
    .ok { background:#e5f7ee; color:#2f8b56; }
    .bad { background:#fdeceb; color:#a0413b; }
  </style>
</head>
<body>
  <div id="sidebarBackdrop" class="sidebar-backdrop" onclick="closeSidebar()"></div>
  <aside id="sidebar" class="sidebar" aria-hidden="true">
    <div class="sidebar-head">
      <h2>Menu</h2>
      <div class="sidebar-head-actions">
        <button id="themeToggle" class="theme-toggle" type="button" aria-label="Switch color theme">Dark</button>
        <button class="sidebar-close" type="button" aria-label="Close menu" onclick="closeSidebar()">&times;</button>
      </div>
    </div>
    <p>Use the sidebar for navigation.</p>
    <div class="sidebar-tabs">
      <a class="sidebar-tab" href="/">Dashboard</a>
      <a class="sidebar-tab" href="/makerworks">MakerWorks</a>
      <a class="sidebar-tab active" href="/add-printer">Add Printer</a>
    </div>
  </aside>
  <div class="wrap">
    <div class="top-row">
      <div class="title-block">
        <button class="hamburger" type="button" aria-label="Open menu" onclick="openSidebar()"><div class="hamburger-lines"><span></span></div></button>
        <div>
          <h1>Add Printer</h1>
          <p>Create a printer entry and review existing printers below.</p>
        </div>
      </div>
    </div>
    <div class="layout">
      <section class="panel">
        <div class="panel-head">
          <div>
            <h2 id="formTitle">New Printer</h2>
            <p id="formSubtitle">Fill in the printer connection details.</p>
          </div>
        </div>
        <input id="editingPrinterId" type="hidden" value="">
        <div class="form-grid">
          <div class="field">
            <label for="printerName">Printer Name</label>
            <input id="printerName" type="text" placeholder="X1C-002">
          </div>
          <div class="field">
            <label for="printerId">Printer ID</label>
            <input id="printerId" type="text" placeholder="printer-2">
          </div>
          <div class="field">
            <label for="printerHost">Printer Host</label>
            <input id="printerHost" type="text" placeholder="192.168.1.67">
          </div>
          <div class="field">
            <label for="printerSerial">Printer Serial</label>
            <input id="printerSerial" type="text" placeholder="SERIAL">
          </div>
          <div class="field" style="grid-column:1 / -1;">
            <label for="printerAccessCode">Printer Access Code</label>
            <input id="printerAccessCode" type="text" placeholder="ACCESS CODE">
          </div>
        </div>
        <div class="check-row">
          <label class="check"><input id="printerLocalMqtt" type="checkbox" checked> Local MQTT</label>
          <label class="check"><input id="printerEnableCamera" type="checkbox" checked> Enable Camera</label>
          <label class="check"><input id="printerDisableSslVerify" type="checkbox"> Disable SSL Verify</label>
        </div>
        <div class="actions">
          <button id="submitPrinterBtn" class="btn btn-primary" type="button" onclick="submitAddPrinter()">Add Printer</button>
          <button id="resetPrinterBtn" class="btn btn-light" type="button" onclick="resetAddPrinterForm()">Clear</button>
        </div>
        <div id="pageStatus" class="status"></div>
      </section>
      <section class="panel">
        <h2>Added Printers</h2>
        <p>Current printer entries.</p>
        <div id="printerList" class="printer-list"></div>
      </section>
    </div>
  </div>
  <script>
    const sidebar = document.getElementById('sidebar');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');
    const printerList = document.getElementById('printerList');
    const themeStorageKey = 'printlab-theme';
    let printersById = {};
    const nativeFetch = window.fetch.bind(window);

    function readCookie(name) {
      const prefix = `${name}=`;
      return document.cookie.split(';').map((item) => item.trim()).find((item) => item.startsWith(prefix))?.slice(prefix.length) || '';
    }

    window.fetch = function(input, init = {}) {
      const next = { ...init, credentials: 'same-origin' };
      const method = String(next.method || 'GET').toUpperCase();
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        const headers = new Headers(next.headers || {});
        const csrf = readCookie('printlab_csrf');
        if (csrf && !headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', csrf);
        next.headers = headers;
      }
      return nativeFetch(input, next);
    };

    function applyTheme(theme) {
      const nextTheme = theme === 'dark' ? 'dark' : 'light';
      document.documentElement.dataset.theme = nextTheme;
      localStorage.setItem(themeStorageKey, nextTheme);
      const toggle = document.getElementById('themeToggle');
      if (toggle) toggle.textContent = nextTheme === 'dark' ? 'Light' : 'Dark';
      const meta = document.getElementById('themeColorMeta');
      if (meta) meta.setAttribute('content', nextTheme === 'dark' ? '#0e1723' : '#cfe2f7');
    }

    function toggleTheme() {
      const current = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
      applyTheme(current === 'dark' ? 'light' : 'dark');
    }

    function openSidebar() {
      sidebar.classList.add('open');
      sidebarBackdrop.classList.add('open');
      sidebar.setAttribute('aria-hidden', 'false');
    }

    function closeSidebar() {
      sidebar.classList.remove('open');
      sidebarBackdrop.classList.remove('open');
      sidebar.setAttribute('aria-hidden', 'true');
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>\"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '\"': '&quot;',
        \"'\": '&#39;'
      }[char]));
    }

    function setPageStatus(message, isError = false) {
      const status = document.getElementById('pageStatus');
      status.textContent = message || '';
      status.classList.toggle('error', !!isError);
    }

    function setFormMode(editingId = '') {
      const isEditing = !!editingId;
      document.getElementById('editingPrinterId').value = editingId;
      document.getElementById('formTitle').textContent = isEditing ? 'Edit Printer' : 'New Printer';
      document.getElementById('formSubtitle').textContent = isEditing
        ? 'Update the saved printer connection details.'
        : 'Fill in the printer connection details.';
      document.getElementById('submitPrinterBtn').textContent = isEditing ? 'Save Changes' : 'Add Printer';
      document.getElementById('resetPrinterBtn').textContent = isEditing ? 'Cancel' : 'Clear';
      document.getElementById('printerId').readOnly = isEditing;
    }

    function resetAddPrinterForm() {
      setFormMode('');
      document.getElementById('printerName').value = '';
      document.getElementById('printerHost').value = '';
      document.getElementById('printerSerial').value = '';
      document.getElementById('printerAccessCode').value = '';
      document.getElementById('printerId').value = '';
      document.getElementById('printerLocalMqtt').checked = true;
      document.getElementById('printerEnableCamera').checked = true;
      document.getElementById('printerDisableSslVerify').checked = false;
      setPageStatus('');
    }

    function startEditPrinter(printerId) {
      const item = printersById[printerId];
      if (!item || !item.can_edit) {
        setPageStatus('This printer cannot be edited here.', true);
        return;
      }
      const settings = item.settings || {};
      setFormMode(printerId);
      document.getElementById('printerName').value = settings.name || item.name || '';
      document.getElementById('printerHost').value = settings.host || '';
      document.getElementById('printerSerial').value = settings.serial || '';
      document.getElementById('printerAccessCode').value = settings.access_code || '';
      document.getElementById('printerId').value = item.id || '';
      document.getElementById('printerLocalMqtt').checked = !!settings.local_mqtt;
      document.getElementById('printerEnableCamera').checked = !!settings.enable_camera;
      document.getElementById('printerDisableSslVerify').checked = !!settings.disable_ssl_verify;
      setPageStatus(`Editing ${item.name}.`);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    async function deletePrinter(printerId) {
      const item = printersById[printerId];
      if (!item || !item.can_delete) {
        setPageStatus('This printer cannot be deleted here.', true);
        return;
      }
      if (!window.confirm(`Delete ${item.name}?`)) return;
      setPageStatus(`Deleting ${item.name}...`);
      try {
        const response = await fetch(`/api/printers/${encodeURIComponent(printerId)}`, { method: 'DELETE' });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail || `HTTP ${response.status}`);
        }
        if (document.getElementById('editingPrinterId').value === printerId) {
          resetAddPrinterForm();
        }
        setPageStatus(`Deleted ${item.name}.`);
        await loadPrinters();
      } catch (error) {
        setPageStatus(`Delete failed: ${String(error?.message || error)}`, true);
      }
    }

    async function loadPrinters() {
      const response = await fetch('/api/printers');
      const data = await response.json();
      const items = data.items || [];
      printersById = Object.fromEntries(items.map((item) => [item.id, item]));
      if (!items.length) {
        printerList.innerHTML = "<div class='printer-item'><div class='printer-meta'>No printers added yet.</div></div>";
        return;
      }
      printerList.innerHTML = items.map((item) => `
        <article class="printer-item">
          <div class="printer-item-head">
            <div>
              <h3 class="printer-name">${escapeHtml(item.name)}</h3>
              <div class="printer-meta">${escapeHtml(item.id)} • ${escapeHtml(item.device_type || 'Unknown device')}</div>
              <div class="printer-meta">${escapeHtml(item.serial || '-')}</div>
            </div>
            <span class="badge ${item.connected ? 'ok' : 'bad'}">${item.connected ? 'Connected' : 'Offline'}</span>
          </div>
          <div class="printer-item-actions">
            ${item.can_edit ? `<button class="btn btn-light" type="button" data-action="edit" data-printer-id="${escapeHtml(item.id)}">Edit</button>` : ''}
            <button class="btn btn-danger" type="button" data-action="delete" data-printer-id="${escapeHtml(item.id)}" ${item.can_delete ? '' : 'disabled'}>Delete</button>
          </div>
          <div class="printer-note">${item.can_edit ? 'Saved from this page.' : 'Configured outside this page. Edit and delete are unavailable here.'}</div>
        </article>
      `).join('');
    }

    async function submitAddPrinter() {
      const editingPrinterId = document.getElementById('editingPrinterId').value.trim();
      const payload = {
        name: document.getElementById('printerName').value.trim(),
        host: document.getElementById('printerHost').value.trim(),
        serial: document.getElementById('printerSerial').value.trim(),
        access_code: document.getElementById('printerAccessCode').value.trim(),
        device_type: 'unknown',
        local_mqtt: document.getElementById('printerLocalMqtt').checked,
        enable_camera: document.getElementById('printerEnableCamera').checked,
        disable_ssl_verify: document.getElementById('printerDisableSslVerify').checked
      };
      if (!editingPrinterId) {
        payload.id = document.getElementById('printerId').value.trim() || null;
      }
      if (!payload.name || !payload.host || !payload.serial || !payload.access_code) {
        setPageStatus('Name, host, serial, and access code are required.', true);
        return;
      }
      try {
        const response = await fetch(editingPrinterId ? `/api/printers/${encodeURIComponent(editingPrinterId)}` : '/api/printers', {
          method: editingPrinterId ? 'PATCH' : 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail || `HTTP ${response.status}`);
        }
        setPageStatus(`${editingPrinterId ? 'Updated' : 'Added'} printer ${data?.printer?.name || payload.name}.`);
        resetAddPrinterForm();
        await loadPrinters();
      } catch (error) {
        setPageStatus(`${editingPrinterId ? 'Update' : 'Add'} failed: ${String(error?.message || error)}`, true);
      }
    }

    printerList.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const action = target.dataset.action;
      const printerId = target.dataset.printerId;
      if (!action || !printerId) return;
      if (action === 'edit') {
        startEditPrinter(printerId);
      } else if (action === 'delete') {
        deletePrinter(printerId);
      }
    });

    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
      themeToggle.addEventListener('click', toggleTheme);
    }
    applyTheme(document.documentElement.dataset.theme);
    setFormMode('');
    loadPrinters();
  </script>
</body>
</html>"""


def render_makerworks_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta id="themeColorMeta" name="theme-color" content="#cfe2f7">
  <title>PrintLab - MakerWorks</title>
  <script>
    (function() {
      const theme = localStorage.getItem("printlab-theme") === "dark" ? "dark" : "light";
      document.documentElement.dataset.theme = theme;
    })();
  </script>
  <style>
    :root {
      --bg: #e6f0fb;
      --text: #213245;
      --panel: linear-gradient(180deg, #f4f8fc 0%, #eaf2fb 100%);
      --panel-border: #cfe0f3;
      --panel-shadow: 18px 0 30px rgba(21,50,80,.18);
      --overlay: rgba(18,34,52,.36);
      --card: #fff;
      --card-shadow: 0 10px 30px rgba(42,90,138,.16);
      --muted: #5d738a;
      --button-bg: #1f4f7b;
      --button-text: #fff;
      --tab-bg: #edf4fb;
      --tab-border: #bdd2e8;
      --tab-text: #375a79;
      --tab-hover: #e3eef9;
      --toggle-bg: #dbe9f7;
      --toggle-text: #244563;
      --toggle-hover: #c6dbef;
      --close-text: #365877;
      --field-bg: #f9fcff;
      --field-border: #c4d9ee;
      --accent: #1f84ea;
      --accent-2: #56ce8a;
      --success-bg: rgba(86,206,138,.16);
      --success-text: #1d6a45;
      --danger-bg: rgba(210,74,74,.14);
      --danger-text: #9a2b2b;
      --theme-color: #cfe2f7;
    }
    :root[data-theme="dark"] {
      --bg: #0e1723;
      --text: #edf5ff;
      --panel: linear-gradient(180deg, #132131 0%, #0f1b2a 100%);
      --panel-border: #24384d;
      --panel-shadow: 18px 0 36px rgba(1,6,14,.48);
      --overlay: rgba(4,10,18,.68);
      --card: #162231;
      --card-shadow: 0 14px 34px rgba(1,6,14,.32);
      --muted: #9db5cf;
      --button-bg: #2c6aa0;
      --button-text: #f5faff;
      --tab-bg: #172536;
      --tab-border: #2a4158;
      --tab-text: #d7e7f8;
      --tab-hover: #203247;
      --toggle-bg: #1f3146;
      --toggle-text: #d9ebfd;
      --toggle-hover: #28415d;
      --close-text: #d0e4f8;
      --field-bg: #0f1b2a;
      --field-border: #2a4158;
      --success-bg: rgba(86,206,138,.18);
      --success-text: #8ce6b2;
      --danger-bg: rgba(210,74,74,.18);
      --danger-text: #ffb4b4;
      --theme-color: #0e1723;
    }
    * { box-sizing:border-box; }
    html { color-scheme: light; }
    :root[data-theme="dark"] { color-scheme: dark; }
    body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; margin:0; background:var(--bg); color:var(--text); }
    .wrap { max-width:1280px; margin:0 auto; padding:24px 16px 40px; }
    .top-row { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:14px; }
    .title-block { display:grid; gap:8px; }
    .layout { display:grid; grid-template-columns:minmax(0, 1fr) 340px; gap:16px; align-items:start; }
    .main-panel, .side-panel { background:var(--card); border-radius:18px; box-shadow:var(--card-shadow); }
    .main-panel { padding:16px; display:grid; gap:14px; }
    .side-panel { padding:16px; position:sticky; top:20px; display:grid; gap:14px; }
    .controls { display:grid; grid-template-columns:minmax(0, 1.1fr) minmax(220px, .85fr) auto; gap:10px; align-items:end; }
    .field-block { display:grid; gap:6px; }
    .field-label { color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.3px; }
    .field, .select {
      width:100%;
      border:1px solid var(--field-border);
      border-radius:12px;
      background:var(--field-bg);
      color:var(--text);
      padding:11px 12px;
      font-size:14px;
      min-width:0;
    }
    .btn {
      border:0;
      border-radius:12px;
      background:var(--button-bg);
      color:var(--button-text);
      padding:11px 14px;
      font-size:14px;
      font-weight:700;
      cursor:pointer;
    }
    .btn.secondary {
      background:var(--tab-bg);
      color:var(--tab-text);
      border:1px solid var(--tab-border);
    }
    .btn:disabled, .link-btn[aria-disabled="true"] {
      opacity:.55;
      cursor:not-allowed;
      pointer-events:none;
    }
    .status-row { display:flex; flex-wrap:wrap; gap:8px; }
    .pill {
      display:inline-flex;
      align-items:center;
      gap:6px;
      padding:6px 10px;
      border-radius:999px;
      border:1px solid var(--tab-border);
      background:var(--tab-bg);
      color:var(--tab-text);
      font-size:12px;
      font-weight:700;
    }
    .pill.success {
      background:var(--success-bg);
      color:var(--success-text);
      border-color:transparent;
    }
    .pill.error {
      background:var(--danger-bg);
      color:var(--danger-text);
      border-color:transparent;
    }
    .model-grid { display:grid; grid-template-columns:1fr; gap:10px; }
    .model-card {
      border:1px solid var(--tab-border);
      border-radius:16px;
      overflow:hidden;
      background:linear-gradient(180deg, rgba(255,255,255,.92), rgba(241,247,253,.94));
      display:grid;
      grid-template-columns:96px minmax(0, 1fr);
      align-items:stretch;
      min-width:0;
    }
    :root[data-theme="dark"] .model-card,
    :root[data-theme="dark"] .main-panel,
    :root[data-theme="dark"] .side-panel,
    :root[data-theme="dark"] .field,
    :root[data-theme="dark"] .select,
    :root[data-theme="dark"] .pill,
    :root[data-theme="dark"] .btn.secondary {
      background:#132131;
      border-color:var(--tab-border);
      color:var(--text);
    }
    .model-card.selected {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(31,132,234,.18);
    }
    .model-preview {
      height:100%;
      min-height:96px;
      background:linear-gradient(160deg, rgba(245,251,255,.95), rgba(216,233,248,.8));
      display:flex;
      align-items:center;
      justify-content:center;
      padding:8px;
    }
    .model-preview img { max-width:100%; max-height:100%; object-fit:contain; }
    .model-body { padding:10px; display:grid; gap:8px; min-width:0; }
    .model-name { font-size:16px; font-weight:800; line-height:1.1; overflow-wrap:anywhere; }
    .model-meta { color:var(--muted); font-size:12px; line-height:1.25; overflow-wrap:anywhere; }
    .compact-summary {
      display:-webkit-box;
      -webkit-box-orient:vertical;
      -webkit-line-clamp:2;
      overflow:hidden;
    }
    .tag-row { display:flex; flex-wrap:wrap; gap:6px; }
    .tag {
      padding:3px 7px;
      border-radius:999px;
      background:rgba(31,132,234,.08);
      color:#2d5b88;
      font-size:10px;
      font-weight:700;
    }
    .queue-inline {
      display:grid;
      grid-template-columns:minmax(0, 1fr) auto;
      gap:6px;
      align-items:end;
    }
    .queue-inline .field-block { min-width:0; }
    .queue-note {
      color:var(--muted);
      font-size:11px;
      line-height:1.25;
      min-height:0;
      display:-webkit-box;
      -webkit-box-orient:vertical;
      -webkit-line-clamp:2;
      overflow:hidden;
    }
    .model-actions { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
    .model-card .btn,
    .model-card .link-btn,
    .model-card .select {
      padding:8px 10px;
      font-size:12px;
    }
    .model-card .field-label { font-size:11px; }
    .empty { color:var(--muted); font-size:14px; padding:18px 4px; }
    .selection-card {
      border:1px solid var(--tab-border);
      border-radius:16px;
      padding:14px;
      display:grid;
      gap:10px;
      background:linear-gradient(180deg, rgba(31,132,234,.08), rgba(86,206,138,.05));
      min-width:0;
    }
    .selection-title { font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.3px; font-weight:800; }
    .selection-name { font-size:20px; font-weight:800; line-height:1.15; overflow-wrap:anywhere; }
    .selection-meta { color:var(--muted); font-size:13px; line-height:1.35; overflow-wrap:anywhere; }
    .link-btn {
      display:inline-flex;
      align-items:center;
      justify-content:center;
      text-decoration:none;
      border-radius:12px;
      background:linear-gradient(145deg, var(--accent), #2fa5ff);
      color:#fff;
      padding:11px 14px;
      font-size:14px;
      font-weight:700;
    }
    .helper { color:var(--muted); font-size:13px; line-height:1.4; }
    .queue-list { display:grid; gap:10px; }
    .queue-printer-card {
      border:1px solid var(--tab-border);
      border-radius:14px;
      padding:12px;
      display:grid;
      gap:8px;
      min-width:0;
      background:rgba(31,132,234,.04);
    }
    .queue-printer-head {
      display:flex;
      justify-content:space-between;
      gap:8px;
      align-items:flex-start;
      flex-wrap:wrap;
    }
    .queue-printer-name { font-size:16px; font-weight:800; overflow-wrap:anywhere; }
    .queue-printer-meta { color:var(--muted); font-size:12px; line-height:1.35; }
    .queue-items { display:grid; gap:6px; }
    .queue-item {
      border:1px solid var(--tab-border);
      border-radius:12px;
      padding:8px 10px;
      display:grid;
      gap:4px;
      background:var(--field-bg);
    }
    .queue-item-name { font-size:13px; font-weight:700; overflow-wrap:anywhere; }
    .queue-item-meta { color:var(--muted); font-size:12px; line-height:1.35; overflow-wrap:anywhere; }
    .notice {
      border-radius:14px;
      padding:10px 12px;
      font-size:13px;
      line-height:1.4;
      border:1px solid transparent;
      display:none;
    }
    .notice.show { display:block; }
    .notice.success { background:var(--success-bg); color:var(--success-text); }
    .notice.error { background:var(--danger-bg); color:var(--danger-text); }
    .pagination-row {
      display:flex;
      align-items:center;
      justify-content:flex-end;
      gap:10px;
      flex-wrap:wrap;
    }
    .hamburger { border:0; border-radius:10px; background:var(--button-bg); color:var(--button-text); cursor:pointer; width:42px; height:34px; display:grid; place-items:center; box-shadow:0 8px 22px rgba(22,54,86,.34); }
    .hamburger-lines { width:16px; height:12px; position:relative; }
    .hamburger-lines::before, .hamburger-lines::after, .hamburger-lines span { content:""; position:absolute; left:0; right:0; height:2px; background:currentColor; border-radius:2px; }
    .hamburger-lines::before { top:0; }
    .hamburger-lines span { top:5px; }
    .hamburger-lines::after { top:10px; }
    .sidebar-backdrop { position:fixed; inset:0; background:var(--overlay); display:none; z-index:40; }
    .sidebar-backdrop.open { display:block; }
    .sidebar { position:fixed; z-index:41; top:0; left:0; height:100vh; width:320px; max-width:85vw; background:var(--panel); border-right:1px solid var(--panel-border); box-shadow:var(--panel-shadow); transform:translateX(-101%); transition:transform .18s ease; padding:18px 14px 16px; overflow:auto; }
    .sidebar.open { transform:translateX(0); }
    .sidebar-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
    .sidebar-head-actions { display:flex; align-items:center; gap:8px; }
    .theme-toggle { border:0; border-radius:999px; background:var(--toggle-bg); color:var(--toggle-text); cursor:pointer; padding:6px 10px; font-size:12px; font-weight:600; }
    .theme-toggle:hover { background:var(--toggle-hover); }
    .sidebar-close { border:0; background:transparent; color:var(--close-text); cursor:pointer; font-size:20px; line-height:1; padding:2px 4px; }
    .sidebar h2 { margin:0; font-size:20px; }
    .sidebar p { color:var(--muted); font-size:13px; line-height:1.4; }
    .sidebar-tabs { display:grid; gap:8px; margin:0 0 12px; }
    .sidebar-tab { display:block; text-decoration:none; border:1px solid var(--tab-border); background:var(--tab-bg); color:var(--tab-text); border-radius:999px; padding:6px 10px; font-size:12px; font-weight:600; text-align:left; }
    .sidebar-tab.active { background:var(--button-bg); border-color:var(--button-bg); color:var(--button-text); }
    .sidebar-tab:hover { background:var(--tab-hover); }
    @media (max-width: 980px) {
      .layout { grid-template-columns:1fr; }
      .side-panel { position:static; }
    }
    @media (max-width: 760px) {
      .controls,
      .queue-inline,
      .model-actions { grid-template-columns:1fr; }
      .model-card { grid-template-columns:1fr; }
      .model-preview { min-height:140px; }
      .model-grid { grid-template-columns:1fr; }
    }
  </style>
</head>
<body>
  <div id="sidebarBackdrop" class="sidebar-backdrop" onclick="closeSidebar()"></div>
  <aside id="sidebar" class="sidebar" aria-hidden="true">
    <div class="sidebar-head">
      <h2>Menu</h2>
      <div class="sidebar-head-actions">
        <button id="themeToggle" class="theme-toggle" type="button" aria-label="Switch color theme">Dark</button>
        <button class="sidebar-close" type="button" aria-label="Close menu" onclick="closeSidebar()">&times;</button>
      </div>
    </div>
    <p>Use the sidebar for navigation.</p>
    <div class="sidebar-tabs">
      <a class="sidebar-tab" href="/">Dashboard</a>
      <a class="sidebar-tab active" href="/makerworks">MakerWorks</a>
      <a class="sidebar-tab" href="/add-printer">Add Printer</a>
    </div>
  </aside>
  <div class="wrap">
    <div class="top-row">
      <div class="title-block">
        <button class="hamburger" type="button" aria-label="Open menu" onclick="openSidebar()"><div class="hamburger-lines"><span></span></div></button>
        <div>
          <h1>MakerWorks Routing</h1>
          <p>Queue MakerWorks models to an idle lab printer directly from each model card.</p>
        </div>
      </div>
    </div>
    <div class="layout">
      <section class="main-panel">
        <div class="controls">
          <div class="field-block">
            <label class="field-label" for="makerworksSearch">Search Models</label>
            <input id="makerworksSearch" class="field" type="text" placeholder="Search MakerWorks models...">
          </div>
          <div class="field-block">
            <label class="field-label" for="destinationPrinter">Default Idle Printer</label>
            <select id="destinationPrinter" class="select"></select>
          </div>
          <button class="btn secondary" type="button" onclick="refreshPageData()">Refresh</button>
        </div>
        <div class="status-row">
          <span id="makerworksCount" class="pill">0 models</span>
          <span id="selectedPrinterPill" class="pill">No idle printer selected</span>
          <span id="idlePrinterCount" class="pill">0 idle printers</span>
        </div>
        <div id="pageNotice" class="notice" role="status" aria-live="polite"></div>
        <div id="makerworksGrid" class="model-grid"></div>
        <div class="pagination-row">
          <button id="makerworksPrev" class="btn secondary" type="button" onclick="changeMakerworksPage(-1)">Previous</button>
          <span id="makerworksPageInfo" class="pill">Page 1</span>
          <button id="makerworksNext" class="btn secondary" type="button" onclick="changeMakerworksPage(1)">Next</button>
        </div>
      </section>
      <aside class="side-panel">
        <div class="selection-card">
          <div class="selection-title">Selected Model</div>
          <div id="selectedModelName" class="selection-name">Choose a MakerWorks model</div>
          <div id="selectedModelMeta" class="selection-meta">The selected model stays here while you browse and queue it.</div>
          <div id="selectedModelTags" class="tag-row"></div>
        </div>
        <div class="selection-card">
          <div class="selection-title">Default Queue Target</div>
          <div id="selectedPrinterName" class="selection-name">Choose an idle printer</div>
          <div id="selectedPrinterMeta" class="selection-meta">Each model card can override this printer before queueing.</div>
          <a id="openPrinterLink" class="link-btn" href="/" onclick="return false;" aria-disabled="true">Open Printer Dashboard</a>
        </div>
        <div class="selection-card">
          <div class="selection-title">Printer Queues</div>
          <div id="queueList" class="queue-list"></div>
        </div>
        <div class="helper">
          Only printers that are connected and not actively printing appear in the per-model queue dropdowns. Queue lists refresh after each submission and on a timer.
        </div>
      </aside>
    </div>
  </div>
  <script>
    const sidebar = document.getElementById('sidebar');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');
    const themeStorageKey = 'printlab-theme';
    const selectedPrinterKey = 'printlab.makerworks.destinationPrinter';
    const selectedModelKey = 'printlab.makerworks.selectedModel';
    const nativeFetch = window.fetch.bind(window);
    let modelSearchTimer = null;
    let printersById = {};
    let selectedPrinterId = '';
    let selectedModel = null;
    let queueSnapshots = {};
    let lastLoadedItems = [];
    let queueingModelIds = new Set();
    let cardPrinterSelections = {};
    let makerworksPage = 1;
    const makerworksPageSize = 8;
    let makerworksTotal = 0;

    function readCookie(name) {
      const prefix = `${name}=`;
      return document.cookie.split(';').map((item) => item.trim()).find((item) => item.startsWith(prefix))?.slice(prefix.length) || '';
    }

    window.fetch = function(input, init = {}) {
      const next = { ...init, credentials: 'same-origin' };
      const method = String(next.method || 'GET').toUpperCase();
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        const headers = new Headers(next.headers || {});
        const csrf = readCookie('printlab_csrf');
        if (csrf && !headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', csrf);
        next.headers = headers;
      }
      return nativeFetch(input, next);
    };

    function applyTheme(theme) {
      const nextTheme = theme === 'dark' ? 'dark' : 'light';
      document.documentElement.dataset.theme = nextTheme;
      localStorage.setItem(themeStorageKey, nextTheme);
      const toggle = document.getElementById('themeToggle');
      if (toggle) toggle.textContent = nextTheme === 'dark' ? 'Light' : 'Dark';
      const meta = document.getElementById('themeColorMeta');
      if (meta) meta.setAttribute('content', nextTheme === 'dark' ? '#0e1723' : '#cfe2f7');
    }

    function toggleTheme() {
      const current = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
      applyTheme(current === 'dark' ? 'light' : 'dark');
    }

    function openSidebar() {
      sidebar.classList.add('open');
      sidebarBackdrop.classList.add('open');
      sidebar.setAttribute('aria-hidden', 'false');
    }

    function closeSidebar() {
      sidebar.classList.remove('open');
      sidebarBackdrop.classList.remove('open');
      sidebar.setAttribute('aria-hidden', 'true');
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>\"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '\"': '&quot;',
        \"'\": '&#39;'
      }[char]));
    }

    function readStoredJson(key) {
      try {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : null;
      } catch (_error) {
        return null;
      }
    }

    function writeStoredJson(key, value) {
      try {
        localStorage.setItem(key, JSON.stringify(value));
      } catch (_error) {}
    }

    function makerworksPlaceholder(item) {
      const title = String(item?.name || 'MakerWorks Model').slice(0, 26);
      const subtitle = String(item?.summary || item?.description || item?.id || 'Preview unavailable').slice(0, 32);
      return 'data:image/svg+xml;utf8,' + encodeURIComponent(`
        <svg xmlns="http://www.w3.org/2000/svg" width="640" height="420" viewBox="0 0 640 420">
          <defs>
            <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0%" stop-color="#dfeafb" />
              <stop offset="100%" stop-color="#bfd3eb" />
            </linearGradient>
          </defs>
          <rect width="640" height="420" fill="url(#bg)" rx="28" />
          <g transform="translate(92 78)">
            <path d="M156 0 280 70 280 210 156 280 32 210 32 70Z" fill="#16314d" opacity=".12"/>
            <path d="M156 26 252 80 252 188 156 242 60 188 60 80Z" fill="#1f84ea" opacity=".16"/>
            <path d="M156 62 220 98 220 170 156 206 92 170 92 98Z" fill="#ffffff" opacity=".9"/>
          </g>
          <text x="50%" y="326" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="30" font-weight="700" fill="#15324f">${title}</text>
          <text x="50%" y="362" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="18" fill="#365a7a">${subtitle}</text>
        </svg>
      `);
    }

    function currentPrinter() {
      return printersById[selectedPrinterId] || null;
    }

    function syncSelectionPanel() {
      const printer = currentPrinter();
      const printerPill = document.getElementById('selectedPrinterPill');
      const printerName = document.getElementById('selectedPrinterName');
      const printerMeta = document.getElementById('selectedPrinterMeta');
      const openPrinterLink = document.getElementById('openPrinterLink');
      const modelName = document.getElementById('selectedModelName');
      const modelMeta = document.getElementById('selectedModelMeta');
      const modelTags = document.getElementById('selectedModelTags');

      if (printer) {
        printerPill.textContent = `Destination: ${printer.name}`;
        printerName.textContent = printer.name;
        printerMeta.textContent = `${printer.device_type || 'Unknown device'}${printer.connected ? ' • Connected' : ' • Offline'}${printer.job?.state ? ` • ${printer.job.state}` : ''}`;
        openPrinterLink.href = `/printer/${encodeURIComponent(printer.id)}`;
        openPrinterLink.onclick = null;
        openPrinterLink.removeAttribute('aria-disabled');
      } else {
        printerPill.textContent = 'No destination selected';
        printerName.textContent = 'Choose a printer';
        printerMeta.textContent = 'Use the destination selector to decide which lab printer should get this model.';
        openPrinterLink.href = '/';
        openPrinterLink.setAttribute('aria-disabled', 'true');
        openPrinterLink.onclick = () => false;
      }

      if (selectedModel) {
        modelName.textContent = selectedModel.name || 'Selected model';
        modelMeta.textContent = `${selectedModel.author || 'Unknown creator'}${selectedModel.summary ? ` • ${selectedModel.summary}` : ''}`;
        modelTags.innerHTML = (Array.isArray(selectedModel.tags) ? selectedModel.tags : []).slice(0, 5)
          .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
          .join('');
      } else {
        modelName.textContent = 'Choose a MakerWorks model';
        modelMeta.textContent = 'The selected model and destination printer will stay here while you browse.';
        modelTags.innerHTML = '';
      }
    }

    async function loadPrinters() {
      const response = await fetch('/api/printers');
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.detail || `HTTP ${response.status}`);
      }
      const items = data.items || [];
      printersById = Object.fromEntries(items.map((item) => [item.id, item]));
      const select = document.getElementById('destinationPrinter');
      select.innerHTML = `<option value="">Choose printer...</option>` + items.map((item) => `
        <option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}${item.connected ? '' : ' (offline)'}</option>
      `).join('');

      const urlPrinterId = new URLSearchParams(window.location.search).get('printer_id') || '';
      const storedPrinterId = localStorage.getItem(selectedPrinterKey) || '';
      selectedPrinterId = printersById[urlPrinterId] ? urlPrinterId : (printersById[storedPrinterId] ? storedPrinterId : (items[0]?.id || ''));
      select.value = selectedPrinterId;
      if (selectedPrinterId) localStorage.setItem(selectedPrinterKey, selectedPrinterId);
      syncSelectionPanel();
    }

    function selectModel(encodedItem) {
      selectedModel = JSON.parse(decodeURIComponent(encodedItem));
      writeStoredJson(selectedModelKey, selectedModel);
      syncSelectionPanel();
      document.querySelectorAll('.model-card').forEach((card) => {
        card.classList.toggle('selected', card.dataset.modelId === String(selectedModel?.id || ''));
      });
    }

    async function loadMakerworks() {
      const grid = document.getElementById('makerworksGrid');
      const count = document.getElementById('makerworksCount');
      const query = (document.getElementById('makerworksSearch').value || '').trim();
      grid.innerHTML = "<div class='empty'>Loading MakerWorks models...</div>";
      try {
        const response = await fetch(`/api/works/makerworks/library?query=${encodeURIComponent(query)}`);
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data?.detail || `HTTP ${response.status}`);
        }
        const items = data.items || [];
        count.textContent = `${data.total ?? items.length} models`;
        if (!items.length) {
          grid.innerHTML = "<div class='empty'>No MakerWorks models matched this search.</div>";
          return;
        }
        grid.innerHTML = items.map((item) => {
          const encoded = encodeURIComponent(JSON.stringify(item));
          const selected = String(item.id || '') === String(selectedModel?.id || '');
          const openModelHref = item.model_url || item.download_url || '#';
          const summary = item.summary || item.description || 'No summary available.';
          const tags = (Array.isArray(item.tags) ? item.tags : []).slice(0, 4);
          const preview = item.thumbnail_url || makerworksPlaceholder(item);
          return `
            <article class="model-card${selected ? ' selected' : ''}" data-model-id="${escapeHtml(item.id || '')}">
              <div class="model-preview">
                <img src="${escapeHtml(preview)}" alt="${escapeHtml(item.name || 'MakerWorks model')}" onerror="this.onerror=null;this.src='${preview}'">
              </div>
              <div class="model-body">
                <div class="model-name">${escapeHtml(item.name || 'Untitled model')}</div>
                <div class="model-meta">${escapeHtml(item.author || 'Unknown creator')}</div>
                <div class="model-meta">${escapeHtml(summary)}</div>
                <div class="tag-row">
                  <span class="tag">${escapeHtml(item.printer_handoff_ready ? 'Assets ready' : 'Metadata only')}</span>
                  ${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}
                </div>
                <div class="model-actions">
                  <button class="btn secondary" type="button" onclick="selectModel('${encoded}')">Pick Model</button>
                  <a class="link-btn" href="${escapeHtml(openModelHref)}" target="_blank" rel="noreferrer"${openModelHref === '#' ? " onclick='return false;' aria-disabled='true'" : ''}>Open Model</a>
                </div>
              </div>
            </article>
          `;
        }).join('');
      } catch (error) {
        grid.innerHTML = `<div class='empty'>Failed to load MakerWorks models: ${escapeHtml(String(error?.message || error))}</div>`;
      }
    }

    function handlePrinterChange() {
      const select = document.getElementById('destinationPrinter');
      selectedPrinterId = select.value || '';
      if (selectedPrinterId) {
        localStorage.setItem(selectedPrinterKey, selectedPrinterId);
      } else {
        localStorage.removeItem(selectedPrinterKey);
      }
      syncSelectionPanel();
    }

    function initFromStorage() {
      selectedModel = readStoredJson(selectedModelKey);
      const search = document.getElementById('makerworksSearch');
      search.addEventListener('input', () => {
        if (modelSearchTimer) clearTimeout(modelSearchTimer);
        modelSearchTimer = setTimeout(() => loadMakerworks(), 240);
      });
      document.getElementById('destinationPrinter').addEventListener('change', handlePrinterChange);
    }

    function showNotice(message, kind = 'success') {
      const notice = document.getElementById('pageNotice');
      notice.className = `notice show ${kind === 'error' ? 'error' : 'success'}`;
      notice.textContent = message;
    }

    function busyState(rawState) {
      const state = String(rawState || '').toUpperCase();
      if (!state) return false;
      return !['IDLE', 'FINISH', 'COMPLETE', 'FAILED', 'STOP'].some((item) => state.includes(item));
    }

    function isPrinterIdle(printer) {
      return Boolean(printer?.connected) && !busyState(printer?.job?.state);
    }

    function idlePrinters() {
      return Object.values(printersById)
        .filter((printer) => isPrinterIdle(printer))
        .sort((left, right) => String(left.name || left.id).localeCompare(String(right.name || right.id)));
    }

    function queueLabelForPrinter(printerId) {
      const queue = queueSnapshots[printerId] || {};
      const count = Number(queue.count || 0);
      return count > 0 ? `${count} queued` : 'Queue empty';
    }

    function queueItemName(item) {
      return item?.display_name || item?.model_name || item?.subtask_name || item?.file_name || item?.file_path || 'Queued model';
    }

    function currentPrinter() {
      return printersById[selectedPrinterId] || null;
    }

    function ensureSelectedPrinter(preferredId) {
      const candidates = idlePrinters();
      const candidateIds = new Set(candidates.map((printer) => printer.id));
      if (preferredId && candidateIds.has(preferredId)) {
        selectedPrinterId = preferredId;
      } else if (!candidateIds.has(selectedPrinterId)) {
        selectedPrinterId = candidates[0]?.id || '';
      }
      const select = document.getElementById('destinationPrinter');
      if (select) select.value = selectedPrinterId;
      if (selectedPrinterId) localStorage.setItem(selectedPrinterKey, selectedPrinterId);
      else localStorage.removeItem(selectedPrinterKey);
    }

    function preferredPrinterForModel(modelId) {
      const stored = cardPrinterSelections[String(modelId || '')];
      const ids = new Set(idlePrinters().map((printer) => printer.id));
      if (stored && ids.has(stored)) return stored;
      if (selectedPrinterId && ids.has(selectedPrinterId)) return selectedPrinterId;
      return idlePrinters()[0]?.id || '';
    }

    function buildPrinterOptions(selectedId) {
      const items = idlePrinters();
      if (!items.length) {
        return '<option value="">No idle printers available</option>';
      }
      return items.map((printer) => `
        <option value="${escapeHtml(printer.id)}"${printer.id === selectedId ? ' selected' : ''}>${escapeHtml(printer.name)} (${escapeHtml(queueLabelForPrinter(printer.id))})</option>
      `).join('');
    }

    function syncSelectionPanel() {
      const printer = currentPrinter();
      const printerPill = document.getElementById('selectedPrinterPill');
      const idleCount = document.getElementById('idlePrinterCount');
      const printerName = document.getElementById('selectedPrinterName');
      const printerMeta = document.getElementById('selectedPrinterMeta');
      const openPrinterLink = document.getElementById('openPrinterLink');
      const modelName = document.getElementById('selectedModelName');
      const modelMeta = document.getElementById('selectedModelMeta');
      const modelTags = document.getElementById('selectedModelTags');
      const idleCountValue = idlePrinters().length;

      if (idleCount) {
        idleCount.textContent = `${idleCountValue} idle printer${idleCountValue === 1 ? '' : 's'}`;
      }

      if (printer) {
        printerPill.textContent = `Default: ${printer.name}`;
        printerName.textContent = printer.name;
        printerMeta.textContent = `${printer.device_type || 'Unknown device'} - ${queueLabelForPrinter(printer.id)}${printer.job?.state ? ` - ${printer.job.state}` : ''}`;
        openPrinterLink.href = `/printer/${encodeURIComponent(printer.id)}`;
        openPrinterLink.onclick = null;
        openPrinterLink.removeAttribute('aria-disabled');
      } else {
        printerPill.textContent = 'No idle printer selected';
        printerName.textContent = 'Choose an idle printer';
        printerMeta.textContent = 'Each model card can target any connected printer that is not actively printing.';
        openPrinterLink.href = '/';
        openPrinterLink.setAttribute('aria-disabled', 'true');
        openPrinterLink.onclick = () => false;
      }

      if (selectedModel) {
        modelName.textContent = selectedModel.name || 'Selected model';
        modelMeta.textContent = `${selectedModel.author || 'Unknown creator'}${selectedModel.summary ? ` - ${selectedModel.summary}` : ''}`;
        modelTags.innerHTML = (Array.isArray(selectedModel.tags) ? selectedModel.tags : []).slice(0, 5)
          .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
          .join('');
      } else {
        modelName.textContent = 'Choose a MakerWorks model';
        modelMeta.textContent = 'The selected model stays here while you browse and queue it.';
        modelTags.innerHTML = '';
      }
    }

    function renderQueueLists() {
      const queueList = document.getElementById('queueList');
      if (!queueList) return;
      const printers = Object.values(printersById)
        .sort((left, right) => String(left.name || left.id).localeCompare(String(right.name || right.id)));
      if (!printers.length) {
        queueList.innerHTML = "<div class='empty'>No printers available.</div>";
        return;
      }

      queueList.innerHTML = printers.map((printer) => {
        const queue = queueSnapshots[printer.id] || { count: 0, items: [] };
        const items = Array.isArray(queue.items) ? queue.items.slice(0, 5) : [];
        const status = isPrinterIdle(printer) ? 'Idle' : (printer.connected ? (printer.job?.state || 'Busy') : 'Offline');
        return `
          <div class="queue-printer-card">
            <div class="queue-printer-head">
              <div>
                <div class="queue-printer-name">${escapeHtml(printer.name)}</div>
                <div class="queue-printer-meta">${escapeHtml(status)} - ${escapeHtml(queueLabelForPrinter(printer.id))}</div>
              </div>
              <a class="link-btn" href="/printer/${encodeURIComponent(printer.id)}">Open</a>
            </div>
            <div class="queue-items">
              ${items.length ? items.map((item) => `
                <div class="queue-item">
                  <div class="queue-item-name">${escapeHtml(queueItemName(item))}</div>
                  <div class="queue-item-meta">${escapeHtml(item.source === 'makerworks' ? 'MakerWorks' : 'Queued file')}${item.start_at ? ` - ${escapeHtml(item.start_at)}` : ' - Start when ready'}</div>
                </div>
              `).join('') : "<div class='queue-item'><div class='queue-item-name'>No queued models</div><div class='queue-item-meta'>This printer queue is currently empty.</div></div>"}
            </div>
          </div>
        `;
      }).join('');
    }

    async function loadPrinters() {
      const response = await fetch('/api/printers');
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.detail || `HTTP ${response.status}`);
      }
      const items = data.items || [];
      printersById = Object.fromEntries(items.map((item) => [item.id, item]));
      const urlPrinterId = new URLSearchParams(window.location.search).get('printer_id') || '';
      const storedPrinterId = localStorage.getItem(selectedPrinterKey) || '';
      const preferredId = printersById[urlPrinterId] ? urlPrinterId : storedPrinterId;
      ensureSelectedPrinter(preferredId);
      const select = document.getElementById('destinationPrinter');
      select.innerHTML = idlePrinters().length ? buildPrinterOptions(selectedPrinterId) : '<option value="">No idle printers available</option>';
      select.value = selectedPrinterId;
      syncSelectionPanel();
    }

    async function loadQueues() {
      const printerIds = Object.keys(printersById);
      const snapshots = await Promise.all(printerIds.map(async (printerId) => {
        const response = await fetch(`/api/printers/${encodeURIComponent(printerId)}/queue`);
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data?.detail || `HTTP ${response.status}`);
        }
        return [printerId, data];
      }));
      queueSnapshots = Object.fromEntries(snapshots);
      renderQueueLists();
      syncSelectionPanel();
    }

    function selectModel(encodedItem) {
      selectedModel = JSON.parse(decodeURIComponent(encodedItem));
      writeStoredJson(selectedModelKey, selectedModel);
      syncSelectionPanel();
      document.querySelectorAll('.model-card').forEach((card) => {
        card.classList.toggle('selected', card.dataset.modelId === String(selectedModel?.id || ''));
      });
    }

    function setCardPrinter(modelId, printerId) {
      cardPrinterSelections[String(modelId || '')] = printerId || '';
      if (printerId) {
        selectedPrinterId = printerId;
        localStorage.setItem(selectedPrinterKey, selectedPrinterId);
      }
      syncSelectionPanel();
    }

    async function queueMakerworksModel(modelId) {
      const item = lastLoadedItems.find((entry) => String(entry.id) === String(modelId));
      if (!item) {
        showNotice('Selected MakerWorks model is no longer in the current results.', 'error');
        return;
      }
      const printerId = preferredPrinterForModel(modelId);
      if (!printerId) {
        showNotice('No idle printers are available for queueing right now.', 'error');
        return;
      }
      if (!item.queue_supported) {
        showNotice(item.printer_handoff_note || 'This MakerWorks model cannot be queued yet.', 'error');
        return;
      }

      queueingModelIds.add(String(modelId));
      await loadMakerworks(false);
      try {
        const response = await fetch(`/api/printers/${encodeURIComponent(printerId)}/works/makerworks/queue-job`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_id: String(modelId) }),
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data?.detail || `HTTP ${response.status}`);
        }
        selectedModel = data.source_item || item;
        writeStoredJson(selectedModelKey, selectedModel);
        selectedPrinterId = printerId;
        localStorage.setItem(selectedPrinterKey, selectedPrinterId);
        showNotice(`Queued ${selectedModel.name || 'MakerWorks model'} to ${printersById[printerId]?.name || printerId}.`, 'success');
        await refreshPageData(false);
      } catch (error) {
        showNotice(`Failed to queue MakerWorks model: ${String(error?.message || error)}`, 'error');
      } finally {
        queueingModelIds.delete(String(modelId));
        await loadMakerworks(false);
      }
    }

    async function loadMakerworks(showLoading = true) {
      const grid = document.getElementById('makerworksGrid');
      const count = document.getElementById('makerworksCount');
      const query = (document.getElementById('makerworksSearch').value || '').trim();
      if (showLoading) {
        grid.innerHTML = "<div class='empty'>Loading MakerWorks models...</div>";
      }
      try {
        const response = await fetch(`/api/works/makerworks/library?query=${encodeURIComponent(query)}`);
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data?.detail || `HTTP ${response.status}`);
        }
        const items = data.items || [];
        lastLoadedItems = items;
        count.textContent = `${data.total ?? items.length} models`;
        if (!items.length) {
          grid.innerHTML = "<div class='empty'>No MakerWorks models matched this search.</div>";
          return;
        }
        grid.innerHTML = items.map((item) => {
          const encoded = encodeURIComponent(JSON.stringify(item));
          const selected = String(item.id || '') === String(selectedModel?.id || '');
          const openModelHref = item.model_url || item.download_url || '#';
          const summary = item.summary || item.description || 'No summary available.';
          const tags = (Array.isArray(item.tags) ? item.tags : []).slice(0, 3);
          const preview = item.thumbnail_url || makerworksPlaceholder(item);
          const printerId = preferredPrinterForModel(item.id);
          const hasIdlePrinters = idlePrinters().length > 0;
          const isQueueing = queueingModelIds.has(String(item.id));
          const queueDisabled = !hasIdlePrinters || !item.queue_supported || isQueueing;
          const queueLabel = isQueueing ? 'Queueing...' : 'Queue Model';
          const queueNote = !item.queue_supported
            ? (item.printer_handoff_note || 'Model assets are not queueable yet.')
            : (hasIdlePrinters
              ? `Queue to ${printersById[printerId]?.name || 'selected printer'} when ready.`
              : 'No connected idle printers are available right now.');
          return `
            <article class="model-card${selected ? ' selected' : ''}" data-model-id="${escapeHtml(item.id || '')}">
              <div class="model-preview">
                <img src="${escapeHtml(preview)}" alt="${escapeHtml(item.name || 'MakerWorks model')}" onerror="this.onerror=null;this.src='${escapeHtml(makerworksPlaceholder(item))}'">
              </div>
              <div class="model-body">
                <div class="model-name">${escapeHtml(item.name || 'Untitled model')}</div>
                <div class="model-meta">${escapeHtml(item.author || 'Unknown creator')}</div>
                <div class="model-meta compact-summary">${escapeHtml(summary)}</div>
                <div class="tag-row">
                  <span class="tag">${escapeHtml(item.queue_supported ? 'Queue ready' : 'Metadata only')}</span>
                  ${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}
                </div>
                <div class="queue-inline">
                  <div class="field-block">
                    <label class="field-label" for="printerSelect-${escapeHtml(item.id || '')}">Queue To Idle Printer</label>
                    <select id="printerSelect-${escapeHtml(item.id || '')}" class="select makerworks-printer-select" onchange="setCardPrinter('${escapeHtml(item.id || '')}', this.value)" ${hasIdlePrinters ? '' : 'disabled'}>
                      ${buildPrinterOptions(printerId)}
                    </select>
                  </div>
                  <button class="btn" type="button" onclick="queueMakerworksModel('${escapeHtml(item.id || '')}')" ${queueDisabled ? 'disabled' : ''}>${escapeHtml(queueLabel)}</button>
                </div>
                <div class="queue-note">${escapeHtml(queueNote)}</div>
                <div class="model-actions">
                  <button class="btn secondary" type="button" onclick="selectModel('${encoded}')">Pick Model</button>
                  <a class="link-btn" href="${escapeHtml(openModelHref)}" target="_blank" rel="noreferrer"${openModelHref === '#' ? " onclick='return false;' aria-disabled='true'" : ''}>Open Model</a>
                </div>
              </div>
            </article>
          `;
        }).join('');
      } catch (error) {
        grid.innerHTML = `<div class='empty'>Failed to load MakerWorks models: ${escapeHtml(String(error?.message || error))}</div>`;
      }
      syncSelectionPanel();
    }

    function handlePrinterChange() {
      const select = document.getElementById('destinationPrinter');
      selectedPrinterId = select.value || '';
      if (selectedPrinterId) {
        localStorage.setItem(selectedPrinterKey, selectedPrinterId);
      } else {
        localStorage.removeItem(selectedPrinterKey);
      }
      syncSelectionPanel();
      loadMakerworks(false);
    }

    function initFromStorage() {
      selectedModel = readStoredJson(selectedModelKey);
      const search = document.getElementById('makerworksSearch');
      search.addEventListener('input', () => {
        if (modelSearchTimer) clearTimeout(modelSearchTimer);
        modelSearchTimer = setTimeout(() => loadMakerworks(), 240);
      });
      document.getElementById('destinationPrinter').addEventListener('change', handlePrinterChange);
    }

    async function refreshPageData(showLoading = true) {
      await loadPrinters();
      await loadQueues();
      await loadMakerworks(showLoading);
    }

    function updateMakerworksPagination() {
      const total = Math.max(0, Number(makerworksTotal || 0));
      const totalPages = Math.max(1, Math.ceil(total / makerworksPageSize));
      if (makerworksPage > totalPages) makerworksPage = totalPages;
      const pageInfo = document.getElementById('makerworksPageInfo');
      const prev = document.getElementById('makerworksPrev');
      const next = document.getElementById('makerworksNext');
      if (pageInfo) {
        pageInfo.textContent = `Page ${makerworksPage} of ${totalPages}`;
      }
      if (prev) prev.disabled = makerworksPage <= 1;
      if (next) next.disabled = makerworksPage >= totalPages;
    }

    function changeMakerworksPage(delta) {
      const totalPages = Math.max(1, Math.ceil(Math.max(0, Number(makerworksTotal || 0)) / makerworksPageSize));
      const nextPage = Math.min(totalPages, Math.max(1, makerworksPage + Number(delta || 0)));
      if (nextPage === makerworksPage) return;
      makerworksPage = nextPage;
      loadMakerworks();
    }

    async function loadMakerworks(showLoading = true) {
      const grid = document.getElementById('makerworksGrid');
      const count = document.getElementById('makerworksCount');
      const query = (document.getElementById('makerworksSearch').value || '').trim();
      if (showLoading) {
        grid.innerHTML = "<div class='empty'>Loading MakerWorks models...</div>";
      }
      try {
        const response = await fetch(`/api/works/makerworks/library?query=${encodeURIComponent(query)}&page=${encodeURIComponent(makerworksPage)}&page_size=${encodeURIComponent(makerworksPageSize)}`);
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data?.detail || `HTTP ${response.status}`);
        }
        const items = data.items || [];
        lastLoadedItems = items;
        makerworksTotal = Number(data.total ?? items.length ?? 0);
        count.textContent = `${makerworksTotal} models`;
        updateMakerworksPagination();
        if (!items.length) {
          grid.innerHTML = "<div class='empty'>No MakerWorks models matched this search.</div>";
          return;
        }
        grid.innerHTML = items.map((item) => {
          const encoded = encodeURIComponent(JSON.stringify(item));
          const selected = String(item.id || '') === String(selectedModel?.id || '');
          const openModelHref = item.model_url || item.download_url || '#';
          const summary = item.summary || item.description || 'No summary available.';
          const tags = (Array.isArray(item.tags) ? item.tags : []).slice(0, 2);
          const preview = item.thumbnail_url || makerworksPlaceholder(item);
          const printerId = preferredPrinterForModel(item.id);
          const hasIdlePrinters = idlePrinters().length > 0;
          const isQueueing = queueingModelIds.has(String(item.id));
          const queueDisabled = !hasIdlePrinters || !item.queue_supported || isQueueing;
          const queueLabel = isQueueing ? 'Queueing...' : 'Queue Model';
          const queueNote = !item.queue_supported
            ? (item.printer_handoff_note || 'Model assets are not queueable yet.')
            : (hasIdlePrinters
              ? `Queue to ${printersById[printerId]?.name || 'selected printer'} when ready.`
              : 'No connected idle printers are available right now.');
          return `
            <article class="model-card${selected ? ' selected' : ''}" data-model-id="${escapeHtml(item.id || '')}">
              <div class="model-preview">
                <img src="${escapeHtml(preview)}" alt="${escapeHtml(item.name || 'MakerWorks model')}" onerror="this.onerror=null;this.src='${escapeHtml(makerworksPlaceholder(item))}'">
              </div>
              <div class="model-body">
                <div class="model-name">${escapeHtml(item.name || 'Untitled model')}</div>
                <div class="model-meta">${escapeHtml(item.author || 'Unknown creator')}</div>
                <div class="model-meta compact-summary">${escapeHtml(summary)}</div>
                <div class="tag-row">
                  <span class="tag">${escapeHtml(item.queue_supported ? 'Queue ready' : 'Metadata only')}</span>
                  ${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}
                </div>
                <div class="queue-inline">
                  <div class="field-block">
                    <label class="field-label" for="printerSelect-${escapeHtml(item.id || '')}">Queue To Idle Printer</label>
                    <select id="printerSelect-${escapeHtml(item.id || '')}" class="select makerworks-printer-select" onchange="setCardPrinter('${escapeHtml(item.id || '')}', this.value)" ${hasIdlePrinters ? '' : 'disabled'}>
                      ${buildPrinterOptions(printerId)}
                    </select>
                  </div>
                  <button class="btn" type="button" onclick="queueMakerworksModel('${escapeHtml(item.id || '')}')" ${queueDisabled ? 'disabled' : ''}>${escapeHtml(queueLabel)}</button>
                </div>
                <div class="queue-note">${escapeHtml(queueNote)}</div>
                <div class="model-actions">
                  <button class="btn secondary" type="button" onclick="selectModel('${encoded}')">Pick Model</button>
                  <a class="link-btn" href="${escapeHtml(openModelHref)}" target="_blank" rel="noreferrer"${openModelHref === '#' ? " onclick='return false;' aria-disabled='true'" : ''}>Open Model</a>
                </div>
              </div>
            </article>
          `;
        }).join('');
      } catch (error) {
        grid.innerHTML = `<div class='empty'>Failed to load MakerWorks models: ${escapeHtml(String(error?.message || error))}</div>`;
      }
      syncSelectionPanel();
      updateMakerworksPagination();
    }

    function initFromStorage() {
      selectedModel = readStoredJson(selectedModelKey);
      const search = document.getElementById('makerworksSearch');
      search.addEventListener('input', () => {
        if (modelSearchTimer) clearTimeout(modelSearchTimer);
        modelSearchTimer = setTimeout(() => {
          makerworksPage = 1;
          loadMakerworks();
        }, 240);
      });
      document.getElementById('destinationPrinter').addEventListener('change', handlePrinterChange);
      updateMakerworksPagination();
    }

    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
      themeToggle.addEventListener('click', toggleTheme);
    }
    applyTheme(document.documentElement.dataset.theme);
    initFromStorage();
    refreshPageData().catch((error) => {
      document.getElementById('makerworksGrid').innerHTML = `<div class='empty'>Failed to load page data: ${escapeHtml(String(error?.message || error))}</div>`;
    });
    window.setInterval(() => {
      refreshPageData(false).catch(() => {});
    }, 15000);
  </script>
</body>
</html>"""


def render_printer_dashboard(printer_id: str) -> str:
    service = service_or_404(printer_id)
    injected = (
        "<script>"
        f"window.PRINTER_ID={json.dumps(printer_id)};"
        f"window.PRINTER_NAME={json.dumps(service.display_name)};"
        "</script>"
    )
    return dashboard_html_template.replace("<script>", f"{injected}<script>", 1)
