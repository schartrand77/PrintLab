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
  <title>PrintLab - Printers</title>
  <style>
    body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; margin:0; background:#e6f0fb; color:#213245; }
    .wrap { max-width:1100px; margin:0 auto; padding:24px 16px 40px; }
    .top-row { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:14px; }
    .title-block { display:grid; gap:8px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; }
    .card { background:#fff; border-radius:16px; padding:14px; box-shadow:0 10px 30px rgba(42,90,138,.16); }
    .card a { color:inherit; text-decoration:none; display:block; }
    .printer-art { width:100%; height:150px; object-fit:contain; background:rgba(255,255,255,.72); border-radius:12px; display:block; }
    .name { margin:12px 0 0; font-size:20px; }
    .meta { color:#5d738a; font-size:13px; }
    .badge { display:inline-block; margin-top:8px; padding:4px 8px; border-radius:999px; font-size:12px; }
    .ok { background:#e5f7ee; color:#2f8b56; }
    .bad { background:#fdeceb; color:#a0413b; }
    .hamburger { border:0; border-radius:10px; background:#1f4f7b; color:#fff; cursor:pointer; width:42px; height:34px; display:grid; place-items:center; box-shadow:0 8px 22px rgba(22,54,86,.34); }
    .hamburger-lines { width:16px; height:12px; position:relative; }
    .hamburger-lines::before, .hamburger-lines::after, .hamburger-lines span { content:""; position:absolute; left:0; right:0; height:2px; background:#fff; border-radius:2px; }
    .hamburger-lines::before { top:0; }
    .hamburger-lines span { top:5px; }
    .hamburger-lines::after { top:10px; }
    .sidebar-backdrop { position:fixed; inset:0; background:rgba(18,34,52,.36); display:none; z-index:40; }
    .sidebar-backdrop.open { display:block; }
    .sidebar { position:fixed; z-index:41; top:0; left:0; height:100vh; width:320px; max-width:85vw; background:linear-gradient(180deg, #f4f8fc 0%, #eaf2fb 100%); border-right:1px solid #cfe0f3; box-shadow:18px 0 30px rgba(21,50,80,.18); transform:translateX(-101%); transition:transform .18s ease; padding:18px 14px 16px; overflow:auto; }
    .sidebar.open { transform:translateX(0); }
    .sidebar-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
    .sidebar-close { border:0; background:transparent; color:#365877; cursor:pointer; font-size:20px; line-height:1; padding:2px 4px; }
    .sidebar h2 { margin:0; font-size:20px; }
    .sidebar p { color:#5d738a; font-size:13px; line-height:1.4; }
    .sidebar-tabs { display:grid; gap:8px; margin:0 0 12px; }
    .sidebar-tab { display:block; text-decoration:none; border:1px solid #bdd2e8; background:#edf4fb; color:#375a79; border-radius:999px; padding:6px 10px; font-size:12px; font-weight:600; text-align:left; }
    .sidebar-tab:hover { background:#e3eef9; }
  </style>
</head>
<body>
  <div id="sidebarBackdrop" class="sidebar-backdrop" onclick="closeSidebar()"></div>
  <aside id="sidebar" class="sidebar" aria-hidden="true">
    <div class="sidebar-head">
      <h2>PrintLab</h2>
      <button class="sidebar-close" type="button" aria-label="Close menu" onclick="closeSidebar()">&times;</button>
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
  <title>PrintLab - Add Printer</title>
  <style>
    body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; margin:0; background:#e6f0fb; color:#213245; }
    .wrap { max-width:1100px; margin:0 auto; padding:24px 16px 40px; }
    .top-row { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:14px; }
    .title-block { display:grid; gap:8px; }
    .hamburger { border:0; border-radius:10px; background:#1f4f7b; color:#fff; cursor:pointer; width:42px; height:34px; display:grid; place-items:center; box-shadow:0 8px 22px rgba(22,54,86,.34); }
    .hamburger-lines { width:16px; height:12px; position:relative; }
    .hamburger-lines::before, .hamburger-lines::after, .hamburger-lines span { content:""; position:absolute; left:0; right:0; height:2px; background:#fff; border-radius:2px; }
    .hamburger-lines::before { top:0; }
    .hamburger-lines span { top:5px; }
    .hamburger-lines::after { top:10px; }
    .sidebar-backdrop { position:fixed; inset:0; background:rgba(18,34,52,.36); display:none; z-index:40; }
    .sidebar-backdrop.open { display:block; }
    .sidebar { position:fixed; z-index:41; top:0; left:0; height:100vh; width:320px; max-width:85vw; background:linear-gradient(180deg, #f4f8fc 0%, #eaf2fb 100%); border-right:1px solid #cfe0f3; box-shadow:18px 0 30px rgba(21,50,80,.18); transform:translateX(-101%); transition:transform .18s ease; padding:18px 14px 16px; overflow:auto; }
    .sidebar.open { transform:translateX(0); }
    .sidebar-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
    .sidebar-close { border:0; background:transparent; color:#365877; cursor:pointer; font-size:20px; line-height:1; padding:2px 4px; }
    .sidebar h2 { margin:0; font-size:20px; }
    .sidebar p { color:#5d738a; font-size:13px; line-height:1.4; }
    .sidebar-tabs { display:grid; gap:8px; margin:0 0 12px; }
    .sidebar-tab { display:block; text-decoration:none; border:1px solid #bdd2e8; background:#edf4fb; color:#375a79; border-radius:999px; padding:6px 10px; font-size:12px; font-weight:600; text-align:left; }
    .sidebar-tab.active { background:#1f4f7b; border-color:#1f4f7b; color:#fff; }
    .layout { display:grid; gap:16px; }
    .panel { background:#fff; border-radius:16px; padding:18px; box-shadow:0 10px 30px rgba(42,90,138,.16); }
    .panel h2 { margin:0 0 8px; }
    .panel p { margin:0 0 14px; color:#5d738a; }
    .form-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px; }
    .field label { display:block; font-size:12px; color:#496986; margin-bottom:4px; }
    .field input { width:100%; box-sizing:border-box; border:1px solid #c4d9ee; border-radius:10px; padding:10px; font-size:14px; background:#fff; }
    .check-row { display:flex; gap:14px; flex-wrap:wrap; margin-top:6px; }
    .check { display:flex; align-items:center; gap:8px; font-size:13px; color:#2f4f6d; }
    .actions { display:flex; gap:8px; margin-top:14px; }
    .btn { border:0; border-radius:10px; padding:10px 14px; cursor:pointer; font-weight:600; }
    .btn-primary { background:#1f4f7b; color:#fff; }
    .btn-light { background:#dbe9f7; color:#244563; }
    .status { min-height:18px; margin-top:10px; color:#496986; font-size:12px; }
    .status.error { color:#8f3d36; }
    .printer-list { display:grid; gap:10px; margin-top:14px; }
    .printer-item { border:1px solid #d6e4f2; border-radius:12px; padding:12px; background:#f9fcff; }
    .printer-item-head { display:flex; justify-content:space-between; gap:8px; align-items:flex-start; }
    .printer-name { margin:0; font-size:18px; }
    .printer-meta { color:#5d738a; font-size:13px; margin-top:4px; }
    .badge { display:inline-block; padding:4px 8px; border-radius:999px; font-size:12px; }
    .ok { background:#e5f7ee; color:#2f8b56; }
    .bad { background:#fdeceb; color:#a0413b; }
  </style>
</head>
<body>
  <div id="sidebarBackdrop" class="sidebar-backdrop" onclick="closeSidebar()"></div>
  <aside id="sidebar" class="sidebar" aria-hidden="true">
    <div class="sidebar-head">
      <h2>PrintLab</h2>
      <button class="sidebar-close" type="button" aria-label="Close menu" onclick="closeSidebar()">&times;</button>
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
        <h2>New Printer</h2>
        <p>Fill in the printer connection details.</p>
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
          <button class="btn btn-primary" type="button" onclick="submitAddPrinter()">Add Printer</button>
          <button class="btn btn-light" type="button" onclick="resetAddPrinterForm()">Clear</button>
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

    function resetAddPrinterForm() {
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

    async function loadPrinters() {
      const response = await fetch('/api/printers');
      const data = await response.json();
      const items = data.items || [];
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
        </article>
      `).join('');
    }

    async function submitAddPrinter() {
      const payload = {
        id: document.getElementById('printerId').value.trim() || null,
        name: document.getElementById('printerName').value.trim(),
        host: document.getElementById('printerHost').value.trim(),
        serial: document.getElementById('printerSerial').value.trim(),
        access_code: document.getElementById('printerAccessCode').value.trim(),
        local_mqtt: document.getElementById('printerLocalMqtt').checked,
        enable_camera: document.getElementById('printerEnableCamera').checked,
        disable_ssl_verify: document.getElementById('printerDisableSslVerify').checked
      };
      if (!payload.name || !payload.host || !payload.serial || !payload.access_code) {
        setPageStatus('Name, host, serial, and access code are required.', true);
        return;
      }
      try {
        const response = await fetch('/api/printers', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail || `HTTP ${response.status}`);
        }
        setPageStatus(`Added printer ${data?.printer?.name || payload.name}.`);
        resetAddPrinterForm();
        await loadPrinters();
      } catch (error) {
        setPageStatus(String(error?.message || error), true);
      }
    }

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
