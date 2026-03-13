from __future__ import annotations

import json
import os
from pathlib import Path

from app.runtime import service_or_404

dashboard_html_template = (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")
static_dir = Path(__file__).with_name("static")


def render_gallery_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content">
  <meta id="themeColorMeta" name="theme-color" content="#cfe2f7">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="PrintLab">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <title>PrintLab - Printers</title>
  <script>
    (function() {
      const theme = localStorage.getItem("printlab-theme") === "dark" ? "dark" : "light";
      document.documentElement.dataset.theme = theme;
    })();
  </script>
  <style>
    :root {
      --safe-top: env(safe-area-inset-top, 0px);
      --safe-right: env(safe-area-inset-right, 0px);
      --safe-bottom: env(safe-area-inset-bottom, 0px);
      --safe-left: env(safe-area-inset-left, 0px);
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
    html { color-scheme: light; min-height:100%; background:var(--bg); }
    :root[data-theme="dark"] { color-scheme: dark; }
    body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; margin:0; background:var(--bg); color:var(--text); min-height:100vh; min-height:100dvh; }
    .wrap { max-width:1100px; margin:0 auto; padding:calc(var(--safe-top) + 24px) calc(var(--safe-right) + 16px) calc(var(--safe-bottom) + 40px) calc(var(--safe-left) + 16px); }
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
    .sidebar { position:fixed; z-index:41; top:0; left:0; height:100vh; height:100dvh; width:320px; max-width:85vw; background:var(--panel); border-right:1px solid var(--panel-border); box-shadow:var(--panel-shadow); transform:translateX(-101%); transition:transform .18s ease; padding:calc(var(--safe-top) + 18px) calc(var(--safe-right) + 14px) calc(var(--safe-bottom) + 16px) calc(var(--safe-left) + 14px); overflow:auto; }
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
      <a class="sidebar-tab" href="/conversion">3D Conversion</a>
      <a class="sidebar-tab" href="/makerworks">MakerWorks</a>
      <a class="sidebar-tab" href="/makerworks-routing">Routing Board</a>
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
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content">
  <meta id="themeColorMeta" name="theme-color" content="#cfe2f7">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="PrintLab">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <title>PrintLab - Add Printer</title>
  <script>
    (function() {
      const theme = localStorage.getItem("printlab-theme") === "dark" ? "dark" : "light";
      document.documentElement.dataset.theme = theme;
    })();
  </script>
  <style>
    :root {
      --safe-top: env(safe-area-inset-top, 0px);
      --safe-right: env(safe-area-inset-right, 0px);
      --safe-bottom: env(safe-area-inset-bottom, 0px);
      --safe-left: env(safe-area-inset-left, 0px);
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
    html { color-scheme: light; min-height:100%; background:var(--bg); }
    :root[data-theme="dark"] { color-scheme: dark; }
    body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; margin:0; background:var(--bg); color:var(--text); min-height:100vh; min-height:100dvh; }
    .wrap { max-width:1100px; margin:0 auto; padding:calc(var(--safe-top) + 24px) calc(var(--safe-right) + 16px) calc(var(--safe-bottom) + 40px) calc(var(--safe-left) + 16px); }
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
    .sidebar { position:fixed; z-index:41; top:0; left:0; height:100vh; height:100dvh; width:320px; max-width:85vw; background:var(--panel); border-right:1px solid var(--panel-border); box-shadow:var(--panel-shadow); transform:translateX(-101%); transition:transform .18s ease; padding:calc(var(--safe-top) + 18px) calc(var(--safe-right) + 14px) calc(var(--safe-bottom) + 16px) calc(var(--safe-left) + 14px); overflow:auto; }
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
      <a class="sidebar-tab" href="/conversion">3D Conversion</a>
      <a class="sidebar-tab" href="/makerworks">MakerWorks</a>
      <a class="sidebar-tab" href="/makerworks-routing">Routing Board</a>
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


def render_makerworks_search_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content">
  <meta id="themeColorMeta" name="theme-color" content="#e6f0fb">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="PrintLab">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <title>PrintLab - MakerWorks Search</title>
  <script>
    (function() {
      const theme = localStorage.getItem("printlab-theme") === "dark" ? "dark" : "light";
      document.documentElement.dataset.theme = theme;
    })();
  </script>
  <style>
    :root { --safe-top:env(safe-area-inset-top, 0px); --safe-right:env(safe-area-inset-right, 0px); --safe-bottom:env(safe-area-inset-bottom, 0px); --safe-left:env(safe-area-inset-left, 0px); --bg:#e6f0fb; --text:#213245; --panel:#fff; --line:#cfe0f3; --soft:#edf4fb; --muted:#5d738a; --button:#1f4f7b; --button-text:#fff; --accent:#1f84ea; }
    :root[data-theme="dark"] { --bg:#0e1723; --text:#edf5ff; --panel:#162231; --line:#24384d; --soft:#132131; --muted:#9db5cf; --button:#2c6aa0; --button-text:#f5faff; --accent:#63b3ff; }
    * { box-sizing:border-box; }
    html { min-height:100%; background:var(--bg); }
    body { margin:0; font-family:"Segoe UI",sans-serif; background:var(--bg); color:var(--text); min-height:100vh; min-height:100dvh; }
    .wrap { max-width:1280px; margin:0 auto; padding:calc(var(--safe-top) + 24px) calc(var(--safe-right) + 16px) calc(var(--safe-bottom) + 40px) calc(var(--safe-left) + 16px); }
    .top { display:flex; gap:12px; align-items:flex-start; margin-bottom:14px; }
    .menu { border:0; border-radius:12px; background:var(--button); color:var(--button-text); padding:10px 12px; font-weight:700; cursor:pointer; }
    .layout { display:grid; grid-template-columns:minmax(0,1fr) 320px; gap:16px; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:22px; padding:16px; }
    .controls { display:grid; grid-template-columns:minmax(0,1fr) auto auto; gap:10px; align-items:end; margin-bottom:12px; }
    .field { width:100%; border:1px solid var(--line); border-radius:14px; background:var(--soft); color:var(--text); padding:12px 14px; }
    .btn, .link-btn { border:0; border-radius:14px; background:var(--button); color:var(--button-text); padding:12px 14px; font-weight:700; text-decoration:none; display:inline-flex; align-items:center; justify-content:center; cursor:pointer; }
    .btn.secondary { background:var(--soft); color:var(--text); border:1px solid var(--line); }
    .pill { display:inline-flex; padding:6px 10px; border-radius:999px; border:1px solid var(--line); background:var(--soft); font-size:12px; font-weight:700; }
    .status { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:12px; }
    .card { border:1px solid var(--line); border-radius:18px; overflow:hidden; background:linear-gradient(180deg, rgba(255,255,255,.94), rgba(237,244,251,.96)); }
    :root[data-theme="dark"] .card { background:linear-gradient(180deg, rgba(22,34,49,.98), rgba(18,32,49,.98)); }
    .preview { height:160px; display:flex; align-items:center; justify-content:center; padding:10px; background:linear-gradient(160deg, rgba(245,251,255,.95), rgba(216,233,248,.8)); }
    .preview img { max-width:100%; max-height:100%; object-fit:contain; }
    .body { padding:12px; display:grid; gap:8px; }
    .name { font-size:18px; font-weight:800; line-height:1.1; overflow-wrap:anywhere; }
    .meta { color:var(--muted); font-size:13px; line-height:1.35; overflow-wrap:anywhere; }
    .tags { display:flex; flex-wrap:wrap; gap:6px; }
    .tag { padding:4px 8px; border-radius:999px; background:rgba(31,132,234,.1); color:var(--accent); font-size:11px; font-weight:700; }
    .actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .notice { display:none; margin-bottom:12px; padding:10px 12px; border-radius:14px; background:rgba(31,132,234,.12); }
    .notice.show { display:block; }
    .route-list { display:grid; gap:8px; margin-top:10px; }
    .route-item { border:1px solid var(--line); border-radius:14px; padding:10px; background:var(--soft); }
    .sidebar-backdrop { position:fixed; inset:0; background:rgba(18,34,52,.36); display:none; z-index:40; }
    .sidebar-backdrop.open { display:block; }
    .sidebar { position:fixed; z-index:41; top:0; left:0; height:100vh; height:100dvh; width:320px; max-width:85vw; background:var(--panel); border-right:1px solid var(--line); transform:translateX(-101%); transition:transform .18s ease; padding:calc(var(--safe-top) + 18px) calc(var(--safe-right) + 14px) calc(var(--safe-bottom) + 16px) calc(var(--safe-left) + 14px); overflow:auto; }
    .sidebar.open { transform:translateX(0); }
    .sidebar-tabs { display:grid; gap:8px; margin-top:12px; }
    .sidebar-tab { display:block; text-decoration:none; border:1px solid var(--line); background:var(--soft); color:var(--text); border-radius:999px; padding:6px 10px; font-size:12px; font-weight:600; }
    .sidebar-tab.active { background:var(--button); color:var(--button-text); border-color:var(--button); }
    @media (max-width: 960px) { .layout { grid-template-columns:1fr; } }
    @media (max-width: 720px) { .controls, .actions { grid-template-columns:1fr; } .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div id="sidebarBackdrop" class="sidebar-backdrop" onclick="closeSidebar()"></div>
  <aside id="sidebar" class="sidebar" aria-hidden="true">
    <h2>Menu</h2>
    <p>Search the model library here. Use the routing board for queueing and printer assignment.</p>
    <div class="sidebar-tabs">
      <a class="sidebar-tab" href="/">Dashboard</a>
      <a class="sidebar-tab" href="/conversion">3D Conversion</a>
      <a class="sidebar-tab active" href="/makerworks">MakerWorks Search</a>
      <a class="sidebar-tab" href="/makerworks-routing">Routing Board</a>
      <a class="sidebar-tab" href="/add-printer">Add Printer</a>
    </div>
  </aside>
  <div class="wrap">
    <div class="top">
      <button class="menu" type="button" onclick="openSidebar()">Menu</button>
      <div>
        <h1>MakerWorks Search</h1>
        <p>Search and shortlist models here. Queueing and routing are handled on the separate routing board.</p>
      </div>
    </div>
    <div class="layout">
      <section class="panel">
        <div class="controls">
          <input id="makerworksSearch" class="field" type="text" placeholder="Search MakerWorks models...">
          <button class="btn secondary" type="button" onclick="refreshPageData()">Refresh</button>
          <a class="link-btn" href="/makerworks-routing">Open Routing Board</a>
        </div>
        <div class="status">
          <span id="makerworksCount" class="pill">0 models</span>
          <span id="routingCount" class="pill">0 on routing board</span>
        </div>
        <div id="pageNotice" class="notice" role="status" aria-live="polite"></div>
        <div id="makerworksGrid" class="grid"></div>
        <div class="status" style="justify-content:flex-end;margin-top:12px;">
          <button id="makerworksPrev" class="btn secondary" type="button" onclick="changeMakerworksPage(-1)">Previous</button>
          <span id="makerworksPageInfo" class="pill">Page 1</span>
          <button id="makerworksNext" class="btn secondary" type="button" onclick="changeMakerworksPage(1)">Next</button>
        </div>
      </section>
      <aside class="panel">
        <div style="font-size:12px;text-transform:uppercase;letter-spacing:.3px;color:var(--muted);font-weight:800;">Routing Board</div>
        <h2 style="margin:6px 0 8px;">Chosen Models</h2>
        <p class="meta">These models are waiting to be routed. Open the routing board to connect them to printers and submit jobs.</p>
        <div id="routingList" class="route-list"></div>
      </aside>
    </div>
  </div>
  <script>
    const nativeFetch = window.fetch.bind(window);
    const routingKey = 'printlab.makerworks.routingModels';
    let makerworksPage = 1;
    const makerworksPageSize = 12;
    let makerworksTotal = 0;
    let modelSearchTimer = null;
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
    function openSidebar() { document.getElementById('sidebar').classList.add('open'); document.getElementById('sidebarBackdrop').classList.add('open'); }
    function closeSidebar() { document.getElementById('sidebar').classList.remove('open'); document.getElementById('sidebarBackdrop').classList.remove('open'); }
    function escapeHtml(value) { return String(value ?? '').replace(/[&<>\"']/g, (char) => ({ '&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;' }[char])); }
    function makerworksPlaceholder(item) { const text = encodeURIComponent((item?.name || 'MakerWorks').slice(0, 32)); return `https://placehold.co/480x320/e8f0fb/23405c?text=${text}`; }
    function getRoutingModels() { try { return JSON.parse(localStorage.getItem(routingKey) || '[]'); } catch (_error) { return []; } }
    function saveRoutingModels(items) { localStorage.setItem(routingKey, JSON.stringify(items)); renderRoutingList(); }
    function showNotice(message) {
      const el = document.getElementById('pageNotice');
      el.textContent = message;
      el.className = 'notice show';
      window.clearTimeout(showNotice._timer);
      showNotice._timer = window.setTimeout(() => { el.className = 'notice'; }, 3200);
    }
    function addToRouting(encoded) {
      const item = JSON.parse(decodeURIComponent(encoded));
      const items = getRoutingModels();
      if (!items.some((entry) => String(entry.id) === String(item.id))) {
        items.unshift(item);
        saveRoutingModels(items.slice(0, 50));
        showNotice(`${item.name || 'Model'} added to the routing board.`);
      } else {
        showNotice(`${item.name || 'Model'} is already on the routing board.`);
      }
    }
    function removeFromRouting(modelId) {
      saveRoutingModels(getRoutingModels().filter((item) => String(item.id) !== String(modelId)));
    }
    function renderRoutingList() {
      const items = getRoutingModels();
      document.getElementById('routingCount').textContent = `${items.length} on routing board`;
      const list = document.getElementById('routingList');
      if (!items.length) {
        list.innerHTML = "<div class='meta'>No models selected yet.</div>";
        return;
      }
      list.innerHTML = items.map((item) => `
        <div class="route-item">
          <div style="font-weight:800;">${escapeHtml(item.name || 'Untitled model')}</div>
          <div class="meta">${escapeHtml(item.author || 'Unknown creator')}</div>
          <div class="actions" style="margin-top:8px;">
            <a class="link-btn" href="/makerworks-routing">Route</a>
            <button class="btn secondary" type="button" onclick="removeFromRouting('${escapeHtml(String(item.id || ''))}')">Remove</button>
          </div>
        </div>
      `).join('');
    }
    function updateMakerworksPagination() {
      const totalPages = Math.max(1, Math.ceil(Math.max(0, makerworksTotal) / makerworksPageSize));
      document.getElementById('makerworksPageInfo').textContent = `Page ${makerworksPage} of ${totalPages}`;
      document.getElementById('makerworksPrev').disabled = makerworksPage <= 1;
      document.getElementById('makerworksNext').disabled = makerworksPage >= totalPages;
    }
    function changeMakerworksPage(delta) {
      const totalPages = Math.max(1, Math.ceil(Math.max(0, makerworksTotal) / makerworksPageSize));
      const nextPage = Math.min(totalPages, Math.max(1, makerworksPage + Number(delta || 0)));
      if (nextPage !== makerworksPage) {
        makerworksPage = nextPage;
        loadMakerworks();
      }
    }
    async function loadMakerworks() {
      const grid = document.getElementById('makerworksGrid');
      const query = (document.getElementById('makerworksSearch').value || '').trim();
      grid.innerHTML = "<div class='meta'>Loading MakerWorks models...</div>";
      try {
        const response = await fetch(`/api/works/makerworks/library?query=${encodeURIComponent(query)}&page=${encodeURIComponent(makerworksPage)}&page_size=${encodeURIComponent(makerworksPageSize)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
        const items = Array.isArray(data.items) ? data.items : [];
        makerworksTotal = Number(data.total ?? items.length ?? 0);
        document.getElementById('makerworksCount').textContent = `${makerworksTotal} models`;
        updateMakerworksPagination();
        if (!items.length) {
          grid.innerHTML = "<div class='meta'>No MakerWorks models matched this search.</div>";
          return;
        }
        grid.innerHTML = items.map((item) => {
          const encoded = encodeURIComponent(JSON.stringify(item));
          const openModelHref = item.model_url || item.download_url || '#';
          const tags = (Array.isArray(item.tags) ? item.tags : []).slice(0, 3);
          return `
            <article class="card">
              <div class="preview"><img src="${escapeHtml(item.thumbnail_url || makerworksPlaceholder(item))}" alt="${escapeHtml(item.name || 'MakerWorks model')}" onerror="this.onerror=null;this.src='${escapeHtml(makerworksPlaceholder(item))}'"></div>
              <div class="body">
                <div class="name">${escapeHtml(item.name || 'Untitled model')}</div>
                <div class="meta">${escapeHtml(item.author || 'Unknown creator')}</div>
                <div class="meta">${escapeHtml(item.summary || item.description || 'No summary available.')}</div>
                <div class="tags">
                  <span class="tag">${escapeHtml(item.queue_supported ? 'Queue ready' : 'Metadata only')}</span>
                  ${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}
                </div>
                <div class="actions">
                  <button class="btn" type="button" onclick="addToRouting('${encoded}')">Add To Routing Board</button>
                  <a class="link-btn" href="${escapeHtml(openModelHref)}" target="_blank" rel="noreferrer"${openModelHref === '#' ? " onclick='return false;'" : ''}>Open Model</a>
                </div>
              </div>
            </article>
          `;
        }).join('');
      } catch (error) {
        grid.innerHTML = `<div class='meta'>Failed to load MakerWorks models: ${escapeHtml(String(error?.message || error))}</div>`;
      }
    }
    function refreshPageData() {
      renderRoutingList();
      return loadMakerworks();
    }
    document.getElementById('makerworksSearch').addEventListener('input', () => {
      if (modelSearchTimer) clearTimeout(modelSearchTimer);
      modelSearchTimer = window.setTimeout(() => {
        makerworksPage = 1;
        loadMakerworks();
      }, 240);
    });
    refreshPageData();
  </script>
</body>
</html>"""


def render_makerworks_routing_html() -> str:
    slicer_target = (os.getenv("SLICER_TARGET", "bambu_studio") or "bambu_studio").strip().lower()
    slicer_protocol_template = (
        os.getenv("SLICER_PROTOCOL_TEMPLATE", "") or ""
    ).strip()
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content">
  <meta id="themeColorMeta" name="theme-color" content="#ecf3fb">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="PrintLab">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <title>PrintLab - Routing Board</title>
  <script>
    (function() {
      const theme = localStorage.getItem("printlab-theme") === "dark" ? "dark" : "light";
      document.documentElement.dataset.theme = theme;
    })();
  </script>
  <style>
    :root { --safe-top:env(safe-area-inset-top, 0px); --safe-right:env(safe-area-inset-right, 0px); --safe-bottom:env(safe-area-inset-bottom, 0px); --safe-left:env(safe-area-inset-left, 0px); --bg:#ecf3fb; --text:#1d2f45; --panel:#fff; --line:#cbddef; --soft:#eff5fb; --button:#1f4f7b; --button-text:#fff; --muted:#617991; --accent:#2d94ff; --success:#2f9b65; --queue-fresh:#3296ff; }
    :root[data-theme="dark"] { --bg:#0d1722; --text:#edf5ff; --panel:#162231; --line:#294056; --soft:#122031; --button:#2c6aa0; --button-text:#fff; --muted:#9fb8d0; --accent:#63b3ff; --success:#6fd39f; --queue-fresh:#78c2ff; }
    * { box-sizing:border-box; }
    html { min-height:100%; background:var(--bg); }
    body { margin:0; font-family:"Segoe UI",sans-serif; background:radial-gradient(circle at top left, rgba(45,148,255,.08), transparent 32%), var(--bg); color:var(--text); min-height:100vh; min-height:100dvh; }
    .wrap { max-width:1600px; margin:0 auto; padding:calc(var(--safe-top) + 18px) calc(var(--safe-right) + 14px) calc(var(--safe-bottom) + 28px) calc(var(--safe-left) + 14px); min-height:100vh; min-height:100dvh; display:flex; flex-direction:column; }
    .top { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:12px; }
    .top-head { display:grid; gap:10px; }
    .menu { border:0; border-radius:12px; background:var(--button); color:var(--button-text); padding:10px 12px; font-weight:700; cursor:pointer; width:max-content; }
    .top-actions { display:flex; gap:10px; flex-wrap:wrap; }
    .btn, .link-btn { border:0; border-radius:12px; background:var(--button); color:var(--button-text); padding:10px 12px; font-weight:700; font-size:13px; text-decoration:none; display:inline-flex; align-items:center; justify-content:center; cursor:pointer; }
    .btn.secondary { background:var(--soft); color:var(--text); border:1px solid var(--line); }
    .status-row { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
    .pill { display:inline-flex; border-radius:999px; background:var(--soft); border:1px solid var(--line); padding:6px 10px; font-size:12px; font-weight:700; }
    .notice { margin-bottom:14px; border-radius:14px; background:rgba(45,148,255,.12); padding:10px 12px; display:none; }
    .notice.show { display:block; }
    .sidebar-backdrop { position:fixed; inset:0; background:rgba(18,34,52,.36); display:none; z-index:40; }
    .sidebar-backdrop.open { display:block; }
    .sidebar { position:fixed; z-index:41; top:0; left:0; height:100vh; height:100dvh; width:320px; max-width:85vw; background:var(--panel); border-right:1px solid var(--line); transform:translateX(-101%); transition:transform .18s ease; padding:calc(var(--safe-top) + 18px) calc(var(--safe-right) + 14px) calc(var(--safe-bottom) + 16px) calc(var(--safe-left) + 14px); overflow:auto; }
    .sidebar.open { transform:translateX(0); }
    .sidebar-tabs { display:grid; gap:8px; margin-top:12px; }
    .sidebar-tab { display:block; text-decoration:none; border:1px solid var(--line); background:var(--soft); color:var(--text); border-radius:999px; padding:6px 10px; font-size:12px; font-weight:600; }
    .sidebar-tab.active { background:var(--button); color:var(--button-text); border-color:var(--button); }
    .toolbar { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto; gap:10px; margin-bottom:12px; align-items:end; }
    .field { display:grid; gap:6px; }
    .field label { font-size:11px; letter-spacing:.35px; text-transform:uppercase; color:var(--muted); font-weight:800; }
    .field input { width:100%; border:1px solid var(--line); border-radius:12px; padding:10px 12px; background:var(--panel); color:var(--text); font:inherit; }
    .board { position:relative; background:var(--panel); border:1px solid var(--line); border-radius:20px; min-height:640px; height:calc(100vh - 220px); height:calc(100dvh - 220px); overflow:hidden; flex:1 1 auto; }
    .board-svg { position:absolute; inset:0; z-index:1; pointer-events:none; }
    .board-grid { position:relative; z-index:2; display:grid; grid-template-columns:minmax(0,1fr) minmax(280px,.95fr); gap:10px; padding:12px; align-items:stretch; height:100%; min-height:0; }
    .column { display:grid; grid-template-rows:auto minmax(0,1fr); gap:10px; min-height:0; height:100%; }
    .lane-title { font-size:12px; letter-spacing:.4px; text-transform:uppercase; color:var(--muted); font-weight:800; }
    .lane-frame { border:1px solid var(--line); border-radius:16px; background:rgba(255,255,255,.45); padding:10px; display:grid; gap:10px; min-height:0; height:100%; overflow:auto; overscroll-behavior:contain; }
    :root[data-theme="dark"] .lane-frame { background:rgba(13,23,34,.4); }
    .stack { display:grid; gap:8px; align-content:start; }
    .stack-section { display:grid; gap:8px; }
    .stack-heading { display:flex; justify-content:space-between; gap:8px; align-items:center; font-size:11px; letter-spacing:.35px; text-transform:uppercase; color:var(--muted); font-weight:800; }
    .stack-count { border-radius:999px; background:var(--soft); border:1px solid var(--line); padding:2px 8px; }
    .node { position:relative; border:1px solid var(--line); background:linear-gradient(180deg, rgba(255,255,255,.95), rgba(239,245,251,.98)); border-radius:14px; padding:10px; display:grid; gap:6px; }
    .node.routeable { padding-right:68px; }
    .node.collapsed { padding-top:8px; padding-bottom:8px; }
    .node-header { display:flex; align-items:flex-start; justify-content:space-between; gap:8px; min-width:0; }
    .node-heading { display:grid; gap:4px; min-width:0; }
    .empty-state { border:1px dashed var(--line); border-radius:14px; padding:12px; color:var(--muted); font-size:12px; text-align:center; }
    :root[data-theme="dark"] .node { background:linear-gradient(180deg, rgba(22,34,49,.98), rgba(18,32,49,.98)); }
    .node.selected { border-color:var(--accent); box-shadow:0 0 0 2px rgba(45,148,255,.18); }
    .node.connected { border-color:var(--success); }
    .node.queue-fresh {
      border-color: rgba(50,150,255,.55);
      box-shadow: inset 0 -16px 28px rgba(50,150,255,.16), 0 16px 34px rgba(50,150,255,.22);
      animation: queueFreshPulse 2.8s ease-out infinite;
    }
    .node.queue-connected {
      border-color: rgba(47,155,101,.55);
      box-shadow: inset 0 -18px 30px rgba(47,155,101,.18), 0 16px 34px rgba(47,155,101,.24);
    }
    .printer-open { box-shadow: inset 0 -14px 24px rgba(47,155,101,.16), 0 12px 28px rgba(47,155,101,.12); }
    .printer-running { box-shadow: inset 0 -14px 24px rgba(210,68,68,.22), 0 12px 28px rgba(210,68,68,.14); border-color: rgba(210,68,68,.42); }
    .node-title { font-size:15px; font-weight:800; line-height:1.15; }
    .node-meta { color:var(--muted); font-size:12px; line-height:1.3; }
    .node-actions { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
    .node-actions.queued-routing-row,
    .node-actions.queued-meta-row { padding-top:6px; border-top:1px solid var(--line); }
    .node-meta.path { overflow-wrap:anywhere; }
    .node-actions.single { grid-template-columns:1fr; }
    .node-admin { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:6px; }
    .node-row { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
    .node-body { display:grid; gap:6px; }
    .state-chip { display:inline-flex; width:max-content; border-radius:999px; padding:3px 8px; background:var(--soft); border:1px solid var(--line); color:var(--text); font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.35px; }
    .collapse-toggle { border:1px solid var(--line); border-radius:999px; background:var(--soft); color:var(--text); padding:4px 8px; font-size:11px; font-weight:800; cursor:pointer; white-space:nowrap; }
    .node.collapsed .node-body { display:none; }
    .node.collapsed .node-title { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .dot { position:absolute; top:50%; width:14px; height:14px; margin-top:-7px; border-radius:999px; background:var(--accent); box-shadow:0 0 0 4px rgba(45,148,255,.14); touch-action:none; }
    .dot.left { left:-7px; }
    .dot.right { right:-7px; }
    .dot.dragging { background:var(--success); box-shadow:0 0 0 6px rgba(47,155,101,.18); }
    .drag-handle { position:absolute; top:50%; display:flex; align-items:center; gap:0; transform:translateY(-50%); cursor:grab; touch-action:none; }
    .drag-handle.right { right:10px; }
    .drag-handle.dragging { cursor:grabbing; }
    .drag-cord { width:20px; height:5px; border-radius:999px; background:linear-gradient(90deg, rgba(45,148,255,.2), rgba(45,148,255,.9)); box-shadow:0 0 0 1px rgba(45,148,255,.18); }
    .drag-knob { position:relative; width:16px; height:16px; margin-left:-2px; border-radius:999px; background:var(--accent); box-shadow:0 0 0 4px rgba(45,148,255,.14); }
    .drag-handle.dragging .drag-cord { background:linear-gradient(90deg, rgba(47,155,101,.25), rgba(47,155,101,.95)); box-shadow:0 0 0 1px rgba(47,155,101,.2); }
    .drag-handle.dragging .drag-knob { background:var(--success); box-shadow:0 0 0 6px rgba(47,155,101,.18); }
    .load-confirmation { display:inline-flex; width:max-content; border-radius:999px; padding:6px 10px; background:rgba(47,155,101,.14); border:1px solid rgba(47,155,101,.32); color:var(--success); font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:.35px; }
    .wire-base { opacity:.34; }
    .wire-live {
      stroke-dasharray: 14 10;
      animation: wireFlow 1.2s linear infinite;
      filter: drop-shadow(0 0 6px rgba(45,148,255,.28));
    }
    @keyframes wireFlow { from { stroke-dashoffset: 24; } to { stroke-dashoffset: 0; } }
    @keyframes queueFreshPulse {
      0% { box-shadow: inset 0 -12px 22px rgba(50,150,255,.10), 0 10px 22px rgba(50,150,255,.12); }
      50% { box-shadow: inset 0 -18px 32px rgba(50,150,255,.18), 0 18px 38px rgba(50,150,255,.26); }
      100% { box-shadow: inset 0 -12px 22px rgba(50,150,255,.10), 0 10px 22px rgba(50,150,255,.12); }
    }
    @media (max-width: 980px) { .toolbar { grid-template-columns:1fr; } .board-grid { grid-template-columns:1fr; height:auto; } .column { grid-template-rows:auto auto; height:auto; } .dot { display:none; } .board { min-height:unset; height:auto; } .lane-frame { height:auto; overflow:visible; } }
    @media (max-width: 540px) {
      .node-actions,
      .node-admin,
      .node-actions.queued-routing-row,
      .node-actions.queued-meta-row { grid-template-columns:1fr; }
    }
  </style>
</head>
<body>
  <div id="sidebarBackdrop" class="sidebar-backdrop" onclick="closeSidebar()"></div>
  <aside id="sidebar" class="sidebar" aria-hidden="true">
    <h2 style="margin:0;">Menu</h2>
    <div class="sidebar-tabs">
      <a class="sidebar-tab" href="/">Dashboard</a>
      <a class="sidebar-tab" href="/conversion">3D Conversion</a>
      <a class="sidebar-tab" href="/makerworks">MakerWorks Search</a>
      <a class="sidebar-tab active" href="/makerworks-routing">Routing Board</a>
      <a class="sidebar-tab" href="/add-printer">Add Printer</a>
    </div>
  </aside>
  <div class="wrap">
    <div class="top">
      <div class="top-head">
        <button class="menu" type="button" onclick="openSidebar()">Menu</button>
        <div>
        <h1 style="margin:0 0 8px;">MakerWorks Routing Board</h1>
        <p style="margin:0;color:var(--muted);max-width:760px;">Models stay in the left queue column and printers stay in the right column. Each column scrolls independently, and cards can collapse to a single summary row.</p>
        </div>
      </div>
      <div class="top-actions">
        <a class="link-btn" href="/makerworks">Back To Search</a>
        <button class="btn secondary" type="button" onclick="refreshBoard()">Refresh</button>
      </div>
    </div>
    <div class="status-row">
      <span id="chosenCount" class="pill">0 chosen</span>
      <span id="queuedCount" class="pill">0 queued jobs</span>
      <span id="printerCount" class="pill">0 available printers</span>
    </div>
    <div id="pageNotice" class="notice" role="status" aria-live="polite"></div>
    <div class="toolbar">
      <div class="field">
        <label for="leftSearch">Find models or queued jobs</label>
        <input id="leftSearch" type="search" placeholder="Search by name, author, status, or job id" oninput="setLeftSearch(this.value)" />
      </div>
      <div class="field">
        <label for="printerSearch">Find printers</label>
        <input id="printerSearch" type="search" placeholder="Search by printer name, type, or state" oninput="setPrinterSearch(this.value)" />
      </div>
      <button class="btn secondary" type="button" onclick="clearFilters()">Clear Filters</button>
    </div>
    <section id="routingBoard" class="board">
      <svg id="boardSvg" class="board-svg"></svg>
      <div class="board-grid">
        <div class="column">
          <div class="lane-title">Models In Queue</div>
          <div class="lane-frame">
            <div id="leftStack" class="stack"></div>
          </div>
        </div>
        <div class="column">
          <div class="lane-title">Printers</div>
          <div class="lane-frame">
            <div id="rightStack" class="stack"></div>
          </div>
        </div>
      </div>
    </section>
  </div>
  <script>
    const slicerTarget = __SLICER_TARGET__;
    const slicerProtocolTemplate = __SLICER_PROTOCOL_TEMPLATE__;
    const nativeFetch = window.fetch.bind(window);
    const routingKey = 'printlab.makerworks.routingModels';
    const collapsedCardKey = 'printlab.makerworks.routingCollapsed';
    const assignmentKey = 'printlab.makerworks.routingAssignments';
    const queueFreshWindowMs = 12000;
    let chosenModels = [];
    let submittedJobs = [];
    let printers = [];
    let activeLeft = null;
    let draftAssignments = {};
    let dragState = null;
    let recentQueuedJobs = {};
    let collapsedCards = {};
    let leftSearch = '';
    let printerSearch = '';
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
    function escapeHtml(value) { return String(value ?? '').replace(/[&<>\"']/g, (char) => ({ '&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;' }[char])); }
    function openSidebar() { document.getElementById('sidebar').classList.add('open'); document.getElementById('sidebarBackdrop').classList.add('open'); document.getElementById('sidebar').setAttribute('aria-hidden', 'false'); }
    function closeSidebar() { document.getElementById('sidebar').classList.remove('open'); document.getElementById('sidebarBackdrop').classList.remove('open'); document.getElementById('sidebar').setAttribute('aria-hidden', 'true'); }
    function getChosenModels() { try { return JSON.parse(localStorage.getItem(routingKey) || '[]'); } catch (_error) { return []; } }
    function saveChosenModels(items) { localStorage.setItem(routingKey, JSON.stringify(items)); chosenModels = items; renderBoard(); }
    function getCollapsedCards() { try { return JSON.parse(localStorage.getItem(collapsedCardKey) || '{}'); } catch (_error) { return {}; } }
    function saveCollapsedCards() { localStorage.setItem(collapsedCardKey, JSON.stringify(collapsedCards)); }
    function getDraftAssignments() { try { return JSON.parse(localStorage.getItem(assignmentKey) || '{}'); } catch (_error) { return {}; } }
    function saveDraftAssignments() { localStorage.setItem(assignmentKey, JSON.stringify(draftAssignments)); }
    collapsedCards = getCollapsedCards();
    draftAssignments = getDraftAssignments();
    function showNotice(message) {
      const el = document.getElementById('pageNotice');
      el.textContent = message;
      el.className = 'notice show';
      window.clearTimeout(showNotice._timer);
      showNotice._timer = window.setTimeout(() => { el.className = 'notice'; }, 3600);
    }
    function leftNodeId(kind, id) { return `${kind}:${id}`; }
    function pruneRecentQueuedJobs() {
      const now = Date.now();
      recentQueuedJobs = Object.fromEntries(
        Object.entries(recentQueuedJobs).filter(([, queuedAt]) => (now - Number(queuedAt || 0)) < queueFreshWindowMs)
      );
    }
    function availablePrinters() { return printers.filter((printer) => !!printer.connected); }
    function matchesSearch(parts, query) {
      if (!query) return true;
      const haystack = parts.filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(query);
    }
    function setLeftSearch(value) { leftSearch = String(value || '').trim().toLowerCase(); renderBoard(); }
    function setPrinterSearch(value) { printerSearch = String(value || '').trim().toLowerCase(); renderBoard(); }
    function clearFilters() {
      leftSearch = '';
      printerSearch = '';
      const leftInput = document.getElementById('leftSearch');
      const printerInput = document.getElementById('printerSearch');
      if (leftInput) leftInput.value = '';
      if (printerInput) printerInput.value = '';
      renderBoard();
    }
    function isCollapsed(cardId) { return !!collapsedCards[String(cardId || '')]; }
    function toggleCardCollapse(cardId, event) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      const key = String(cardId || '');
      if (!key) return;
      if (collapsedCards[key]) delete collapsedCards[key];
      else collapsedCards[key] = true;
      saveCollapsedCards();
      renderBoard();
    }
    function upgradeCards() {
      document.querySelectorAll('#leftStack article.node.routeable, #rightStack article.node[data-printer-id]').forEach((card) => {
        const cardId = String(card.id || '');
        const handle = card.querySelector('.drag-handle, .dot');
        const title = card.querySelector(':scope > .node-title');
        if (!title) {
          card.classList.toggle('collapsed', isCollapsed(cardId));
          const existingToggle = card.querySelector('.collapse-toggle');
          if (existingToggle) existingToggle.textContent = isCollapsed(cardId) ? 'Expand' : 'Collapse';
          return;
        }
        const summary = title.nextElementSibling && title.nextElementSibling.classList.contains('node-meta')
          ? title.nextElementSibling
          : null;
        const header = document.createElement('div');
        header.className = 'node-header';
        const heading = document.createElement('div');
        heading.className = 'node-heading';
        heading.appendChild(title);
        if (summary) heading.appendChild(summary);
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'collapse-toggle';
        toggle.textContent = isCollapsed(cardId) ? 'Expand' : 'Collapse';
        toggle.addEventListener('click', (event) => toggleCardCollapse(cardId, event));
        header.appendChild(heading);
        header.appendChild(toggle);
        const body = document.createElement('div');
        body.className = 'node-body';
        const remaining = Array.from(card.children).filter((child) => child !== handle && child !== title && child !== summary);
        remaining.forEach((child) => body.appendChild(child));
        if (handle) card.appendChild(handle);
        card.appendChild(header);
        card.appendChild(body);
        card.classList.toggle('collapsed', isCollapsed(cardId));
      });
    }
    function updateCount(id, visible, total, label) {
      document.getElementById(id).textContent = visible === total ? `${total} ${label}` : `${visible}/${total} ${label}`;
    }
    function applyBoardFilters() {
      const leftStack = document.getElementById('leftStack');
      const rightStack = document.getElementById('rightStack');
      if (!leftStack || !rightStack) return;
      let visibleChosen = 0;
      let visibleJobs = 0;
      let visiblePrinters = 0;
      leftStack.querySelectorAll('article.node.routeable').forEach((node) => {
        const isVisible = matchesSearch([node.textContent || ''], leftSearch);
        node.style.display = isVisible ? '' : 'none';
        if (!isVisible) return;
        if (String(node.id || '').startsWith('chosen:')) visibleChosen += 1;
        else visibleJobs += 1;
      });
      rightStack.querySelectorAll('article.node[data-printer-id]').forEach((node) => {
        const isVisible = matchesSearch([node.textContent || ''], printerSearch);
        node.style.display = isVisible ? '' : 'none';
        if (isVisible) visiblePrinters += 1;
      });
      updateCount('chosenCount', visibleChosen, chosenModels.length, 'chosen');
      updateCount('queuedCount', visibleJobs, submittedJobs.length, 'queued jobs');
      updateCount('printerCount', visiblePrinters, availablePrinters().length, 'available printers');
      let leftEmpty = leftStack.querySelector('[data-empty-state="left"]');
      const hasVisibleLeft = visibleChosen + visibleJobs > 0;
      if (!hasVisibleLeft) {
        if (!leftEmpty) {
          leftEmpty = document.createElement('div');
          leftEmpty.className = 'empty-state';
          leftEmpty.dataset.emptyState = 'left';
          leftStack.appendChild(leftEmpty);
        }
        leftEmpty.textContent = leftSearch ? 'No models or queued jobs match the current search.' : 'No models or queued jobs to route yet.';
      } else if (leftEmpty) {
        leftEmpty.remove();
      }
      let rightEmpty = rightStack.querySelector('[data-empty-state="right"]');
      if (!visiblePrinters) {
        if (!rightEmpty) {
          rightEmpty = document.createElement('div');
          rightEmpty.className = 'empty-state';
          rightEmpty.dataset.emptyState = 'right';
          rightStack.appendChild(rightEmpty);
        }
        rightEmpty.textContent = printerSearch ? 'No printers match the current search.' : 'No connected printers are available.';
      } else if (rightEmpty) {
        rightEmpty.remove();
      }
    }
    function printerGlowClass(printer) {
      const state = String(printer?.job?.state || '').toLowerCase();
      if (['running', 'printing', 'started', 'busy', 'processing'].includes(state)) return 'printer-running';
      if (printer?.connected) return 'printer-open';
      return '';
    }
    function selectLeftNode(nodeId) { activeLeft = nodeId; renderBoard(); }
    function eventPoint(event) {
      if (event.touches && event.touches[0]) return { x: event.touches[0].clientX, y: event.touches[0].clientY };
      if (event.changedTouches && event.changedTouches[0]) return { x: event.changedTouches[0].clientX, y: event.changedTouches[0].clientY };
      return { x: event.clientX, y: event.clientY };
    }
    function startWireDrag(nodeId, event) {
      event.preventDefault();
      event.stopPropagation();
      const source = document.getElementById(nodeId);
      const board = document.getElementById('routingBoard');
      if (!source || !board) return;
      const sourceHandle = source.querySelector('.drag-handle.right');
      const sourceDot = source.querySelector('.drag-knob');
      if (!sourceHandle || !sourceDot) return;
      activeLeft = nodeId;
      const boardRect = board.getBoundingClientRect();
      const dotRect = sourceDot.getBoundingClientRect();
      dragState = {
        nodeId,
        x1: dotRect.left + (dotRect.width / 2) - boardRect.left,
        y1: dotRect.top + (dotRect.height / 2) - boardRect.top,
        x2: dotRect.left + (dotRect.width / 2) - boardRect.left,
        y2: dotRect.top + (dotRect.height / 2) - boardRect.top,
      };
      sourceHandle.classList.add('dragging');
      renderBoard();
    }
    function updateWireDrag(event) {
      if (!dragState) return;
      const board = document.getElementById('routingBoard');
      if (!board) return;
      const boardRect = board.getBoundingClientRect();
      const point = eventPoint(event);
      dragState.x2 = point.x - boardRect.left;
      dragState.y2 = point.y - boardRect.top;
      drawConnections();
    }
    function completeWireDrag(printerId) {
      if (!dragState) return;
      const nodeId = dragState.nodeId;
      cleanupWireDrag();
      activeLeft = nodeId;
      connectToPrinter(printerId);
    }
    function cleanupWireDrag() {
      document.querySelectorAll('.drag-handle.dragging').forEach((item) => item.classList.remove('dragging'));
      dragState = null;
      drawConnections();
    }
    function stopWireDrag(event) {
      if (!dragState) return;
      event.preventDefault();
      const target = event.target instanceof Element ? event.target.closest('[data-printer-id]') : null;
      if (target?.dataset.printerId) {
        completeWireDrag(target.dataset.printerId);
        return;
      }
      cleanupWireDrag();
    }
    function connectToPrinter(printerId) {
      if (!activeLeft) {
        showNotice('Select a chosen model or queued job on the left first.');
        return;
      }
      draftAssignments[activeLeft] = printerId;
      saveDraftAssignments();
      renderBoard();
      showNotice(`Model loaded on ${printers.find((printer) => printer.id === printerId)?.name || printerId}.`);
    }
    function getAssignedPrinter(entryId, item) {
      if (Object.prototype.hasOwnProperty.call(draftAssignments, entryId)) {
        return draftAssignments[entryId] || '';
      }
      return item?.printer_id || '';
    }
    function disconnectPrinter(nodeId) {
      const key = String(nodeId || '');
      if (!key) return;
      draftAssignments[key] = '';
      saveDraftAssignments();
      renderBoard();
      showNotice('Model disconnected from printer.');
    }
    function removeChosenModel(modelId) {
      const nodeId = leftNodeId('chosen', modelId);
      delete draftAssignments[nodeId];
      saveDraftAssignments();
      saveChosenModels(chosenModels.filter((item) => String(item.id) !== String(modelId)));
    }
    function moveChosenModel(modelId, direction) {
      const items = [...chosenModels];
      const index = items.findIndex((item) => String(item.id) === String(modelId));
      if (index < 0) return;
      const nextIndex = direction === 'up' ? index - 1 : index + 1;
      if (nextIndex < 0 || nextIndex >= items.length) return;
      [items[index], items[nextIndex]] = [items[nextIndex], items[index]];
      saveChosenModels(items);
    }
    async function submitChosenModel(nodeId) {
      const printerId = draftAssignments[nodeId];
      const modelId = String(nodeId).split(':').slice(1).join(':');
      const item = chosenModels.find((entry) => String(entry.id) === modelId);
      if (!item || !printerId) return;
      try {
        const response = await fetch('/api/works/makerworks/jobs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model_id: String(item.id),
            printer_id: printerId,
            idempotency_key: `makerworks-ui:${printerId}:${String(item.id)}`,
            source_job_id: `makerworks-ui-job:${printerId}:${String(item.id)}`,
            source_order_id: `makerworks-ui-order:${String(item.id)}`
          })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data?.message || data?.detail || `HTTP ${response.status}`);
        removeChosenModel(String(item.id));
        delete draftAssignments[nodeId];
        saveDraftAssignments();
        await refreshBoard();
        showNotice(`${item.name || 'Model'} queued to ${printers.find((printer) => printer.id === printerId)?.name || printerId}.`);
      } catch (error) {
        showNotice(`Failed to queue model: ${String(error?.message || error)}`);
      }
    }
    async function syncSubmittedJob(jobId) {
      try {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/sync-makerworks`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force: true }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
        showNotice(`Resent callback for ${data.item?.model_name || data.item?.file_name || 'job'}.`);
        await refreshBoard();
      } catch (error) {
        showNotice(`Failed to resend callback: ${String(error?.message || error)}`);
      }
    }
    function decodeRoutingItem(encoded) {
      try {
        return JSON.parse(decodeURIComponent(String(encoded || '')));
      } catch (_error) {
        return null;
      }
    }
    function openExternalUrl(url) {
      if (!url) return false;
      const opened = window.open(String(url), '_blank', 'noopener,noreferrer');
      return !!opened;
    }
    function buildSlicerLaunchUrl(assetUrl) {
      const url = String(assetUrl || '').trim();
      if (!url) return '';
      const encoded = encodeURIComponent(url);
      if (slicerProtocolTemplate && slicerProtocolTemplate.includes('{url}')) {
        return slicerProtocolTemplate.replace('{url}', encoded);
      }
      if (slicerTarget === 'orca' || slicerTarget === 'orca_slicer' || slicerTarget === 'orcaslicer') {
        return `orcaslicer://open?file=${encoded}`;
      }
      if (slicerTarget === 'browser') {
        return url;
      }
      return `bambustudioopen://open?file=${encoded}`;
    }
    function sendQueuedJobToSlicer(encodedItem) {
      const item = decodeRoutingItem(encodedItem);
      const assetUrl = String(item?.download_url || '').trim();
      const label = item?.model_name || item?.file_name || item?.id || 'Queued model';
      if (!assetUrl) {
        showNotice(`${label} does not have a slicer asset URL yet.`);
        return;
      }
      const slicerUrl = buildSlicerLaunchUrl(assetUrl);
      if (!slicerUrl || !openExternalUrl(slicerUrl)) {
        showNotice(`Popup blocked while opening ${label} in slicer.`);
        return;
      }
      showNotice(`Sent ${label} to ${slicerTarget === 'browser' ? 'browser' : (slicerTarget.startsWith('orca') ? 'OrcaSlicer' : 'Bambu Studio')}.`);
    }
    function importQueuedRevision(encodedItem) {
      const item = decodeRoutingItem(encodedItem);
      const revisionUrl = String(item?.model_url || item?.download_url || '').trim();
      const label = item?.model_name || item?.file_name || item?.id || 'Queued model';
      if (!revisionUrl) {
        showNotice(`${label} does not have a revision link yet.`);
        return;
      }
      if (!openExternalUrl(revisionUrl)) {
        showNotice(`Popup blocked while opening ${label} revision.`);
        return;
      }
      showNotice(`Opened ${label} revision.`);
    }
    async function deleteQueuedJob(nodeId, queueItemId, label) {
      if (!queueItemId) {
        showNotice('Queued job is missing a queue entry id.');
        return;
      }
      if (!window.confirm(`Delete ${label || 'queued job'} from the queue?`)) return;
      try {
        const response = await fetch(`/api/queue/${encodeURIComponent(queueItemId)}`, { method: 'DELETE' });
        const data = await response.json();
        if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
        delete draftAssignments[nodeId];
        saveDraftAssignments();
        if (activeLeft === nodeId) activeLeft = null;
        await refreshBoard();
        showNotice(`${label || 'Queued job'} removed from the queue.`);
      } catch (error) {
        showNotice(`Failed to delete queued job: ${String(error?.message || error)}`);
      }
    }
    function drawConnections() {
      const svg = document.getElementById('boardSvg');
      const board = document.getElementById('routingBoard');
      const boardRect = board.getBoundingClientRect();
      svg.setAttribute('viewBox', `0 0 ${boardRect.width} ${boardRect.height}`);
      svg.setAttribute('width', String(boardRect.width));
      svg.setAttribute('height', String(boardRect.height));
      const lines = [];
      Object.entries(draftAssignments).forEach(([leftId, printerId]) => {
        const left = document.getElementById(leftId);
        const right = document.getElementById(`printer:${printerId}`);
        if (!left || !right) return;
        const leftRect = left.getBoundingClientRect();
        const rightRect = right.getBoundingClientRect();
        const x1 = leftRect.right - boardRect.left;
        const y1 = leftRect.top + (leftRect.height / 2) - boardRect.top;
        const x2 = rightRect.left - boardRect.left;
        const y2 = rightRect.top + (rightRect.height / 2) - boardRect.top;
        const c1 = x1 + Math.max(40, (x2 - x1) * 0.35);
        const c2 = x2 - Math.max(40, (x2 - x1) * 0.35);
        const path = `M ${x1} ${y1} C ${c1} ${y1}, ${c2} ${y2}, ${x2} ${y2}`;
        lines.push(`<path class="wire-base" d="${path}" fill="none" stroke="var(--accent)" stroke-width="6" stroke-linecap="round" />`);
        lines.push(`<path class="wire-live" d="${path}" fill="none" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" />`);
      });
      if (dragState) {
        const c1 = dragState.x1 + Math.max(40, (dragState.x2 - dragState.x1) * 0.35);
        const c2 = dragState.x2 - Math.max(40, (dragState.x2 - dragState.x1) * 0.35);
        const path = `M ${dragState.x1} ${dragState.y1} C ${c1} ${dragState.y1}, ${c2} ${dragState.y2}, ${dragState.x2} ${dragState.y2}`;
        lines.push(`<path class="wire-base" d="${path}" fill="none" stroke="var(--success)" stroke-width="6" stroke-linecap="round" />`);
        lines.push(`<path class="wire-live" d="${path}" fill="none" stroke="var(--success)" stroke-width="3" stroke-linecap="round" />`);
      }
      svg.innerHTML = lines.join('');
    }
    function renderBoard() {
      document.getElementById('chosenCount').textContent = `${chosenModels.length} chosen`;
      document.getElementById('queuedCount').textContent = `${submittedJobs.length} queued jobs`;
      document.getElementById('printerCount').textContent = `${availablePrinters().length} available printers`;
      const leftItems = [
        ...chosenModels.map((item) => ({ kind: 'chosen', id: leftNodeId('chosen', item.id), item })),
        ...submittedJobs.map((item) => ({ kind: 'job', id: leftNodeId('job', item.id), item })),
      ];
      const leftStack = document.getElementById('leftStack');
      if (!leftItems.length) {
        leftStack.innerHTML = "<div class='node'><div class='node-title'>No models or queued jobs</div><div class='node-meta'>Add models from MakerWorks Search first, or wait for queued PrintLab jobs to appear.</div></div>";
      } else {
        leftStack.innerHTML = leftItems.map((entry) => {
          const item = entry.item;
          const isChosen = entry.kind === 'chosen';
          const assignedPrinter = getAssignedPrinter(entry.id, item);
          const isFreshQueuedJob = !isChosen && recentQueuedJobs[String(item.id || '')];
          const queuedJobStateClass = !isChosen
            ? (isFreshQueuedJob ? 'queue-fresh' : (assignedPrinter ? 'queue-connected' : ''))
            : '';
          const encodedItem = encodeURIComponent(JSON.stringify(item));
          return `
            <article id="${escapeHtml(entry.id)}" class="node routeable ${activeLeft === entry.id ? 'selected' : ''} ${assignedPrinter ? 'connected' : ''} ${queuedJobStateClass}" onclick="selectLeftNode('${escapeHtml(entry.id)}')">
              <span class="drag-handle right" title="Drag to printer" onpointerdown="startWireDrag('${escapeHtml(entry.id)}', event)">
                <span class="drag-cord"></span>
                <span class="drag-knob"></span>
              </span>
              <div class="node-title">${escapeHtml(isChosen ? (item.name || 'Untitled model') : (item.model_name || item.file_name || item.id || 'Queued job'))}</div>
              <div class="node-meta">${escapeHtml(isChosen ? `Chosen model • ${item.author || 'Unknown creator'}` : `${String(item.status || 'queued').toUpperCase()} • ${item.source_job_id || item.source_order_id || item.id}`)}</div>
              <div class="node-meta">${escapeHtml(assignedPrinter ? `Connected to ${printers.find((printer) => printer.id === assignedPrinter)?.name || assignedPrinter}` : 'No printer connected yet')}</div>
              ${assignedPrinter ? `<div class="load-confirmation">Model Loaded</div>` : ''}
              ${isChosen ? `
                <div class="node-admin">
                  <button class="btn secondary" type="button" onclick="event.stopPropagation(); moveChosenModel('${escapeHtml(String(item.id || ''))}', 'up')">Up</button>
                  <button class="btn secondary" type="button" onclick="event.stopPropagation(); moveChosenModel('${escapeHtml(String(item.id || ''))}', 'down')">Down</button>
                  <button class="btn secondary" type="button" onclick="event.stopPropagation(); removeChosenModel('${escapeHtml(String(item.id || ''))}')">Delete</button>
                </div>
              ` : ''}
              <div class="node-actions">
                ${assignedPrinter ? `<button class="btn secondary" type="button" onclick="event.stopPropagation(); disconnectPrinter('${escapeHtml(entry.id)}')">Disconnect Printer</button>` : (isChosen ? `<button class="btn secondary" type="button" disabled>No Printer Connected</button>` : `<a class="link-btn" href="/printer/${encodeURIComponent(item.printer_id || '')}" onclick="event.stopPropagation();">Open</a>`)}
                ${isChosen ? `<button class="btn" type="button" onclick="event.stopPropagation(); submitChosenModel('${escapeHtml(entry.id)}')" ${assignedPrinter ? '' : 'disabled'}>Queue Now</button>` : `<button class="btn secondary" type="button" onclick="event.stopPropagation(); deleteQueuedJob('${escapeHtml(entry.id)}', '${escapeHtml(String(item.queue_item_id || ''))}', '${escapeHtml(String(item.model_name || item.file_name || item.id || 'Queued job'))}')">Delete Queue</button>`}
              </div>
              ${isChosen ? '' : `<div class="node-actions queued-routing-row"><button class="btn secondary" type="button" onclick="event.stopPropagation(); sendQueuedJobToSlicer('${escapeHtml(encodedItem)}')">Send to slicer</button><button class="btn secondary" type="button" onclick="event.stopPropagation(); importQueuedRevision('${escapeHtml(encodedItem)}')">Import revision</button></div>`}
              ${isChosen ? '' : `<div class="node-actions queued-meta-row"><button class="btn secondary" type="button" onclick="event.stopPropagation(); syncSubmittedJob('${escapeHtml(String(item.id || ''))}')">Resend Callback</button><span class="node-meta path">${escapeHtml(String(item.file_path || ''))}</span></div>`}
            </article>
          `;
        }).join('');
      }
      const printerItems = availablePrinters();
      const rightStack = document.getElementById('rightStack');
      rightStack.innerHTML = printerItems.length ? printerItems.map((printer) => `
        <article id="printer:${escapeHtml(printer.id)}" data-printer-id="${escapeHtml(printer.id)}" class="node ${printerGlowClass(printer)}" onclick="connectToPrinter('${escapeHtml(printer.id)}')">
          <span class="dot left"></span>
          <div class="node-title">${escapeHtml(printer.name)}</div>
          <div class="node-meta">${escapeHtml(printer.device_type || 'Printer')} • ${escapeHtml(printer.connected ? 'Connected' : 'Offline')}</div>
          <div class="node-meta">${escapeHtml(`Queue ${Number(printer.queue?.count || 0)} • ${String(printer.job?.state || 'Ready')}`)}</div>
          <div class="node-actions">
            <a class="link-btn" href="/printer/${encodeURIComponent(printer.id)}" onclick="event.stopPropagation();">Open Dashboard</a>
            <button class="btn secondary" type="button" onclick="event.stopPropagation(); connectToPrinter('${escapeHtml(printer.id)}')">${activeLeft ? 'Connect' : 'Select Left Node First'}</button>
          </div>
        </article>
      `).join('') : "<div class='node'><div class='node-title'>No printers available</div><div class='node-meta'>Bring a printer online to start routing.</div></div>";
      upgradeCards();
      applyBoardFilters();
      window.requestAnimationFrame(drawConnections);
    }
    async function refreshBoard() {
      const previousSubmittedIds = new Set(submittedJobs.map((item) => String(item.id || '')));
      chosenModels = getChosenModels();
      const [printerRes, jobRes] = await Promise.all([fetch('/api/printers'), fetch('/api/jobs?status=queued')]);
      const printerData = await printerRes.json();
      const jobData = await jobRes.json();
      if (!printerRes.ok) throw new Error(printerData?.detail || `HTTP ${printerRes.status}`);
      if (!jobRes.ok) throw new Error(jobData?.detail || `HTTP ${jobRes.status}`);
      printers = Array.isArray(printerData.items) ? printerData.items : [];
      submittedJobs = (Array.isArray(jobData.items) ? jobData.items : []).filter((item) => String(item.source || '').toLowerCase() === 'makerworks');
      const now = Date.now();
      submittedJobs.forEach((item) => {
        const itemId = String(item.id || '');
        if (itemId && !previousSubmittedIds.has(itemId) && !item.printer_id) {
          recentQueuedJobs[itemId] = now;
        }
      });
      submittedJobs.forEach((item) => {
        if (item?.printer_id) {
          delete recentQueuedJobs[String(item.id || '')];
        }
      });
      pruneRecentQueuedJobs();
      renderBoard();
    }
    window.addEventListener('pointermove', updateWireDrag);
    window.addEventListener('pointerup', stopWireDrag);
    window.addEventListener('pointercancel', cleanupWireDrag);
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeSidebar(); });
    window.addEventListener('resize', drawConnections);
    refreshBoard().catch((error) => showNotice(`Failed to load routing board: ${String(error?.message || error)}`));
    window.setInterval(() => {
      refreshBoard().catch(() => {});
    }, 5000);
  </script>
</body>
</html>"""
    return (
        html.replace("__SLICER_TARGET__", json.dumps(slicer_target))
        .replace("__SLICER_PROTOCOL_TEMPLATE__", json.dumps(slicer_protocol_template))
    )


def render_conversion_html() -> str:
    try:
        from app.conversion import supported_conversion_formats

        initial_formats = supported_conversion_formats()
    except Exception:
        initial_formats = {
            "source_formats": ["3mf", "dae", "dxf", "glb", "gltf", "obj", "off", "ply", "stl", "xaml", "xyz"],
            "target_formats": [
                {"id": "obj", "label": "OBJ", "recommended": True, "description": "Recommended OBJ mesh export."},
                {"id": "stl", "label": "STL", "recommended": False, "description": "Mesh export format."},
                {"id": "ply", "label": "PLY", "recommended": False, "description": "Mesh export format."},
                {"id": "off", "label": "OFF", "recommended": False, "description": "Mesh export format."},
                {"id": "glb", "label": "GLB", "recommended": False, "description": "Mesh export format."},
                {"id": "3mf", "label": "3MF", "recommended": False, "description": "Mesh export format."},
                {"id": "dae", "label": "DAE", "recommended": False, "description": "Mesh export format."},
            ],
            "recommended_target": "obj",
        }

    target_options_html = "".join(
        f'<option value="{item["id"]}"{" selected" if item["id"] == initial_formats.get("recommended_target") else ""}>'
        f'{item["label"]}{" - Recommended" if item.get("recommended") else ""}</option>'
        for item in initial_formats["target_formats"]
    )
    source_options_html = "".join(
        f'<option value="{item}">{item.upper()}</option>' for item in initial_formats["source_formats"]
    )

    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content">
  <meta id="themeColorMeta" name="theme-color" content="#cfe2f7">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="PrintLab">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <title>PrintLab - 3D Conversion</title>
  <script>
    (function() {
      const theme = localStorage.getItem("printlab-theme") === "dark" ? "dark" : "light";
      document.documentElement.dataset.theme = theme;
    })();
  </script>
  <style>
    :root {
      --safe-top: env(safe-area-inset-top, 0px);
      --safe-right: env(safe-area-inset-right, 0px);
      --safe-bottom: env(safe-area-inset-bottom, 0px);
      --safe-left: env(safe-area-inset-left, 0px);
      --bg: #e7f0fa;
      --bg-2: #d6e5f7;
      --text: #203043;
      --muted: #5e758c;
      --card: rgba(255, 255, 255, 0.72);
      --line: rgba(89, 126, 164, 0.2);
      --button: #1f84ea;
      --button-text: #ffffff;
      --soft: rgba(255, 255, 255, 0.68);
      --shadow: 0 18px 38px rgba(31, 72, 116, 0.16);
    }
    :root[data-theme="dark"] {
      --bg: #101925;
      --bg-2: #172537;
      --text: #ecf4ff;
      --muted: #9fb6cf;
      --card: rgba(16, 28, 42, 0.82);
      --line: rgba(136, 164, 194, 0.2);
      --button: #54aaf5;
      --button-text: #09131d;
      --soft: rgba(255, 255, 255, 0.08);
      --shadow: 0 24px 44px rgba(1, 8, 17, 0.4);
    }
    * { box-sizing: border-box; }
    html { color-scheme: light; min-height: 100%; background: var(--bg); }
    :root[data-theme="dark"] { color-scheme: dark; }
    body {
      margin: 0;
      min-height: 100vh;
      min-height: 100dvh;
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:
        radial-gradient(1000px 560px at 0% 0%, rgba(255,255,255,0.66), transparent 52%),
        linear-gradient(155deg, var(--bg), var(--bg-2));
    }
    .sidebar-backdrop { position: fixed; inset: 0; background: rgba(10, 19, 29, 0.38); display: none; z-index: 40; }
    .sidebar-backdrop.open { display: block; }
    .sidebar {
      position: fixed;
      top: 0;
      left: 0;
      z-index: 41;
      width: 320px;
      max-width: 86vw;
      height: 100vh;
      height: 100dvh;
      padding: calc(var(--safe-top) + 18px) 14px calc(var(--safe-bottom) + 16px);
      background: rgba(248, 252, 255, 0.96);
      border-right: 1px solid rgba(202, 220, 239, 0.96);
      box-shadow: 18px 0 32px rgba(17, 42, 68, 0.16);
      transform: translateX(-101%);
      transition: transform .18s ease;
      overflow: auto;
    }
    :root[data-theme="dark"] .sidebar {
      background: rgba(15, 24, 36, 0.96);
      border-right-color: rgba(69, 94, 120, 0.8);
      box-shadow: 18px 0 34px rgba(0, 0, 0, 0.38);
    }
    .sidebar.open { transform: translateX(0); }
    .sidebar-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .sidebar-head-actions { display: flex; gap: 8px; align-items: center; }
    .theme-toggle, .sidebar-close, .menu, .btn, .download-link, .select, .field {
      border-radius: 12px;
      border: 1px solid transparent;
      font: inherit;
    }
    .theme-toggle, .sidebar-close, .menu {
      background: var(--soft);
      color: var(--text);
      cursor: pointer;
      padding: 8px 10px;
    }
    .sidebar-close { font-size: 18px; line-height: 1; padding: 6px 10px; }
    .sidebar-tabs { display: grid; gap: 8px; margin-top: 12px; }
    .sidebar-tab {
      display: block;
      text-decoration: none;
      border: 1px solid var(--line);
      background: var(--soft);
      color: var(--text);
      border-radius: 999px;
      padding: 7px 11px;
      font-size: 12px;
      font-weight: 700;
    }
    .sidebar-tab.active { background: var(--button); color: var(--button-text); border-color: var(--button); }
    .wrap {
      max-width: 1080px;
      margin: 0 auto;
      padding: calc(var(--safe-top) + 20px) calc(var(--safe-right) + 16px) calc(var(--safe-bottom) + 36px) calc(var(--safe-left) + 16px);
      display: grid;
      gap: 16px;
    }
    .hero, .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
    }
    .hero {
      padding: 18px;
      display: grid;
      gap: 16px;
    }
    .hero-top { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
    .hero-copy { max-width: 720px; }
    .hero h1 { margin: 10px 0 8px; font-size: clamp(28px, 4vw, 44px); line-height: 1; }
    .hero p, .sidebar p, .meta, .status-line { color: var(--muted); line-height: 1.5; }
    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(260px, 0.85fr);
      gap: 14px;
    }
    .panel { padding: 16px; display: grid; gap: 14px; }
    .panel h2, .panel h3 { margin: 0; }
    .field, .select {
      width: 100%;
      background: rgba(255, 255, 255, 0.72);
      border-color: var(--line);
      color: var(--text);
      padding: 10px 12px;
      font-weight: 700;
    }
    :root[data-theme="dark"] .field,
    :root[data-theme="dark"] .select {
      background: rgba(255, 255, 255, 0.06);
    }
    .select {
      appearance: none;
      -webkit-appearance: none;
      background-image:
        linear-gradient(45deg, transparent 50%, var(--text) 50%),
        linear-gradient(135deg, var(--text) 50%, transparent 50%);
      background-position:
        calc(100% - 18px) calc(50% - 3px),
        calc(100% - 12px) calc(50% - 3px);
      background-size: 6px 6px, 6px 6px;
      background-repeat: no-repeat;
      padding-right: 32px;
    }
    .select option {
      color: #122235;
      background: #f3f8fe;
    }
    :root[data-theme="dark"] .select option {
      color: #edf5ff;
      background: #162638;
    }
    .dropzone {
      border: 1.5px dashed rgba(31, 132, 234, 0.42);
      border-radius: 18px;
      background: rgba(31, 132, 234, 0.06);
      padding: 18px;
      display: grid;
      gap: 8px;
    }
    .form-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 220px); gap: 12px; }
    .label { display: grid; gap: 6px; font-size: 13px; font-weight: 700; }
    .btn {
      background: var(--button);
      border-color: var(--button);
      color: var(--button-text);
      cursor: pointer;
      padding: 10px 14px;
      font-weight: 800;
    }
    .btn[disabled] { opacity: .55; cursor: wait; }
    .btn.secondary {
      background: var(--soft);
      border-color: var(--line);
      color: var(--text);
    }
    .btn-row { display: flex; gap: 10px; flex-wrap: wrap; }
    .stat-list, .format-list { display: grid; gap: 10px; }
    .stat, .format-chip {
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.44);
      padding: 12px;
    }
    :root[data-theme="dark"] .stat,
    :root[data-theme="dark"] .format-chip {
      background: rgba(255, 255, 255, 0.05);
    }
    .format-list { grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }
    .format-chip strong { display: block; margin-bottom: 5px; }
    .target-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
      gap: 10px;
    }
    .target-chip {
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.44);
      color: var(--text);
      padding: 10px 12px;
      text-align: left;
      cursor: pointer;
      display: grid;
      gap: 4px;
    }
    .target-chip.active {
      border-color: var(--button);
      box-shadow: inset 0 0 0 1px rgba(84, 170, 245, 0.28);
      background: rgba(31, 132, 234, 0.12);
    }
    .target-chip-label {
      font-size: 13px;
      font-weight: 800;
    }
    .target-chip-note {
      font-size: 12px;
      line-height: 1.35;
      color: var(--muted);
    }
    .status {
      min-height: 48px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.4);
      padding: 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .download-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      text-decoration: none;
      background: var(--button);
      color: var(--button-text);
      border-color: var(--button);
      padding: 10px 14px;
      font-weight: 800;
    }
    .result-card { display: none; }
    .result-card.open { display: grid; }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(31, 132, 234, 0.1);
      border: 1px solid rgba(31, 132, 234, 0.16);
      font-size: 12px;
      font-weight: 800;
      color: var(--button);
    }
    @media (max-width: 860px) {
      .hero-grid, .form-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div id="sidebarBackdrop" class="sidebar-backdrop" onclick="closeSidebar()"></div>
  <aside id="sidebar" class="sidebar" aria-hidden="true">
    <div class="sidebar-head">
      <h2 style="margin:0;">Menu</h2>
      <div class="sidebar-head-actions">
        <button id="themeToggle" class="theme-toggle" type="button" aria-label="Switch color theme">Dark</button>
        <button class="sidebar-close" type="button" aria-label="Close menu" onclick="closeSidebar()">&times;</button>
      </div>
    </div>
    <p>Convert common 3D mesh files for downstream tools. OBJ remains the recommended default target, with UV generation when the source mesh does not have them.</p>
    <div class="sidebar-tabs">
      <a class="sidebar-tab" href="/">Dashboard</a>
      <a class="sidebar-tab active" href="/conversion">3D Conversion</a>
      <a class="sidebar-tab" href="/makerworks">MakerWorks Search</a>
      <a class="sidebar-tab" href="/makerworks-routing">Routing Board</a>
      <a class="sidebar-tab" href="/add-printer">Add Printer</a>
    </div>
  </aside>
  <div class="wrap">
    <section class="hero">
      <div class="hero-top">
        <div class="hero-copy">
          <button class="menu" type="button" onclick="openSidebar()">Menu</button>
          <h1>3D File Conversion</h1>
          <p>Upload a 3D file, convert it to another mesh format, and download the result. OBJ is preselected as the default target, and UVs are generated automatically when needed.</p>
        </div>
        <span class="pill">OBJ recommended</span>
      </div>
      <div class="hero-grid">
        <section class="panel">
          <h2>Convert A Model</h2>
          <div class="dropzone">
            <strong>Select one or more source files</strong>
            <span class="meta">Supported source and target formats are loaded from the backend at runtime.</span>
            <input id="fileInput" class="field" type="file" multiple accept=".3mf,.gcode.3mf,.dae,.dxf,.glb,.gltf,.obj,.off,.ply,.stl,.xaml,.xyz">
          </div>
          <div class="form-grid">
            <label class="label">Target format
              <select id="targetFormat" class="select">__TARGET_OPTIONS__</select>
            </label>
            <label class="label">Source format override
              <select id="sourceFormat" class="select">
                <option value="">Auto detect</option>
                __SOURCE_OPTIONS__
              </select>
            </label>
          </div>
          <div id="targetQuickPicks" class="target-grid"></div>
          <div id="formatCapabilities" class="stat"></div>
          <div id="formatWarnings" class="status">No format warnings yet.</div>
          <div class="btn-row">
            <button id="convertBtn" class="btn" type="button" onclick="convertFile()">Convert File</button>
            <button class="btn secondary" type="button" onclick="resetConverter()">Reset</button>
          </div>
          <div id="status" class="status">Loading supported formats...</div>
        </section>
        <section class="panel">
          <h3>Current File</h3>
          <div class="stat-list">
            <div class="stat"><strong>Name</strong><div id="fileName" class="status-line">No file selected</div></div>
            <div class="stat"><strong>Detected source</strong><div id="detectedSource" class="status-line">-</div></div>
            <div class="stat"><strong>Size</strong><div id="fileSize" class="status-line">-</div></div>
          </div>
          <div id="resultCard" class="panel result-card">
            <h3>Converted Output</h3>
            <div class="stat-list">
              <div class="stat"><strong>Output file</strong><div id="resultName" class="status-line">-</div></div>
              <div class="stat"><strong>Target format</strong><div id="resultFormat" class="status-line">-</div></div>
              <div class="stat"><strong>Output size</strong><div id="resultSize" class="status-line">-</div></div>
              <div class="stat"><strong>UV map</strong><div id="resultUv" class="status-line">-</div></div>
            </div>
            <a id="downloadLink" class="download-link" href="#" download>Download Converted File</a>
          </div>
          <div id="batchResultCard" class="panel result-card">
            <h3>Batch Results</h3>
            <div id="batchResultList" class="stat-list"></div>
          </div>
        </section>
      </div>
    </section>
    <section class="panel">
      <h2>Available Formats</h2>
      <div id="formatList" class="format-list"></div>
      <h3 style="margin:8px 0 0;">Popular conversions</h3>
      <div id="commonConversionList" class="stat-list"></div>
      <div class="meta">This page only shows formats the current server can actually convert right now.</div>
    </section>
  </div>
  <script>
    const nativeFetch = window.fetch.bind(window);
    const defaultSupportedFormats = __DEFAULT_SUPPORTED_FORMATS__;
    let supportedFormats = defaultSupportedFormats;

    function readCookie(name) {
      const prefix = `${name}=`;
      return document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith(prefix))?.slice(prefix.length) || "";
    }

    window.fetch = function(input, init = {}) {
      const next = { ...init, credentials: "same-origin" };
      const method = String(next.method || "GET").toUpperCase();
      if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
        const headers = new Headers(next.headers || {});
        const csrf = readCookie("printlab_csrf");
        if (csrf && !headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", csrf);
        next.headers = headers;
      }
      return nativeFetch(input, next);
    };

    function applyTheme(theme) {
      const nextTheme = theme === "dark" ? "dark" : "light";
      document.documentElement.dataset.theme = nextTheme;
      localStorage.setItem("printlab-theme", nextTheme);
      const toggle = document.getElementById("themeToggle");
      if (toggle) toggle.textContent = nextTheme === "dark" ? "Light" : "Dark";
      const meta = document.getElementById("themeColorMeta");
      if (meta) meta.setAttribute("content", nextTheme === "dark" ? "#101925" : "#cfe2f7");
    }

    function toggleTheme() {
      applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    }

    function openSidebar() {
      document.getElementById("sidebar").classList.add("open");
      document.getElementById("sidebarBackdrop").classList.add("open");
      document.getElementById("sidebar").setAttribute("aria-hidden", "false");
    }

    function closeSidebar() {
      document.getElementById("sidebar").classList.remove("open");
      document.getElementById("sidebarBackdrop").classList.remove("open");
      document.getElementById("sidebar").setAttribute("aria-hidden", "true");
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>\"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[char]));
    }

    function formatBytes(size) {
      const value = Number(size);
      if (!Number.isFinite(value) || value < 0) return "-";
      if (value < 1024) return `${value} B`;
      if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
      return `${(value / (1024 * 1024)).toFixed(2)} MB`;
    }

    function fileExtension(name) {
      const lowered = String(name || "").toLowerCase();
      if (lowered.endsWith(".gcode.3mf")) return "3mf";
      const parts = String(name || "").toLowerCase().split(".");
      return parts.length > 1 ? parts.pop() : "";
    }

    function updateFileSummary() {
      const files = Array.from(document.getElementById("fileInput").files || []);
      const first = files[0] || null;
      const totalBytes = files.reduce((sum, file) => sum + Number(file.size || 0), 0);
      document.getElementById("fileName").textContent = !files.length
        ? "No file selected"
        : (files.length === 1 ? first.name : `${files.length} files selected`);
      document.getElementById("detectedSource").textContent = !first
        ? "-"
        : (files.length === 1 ? (fileExtension(first.name) || "Unknown") : "Mixed / batch");
      document.getElementById("fileSize").textContent = files.length ? formatBytes(totalBytes) : "-";
      document.getElementById("convertBtn").textContent = files.length > 1 ? "Convert Files" : "Convert File";
      renderFormatCapabilities();
    }

    function setStatus(message) {
      document.getElementById("status").textContent = message;
    }

    function renderFormatOptions() {
      const target = document.getElementById("targetFormat");
      const source = document.getElementById("sourceFormat");
      const list = document.getElementById("formatList");
      const commonList = document.getElementById("commonConversionList");
      const targetQuickPicks = document.getElementById("targetQuickPicks");
      target.innerHTML = supportedFormats.target_formats.map((item) => (
        `<option value="${escapeHtml(item.id)}"${item.id === supportedFormats.recommended_target ? " selected" : ""}>${escapeHtml(item.label)}${item.recommended ? " - Recommended" : ""}</option>`
      )).join("");
      source.innerHTML = `<option value="">Auto detect</option>${supportedFormats.source_formats.map((item) => (
        `<option value="${escapeHtml(item)}">${escapeHtml(item.toUpperCase())}</option>`
      )).join("")}`;
      list.innerHTML = [
        ...supportedFormats.target_formats.map((item) => `
          <article class="format-chip">
            <strong>${escapeHtml(item.label)}</strong>
            <div class="status-line">${escapeHtml(item.description || "Mesh conversion target.")}</div>
          </article>
        `),
      ].join("");
      commonList.innerHTML = (supportedFormats.common_conversions || []).map((item) => `
        <article class="stat">
          <strong>${escapeHtml(item.label || `${item.source || ""} to ${item.target || ""}`)}</strong>
          <div class="status-line">${escapeHtml(item.note || "Mesh conversion workflow.")}</div>
        </article>
      `).join("");
      targetQuickPicks.innerHTML = (supportedFormats.target_formats || []).map((item) => `
        <button class="target-chip ${item.id === target.value ? "active" : ""}" type="button" data-target-id="${escapeHtml(item.id)}">
          <span class="target-chip-label">${escapeHtml(item.label)}</span>
          <span class="target-chip-note">${escapeHtml(item.recommended ? "Recommended default target" : (item.preserves_scene ? "Keeps scene/material structure" : "Geometry-first export"))}</span>
        </button>
      `).join("");
      targetQuickPicks.querySelectorAll(".target-chip").forEach((button) => {
        button.addEventListener("click", () => {
          target.value = button.dataset.targetId || supportedFormats.recommended_target || "obj";
          renderFormatOptions();
        });
      });
      renderFormatCapabilities();
    }

    function renderFormatCapabilities() {
      const selectedTarget = document.getElementById("targetFormat")?.value || supportedFormats.recommended_target || "obj";
      const forcedSource = document.getElementById("sourceFormat")?.value || "";
      const files = Array.from(document.getElementById("fileInput").files || []);
      const detected = forcedSource || (files[0] ? fileExtension(files[0].name) : "");
      const targetMeta = (supportedFormats.target_details || supportedFormats.target_formats || []).find((item) => item.id === selectedTarget) || null;
      const sourceMeta = (supportedFormats.source_details || []).find((item) => item.id === detected) || null;
      const capability = document.getElementById("formatCapabilities");
      const warningsBox = document.getElementById("formatWarnings");
      if (!capability || !warningsBox) return;

      capability.innerHTML = `
        <strong>${escapeHtml((targetMeta?.label || selectedTarget || "Target").toUpperCase())} capabilities</strong>
        <div class="status-line">${escapeHtml(targetMeta?.description || "Mesh export target.")}</div>
        <div class="status-line">Scene preservation: ${targetMeta?.preserves_scene ? "Yes" : "No"}</div>
        <div class="status-line">Materials/textures: ${targetMeta?.preserves_materials ? "Preserved when scene export succeeds" : "Flattened or discarded"}</div>
        <div class="status-line">UV generation: ${targetMeta?.generates_uvs ? "Generated for OBJ when needed" : "Not added automatically"}</div>
        <div class="status-line">Source profile: ${escapeHtml(sourceMeta ? `${sourceMeta.label} (${sourceMeta.kind}) - ${sourceMeta.notes}` : "Choose a file to see source-specific notes.")}</div>
      `;

      const warnings = [
        ...(targetMeta?.warnings || []),
        ...(sourceMeta && sourceMeta.kind === "scene" && !targetMeta?.preserves_scene ? ["Scene hierarchy will be flattened for this export."] : []),
      ];
      warningsBox.textContent = warnings.length ? warnings.join(" ") : "No special warnings for this source/target combination.";
    }

    async function loadFormats() {
      try {
        const response = await fetch("/api/conversion/formats");
        const data = await response.json();
        if (!response.ok) throw new Error(data?.detail?.message || data?.error?.message || `HTTP ${response.status}`);
        supportedFormats = data;
        renderFormatOptions();
        setStatus("Ready. Choose a source file and convert it. OBJ exports generate UVs automatically when needed.");
      } catch (error) {
        renderFormatOptions();
        setStatus(`Using built-in format list. Live refresh failed: ${String(error?.message || error)}`);
      }
    }

    function resetConverter() {
      document.getElementById("fileInput").value = "";
      document.getElementById("sourceFormat").value = "";
      document.getElementById("targetFormat").value = supportedFormats.recommended_target || "obj";
      document.getElementById("resultCard").classList.remove("open");
      document.getElementById("batchResultCard").classList.remove("open");
      document.getElementById("downloadLink").removeAttribute("href");
      document.getElementById("resultUv").textContent = "-";
      updateFileSummary();
      setStatus("Ready for another conversion.");
    }

    async function fileToBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const result = String(reader.result || "");
          const marker = "base64,";
          const index = result.indexOf(marker);
          resolve(index >= 0 ? result.slice(index + marker.length) : result);
        };
        reader.onerror = () => reject(reader.error || new Error("Failed to read file."));
        reader.readAsDataURL(file);
      });
    }

    async function convertFile() {
      const files = Array.from(document.getElementById("fileInput").files || []);
      if (!files.length) {
        setStatus("Choose a file first.");
        return;
      }
      if (files.some((file) => file.size > 40 * 1024 * 1024)) {
        setStatus("The current limit is 40 MB per file.");
        return;
      }

      const button = document.getElementById("convertBtn");
      button.disabled = true;
      setStatus(`Reading ${files.length === 1 ? files[0].name : `${files.length} files`}...`);
      try {
        if (files.length > 1) {
          const items = await Promise.all(files.map(async (file) => ({
            filename: file.name,
            content_base64: await fileToBase64(file),
            target_format: document.getElementById("targetFormat").value,
            source_format: document.getElementById("sourceFormat").value || null
          })));
          setStatus(`Converting ${files.length} files to ${document.getElementById("targetFormat").value.toUpperCase()}...`);
          const response = await fetch("/api/conversion/batch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ items })
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data?.detail?.message || data?.error?.message || `HTTP ${response.status}`);
          document.getElementById("resultCard").classList.remove("open");
          document.getElementById("batchResultCard").classList.add("open");
          document.getElementById("batchResultList").innerHTML = (data.items || []).map((item) => `
            <article class="stat">
              <strong>${escapeHtml(item.filename || "File")}</strong>
              <div class="status-line">${escapeHtml(item.ok ? `${String(item.target_format || "").toUpperCase()} ready` : `Failed: ${item.error || "Unknown error"}`)}</div>
              ${item.ok ? `<div class="status-line">${escapeHtml(item.uv_generated ? (item.simplified_for_uv ? "UVs generated after simplification." : "UVs generated for OBJ export.") : (item.scene_preserved ? "Scene/material structure preserved." : "Geometry export completed."))}</div>` : ""}
              ${item.ok ? `<a class="download-link" href="${escapeHtml(item.download_url || "#")}" download="${escapeHtml(item.output_filename || "converted-model")}">Download</a>` : ""}
            </article>
          `).join("");
          const okCount = (data.items || []).filter((item) => item.ok).length;
          setStatus(`Converted ${okCount} of ${files.length} files.`);
          return;
        }

        const file = files[0];
        const contentBase64 = await fileToBase64(file);
        setStatus(`Converting ${file.name} to ${document.getElementById("targetFormat").value.toUpperCase()}...`);
        const response = await fetch("/api/conversion", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            filename: file.name,
            content_base64: contentBase64,
            target_format: document.getElementById("targetFormat").value,
            source_format: document.getElementById("sourceFormat").value || null
          })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data?.detail?.message || data?.error?.message || `HTTP ${response.status}`);
        document.getElementById("batchResultCard").classList.remove("open");
        document.getElementById("resultCard").classList.add("open");
        document.getElementById("resultName").textContent = data.output_filename || "-";
        document.getElementById("resultFormat").textContent = (data.target_format || "-").toUpperCase();
        document.getElementById("resultSize").textContent = formatBytes(data.output_size);
        document.getElementById("resultUv").textContent = data.target_format === "obj"
          ? (
              data.uv_generated
                ? (data.simplified_for_uv ? "Generated after simplifying dense mesh" : "Generated for OBJ export")
                : "Already present on source mesh"
            )
          : (data.scene_preserved ? "Scene/material structure preserved" : "Not required for this export");
        const link = document.getElementById("downloadLink");
        link.href = data.download_url || "#";
        link.download = data.output_filename || "converted-model";
        setStatus(
          data.target_format === "obj" && data.uv_generated
            ? `Converted ${file.name} to OBJ and generated UVs automatically${data.simplified_for_uv ? " after simplifying the mesh for unwrap speed" : ""}.`
            : `Converted ${file.name} from ${(data.source_format || "unknown").toUpperCase()} to ${(data.target_format || "unknown").toUpperCase()}.`
        );
      } catch (error) {
        setStatus(`Conversion failed: ${String(error?.message || error)}`);
      } finally {
        button.disabled = false;
      }
    }

    document.getElementById("fileInput").addEventListener("change", updateFileSummary);
    document.getElementById("targetFormat").addEventListener("change", renderFormatCapabilities);
    document.getElementById("sourceFormat").addEventListener("change", renderFormatCapabilities);
    document.getElementById("themeToggle").addEventListener("click", toggleTheme);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeSidebar();
    });
    applyTheme(document.documentElement.dataset.theme);
    renderFormatOptions();
    updateFileSummary();
    loadFormats();
  </script>
</body>
</html>""".replace("__DEFAULT_SUPPORTED_FORMATS__", json.dumps(initial_formats)).replace("__TARGET_OPTIONS__", target_options_html).replace("__SOURCE_OPTIONS__", source_options_html)


def render_printer_dashboard(printer_id: str) -> str:
    service = service_or_404(printer_id)
    injected = (
        "<script>"
        f"window.PRINTER_ID={json.dumps(printer_id)};"
        f"window.PRINTER_NAME={json.dumps(service.display_name)};"
        "</script>"
    )
    return dashboard_html_template.replace("<script>", f"{injected}<script>", 1)
