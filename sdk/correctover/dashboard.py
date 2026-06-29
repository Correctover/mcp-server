"""Correctover Dashboard — Real-time web monitoring UI

Starts an HTTP server serving a Chart.js dashboard that polls
/api/{section} endpoints every 2 seconds.

Public API:
    dashboard(port=8765, open_browser=True, background=True)
    stop_dashboard()
    dashboard_url()
    dashboard_status()
"""

import json
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, Optional


# ── Module state ──────────────────────────────────────────────────

_server: Optional[HTTPServer] = None
_server_port: Optional[int] = None
_server_thread: Optional[threading.Thread] = None


# ── Data collectors ──────────────────────────────────────────────

def _collect_overview() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    try:
        import correctover
        dashboard_data = getattr(correctover, "dashboard_data", None)
        if dashboard_data:
            d = dashboard_data()
            data["total_calls"] = d.get("total_requests", 0)
            savings = d.get("savings_this_month", {})
            data["total_cost_usd"] = savings.get("model_difference_usd", 0)
            data["total_savings_usd"] = savings.get("model_difference_usd", 0)
        else:
            data["total_calls"] = 0
            data["total_cost_usd"] = 0
            data["total_savings_usd"] = 0
    except Exception:
        data["total_calls"] = 0
        data["total_cost_usd"] = 0
        data["total_savings_usd"] = 0

    data["total_tokens"] = 0
    data["savings_pct"] = 0.0
    data["healthy"] = True

    try:
        from correctover import __version__
        data["version"] = __version__
    except Exception:
        data["version"] = "4.4.2"

    try:
        from correctover.carbon import get_carbon_tracker
        ct = get_carbon_tracker()
        r = ct.report()
        data["carbon_wh"] = r.get("actual", {}).get("wh", 0)
        data["carbon_co2_kg"] = r.get("actual", {}).get("co2_kg", 0)
        data["carbon_savings_rate"] = r.get("savings", {}).get("rate", 0)
        data["by_provider"] = r.get("by_provider", {})
    except Exception:
        data["carbon_wh"] = 0
        data["carbon_co2_kg"] = 0
        data["carbon_savings_rate"] = 0.0
        data["by_provider"] = {}

    try:
        from correctover.drift import get_drift_monitor
        dm = get_drift_monitor()
        s = dm.status()
        data["drift_healthy"] = s.get("healthy", True)
        data["drift_alerts"] = s.get("drift_detected", 0)
    except Exception:
        data["drift_healthy"] = True
        data["drift_alerts"] = 0

    try:
        from correctover._stats import stats
        report = stats.savings_report()
        data["total_calls"] = report.get("total_requests", data.get("total_calls", 0))
        data["total_tokens"] = report.get("total_tokens", {}).get("total", 0)
        savings_info = report.get("savings", {})
        data["total_cost_usd"] = report.get("counterfactual", {}).get("if_no_nb", {}).get("all_original_model_cost_usd", 0)
        data["total_savings_usd"] = savings_info.get("model_difference_usd", 0)
        actual_cost = report.get("counterfactual", {}).get("with_nb", {}).get("actual_cost_usd", 0)
        if actual_cost > 0:
            data["savings_pct"] = data["total_savings_usd"] / actual_cost
    except Exception:
        pass

    return data


def _collect_api() -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "calls": [],
        "by_provider": {},
        "by_model": {},
        "total_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cost_usd": 0.0,
        "total_savings_usd": 0.0,
        "latency_p50": 0,
        "latency_p95": 0,
        "latency_p99": 0,
    }
    try:
        from correctover._stats import stats
        dashboard_data = stats.dashboard_data()
        d = dashboard_data
        data["total_calls"] = d.get("total_requests", 0)
    except Exception:
        d = {}

    try:
        from correctover.carbon import get_carbon_tracker
        ct = get_carbon_tracker()
        r = ct.report()
        data["by_provider"] = r.get("by_provider", {})
        data["by_model"] = r.get("by_model", {})
    except Exception:
        pass

    try:
        from correctover.drift import get_drift_monitor
        dm = get_drift_monitor()
        s = dm.status()
        provider_latencies = {}
        for key in s.get("tracked_providers", []):
            provider_latencies[key] = {}
        data["latency_p50"] = 0
        data["latency_p95"] = 0
        data["latency_p99"] = 0
    except Exception:
        pass

    return data


def _collect_routing() -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "strategy": "",
        "decisions": [],
        "by_provider": {},
        "by_tier": {},
        "cost_saved_usd": 0,
        "tokens_saved": 0,
        "routing_decisions": 0,
        "checkpoint_resumes": 0,
    }
    try:
        from correctover.carbon import get_carbon_tracker
        ct = get_carbon_tracker()
        r = ct.report()
        data["cost_saved_usd"] = r.get("savings", {}).get("cost_usd", 0)
        data["routing_decisions"] = r.get("savings", {}).get("routing_decisions", 0)
        data["checkpoint_resumes"] = r.get("savings", {}).get("checkpoint_resumes", 0)
    except Exception:
        pass

    try:
        from correctover.drift import get_drift_monitor
        dm = get_drift_monitor()
        s = dm.status()
        data["drift"] = s
    except Exception:
        data["drift"] = {
            "total_observations": 0,
            "drift_detected": 0,
            "tracked_providers": [],
            "alerts_by_type": {},
            "alerts_by_severity": {},
            "recent_alerts": [],
            "healthy": True,
        }

    return data


