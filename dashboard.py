#!/usr/bin/env python3

import datetime as dt
import html
import json
import os
import re
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_FILE = os.environ.get("DASHBOARD_CONFIG_FILE", os.path.join(SCRIPT_DIR, "dashboard.conf"))


def load_config_file(path):
  config = {}
  if not os.path.exists(path):
    return config

  with open(path, encoding="utf-8") as handle:
    for line_number, raw_line in enumerate(handle, start=1):
      stripped = raw_line.strip()
      if not stripped or stripped.startswith("#"):
        continue
      if "=" not in raw_line:
        raise RuntimeError(f"Invalid config line {line_number} in {path}: expected KEY=VALUE")

      key, value = raw_line.split("=", 1)
      key = key.strip()
      value = value.strip()

      if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
        value = value[1:-1]

      config[key] = value

  return config


FILE_CONFIG = load_config_file(DEFAULT_CONFIG_FILE)


def get_config(name, default):
  return os.environ.get(name, FILE_CONFIG.get(name, default))


PROXMOX_BASE_URL = get_config("PROXMOX_BASE_URL", "https://proxmox.example.com:8006")
PROXMOX_TOKEN_ID = get_config("PROXMOX_TOKEN_ID", "")
PROXMOX_TOKEN_SECRET = get_config("PROXMOX_TOKEN_SECRET", "")
PROXMOX_VERIFY_TLS = get_config("PROXMOX_VERIFY_TLS", "true").lower() not in {"0", "false", "no"}
API_TIMEOUT_SECONDS = float(get_config("PROXMOX_API_TIMEOUT", "8"))
HOST = get_config("DASHBOARD_HOST", "0.0.0.0")
PORT = int(get_config("DASHBOARD_PORT", "8080"))
REFRESH_SECONDS = int(get_config("DASHBOARD_REFRESH_SECONDS", "15"))
DEFAULT_IP_FILTER = get_config("DASHBOARD_DEFAULT_IP_FILTER", "")

IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Proxmox Simple Dashboard</title>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <style>
    :root {
      --bg: #1a1d2e;
      --bg-alt: #151827;
      --panel: #202437;
      --panel-alt: #232842;
      --panel-strong: #171b2b;
      --text: #ffffff;
      --muted: #8892a4;
      --line: #2a2d42;
      --cyan: #00bcd4;
      --purple: #9b59f5;
      --blue: #2a6bdb;
      --radius: 16px;
      --radius-sm: 12px;
      --shadow: 0 16px 32px rgba(0, 0, 0, 0.28);
      --sans: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
      --mono: "IBM Plex Mono", "SFMono-Regular", Consolas, monospace;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: var(--sans);
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(0, 188, 212, 0.12), transparent 24%),
        radial-gradient(circle at top right, rgba(155, 89, 245, 0.14), transparent 28%),
        linear-gradient(180deg, #1b2033 0%, var(--bg) 52%, var(--bg-alt) 100%);
    }

    .shell {
      max-width: 1320px;
      margin: 0 auto;
      padding: 24px 18px 32px;
    }

    .stack {
      display: grid;
      gap: 16px;
    }

    .panel,
    .stat,
    .board {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: rgba(32, 36, 55, 0.96);
      box-shadow: var(--shadow);
    }

    .header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-end;
      padding: 12px 14px;
    }

    .header-brand {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .header-logo {
      display: block;
      border-radius: 8px;
      flex: 0 0 auto;
    }

    .eyebrow {
      margin: 0 0 4px;
      color: var(--cyan);
      font-size: 0.66rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }

    .title {
      margin: 0;
      font-size: clamp(1.45rem, 2.8vw, 2rem);
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 1.02;
    }

    .subtitle {
      margin: 4px 0 0;
      max-width: 48rem;
      color: var(--muted);
      font-size: 0.8rem;
      line-height: 1.4;
    }

    .meta {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 10px;
    }

    .meta-item {
      padding: 0.36rem 0.64rem;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel-alt);
      color: var(--muted);
      font-size: 0.74rem;
      white-space: nowrap;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }

    .stat {
      padding: 12px;
      display: grid;
      gap: 10px;
      min-height: 128px;
    }

    .stat-top {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
    }

    .label {
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 0.74rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }

    .metric {
      display: block;
      font-size: clamp(1.8rem, 3vw, 2.5rem);
      font-weight: 700;
      line-height: 1;
      letter-spacing: -0.04em;
    }

    .metric-sub {
      color: var(--muted);
      font-size: 0.8rem;
      white-space: nowrap;
    }

    .mini-chart {
      display: grid;
      gap: 8px;
      align-content: end;
      min-height: 58px;
    }

    .chart-note {
      color: var(--muted);
      font-size: 0.76rem;
    }

    .area-chart svg {
      display: block;
      width: 100%;
      height: 48px;
    }

    .progress-wrap {
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .ring {
      --percent: 0;
      --accent: var(--cyan);
      position: relative;
      width: 54px;
      height: 54px;
      border-radius: 50%;
      background: conic-gradient(var(--accent) calc(var(--percent) * 1%), rgba(255, 255, 255, 0.08) 0);
      flex: 0 0 auto;
    }

    .ring::before {
      content: "";
      position: absolute;
      inset: 8px;
      border-radius: 50%;
      background: var(--panel);
      border: 1px solid rgba(255, 255, 255, 0.04);
    }

    .ring.donut::before {
      inset: 11px;
    }

    .ring span {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      font-size: 0.72rem;
      font-weight: 700;
      z-index: 1;
    }

    .progress-copy {
      display: grid;
      gap: 4px;
    }

    .progress-copy strong {
      font-size: 1rem;
      font-weight: 700;
    }

    .progress-copy span {
      color: var(--muted);
      font-size: 0.8rem;
    }

    .bar-chart {
      display: grid;
      gap: 10px;
    }

    .bar-row {
      display: grid;
      grid-template-columns: 56px minmax(0, 1fr) 30px;
      gap: 8px;
      align-items: center;
      font-size: 0.8rem;
    }

    .bar-label,
    .bar-value {
      color: var(--muted);
      font-family: var(--mono);
      font-size: 0.76rem;
    }

    .bar-track {
      height: 7px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.06);
      overflow: hidden;
    }

    .bar-fill {
      display: block;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--blue), var(--cyan));
    }

    .error {
      padding: 12px 14px;
      border-left: 3px solid var(--purple);
      border-radius: var(--radius-sm);
      background: rgba(155, 89, 245, 0.12);
      color: var(--text);
      font-size: 0.9rem;
    }

    .board {
      overflow: visible;
    }

    .node-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(520px, 1fr));
      gap: 12px;
      padding: 12px;
    }

    .node-card {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: rgba(23, 27, 43, 0.72);
      overflow: visible;
    }

    .node-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      background: rgba(35, 40, 66, 0.78);
    }

    .node-head h3 {
      margin: 0;
      font-size: 0.82rem;
      font-weight: 700;
      letter-spacing: -0.01em;
    }

    .node-summary {
      color: var(--muted);
      font-size: 0.68rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .board-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
    }

    .board-copy h2 {
      margin: 0;
      font-size: 0.88rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }

    .board-note {
      display: block;
      margin-top: 2px;
      color: var(--muted);
      font-size: 0.72rem;
    }

    .board-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    .board-tools {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }

    .filter-summary,
    .status-legend,
    .clear-filters {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel-alt);
      color: var(--muted);
      font-size: 0.68rem;
    }

    .filter-summary {
      padding: 0.28rem 0.52rem;
      font-family: var(--mono);
    }

    .status-legend {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.28rem 0.52rem;
    }

    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 0.28rem;
      white-space: nowrap;
    }

    .clear-filters {
      padding: 0.28rem 0.58rem;
      color: var(--text);
      font: inherit;
      font-size: 0.68rem;
      cursor: pointer;
    }

    .clear-filters:hover,
    .clear-filters:focus-visible {
      border-color: rgba(0, 188, 212, 0.45);
      color: #ffffff;
      outline: none;
    }

    .control-group {
      display: grid;
      gap: 4px;
      min-width: 220px;
    }

    .control-label {
      color: var(--muted);
      font-size: 0.64rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .control-hint {
      color: var(--muted);
      font-size: 0.68rem;
      line-height: 1.35;
    }

    .filter-input {
      min-width: 220px;
      padding: 0.34rem 0.58rem;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel-alt);
      color: var(--text);
      font: inherit;
      font-size: 0.72rem;
    }

    .filter-input::placeholder {
      color: var(--muted);
    }

    .filter-input:focus {
      outline: none;
      border-color: rgba(0, 188, 212, 0.45);
      box-shadow: 0 0 0 2px rgba(0, 188, 212, 0.12);
    }

    .toggle-control {
      display: inline-flex;
      align-items: center;
      gap: 0.52rem;
      padding-top: 1rem;
      color: var(--text);
      font-size: 0.74rem;
      white-space: nowrap;
    }

    .toggle-input {
      width: 0.95rem;
      height: 0.95rem;
      margin: 0;
      accent-color: var(--cyan);
      cursor: pointer;
    }

    .table-wrap {
      min-width: 0;
      overflow: visible;
    }

    .node-card .table-wrap {
      overflow: visible;
    }

    table {
      width: 100%;
      min-width: 0;
      table-layout: fixed;
      border-collapse: collapse;
    }

    .node-card table {
      min-width: 0;
    }

    thead th {
      padding: 0;
      border-bottom: 1px solid var(--line);
      background: var(--panel-strong);
      text-align: left;
      vertical-align: middle;
    }

    .table-head-label {
      display: block;
      padding: 7px 10px;
      color: var(--muted);
      font-size: 0.67rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    tbody td {
      padding: 6px 8px;
      border-bottom: 1px solid var(--line);
      font-size: 0.8rem;
      vertical-align: middle;
      line-height: 1.15;
      overflow-wrap: anywhere;
    }

    tbody tr:hover {
      background: rgba(42, 107, 219, 0.08);
    }

    tbody td:first-child {
      font-weight: 600;
      letter-spacing: -0.01em;
    }

    tbody tr[data-running="0"] td {
      opacity: 0.72;
    }

    tbody tr[data-running="0"] td:first-child {
      border-left: 2px solid rgba(136, 146, 164, 0.32);
    }

    tbody tr[data-running="1"] td:first-child {
      border-left: 2px solid rgba(0, 188, 212, 0.42);
    }

    th:nth-child(1) { width: 42%; }
    th:nth-child(2) { width: 13%; }
    th:nth-child(3) { width: 13%; }
    th:nth-child(4) { width: 10%; }
    th:nth-child(5) { width: 22%; }

    tbody td:nth-child(2),
    tbody td:nth-child(3) {
      color: var(--muted);
    }

    .status-head,
    .status-cell {
      text-align: center;
      width: 40px;
    }

    .status-head .table-head-label {
      padding-left: 0;
      padding-right: 0;
      text-align: center;
    }

    .type-pill {
      display: inline-flex;
      align-items: center;
      gap: 0.34rem;
      padding: 0.18rem 0.42rem;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--text);
      font-size: 0.68rem;
      line-height: 1;
      white-space: nowrap;
    }

    .type-pill-vm {
      border-color: rgba(42, 107, 219, 0.28);
      background: rgba(42, 107, 219, 0.16);
      color: #dbe7ff;
    }

    .type-pill-lxc {
      border-color: rgba(0, 188, 212, 0.28);
      background: rgba(0, 188, 212, 0.12);
      color: #d8fbff;
    }

    .type-pill-unknown {
      border-color: rgba(136, 146, 164, 0.24);
      background: rgba(136, 146, 164, 0.12);
    }

    .type-icon {
      width: 0.78rem;
      height: 0.78rem;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
    }

    .type-icon svg {
      width: 100%;
      height: 100%;
      display: block;
    }

    .status {
      display: inline-block;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--muted);
    }

    .status-running {
      background: var(--cyan);
      box-shadow: 0 0 0 3px rgba(0, 188, 212, 0.14);
    }

    .status-paused {
      background: var(--purple);
      box-shadow: 0 0 0 3px rgba(155, 89, 245, 0.14);
    }

    .status-stopped {
      background: #8892a4;
      box-shadow: 0 0 0 3px rgba(136, 146, 164, 0.12);
    }

    .status-unknown,
    .status-error {
      background: var(--blue);
      box-shadow: 0 0 0 3px rgba(42, 107, 219, 0.14);
    }

    .ips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .ip {
      padding: 0.14rem 0.38rem;
      border: 1px solid rgba(42, 107, 219, 0.24);
      border-radius: 999px;
      background: rgba(42, 107, 219, 0.14);
      color: #dbe7ff;
      font-family: var(--mono);
      font-size: 0.68rem;
      white-space: nowrap;
      cursor: pointer;
      appearance: none;
      transition: border-color 120ms ease, background-color 120ms ease, color 120ms ease;
    }

    .ip:hover,
    .ip:focus-visible {
      border-color: rgba(0, 188, 212, 0.4);
      background: rgba(0, 188, 212, 0.16);
      outline: none;
    }

    .ip.copied {
      border-color: rgba(0, 188, 212, 0.48);
      background: rgba(0, 188, 212, 0.22);
      color: #ffffff;
    }

    .ip.copied::after {
      content: " copied";
      color: var(--cyan);
    }

    .hint {
      color: var(--muted);
      font-size: 0.8rem;
    }

    .ip-count {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: 0.2rem;
      padding-bottom: 1px;
      border-bottom: 1px dotted rgba(136, 146, 164, 0.72);
      color: var(--muted);
      font-family: var(--mono);
      font-size: 0.72rem;
      letter-spacing: 0.02em;
      cursor: help;
    }

    .ip-count::before {
      content: "i";
      display: inline-grid;
      place-items: center;
      width: 0.82rem;
      height: 0.82rem;
      border: 1px solid rgba(136, 146, 164, 0.42);
      border-radius: 999px;
      color: var(--cyan);
      font-family: var(--sans);
      font-size: 0.58rem;
      line-height: 1;
    }

    .ip-count:focus-visible {
      outline: none;
    }

    .ip-tooltip {
      position: absolute;
      left: 0;
      top: calc(100% + 8px);
      min-width: max-content;
      max-width: 260px;
      padding: 0.45rem 0.55rem;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel-strong);
      color: var(--text);
      font-family: var(--mono);
      font-size: 0.68rem;
      line-height: 1.45;
      white-space: normal;
      box-shadow: var(--shadow);
      opacity: 0;
      pointer-events: none;
      transform: translateY(-4px);
      transition: opacity 120ms ease, transform 120ms ease;
      z-index: 20;
    }

    .ip-count:hover .ip-tooltip,
    .ip-count:focus-visible .ip-tooltip {
      opacity: 1;
      transform: translateY(0);
    }

    .empty {
      padding: 24px 18px;
      text-align: center;
      color: var(--muted);
    }

    .filter-empty:not([hidden]) {
      display: table-row;
    }

    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }

    @media (max-width: 1100px) {
      .stats {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .node-grid {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 860px) {
      .header {
        flex-direction: column;
        align-items: flex-start;
      }

      .meta {
        justify-content: flex-start;
      }
    }

    @media (max-width: 680px) {
      .shell {
        padding: 14px 10px 24px;
      }

      .stats {
        grid-template-columns: 1fr;
      }

      .stat,
      .header,
      .board-head {
        padding: 14px;
      }

      .board-head {
        align-items: flex-start;
        flex-direction: column;
      }

      .board-actions {
        width: 100%;
        justify-content: flex-start;
      }

      .board-tools {
        width: 100%;
      }

      .control-group {
        width: 100%;
      }

      .filter-input {
        min-width: 0;
        width: 100%;
      }

      .toggle-control {
        padding-top: 0.2rem;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="stack">
      <header class="panel header">
        <div class="header-brand">
          <img src="/favicon.svg" alt="" class="header-logo" width="36" height="36">
          <div>
            <p class="eyebrow">Proxmox cluster - __CLUSTER_NAME__</p>
            <h1 class="title">Proxmox Simple Dashboard</h1>
          </div>
        </div>
        <div class="meta">
          <label class="meta-item"><input class="toggle-input" type="checkbox" data-pause-refresh> Pause refresh</label>
          <span class="meta-item">__LAST_UPDATED__</span>
        </div>
      </header>

      <section class="stats" id="stats">
        <article class="stat">
          <div class="stat-top">
            <div>
              <span class="label">Total VMs</span>
              <span class="metric" id="total-vms">__TOTAL_VMS__</span>
            </div>
            <span class="metric-sub">Inventory</span>
          </div>
          __TOTAL_CHART__
        </article>

        <article class="stat">
          <div class="stat-top">
            <div>
              <span class="label">Running</span>
              <span class="metric" id="running-vms">__RUNNING_VMS__</span>
            </div>
            <span class="metric-sub">Online ratio</span>
          </div>
          __RUNNING_CHART__
        </article>

        <article class="stat">
          <div class="stat-top">
            <div>
              <span class="label">With IP</span>
              <span class="metric" id="with-ips">__WITH_IPS__</span>
            </div>
            <span class="metric-sub">Detected IPs</span>
          </div>
          __IP_CHART__
        </article>

        <article class="stat">
          <div class="stat-top">
            <div>
              <span class="label">Nodes</span>
              <span class="metric" id="nodes-count">__NODES_COUNT__</span>
            </div>
            <span class="metric-sub">VMs per node</span>
          </div>
          __NODE_CHART__
        </article>
      </section>

      <div class="error" id="error-box" style="display: __ERROR_DISPLAY__">__ERROR_MESSAGE__</div>

      <section class="board">
        <div class="board-head">
          <div class="board-copy">
            <h2>Machine inventory</h2>
            <span class="board-note">Each node has its own table. Rows stay sorted by status first, then by name.</span>
            <div class="board-tools">
              <span class="filter-summary" data-filter-summary>Showing all machines</span>
              <span class="status-legend" aria-label="Status legend">
                <span class="legend-item"><span class="status status-running"></span> running</span>
                <span class="legend-item"><span class="status status-paused"></span> paused</span>
                <span class="legend-item"><span class="status status-stopped"></span> stopped</span>
              </span>
              <button class="clear-filters" type="button" data-clear-filters>Clear filters</button>
            </div>
          </div>
          <div class="board-actions">
            <label class="control-group">
              <span class="control-label">IP filter</span>
              <input class="filter-input" type="text" data-ip-filter placeholder="IP pattern, e.g. 10.* or 192.168.*">
              <span class="control-hint">Use `*` or `?` to match IPs. Leave it empty to keep the default IP view.</span>
            </label>
            <label class="control-group">
              <span class="control-label">Name filter</span>
              <input class="filter-input" type="text" data-name-filter placeholder="db* or api">
              <span class="control-hint">Case-insensitive name match by plain text or wildcard.</span>
            </label>
            <label class="toggle-control">
              <input class="toggle-input" type="checkbox" data-show-inactive checked>
              <span>Show inactive</span>
            </label>
          </div>
        </div>
        <div class="node-grid">__NODE_TABLES__</div>
      </section>
    </section>
  </main>

  <script>
    (() => {
      const tables = Array.from(document.querySelectorAll("[data-node-table]"));
      const ipFilterInput = document.querySelector("[data-ip-filter]");
      const nameFilterInput = document.querySelector("[data-name-filter]");
      const showInactiveInput = document.querySelector("[data-show-inactive]");
      const pauseRefreshInput = document.querySelector("[data-pause-refresh]");
      const clearFiltersButton = document.querySelector("[data-clear-filters]");
      const filterSummary = document.querySelector("[data-filter-summary]");
      const ipFilterStorageKey = "ip-dashboard-ip-filter";
      const defaultIpFilter = "__DEFAULT_IP_FILTER__";
      const nameFilterStorageKey = "ip-dashboard-name-filter";
      const inactiveStorageKey = "ip-dashboard-show-inactive";
      const pauseRefreshStorageKey = "ip-dashboard-pause-refresh";
      const refreshMs = __REFRESH_SECONDS__ * 1000;
      let refreshTimer = null;

      function loadStoredText(key) {
        try {
          return localStorage.getItem(key) || "";
        } catch {
          return "";
        }
      }

      function saveStoredText(key, value) {
        try {
          if (!value) {
            localStorage.removeItem(key);
            return;
          }
          localStorage.setItem(key, value);
        } catch {
          return;
        }
      }

      function loadStoredFlag(key, fallback) {
        try {
          const value = localStorage.getItem(key);
          if (value === null) {
            return fallback;
          }
          return value !== "0";
        } catch {
          return fallback;
        }
      }

      function saveStoredFlag(key, value) {
        try {
          localStorage.setItem(key, value ? "1" : "0");
        } catch {
          return;
        }
      }

      async function copyText(value) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(value);
          return;
        }

        const field = document.createElement("textarea");
        field.value = value;
        field.setAttribute("readonly", "");
        field.style.position = "absolute";
        field.style.left = "-9999px";
        document.body.appendChild(field);
        field.select();
        document.execCommand("copy");
        document.body.removeChild(field);
      }

      function escapeHtml(value) {
        return String(value)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/\"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }

      function ipListFor(row) {
        return (row.dataset.allIps || "").split(",").filter(Boolean);
      }

      function ipCellFor(row) {
        return row.querySelector(".ip-cell");
      }

      function rowsFor(table) {
        return Array.from(table.querySelectorAll("tr[data-sort-row='1']"));
      }

      function bodyFor(table) {
        return table.querySelector(".vm-table-body");
      }

      function summaryFor(table) {
        return table.querySelector("[data-node-summary]");
      }

      function emptyRowFor(table) {
        return table.querySelector("[data-filter-empty]");
      }

      function wildcardToRegExp(pattern) {
        const escaped = pattern.replace(/[.+^${}()|[\\]\\\\]/g, "\\\\$&");
        const wildcard = escaped.replace(/\\*/g, ".*").replace(/\\?/g, ".");
        return new RegExp(wildcard, "i");
      }

      function renderIpButtons(ips) {
        return '<div class="ips">' + ips.map((ip) => (
          `<button class="ip" type="button" data-copy-ip="${escapeHtml(ip)}" data-copy-label="${escapeHtml(ip)}" title="Copy ${escapeHtml(ip)} to clipboard">${escapeHtml(ip)}</button>`
        )).join("") + '</div>';
      }

      function renderIpCount(ips) {
        const tooltip = ips.map((ip) => escapeHtml(ip)).join("<br>");
        return `<span class="ip-count" tabindex="0">${ips.length} IPs<span class="ip-tooltip">${tooltip}</span></span>`;
      }

      function defaultIpMarkup(row) {
        const ips = ipListFor(row);
        if (!ips.length) {
          return `<span class="hint">${escapeHtml(row.dataset.ipNote || "-")}</span>`;
        }
        if (ips.length === 1) {
          return renderIpButtons(ips);
        }
        return renderIpCount(ips);
      }

      function filteredIpMarkup(row, pattern) {
        const ips = ipListFor(row);
        if (!pattern) {
          return defaultIpMarkup(row);
        }

        if (!ips.length) {
          return defaultIpMarkup(row);
        }

        const regex = wildcardToRegExp(pattern);
        const matches = ips.filter((ip) => regex.test(ip));
        if (!matches.length) {
          return '<span class="hint">no match</span>';
        }
        if (matches.length === 1) {
          return renderIpButtons(matches);
        }
        return renderIpCount(matches);
      }

      function compareText(left, right) {
        return String(left || "").localeCompare(String(right || ""));
      }

      function compareNumber(left, right) {
        if (left === right) {
          return 0;
        }
        return left < right ? -1 : 1;
      }

      function compareRows(leftRow, rightRow) {
        const statusDelta = compareNumber(Number(leftRow.dataset.statusRank), Number(rightRow.dataset.statusRank));
        if (statusDelta) {
          return statusDelta;
        }

        return compareText(leftRow.dataset.name, rightRow.dataset.name) || compareNumber(Number(leftRow.dataset.vmid), Number(rightRow.dataset.vmid));
      }

      function sortRows(table) {
        const body = bodyFor(table);
        const items = rowsFor(table);
        if (!body || !items.length) {
          return;
        }

        items.sort((leftRow, rightRow) => compareRows(leftRow, rightRow));
        items.forEach((row) => body.appendChild(row));
      }

      function applyFilters() {
        const ipPattern = ipFilterInput ? ipFilterInput.value.trim() : "";
        const namePattern = nameFilterInput ? nameFilterInput.value.trim() : "";
        const nameRegex = namePattern ? wildcardToRegExp(namePattern) : null;
        const showInactive = showInactiveInput ? showInactiveInput.checked : true;
        let totalRows = 0;
        let totalVisible = 0;

        tables.forEach((table) => {
          let nodeVisible = 0;
          let nodeHidden = 0;
          let nodeRunningVisible = 0;
          rowsFor(table).forEach((row) => {
            totalRows += 1;
            const cell = ipCellFor(row);
            if (cell) {
              cell.innerHTML = filteredIpMarkup(row, ipPattern);
            }

            const matchesName = !nameRegex || nameRegex.test(row.dataset.name || "");
            const isActive = row.dataset.running === "1";
            const isVisible = matchesName && (showInactive || isActive);
            row.hidden = !isVisible;
            if (isVisible) {
              nodeVisible += 1;
              totalVisible += 1;
              if (isActive) {
                nodeRunningVisible += 1;
              }
            } else {
              nodeHidden += 1;
            }
          });

          const summary = summaryFor(table);
          if (summary) {
            summary.textContent = `${nodeVisible} shown · ${nodeRunningVisible} running${nodeHidden ? ` · ${nodeHidden} hidden` : ""}`;
          }

          const emptyRow = emptyRowFor(table);
          if (emptyRow) {
            emptyRow.hidden = nodeVisible !== 0;
          }
        });

        if (filterSummary) {
          filterSummary.textContent = totalVisible === totalRows ? `Showing all ${totalRows} machines` : `Showing ${totalVisible} of ${totalRows} machines`;
        }
      }

      function clearFilters() {
        if (ipFilterInput) {
          ipFilterInput.value = "";
          saveStoredText(ipFilterStorageKey, "");
        }
        if (nameFilterInput) {
          nameFilterInput.value = "";
          saveStoredText(nameFilterStorageKey, "");
        }
        if (showInactiveInput) {
          showInactiveInput.checked = true;
          saveStoredFlag(inactiveStorageKey, true);
        }
        applyFilters();
      }

      function scheduleRefresh() {
        if (refreshTimer) {
          window.clearTimeout(refreshTimer);
        }
        if (pauseRefreshInput && pauseRefreshInput.checked) {
          return;
        }
        refreshTimer = window.setTimeout(() => window.location.reload(), refreshMs);
      }

      document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-copy-ip]");
        if (!button) {
          return;
        }

        const value = button.dataset.copyIp || "";
        const label = button.dataset.copyLabel || value;
        if (!value) {
          return;
        }

        try {
          await copyText(value);
          button.classList.add("copied");
          button.title = `Copied ${label}`;
          window.setTimeout(() => {
            button.classList.remove("copied");
            button.title = `Copy ${label} to clipboard`;
          }, 900);
        } catch {
          button.classList.add("copied");
          button.title = "Copy failed";
          window.setTimeout(() => {
            button.classList.remove("copied");
            button.title = `Copy ${label} to clipboard`;
          }, 900);
        }
      });

      if (clearFiltersButton) {
        clearFiltersButton.addEventListener("click", clearFilters);
      }

      if (ipFilterInput) {
        const storedIp = loadStoredText(ipFilterStorageKey);
        ipFilterInput.value = storedIp || defaultIpFilter;
        if (!storedIp && defaultIpFilter) {
          saveStoredText(ipFilterStorageKey, defaultIpFilter);
        }
        ipFilterInput.addEventListener("input", () => {
          const value = ipFilterInput.value.trim();
          saveStoredText(ipFilterStorageKey, value);
          applyFilters();
        });
      }

      if (nameFilterInput) {
        nameFilterInput.value = loadStoredText(nameFilterStorageKey);
        nameFilterInput.addEventListener("input", () => {
          const value = nameFilterInput.value.trim();
          saveStoredText(nameFilterStorageKey, value);
          applyFilters();
        });
      }

      if (showInactiveInput) {
        showInactiveInput.checked = loadStoredFlag(inactiveStorageKey, true);
        showInactiveInput.addEventListener("change", () => {
          saveStoredFlag(inactiveStorageKey, showInactiveInput.checked);
          applyFilters();
        });
      }

      if (pauseRefreshInput) {
        pauseRefreshInput.checked = loadStoredFlag(pauseRefreshStorageKey, false);
        pauseRefreshInput.addEventListener("change", () => {
          saveStoredFlag(pauseRefreshStorageKey, pauseRefreshInput.checked);
          scheduleRefresh();
        });
      }

      tables.forEach((table) => {
        sortRows(table);
      });

      applyFilters();
      scheduleRefresh();
    })();
  </script>
