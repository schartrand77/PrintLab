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
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; }
    .card { background:var(--card); border-radius:16px; padding:14px; box-shadow:var(--card-shadow); }
    .card a { color:inherit; text-decoration:none; display:block; }
    .printer-art { width:100%; height:150px; object-fit:contain; background:rgba(255,255,255,.72); border-radius:12px; display:block; }
    .name { margin:12px 0 0; font-size:20px; }
    .meta { color:var(--muted); font-size:13px; }
    .badge { display:inline-block; margin-top:8px; padding:4px 8px; border-radius:999px; font-size:12px; }
    .ok { background:#e5f7ee; color:#2f8b56; }
    .bad { background:#fdeceb; color:#a0413b; }
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

    async function loadPrinters() {
      const response = await fetch('/api/printers');
      const data = await response.json();
      cards.innerHTML = (data.items || []).map((item) => `
        <div class="card">
          <a href="/printer/${encodeURIComponent(item.id)}">
            <img class="printer-art" src="/static/printers/x1c.jpg" alt="Bambu Lab X1C printer">
            <h2 class="name">${escapeHtml(item.name)}</h2>
            <div class="meta">${escapeHtml(item.device_type || 'Unknown device')}</div>
            <div class="badge ${item.connected ? 'ok' : 'bad'}">${item.connected ? 'Connected' : 'Offline'}</div>
          </a>
        </div>
      `).join('');
    }

    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
      themeToggle.addEventListener('click', toggleTheme);
    }
    applyTheme(document.documentElement.dataset.theme);
    loadPrinters();
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


def render_printer_dashboard(printer_id: str) -> str:
    service = service_or_404(printer_id)
    injected = (
        "<script>"
        f"window.PRINTER_ID={json.dumps(printer_id)};"
        f"window.PRINTER_NAME={json.dumps(service.display_name)};"
        "</script>"
    )
    return dashboard_html_template.replace("<script>", f"{injected}<script>", 1)