def _collect_carbon() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    try:
        from correctover.carbon import get_carbon_tracker
        ct = get_carbon_tracker()
        r = ct.report()
        data.update(r)
        data["esg"] = ct.esg_summary()
    except Exception:
        data = {
            "actual": {"calls": 0, "wh": 0, "kwh": 0.0, "co2_kg": 0, "co2_tons": 0.0},
            "waste": {"calls": 0, "wh": 0, "co2_kg": 0},
            "savings": {"routing_decisions": 0, "checkpoint_resumes": 0, "wh": 0, "co2_kg": 0, "cost_usd": 0, "rate": 0.0},
            "intensity": {"g_co2_per_1k_tokens": 0.0, "grid_factor": 0.6},
            "by_provider": {},
            "by_model": {},
            "esg": {
                "reporting_period": "0.0 hours",
                "scope2_emissions_kg_co2": 0,
                "avoided_emissions_kg_co2": 0,
                "waste_emissions_kg_co2": 0,
                "energy_consumed_kwh": 0.0,
                "energy_saved_kwh": 0.0,
                "energy_waste_kwh": 0.0,
                "carbon_intensity_g_per_1k_tokens": 0.0,
                "savings_rate_pct": 0.0,
                "waste_rate_pct": 0.0,
                "grid_carbon_factor": "0.6 kg CO\u2082/kWh",
                "methodology": "Token-based estimation with model-tier energy coefficients",
                "data_sources": [
                    "EPRI AI Energy Research 2024",
                    "ODCC \u6570\u636e\u4e2d\u5fc3\u7b97\u529b\u78b3\u6548\u767d\u76ae\u4e66",
                    "\u4fe1\u901a\u9662 \u4e2d\u56fd\u6570\u636e\u4e2d\u5fc3\u78b3\u6392\u653e 2024",
                ],
            },
        }
    return data


def _collect_drift() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    try:
        from correctover.drift import get_drift_monitor
        dm = get_drift_monitor()
        s = dm.status()
        data.update(s)
    except Exception:
        data = {
            "total_observations": 0,
            "drift_detected": 0,
            "tracked_providers": [],
            "alerts_by_type": {},
            "alerts_by_severity": {},
            "recent_alerts": [],
            "healthy": True,
        }
    return data


# ── Collector registry ────────────────────────────────────────────

_COLLECTORS = {
    "overview": _collect_overview,
    "api": _collect_api,
    "routing": _collect_routing,
    "carbon": _collect_carbon,
    "drift": _collect_drift,
}