</body>
</html>
"""


TABLE_HEAD_HTML = """<thead>
              <tr>
                <th><span class=\"table-head-label\">NAME</span></th>
                <th><span class=\"table-head-label\">VMID</span></th>
                <th><span class=\"table-head-label\">Type</span></th>
                <th class=\"status-head\"><span class=\"table-head-label\">Status</span></th>
                <th><span class=\"table-head-label\">IP</span></th>
              </tr>
            </thead>"""


def build_ssl_context():
    if PROXMOX_VERIFY_TLS:
        return ssl.create_default_context()
    return ssl._create_unverified_context()


SSL_CONTEXT = build_ssl_context()


def is_valid_ipv4(value):
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


def ip_sort_key(value):
    return tuple(int(part) for part in value.split("."))


def primary_ip(item):
  ips = item.get("ips") or []
  return ips[0] if ips else ""


def status_rank(status):
  return {"running": 0, "paused": 1, "stopped": 2}.get(status, 3)


def sort_dashboard_items(items):
  return sorted(
    items,
    key=lambda item: (
      status_rank(item.get("status", "unknown")),
      item.get("name", "").lower(),
      item.get("vmid") or 0,
    ),
  )


def percentage(value, total):
  if total <= 0:
    return 0
  return round((value / total) * 100)


def sample_values(values, limit):
  if len(values) <= limit:
    return values

  sampled = []
  step = (len(values) - 1) / (limit - 1)
  for index in range(limit):
    sampled.append(values[round(index * step)])
  return sampled


def render_area_chart(items):
  octets = sorted(int(primary_ip(item).split(".")[-1]) for item in items if primary_ip(item))
  octets = sample_values(octets, 18)

  if not octets:
    octets = [0, 0, 0, 0]
  elif len(octets) == 1:
    octets = [octets[0], octets[0]]

  width = 240
  height = 72
  pad = 6
  low = min(octets)
  high = max(octets)
  spread = max(high - low, 1)
  usable_height = height - (pad * 2) - 8
  step = (width - (pad * 2)) / max(len(octets) - 1, 1)
  points = []

  for index, value in enumerate(octets):
    x = pad + (index * step)
    y = height - pad - (((value - low) / spread) * usable_height)
    points.append(f"{x:.1f},{y:.1f}")

  line = " ".join(points)
  area = f"{pad},{height - pad} {line} {width - pad},{height - pad}"

  return (
    '<div class="mini-chart area-chart">'
    f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="IP spread area chart">'
    '<defs><linearGradient id="area-fill" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0%" stop-color="#2a6bdb" stop-opacity="0.55"></stop>'
    '<stop offset="100%" stop-color="#2a6bdb" stop-opacity="0"></stop>'
    '</linearGradient></defs>'
    f'<polygon points="{area}" fill="url(#area-fill)"></polygon>'
    f'<polyline points="{line}" fill="none" stroke="#2a6bdb" stroke-width="2" stroke-linecap="round"></polyline>'
    '</svg>'
    f'<span class="chart-note">Address spread: {low} to {high}</span>'
    '</div>'
  )


def render_progress_chart(value, total, accent, label, variant="ring"):
  percent = percentage(value, total)
  variant_class = "ring donut" if variant == "donut" else "ring"
  return (
    '<div class="mini-chart">'
    '<div class="progress-wrap">'
    f'<div class="{variant_class}" style="--percent: {percent}; --accent: {accent};" role="img" aria-label="{html.escape(label)} {percent} percent">'
    f'<span>{percent}%</span>'
    '</div>'
    '<div class="progress-copy">'
    f'<strong>{value}/{total}</strong>'
    f'<span>{html.escape(label)}</span>'
    '</div>'
    '</div>'
    '</div>'
  )


def render_node_chart(items):
  counts = {}
  for item in items:
    node = item.get("node") or "-"
    counts[node] = counts.get(node, 0) + 1

  if not counts:
    return '<div class="mini-chart"><span class="chart-note">No node data</span></div>'

  highest = max(counts.values())
  rows = []
  for node, count in sorted(counts.items()):
    width = round((count / highest) * 100) if highest else 0
    rows.append(
      '<div class="bar-row">'
      f'<span class="bar-label">{html.escape(node)}</span>'
      '<div class="bar-track">'
      f'<span class="bar-fill" style="width: {max(width, 8)}%"></span>'
      '</div>'
      f'<span class="bar-value">{count}</span>'
      '</div>'
    )

  return '<div class="mini-chart"><div class="bar-chart">' + "".join(rows) + '</div></div>'


def extract_ipv4_ips(payload):
    seen = set()

    def walk(value):
        if isinstance(value, dict):
            for nested in value.values():
                walk(nested)
            return
        if isinstance(value, list):
            for nested in value:
                walk(nested)
            return
        if isinstance(value, str):
            for candidate in IPV4_RE.findall(value):
              if is_valid_ipv4(candidate):
                    seen.add(candidate)

    walk(payload)
    return sorted(seen, key=ip_sort_key)


def proxmox_headers():
    if not PROXMOX_TOKEN_ID or not PROXMOX_TOKEN_SECRET:
        raise RuntimeError("Set PROXMOX_TOKEN_ID and PROXMOX_TOKEN_SECRET before using /api/vms.")
    return {
        "Accept": "application/json",
        "Authorization": f"PVEAPIToken={PROXMOX_TOKEN_ID}={PROXMOX_TOKEN_SECRET}",
    }


def proxmox_get(path):
    url = f"{PROXMOX_BASE_URL.rstrip('/')}" + "/api2/json" + path
    request = Request(url, headers=proxmox_headers(), method="GET")

    try:
        with urlopen(request, timeout=API_TIMEOUT_SECONDS, context=SSL_CONTEXT) as response:
            payload = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        raise RuntimeError(f"Proxmox API returned {exc.code} {exc.reason}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to reach Proxmox API: {exc.reason}") from exc

    return payload.get("data")


def fallback_cluster_name():
  base = PROXMOX_BASE_URL.split("://", 1)[-1]
  host = base.split("/", 1)[0]
  return host.split(":", 1)[0] or "unknown"


def fetch_cluster_name():
  try:
    status = proxmox_get("/cluster/status") or []
  except RuntimeError:
    return fallback_cluster_name()

  for entry in status:
    if entry.get("type") == "cluster" and entry.get("name"):
      return str(entry["name"])

  return fallback_cluster_name()


def format_ip_note(error_message):
    lowered = error_message.lower()
    if "guest agent" in lowered:
        return "guest agent unavailable"
    if "not running" in lowered:
        return "vm is not running"
    return "ip lookup failed"


def fetch_vm_ips(resource):
    if resource.get("status") != "running":
        return [], "vm is not running"

    node = resource.get("node")
    vmid = resource.get("vmid")
    kind = resource.get("type")

    if kind == "qemu":
        payload = proxmox_get(f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces")
    elif kind == "lxc":
        payload = proxmox_get(f"/nodes/{node}/lxc/{vmid}/interfaces")
    else:
        return [], "unsupported vm type"

    ipv4_ips = extract_ipv4_ips(payload)
    if ipv4_ips:
      return ipv4_ips, ""
    return [], "no IP address"


def fetch_dashboard_data():
    cluster_name = fetch_cluster_name()
    resources = proxmox_get("/cluster/resources?type=vm") or []
    items = []
    nodes = set()
    running = 0
    with_pool_ip = 0

    for resource in sorted(resources, key=lambda item: (item.get("node", ""), item.get("name", ""), item.get("vmid", 0))):
        node = resource.get("node") or "-"
        status = resource.get("status") or "unknown"
        name = resource.get("name") or f"vm-{resource.get('vmid', '?')}"
        nodes.add(node)

        if status == "running":
            running += 1

        try:
            ips, ip_note = fetch_vm_ips(resource)
        except RuntimeError as exc:
            ips, ip_note = [], format_ip_note(str(exc))

        if ips:
            with_pool_ip += 1

        items.append(
            {
                "vmid": resource.get("vmid"),
                "name": name,
                "kind": resource.get("type", "unknown"),
                "node": node,
                "status": status,
                "ips": ips,
                "ip_note": ip_note,
            }
        )

    items = sort_dashboard_items(items)

    return {
      "cluster_name": cluster_name,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "refresh_seconds": REFRESH_SECONDS,
        "summary": {
            "total": len(items),
            "running": running,
            "with_pool_ip": with_pool_ip,
            "nodes": len(nodes),
        },
        "items": items,
    }


def render_ip_buttons(ips):
  return '<div class="ips">' + "".join(
    f'<button class="ip" type="button" data-copy-ip="{html.escape(ip, quote=True)}" data-copy-label="{html.escape(ip, quote=True)}" title="Copy {html.escape(ip, quote=True)} to clipboard">{html.escape(ip)}</button>'
    for ip in ips
  ) + "</div>"


def render_ip_count(ips):
  tooltip = "<br>".join(html.escape(ip) for ip in ips)
  return f'<span class="ip-count" tabindex="0">{len(ips)} IPs<span class="ip-tooltip">{tooltip}</span></span>'


def kind_display(kind):
  lowered = (kind or "").lower()
  if lowered == "qemu":
    return (
      "vm",
      "VM",
      '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="3" width="11" height="7" rx="1.6"></rect><path d="M6 13h4"></path><path d="M8 10v3"></path></svg>',
    )
  if lowered == "lxc":
    return (
      "lxc",
      "LXC",
      '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1"></rect><rect x="9" y="2.5" width="4.5" height="4.5" rx="1"></rect><rect x="5.75" y="9" width="4.5" height="4.5" rx="1"></rect></svg>',
    )
  return (
    "unknown",
    (kind or "unknown").upper(),
    '<svg viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="8" r="2.5"></circle></svg>',
  )


def render_kind_cell(kind):
  kind_class, label, icon = kind_display(kind)
  return (
    f'<span class="type-pill type-pill-{kind_class}">'
    f'<span class="type-icon" aria-hidden="true">{icon}</span>'
    f'<span>{html.escape(label)}</span>'
    '</span>'
  )


def render_status_class(status):
    if status in {"running", "stopped", "paused"}:
        return status
    return "unknown"


def render_ips_cell(item):
  ips = item.get("ips") or []
  if not ips:
    return f'<span class="hint">{html.escape(item.get("ip_note") or "-")}</span>'
  if len(ips) == 1:
    return render_ip_buttons(ips)
  return render_ip_count(ips)


def render_table_rows(items):
  if not items:
    return '<tr><td colspan="5" class="empty">No VMs returned by the Proxmox API.</td></tr>'

  rows = []
  for item in items:
    name = item.get("name", "")
    kind = item.get("kind", "")
    node = item.get("node", "")
    status = item.get("status", "unknown")
    vmid = item.get("vmid") or 0
    _, kind_label, _ = kind_display(kind)
    escaped_name = html.escape(name)
    escaped_status = html.escape(status)
    running_flag = 1 if status == "running" else 0
    row_open = (
      f'<tr data-sort-row="1" '
      f'data-name="{html.escape(name.lower(), quote=True)}" '
      f'data-vmid="{vmid}" '
      f'data-kind="{html.escape(kind_label.lower(), quote=True)}" '
      f'data-node="{html.escape(node.lower(), quote=True)}" '
      f'data-status="{html.escape(status.lower(), quote=True)}" '
      f'data-status-rank="{status_rank(status)}" '
      f'data-running="{running_flag}" '
      f'data-all-ips="{html.escape(",".join(item.get("ips", [])), quote=True)}" '
      f'data-ip-note="{html.escape(item.get("ip_note", ""), quote=True)}">'
    )

    rows.append(
      "".join(
        [
          row_open,
          f'<td>{escaped_name}</td>',
          f'<td>{vmid}</td>',
          f'<td>{render_kind_cell(kind)}</td>',
          f'<td class="status-cell"><span class="status status-{render_status_class(status)}" title="{escaped_status}" aria-label="{escaped_status}"></span><span class="sr-only">{escaped_status}</span></td>',
          f"<td class=\"ip-cell\">{render_ips_cell(item)}</td>",
          "</tr>",
        ]
      )
    )
  return "".join(rows)


def render_node_tables(items):
  if not items:
    return '<section class="node-card"><div class="table-wrap"><table>' + TABLE_HEAD_HTML + '<tbody class="vm-table-body"><tr><td colspan="5" class="empty">No VMs returned by the Proxmox API.</td></tr></tbody></table></div></section>'

  grouped = {}
  for item in items:
    node = item.get("node") or "-"
    grouped.setdefault(node, []).append(item)

  sections = []
  for index, node in enumerate(sorted(grouped)):
    node_items = sort_dashboard_items(grouped[node])
    running_count = sum(1 for item in node_items if item.get("status") == "running")
    rows_html = render_table_rows(node_items)
    sections.append(
      "".join(
        [
          f'<section class="node-card" data-node-table="node-{index}">',
          '<div class="node-head">',
          f'<h3>{html.escape(node)}</h3>',
          f'<span class="node-summary" data-node-summary data-default-summary="{running_count}/{len(node_items)} running">{running_count}/{len(node_items)} running</span>',
          '</div>',
          '<div class="table-wrap">',
          '<table>',
          TABLE_HEAD_HTML,
          f'<tbody class="vm-table-body">{rows_html}<tr class="filter-empty" data-filter-empty hidden><td colspan="5" class="empty">No machines match the active filters.</td></tr></tbody>',
          '</table>',
          '</div>',
          '</section>',
        ]
      )
    )

  return "".join(sections)


def format_generated_at(generated_at):
    if not generated_at:
        return "Waiting for first refresh"

    try:
        parsed = dt.datetime.fromisoformat(generated_at)
    except ValueError:
        return f"Updated {generated_at}"

    return parsed.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def render_dashboard_page(payload=None, error_message=""):
  summary = payload["summary"] if payload else {"total": 0, "running": 0, "with_pool_ip": 0, "nodes": 0}
  generated_at = payload["generated_at"] if payload else ""
  last_updated = format_generated_at(generated_at)
  items = payload["items"] if payload else []
  cluster_name = payload.get("cluster_name", fallback_cluster_name()) if payload else fallback_cluster_name()

  error_display = "block" if error_message else "none"
  node_tables = render_node_tables(items) if payload else (
    '<section class="node-card"><div class="table-wrap"><table>' + TABLE_HEAD_HTML + '<tbody class="vm-table-body"><tr><td colspan="5" class="empty">Unable to load cluster data.</td></tr></tbody></table></div></section>'
  )

  return (
    INDEX_HTML
    .replace("__CLUSTER_NAME__", html.escape(cluster_name))
    .replace("__DEFAULT_IP_FILTER__", html.escape(DEFAULT_IP_FILTER, quote=True))
    .replace("__REFRESH_SECONDS__", str(REFRESH_SECONDS))
    .replace("__LAST_UPDATED__", html.escape(last_updated))
    .replace("__TOTAL_VMS__", str(summary["total"]))
    .replace("__RUNNING_VMS__", str(summary["running"]))
    .replace("__WITH_IPS__", str(summary["with_pool_ip"]))
    .replace("__NODES_COUNT__", str(summary["nodes"]))
    .replace("__TOTAL_CHART__", render_area_chart(items))
    .replace("__RUNNING_CHART__", render_progress_chart(summary["running"], summary["total"], "var(--cyan)", "online", "ring"))
    .replace("__IP_CHART__", render_progress_chart(summary["with_pool_ip"], summary["total"], "var(--purple)", "with IP", "donut"))
    .replace("__NODE_CHART__", render_node_chart(items))
    .replace("__ERROR_DISPLAY__", error_display)
    .replace("__ERROR_MESSAGE__", html.escape(error_message))
    .replace("__NODE_TABLES__", node_tables)
  )


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in {"/", "/index.html"}:
            try:
                body = render_dashboard_page(fetch_dashboard_data()).encode("utf-8")
            except RuntimeError as exc:
                body = render_dashboard_page(error_message=str(exc)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/healthz":
            self.write_json(200, {"ok": True})
            return

        if self.path == "/favicon.svg":
            favicon_path = os.path.join(SCRIPT_DIR, "favicon.svg")
            try:
                with open(favicon_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.write_json(404, {"error": "favicon not found"})
            return

        if self.path == "/api/vms":
            try:
                payload = fetch_dashboard_data()
            except RuntimeError as exc:
                self.write_json(500, {"error": str(exc)})
                return

            self.write_json(200, payload)
            return

        self.write_json(404, {"error": "Not found"})

    def log_message(self, format_string, *args):
        return

    def write_json(self, status_code, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"Dashboard listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()