# ── HTML dashboard ───────────────────────────────────────────────

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Correctover Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
:root {
  --bg-primary: #0a0e1a;
  --bg-secondary: #111827;
  --bg-card: #1a2236;
  --bg-card-hover: #1f2a42;
  --border: #2a3654;
  --text-primary: #e8edf5;
  --text-secondary: #8b9cc7;
  --text-muted: #5a6d96;
  --accent-blue: #3b82f6;
  --accent-cyan: #06b6d4;
  --accent-green: #10b981;
  --accent-yellow: #f59e0b;
  --accent-red: #ef4444;
  --accent-purple: #8b5cf6;
  --accent-pink: #ec4899;
  --gradient-1: linear-gradient(135deg, #3b82f6, #8b5cf6);
  --gradient-2: linear-gradient(135deg, #10b981, #06b6d4);
  --gradient-3: linear-gradient(135deg, #f59e0b, #ef4444);
  --shadow: 0 4px 24px rgba(0,0,0,0.4);
  --radius: 12px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', Roboto, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  min-height: 100vh;
  overflow-x: hidden;
}
/* ── Animated background ── */
.bg-animation {
  position: fixed; top:0; left:0; width:100%; height:100%;
  z-index:0; pointer-events:none; opacity:0.03;
  background:
    radial-gradient(ellipse 600px 600px at 20% 30%, #3b82f6, transparent),
    radial-gradient(ellipse 500px 500px at 80% 70%, #8b5cf6, transparent),
    radial-gradient(ellipse 400px 400px at 50% 50%, #06b6d4, transparent);
  animation: bgPulse 8s ease-in-out infinite alternate;
}
@keyframes bgPulse {
  0% { opacity:0.02; transform:scale(1); }
  100% { opacity:0.05; transform:scale(1.05); }
}
/* ── Layout ── */
.app { position:relative; z-index:1; display:flex; min-height:100vh; }
/* ── Sidebar ── */
.sidebar {
  width: 240px; background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column; padding: 0;
  position: fixed; top:0; left:0; bottom:0; z-index:100;
}
.sidebar-brand {
  padding: 24px 20px; border-bottom: 1px solid var(--border);
  display:flex; align-items:center; gap:12px;
}
.brand-icon {
  width:36px; height:36px; border-radius:10px;
  background: var(--gradient-1); display:flex; align-items:center;
  justify-content:center; font-weight:700; font-size:16px;
  box-shadow: 0 0 20px rgba(59,130,246,0.3);
}
.brand-text { font-size:15px; font-weight:600; letter-spacing:-0.3px; }
.brand-ver { font-size:11px; color:var(--text-muted); margin-top:2px; }
.sidebar-nav { padding:12px 8px; flex:1; }
.nav-section { font-size:10px; text-transform:uppercase; letter-spacing:1.5px;
  color:var(--text-muted); padding:16px 12px 8px; font-weight:600; }
.nav-item {
  display:flex; align-items:center; gap:10px; padding:10px 12px;
  border-radius:8px; cursor:pointer; font-size:13px; font-weight:500;
  color:var(--text-secondary); transition:all 0.2s; margin-bottom:2px;
}
.nav-item:hover { background:var(--bg-card); color:var(--text-primary); }
.nav-item.active {
  background:rgba(59,130,246,0.12); color:var(--accent-blue);
  box-shadow: inset 3px 0 0 var(--accent-blue);
}
.nav-item .icon { font-size:16px; width:20px; text-align:center; }
.nav-item .badge {
  margin-left:auto; font-size:10px; padding:2px 7px;
  border-radius:10px; font-weight:600;
}
.badge-green { background:rgba(16,185,129,0.15); color:var(--accent-green); }
.badge-yellow { background:rgba(245,158,11,0.15); color:var(--accent-yellow); }
.badge-red { background:rgba(239,68,68,0.15); color:var(--accent-red); }
.sidebar-footer {
  padding:16px 20px; border-top:1px solid var(--border);
  font-size:11px; color:var(--text-muted);
}
.sidebar-footer .status-dot {
  display:inline-block; width:6px; height:6px; border-radius:50%;
  background:var(--accent-green); margin-right:6px;
  animation: pulse 2s infinite;
}
@keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.4;} }
/* ── Main Content ── */
.main { margin-left:240px; flex:1; padding:24px 32px; min-height:100vh; }
.page { display:none; animation: fadeIn 0.3s ease; }
.page.active { display:block; }
@keyframes fadeIn { from{opacity:0;transform:translateY(8px);} to{opacity:1;transform:translateY(0);} }
.page-title {
  font-size:24px; font-weight:700; letter-spacing:-0.5px;
  margin-bottom:4px;
}
.page-subtitle { font-size:13px; color:var(--text-secondary); margin-bottom:24px; }
/* ── Cards ── */
.card-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px,1fr)); gap:16px; margin-bottom:24px; }
.card {
  background:var(--bg-card); border:1px solid var(--border);
  border-radius:var(--radius); padding:20px; transition:all 0.25s;
  position:relative; overflow:hidden;
}
.card:hover { background:var(--bg-card-hover); border-color:rgba(59,130,246,0.3); transform:translateY(-1px); }
.card::before {
  content:''; position:absolute; top:0; left:0; right:0; height:3px;
  background:var(--gradient-1); opacity:0; transition:opacity 0.25s;
}
.card:hover::before { opacity:1; }
.card-label { font-size:12px; color:var(--text-muted); font-weight:500; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px; }
.card-value { font-size:28px; font-weight:700; letter-spacing:-1px; line-height:1; }
.card-value.small { font-size:20px; }
.card-sub { font-size:12px; color:var(--text-secondary); margin-top:6px; }
.card-trend { display:inline-flex; align-items:center; gap:4px; font-size:12px; font-weight:600; padding:2px 8px; border-radius:10px; margin-top:8px; }
.trend-up { background:rgba(16,185,129,0.12); color:var(--accent-green); }
.trend-down { background:rgba(239,68,68,0.12); color:var(--accent-red); }
/* ── Chart containers ── */
.chart-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:24px; }
.chart-card {
  background:var(--bg-card); border:1px solid var(--border);
  border-radius:var(--radius); padding:20px;
}
.chart-title { font-size:14px; font-weight:600; margin-bottom:16px; display:flex; align-items:center; gap:8px; }
.chart-title .dot { width:8px; height:8px; border-radius:50%; }
.chart-wrap { position:relative; height:240px; }
/* ── Alert list ── */
.alert-list { display:flex; flex-direction:column; gap:8px; }
.alert-item {
  display:flex; align-items:flex-start; gap:12px; padding:12px 16px;
  background:var(--bg-card); border:1px solid var(--border);
  border-radius:10px; font-size:13px;
}
.alert-severity {
  width:8px; height:8px; border-radius:50%; margin-top:5px; flex-shrink:0;
}
.severity-critical { background:var(--accent-red); box-shadow:0 0 8px rgba(239,68,68,0.5); }
.severity-warn { background:var(--accent-yellow); box-shadow:0 0 8px rgba(245,158,11,0.5); }
.severity-info { background:var(--accent-blue); }
.alert-content { flex:1; }
.alert-type { font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:2px; }
.alert-detail { color:var(--text-secondary); font-size:12px; }
.alert-time { font-size:11px; color:var(--text-muted); white-space:nowrap; }
/* ── Table ── */
.data-table { width:100%; border-collapse:collapse; font-size:13px; }
.data-table th {
  text-align:left; padding:10px 12px; font-size:11px; text-transform:uppercase;
  letter-spacing:0.5px; color:var(--text-muted); border-bottom:1px solid var(--border);
  font-weight:600;
}
.data-table td { padding:10px 12px; border-bottom:1px solid rgba(42,54,84,0.5); }
.data-table tr:hover td { background:rgba(59,130,246,0.04); }
/* ── Carbon tree ── */
.carbon-viz {
  display:flex; flex-direction:column; align-items:center;
  padding:30px; margin:16px 0;
}
.tree-icon { font-size:64px; filter:drop-shadow(0 0 20px rgba(16,185,129,0.4)); }
.tree-text { margin-top:12px; text-align:center; }
.tree-value { font-size:36px; font-weight:700; color:var(--accent-green); }
.tree-label { font-size:13px; color:var(--text-secondary); margin-top:4px; }
/* ── Provider bar ── */
.provider-bar { display:flex; height:8px; border-radius:4px; overflow:hidden; margin:8px 0; }
.provider-bar > div { height:100%; transition:width 0.5s; }
/* ── ESG card ── */
.esg-card {
  background:var(--bg-card); border:1px solid var(--border);
  border-radius:var(--radius); padding:20px; margin-top:16px;
}
.esg-title { font-size:14px; font-weight:600; margin-bottom:12px; display:flex; align-items:center; gap:8px; }
.esg-row { display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid rgba(42,54,84,0.3); font-size:13px; }
.esg-row:last-child { border-bottom:none; }
.esg-label { color:var(--text-secondary); }
.esg-value { font-weight:600; }
/* ── Empty state ── */
.empty-state { text-align:center; padding:60px 20px; color:var(--text-muted); }
.empty-icon { font-size:48px; margin-bottom:12px; }
.empty-text { font-size:14px; }
/* ── Responsive ── */
@media (max-width: 900px) {
  .chart-grid { grid-template-columns:1fr; }
  .card-grid { grid-template-columns:1fr 1fr; }
}
@media (max-width: 600px) {
  .sidebar { width:60px; }
  .brand-text,.brand-ver,.nav-item span,.sidebar-footer span { display:none; }
  .main { margin-left:60px; padding:16px; }
  .card-grid { grid-template-columns:1fr; }
}
/* ── Spin animation for loading ── */
.spin { animation: spin 1s linear infinite; display:inline-block; }
@keyframes spin { from{transform:rotate(0)} to{transform:rotate(360deg)} }
/* ── Number counter animation ── */
.counter { display:inline-block; transition:all 0.3s; }
</style>
</head>
<body>
<div class="bg-animation"></div>
<div class="app">
  <!-- Sidebar -->
  <div class="sidebar">
    <div class="sidebar-brand">
      <div class="brand-icon">NB</div>
      <div>
        <div class="brand-text">Correctover</div>
        <div class="brand-ver" id="sdk-version">v4.4.2</div>
      </div>
    </div>
    <div class="sidebar-nav">
      <div class="nav-section">Monitor</div>
      <div class="nav-item active" data-page="overview">
        <span class="icon">&#x1F4CA;</span><span>Overview</span>
        <span class="badge badge-green" id="health-badge">Healthy</span>
      </div>
      <div class="nav-item" data-page="api">
        <span class="icon">&#x1F50C;</span><span>API Usage</span>
      </div>
      <div class="nav-item" data-page="routing">
        <span class="icon">&#x1F9ED;</span><span>Routing</span>
      </div>
      <div class="nav-item" data-page="carbon">
        <span class="icon">&#x1F331;</span><span>Carbon</span>
      </div>
      <div class="nav-item" data-page="drift">
        <span class="icon">&#x1F6E1;&#xFE0F;</span><span>Drift</span>
        <span class="badge badge-green" id="drift-badge">0</span>
      </div>
    </div>
    <div class="sidebar-footer">
      <span class="status-dot"></span><span>Live &middot; <span id="uptime">0s</span></span>
    </div>
  </div>

  <!-- Main Content -->
  <div class="main">
    <!-- ═══ Overview ═══ -->
    <div class="page active" id="page-overview">
      <div class="page-title">Overview</div>
      <div class="page-subtitle">Real-time Correctover SDK monitoring</div>
      <div class="card-grid" id="overview-cards">
        <div class="card">
          <div class="card-label">Total API Calls</div>
          <div class="card-value counter" id="ov-calls">0</div>
          <div class="card-sub">across all providers</div>
        </div>
        <div class="card">
          <div class="card-label">Total Tokens</div>
          <div class="card-value counter" id="ov-tokens">0</div>
          <div class="card-sub">input + output</div>
        </div>
        <div class="card">
          <div class="card-label">Cost Savings</div>
          <div class="card-value counter" id="ov-savings">$0.00</div>
          <div class="card-sub" id="ov-savings-pct">0% saved vs premium</div>
        </div>
        <div class="card">
          <div class="card-label">Carbon Footprint</div>
          <div class="card-value counter" id="ov-carbon">0 Wh</div>
          <div class="card-sub" id="ov-carbon-co2">0 kg CO&#x2082;</div>
        </div>
      </div>
      <div class="chart-grid">
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-blue)"></span>API Calls Over Time</div>
          <div class="chart-wrap"><canvas id="chart-calls"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-green)"></span>Cost & Savings</div>
          <div class="chart-wrap"><canvas id="chart-cost"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-purple)"></span>Provider Distribution</div>
          <div class="chart-wrap"><canvas id="chart-providers"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-cyan)"></span>Carbon Savings Rate</div>
          <div class="chart-wrap"><canvas id="chart-carbon-rate"></canvas></div>
        </div>
      </div>
    </div>

    <!-- ═══ API Usage ═══ -->
    <div class="page" id="page-api">
      <div class="page-title">API Usage</div>
      <div class="page-subtitle">Detailed provider and model usage metrics</div>
      <div class="card-grid">
        <div class="card">
          <div class="card-label">Total Calls</div>
          <div class="card-value counter" id="api-calls">0</div>
        </div>
        <div class="card">
          <div class="card-label">Total Cost</div>
          <div class="card-value counter" id="api-cost">$0.00</div>
        </div>
        <div class="card">
          <div class="card-label">Input Tokens</div>
          <div class="card-value counter" id="api-in-tokens">0</div>
        </div>
        <div class="card">
          <div class="card-label">Output Tokens</div>
          <div class="card-value counter" id="api-out-tokens">0</div>
        </div>
      </div>
      <div class="chart-grid">
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-blue)"></span>By Provider</div>
          <div class="chart-wrap"><canvas id="chart-api-provider"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-purple)"></span>By Model</div>
          <div class="chart-wrap"><canvas id="chart-api-model"></canvas></div>
        </div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Provider Details</div>
        <table class="data-table" id="api-table">
          <thead><tr><th>Provider</th><th>Calls</th><th>Tokens</th><th>Cost</th><th>Share</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <!-- ═══ Routing ═══ -->
    <div class="page" id="page-routing">
      <div class="page-title">Model Routing</div>
      <div class="page-subtitle">Smart routing optimization and cost savings</div>
      <div class="card-grid">
        <div class="card">
          <div class="card-label">Routing Decisions</div>
          <div class="card-value counter" id="rt-decisions">0</div>
          <div class="card-sub">intelligent re-routes</div>
        </div>
        <div class="card">
          <div class="card-label">Cost Saved</div>
          <div class="card-value counter" id="rt-cost-saved">$0.00</div>
        </div>
        <div class="card">
          <div class="card-label">Checkpoint Resumes</div>
          <div class="card-value counter" id="rt-checkpoints">0</div>
          <div class="card-sub">crash recovery saves</div>
        </div>
        <div class="card">
          <div class="card-label">Routing Drift</div>
          <div class="card-value small" id="rt-drift" style="color:var(--accent-green)">Stable</div>
        </div>
      </div>
      <div class="chart-grid">
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-cyan)"></span>Routing Strategy Distribution</div>
          <div class="chart-wrap"><canvas id="chart-routing-strategy"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-green)"></span>Cost Savings Over Time</div>
          <div class="chart-wrap"><canvas id="chart-routing-savings"></canvas></div>
        </div>
      </div>
    </div>

    <!-- ═══ Carbon ═══ -->
    <div class="page" id="page-carbon">
      <div class="page-title">Carbon Tracker</div>
      <div class="page-subtitle">LLM inference carbon emissions & ESG reporting</div>
      <div class="card-grid">
        <div class="card">
          <div class="card-label">Energy Consumed</div>
          <div class="card-value counter" id="cb-wh">0 Wh</div>
          <div class="card-sub" id="cb-kwh">0 kWh</div>
        </div>
        <div class="card">
          <div class="card-label">CO&#x2082; Emissions</div>
          <div class="card-value counter" id="cb-co2">0 kg</div>
          <div class="card-sub">Scope 2 (indirect)</div>
        </div>
        <div class="card">
          <div class="card-label">Energy Saved</div>
          <div class="card-value counter" id="cb-saved-wh" style="color:var(--accent-green)">0 Wh</div>
          <div class="card-sub" id="cb-saved-co2">0 kg CO&#x2082; avoided</div>
        </div>
        <div class="card">
          <div class="card-label">Savings Rate</div>
          <div class="card-value counter" id="cb-rate" style="color:var(--accent-green)">0%</div>
          <div class="card-sub">routing + checkpoint</div>
        </div>
      </div>
      <div class="carbon-viz">
        <div class="tree-icon">&#x1F333;</div>
        <div class="tree-text">
          <div class="tree-value" id="cb-trees">0</div>
          <div class="tree-label">equivalent trees needed to offset</div>
        </div>
      </div>
      <div class="chart-grid">
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-green)"></span>Energy by Provider</div>
          <div class="chart-wrap"><canvas id="chart-carbon-provider"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-yellow)"></span>Energy by Model</div>
          <div class="chart-wrap"><canvas id="chart-carbon-model"></canvas></div>
        </div>
      </div>
      <div class="esg-card">
        <div class="esg-title">&#x1F4CB; ESG Report</div>
        <div id="esg-rows"></div>
      </div>
    </div>

    <!-- ═══ Drift ═══ -->
    <div class="page" id="page-drift">
      <div class="page-title">Drift Monitor</div>
      <div class="page-subtitle">Continuous drift detection across 4 dimensions</div>
      <div class="card-grid">
        <div class="card">
          <div class="card-label">Total Observations</div>
          <div class="card-value counter" id="dr-obs">0</div>
        </div>
        <div class="card">
          <div class="card-label">Drift Detected</div>
          <div class="card-value counter" id="dr-detected" style="color:var(--accent-yellow)">0</div>
        </div>
        <div class="card">
          <div class="card-label">Tracked Providers</div>
          <div class="card-value counter" id="dr-providers">0</div>
        </div>
        <div class="card">
          <div class="card-label">System Health</div>
          <div class="card-value small" id="dr-health" style="color:var(--accent-green)">Healthy</div>
        </div>
      </div>
      <div class="chart-grid">
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-yellow)"></span>Alerts by Type</div>
          <div class="chart-wrap"><canvas id="chart-drift-type"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title"><span class="dot" style="background:var(--accent-red)"></span>Alerts by Severity</div>
          <div class="chart-wrap"><canvas id="chart-drift-severity"></canvas></div>
        </div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Recent Alerts</div>
        <div class="alert-list" id="drift-alerts">
          <div class="empty-state">
            <div class="empty-icon">&#x1F6E1;&#xFE0F;</div>
            <div class="empty-text">No drift alerts &#8212; system is stable</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
// ══════════════════════════════════════════════════════════════
// Correctover Dashboard &#8212; Frontend Engine
// ══════════════════════════════════════════════════════════════

const COLORS = {
  blue: '#3b82f6', cyan: '#06b6d4', green: '#10b981',
  yellow: '#f59e0b', red: '#ef4444', purple: '#8b5cf6',
  pink: '#ec4899', orange: '#f97316', teal: '#14b8a6', indigo: '#6366f1'
};
const PALETTE = Object.values(COLORS);
const chartOpts = {
  responsive:true, maintainAspectRatio:false,
  plugins:{legend:{labels:{color:'#8b9cc7',font:{size:11}}}},
  scales:{
    x:{grid:{color:'rgba(42,54,84,0.3)'},ticks:{color:'#5a6d96',font:{size:10}}},
    y:{grid:{color:'rgba(42,54,84,0.3)'},ticks:{color:'#5a6d96',font:{size:10}}}
  }
};
const doughnutOpts = {
  responsive:true, maintainAspectRatio:false,
  plugins:{legend:{position:'right',labels:{color:'#8b9cc7',font:{size:11},padding:12}}}
};

// Chart instances
const charts = {};
let startTime = Date.now();

function makeChart(id, type, labels, datasets, opts) {
  const ctx = document.getElementById(id);
  if (!ctx) return null;
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(ctx, {type, data:{labels, datasets}, options:opts||chartOpts});
  return charts[id];
}

// &#8211;&#8211; Navigation &#8211;&#8211;
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
    document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
    item.classList.add('active');
    document.getElementById('page-'+item.dataset.page).classList.add('active');
  });
});

// &#8211;&#8211; Data Fetch &#8211;&#8211;
async function fetchData(section) {
  try {
    const r = await fetch('/api/'+section);
    return await r.json();
  } catch(e) { return {}; }
}

// &#8211;&#8211; Formatters &#8211;&#8211;
function fmtNum(n) { return n==null?'0':Number(n).toLocaleString(); }
function fmtUSD(n) { return '$'+Number(n||0).toFixed(2); }
function fmtPct(n) { return (Number(n||0)*100).toFixed(1)+'%'; }
function fmtWh(n) { return Number(n||0)<1000?Number(n||0).toFixed(1)+' Wh':(Number(n||0)/1000).toFixed(3)+' kWh'; }
function fmtCo2(n) { return Number(n||0).toFixed(4)+' kg'; }
function timeAgo(ts) {
  const s = Math.floor(Date.now()/1000 - ts);
  if(s<60) return s+'s ago';
  if(s<3600) return Math.floor(s/60)+'m ago';
  return Math.floor(s/3600)+'h ago';
}

// &#8211;&#8211; Time series buffer &#8211;&#8211;
const TS_LEN = 30;
const tsBuffer = { calls:[], cost:[], savings:[], carbonRate:[], labels:[] };
function pushTS(label, calls, cost, savings, carbonRate) {
  tsBuffer.labels.push(label);
  tsBuffer.calls.push(calls);
  tsBuffer.cost.push(cost);
  tsBuffer.savings.push(savings);
  tsBuffer.carbonRate.push(carbonRate);
  if(tsBuffer.labels.length > TS_LEN) {
    tsBuffer.labels.shift(); tsBuffer.calls.shift(); tsBuffer.cost.shift();
    tsBuffer.savings.shift(); tsBuffer.carbonRate.shift();
  }
}

// &#8211;&#8211; Overview Update &#8211;&#8211;
let prevCalls = 0;
async function updateOverview() {
  const d = await fetchData('overview');
  document.getElementById('sdk-version').textContent = 'v'+(d.version||'4.3.8');
  document.getElementById('ov-calls').textContent = fmtNum(d.total_calls);
  document.getElementById('ov-tokens').textContent = fmtNum(d.total_tokens);
  document.getElementById('ov-savings').textContent = fmtUSD(d.total_savings_usd);
  document.getElementById('ov-savings-pct').textContent = fmtPct(d.savings_pct)+' saved vs premium';
  document.getElementById('ov-carbon').textContent = fmtWh(d.carbon_wh);
  document.getElementById('ov-carbon-co2').textContent = fmtCo2(d.carbon_co2_kg)+' CO\u2082';

  // Health badge
  const hb = document.getElementById('health-badge');
  if(d.drift_healthy) { hb.textContent='Healthy'; hb.className='badge badge-green'; }
  else { hb.textContent='Alert'; hb.className='badge badge-red'; }

  // Time series
  const now = new Date();
  const label = now.getHours().toString().padStart(2,'0')+':'+now.getMinutes().toString().padStart(2,'0')+':'+now.getSeconds().toString().padStart(2,'0');
  const delta = Math.max(0, d.total_calls - prevCalls);
  prevCalls = d.total_calls;
  pushTS(label, delta, d.total_cost_usd||0, d.total_savings_usd||0, d.carbon_savings_rate||0);

  // Charts
  makeChart('chart-calls','line', tsBuffer.labels, [{
    label:'Calls', data:tsBuffer.calls, borderColor:COLORS.blue,
    backgroundColor:'rgba(59,130,246,0.1)', fill:true, tension:0.4, pointRadius:2
  }]);
  makeChart('chart-cost','bar', tsBuffer.labels, [
    {label:'Cost ($)',data:tsBuffer.cost,borderColor:COLORS.purple,backgroundColor:'rgba(139,92,246,0.6)'},
    {label:'Savings ($)',data:tsBuffer.savings,borderColor:COLORS.green,backgroundColor:'rgba(16,185,129,0.6)'}
  ]);
  makeChart('chart-carbon-rate','line', tsBuffer.labels, [{
    label:'Savings Rate', data:tsBuffer.carbonRate.map(v=>v*100),
    borderColor:COLORS.cyan, backgroundColor:'rgba(6,182,212,0.1)',
    fill:true, tension:0.4, pointRadius:2
  }], {...chartOpts, scales:{...chartOpts.scales, y:{...chartOpts.scales.y, ticks:{...chartOpts.scales.y.ticks, callback:v=>v+'%'}}}});

  // Provider doughnut
  const prov = d.by_provider||{};
  const provKeys = Object.keys(prov);
  if(provKeys.length > 0) {
    makeChart('chart-providers','doughnut', provKeys,
      [{data:provKeys.map(k=>prov[k].calls||0), backgroundColor:provKeys.map((_,i)=>PALETTE[i%PALETTE.length])}],
      doughnutOpts);
  }
}

// &#8211;&#8211; API Update &#8211;&#8211;
async function updateAPI() {
  const d = await fetchData('api');
  document.getElementById('api-calls').textContent = fmtNum(d.total_calls);
  document.getElementById('api-cost').textContent = fmtUSD(d.total_cost_usd);
  document.getElementById('api-in-tokens').textContent = fmtNum(d.total_input_tokens||0);
  document.getElementById('api-out-tokens').textContent = fmtNum(d.total_output_tokens||0);

  const prov = d.by_provider||{};
  const provKeys = Object.keys(prov);
  if(provKeys.length > 0) {
    makeChart('chart-api-provider','doughnut', provKeys,
      [{data:provKeys.map(k=>prov[k].calls||0), backgroundColor:provKeys.map((_,i)=>PALETTE[i%PALETTE.length])}],
      doughnutOpts);
  }
  const mdl = d.by_model||{};
  const mdlKeys = Object.keys(mdl);
  if(mdlKeys.length > 0) {
    makeChart('chart-api-model','doughnut', mdlKeys,
      [{data:mdlKeys.map(k=>mdl[k].calls||0), backgroundColor:mdlKeys.map((_,i)=>PALETTE[i%PALETTE.length])}],
      doughnutOpts);
  }
  // Table
  const tbody = document.querySelector('#api-table tbody');
  tbody.innerHTML = '';
  for(const k of provKeys) {
    const p = prov[k];
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>'+k+'</td><td>'+fmtNum(p.calls)+'</td><td>'+fmtNum(p.tokens||0)+'</td><td>'+fmtUSD(p.cost||0)+'</td><td>'+fmtPct(p.calls/(d.total_calls||1))+'</td>';
    tbody.appendChild(tr);
  }
}

// &#8211;&#8211; Routing Update &#8211;&#8211;
async function updateRouting() {
  const d = await fetchData('routing');
  document.getElementById('rt-decisions').textContent = fmtNum(d.routing_decisions);
  document.getElementById('rt-cost-saved').textContent = fmtUSD(d.cost_saved_usd);
  document.getElementById('rt-checkpoints').textContent = fmtNum(d.checkpoint_resumes);
  const driftData = d.drift||{};
  if(driftData.healthy) {
    document.getElementById('rt-drift').textContent = 'Stable';
    document.getElementById('rt-drift').style.color = 'var(--accent-green)';
  } else {
    document.getElementById('rt-drift').textContent = 'Drift Detected';
    document.getElementById('rt-drift').style.color = 'var(--accent-red)';
  }
  const alertTypes = driftData.alerts_by_type||{};
  const typeKeys = Object.keys(alertTypes);
  if(typeKeys.length > 0) {
    makeChart('chart-routing-strategy','doughnut', typeKeys,
      [{data:typeKeys.map(k=>alertTypes[k]), backgroundColor:typeKeys.map((_,i)=>PALETTE[i%PALETTE.length])}],
      doughnutOpts);
  }
}

// &#8211;&#8211; Carbon Update &#8211;&#8211;
async function updateCarbon() {
  const d = await fetchData('carbon');
  const actual = d.actual||{};
  const waste = d.waste||{};
  const savings = d.savings||{};
  const intensity = d.intensity||{};
  document.getElementById('cb-wh').textContent = fmtWh(actual.wh||0);
  document.getElementById('cb-kwh').textContent = (actual.kwh||0).toFixed(4)+' kWh';
  document.getElementById('cb-co2').textContent = fmtCo2(actual.co2_kg);
  document.getElementById('cb-saved-wh').textContent = fmtWh(savings.wh||0);
  document.getElementById('cb-saved-co2').textContent = fmtCo2(savings.co2_kg)+' CO\u2082 avoided';
  document.getElementById('cb-rate').textContent = fmtPct(savings.rate||0);
  // Trees: 1 tree absorbs ~22 kg CO2/year
  const trees = Math.max(0, ((actual.co2_kg||0)/22)*365).toFixed(1);
  document.getElementById('cb-trees').textContent = trees;

  const prov = d.by_provider||{};
  const provKeys = Object.keys(prov);
  if(provKeys.length > 0) {
    makeChart('chart-carbon-provider','bar', provKeys,
      [{label:'Energy (Wh)',data:provKeys.map(k=>prov[k].wh||0), backgroundColor:provKeys.map((_,i)=>PALETTE[i%PALETTE.length])}]);
  }
  const mdl = d.by_model||{};
  const mdlKeys = Object.keys(mdl);
  if(mdlKeys.length > 0) {
    makeChart('chart-carbon-model','bar', mdlKeys,
      [{label:'Energy (Wh)',data:mdlKeys.map(k=>mdl[k].wh||0), backgroundColor:mdlKeys.map((_,i)=>PALETTE[i%PALETTE.length])}]);
  }
  // ESG
  const esg = d.esg||{};
  const esgDiv = document.getElementById('esg-rows');
  esgDiv.innerHTML = '';
  const esgItems = [
    ['Reporting Period', esg.reporting_period],
    ['Scope 2 Emissions', esg.scope2_emissions_kg_co2+' kg CO\u2082'],
    ['Avoided Emissions', esg.avoided_emissions_kg_co2+' kg CO\u2082'],
    ['Waste Emissions', esg.waste_emissions_kg_co2+' kg CO\u2082'],
    ['Energy Consumed', esg.energy_consumed_kwh+' kWh'],
    ['Energy Saved', esg.energy_saved_kwh+' kWh'],
    ['Savings Rate', esg.savings_rate_pct+'%'],
    ['Grid Factor', esg.grid_carbon_factor],
    ['Methodology', esg.methodology],
  ];
  for(const [label, value] of esgItems) {
    if(value==null||value==='undefined') continue;
    const row = document.createElement('div');
    row.className = 'esg-row';
    row.innerHTML = '<span class="esg-label">'+label+'</span><span class="esg-value">'+value+'</span>';
    esgDiv.appendChild(row);
  }
}

// &#8211;&#8211; Drift Update &#8211;&#8211;
async function updateDrift() {
  const d = await fetchData('drift');
  document.getElementById('dr-obs').textContent = fmtNum(d.total_observations);
  document.getElementById('dr-detected').textContent = fmtNum(d.drift_detected);
  document.getElementById('dr-providers').textContent = fmtNum((d.tracked_providers||[]).length);

  const db = document.getElementById('drift-badge');
  db.textContent = d.drift_detected||0;
  db.className = d.healthy ? 'badge badge-green' : (d.drift_detected>3?'badge badge-red':'badge badge-yellow');

  if(d.healthy) {
    document.getElementById('dr-health').textContent = 'Healthy';
    document.getElementById('dr-health').style.color = 'var(--accent-green)';
  } else {
    document.getElementById('dr-health').textContent = 'Drift Alert';
    document.getElementById('dr-health').style.color = 'var(--accent-red)';
  }

  const byType = d.alerts_by_type||{};
  const typeKeys = Object.keys(byType);
  if(typeKeys.length > 0) {
    makeChart('chart-drift-type','doughnut', typeKeys,
      [{data:typeKeys.map(k=>byType[k]), backgroundColor:typeKeys.map((_,i)=>PALETTE[i%PALETTE.length])}],
      doughnutOpts);
  }
  const bySev = d.alerts_by_severity||{};
  const sevKeys = Object.keys(bySev);
  if(sevKeys.length > 0) {
    const sevColors = {CRITICAL:COLORS.red,WARN:COLORS.yellow,INFO:COLORS.blue};
    makeChart('chart-drift-severity','doughnut', sevKeys,
      [{data:sevKeys.map(k=>bySev[k]), backgroundColor:sevKeys.map(k=>sevColors[k]||COLORS.purple)}],
      doughnutOpts);
  }

  // Alert list
  const alertDiv = document.getElementById('drift-alerts');
  const alerts = d.recent_alerts||[];
  if(alerts.length === 0) {
    alertDiv.innerHTML = '<div class="empty-state"><div class="empty-icon">&#x1F6E1;&#xFE0F;</div><div class="empty-text">No drift alerts &#8212; system is stable</div></div>';
  } else {
    alertDiv.innerHTML = '';
    for(const a of alerts.reverse().slice(0,15)) {
      const sevClass = a.severity==='CRITICAL'?'severity-critical':a.severity==='WARN'?'severity-warn':'severity-info';
      const item = document.createElement('div');
      item.className = 'alert-item';
      item.innerHTML =
        '<div class="alert-severity '+sevClass+'"></div>' +
        '<div class="alert-content">' +
          '<div class="alert-type">'+(a.drift_type||'unknown')+' '+(a.provider?'&#183; '+a.provider+'/'+a.model:'')+'</div>' +
          '<div class="alert-detail">'+(a.detail||'')+'</div>' +
        '</div>' +
        '<div class="alert-time">'+(a.ts?timeAgo(a.ts):'')+'</div>';
      alertDiv.appendChild(item);
    }
  }
}

// &#8211;&#8211; Uptime ticker &#8211;&#8211;
function updateUptime() {
  const s = Math.floor((Date.now()-startTime)/1000);
  const m = Math.floor(s/60);
  const h = Math.floor(m/60);
  document.getElementById('uptime').textContent = h>0?h+'h '+m%60+'m':m>0?m+'m '+s%60+'s':s+'s';
}

// &#8211;&#8211; Main loop &#8211;&#8211;
async function tick() {
  await Promise.all([updateOverview(), updateAPI(), updateRouting(), updateCarbon(), updateDrift()]);
  updateUptime();
}
tick();
setInterval(tick, 2000);
</script>
</body>
</html>"""


# ── HTTP Handler ──────────────────────────────────────────────────

class _DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the dashboard."""

    def do_GET(self):
        if self.path == "/" or self.path == "":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_DASHBOARD_HTML.encode("utf-8"))
        elif self.path.startswith("/api/"):
            section = self.path[5:].split("?")[0].strip("/")
            collector = _COLLECTORS.get(section)
            if collector:
                try:
                    data = collector()
                except Exception:
                    data = {"error": "collection failed"}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(data, default=str).encode("utf-8"))
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"unknown section"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress request logging


# ── Public API ────────────────────────────────────────────────────

def dashboard(port: int = 8765, open_browser: bool = True, background: bool = True) -> str:
    """Start the Correctover dashboard HTTP server.

    Args:
        port: Port to bind the HTTP server to.
        open_browser: Whether to open a browser tab automatically.
        background: Whether to run the server in a background thread.

    Returns:
        The dashboard URL string.
    """
    global _server, _server_port, _server_thread

    if _server is not None:
        url = f"http://localhost:{_server_port}"
        print(f"[Correctover] Dashboard already running at {url}")
        return url

    _server = HTTPServer(("0.0.0.0", port), _DashboardHandler)
    _server_port = port

    def _serve():
        try:
            _server.serve_forever()
        except Exception:
            pass

    if background:
        _server_thread = threading.Thread(target=_serve, daemon=True)
        _server_thread.start()
    else:
        _server_thread = None
        _serve()

    url = f"http://localhost:{port}"
    print(f"[Correctover] Dashboard running at {url}")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    return url


def stop_dashboard():
    """Stop the running dashboard server."""
    global _server, _server_port, _server_thread
    if _server is not None:
        _server.shutdown()
        _server.server_close()
        _server = None
        _server_port = None
        _server_thread = None
        print("[Correctover] Dashboard stopped")


def dashboard_url() -> Optional[str]:
    """Return the current dashboard URL, or None if not running."""
    if _server is not None and _server_port is not None:
        return f"http://localhost:{_server_port}"
    return None


def dashboard_status() -> Dict[str, Any]:
    """Return the current dashboard status."""
    return {
        "running": _server is not None,
        "url": dashboard_url(),
        "port": _server_port,
    }
