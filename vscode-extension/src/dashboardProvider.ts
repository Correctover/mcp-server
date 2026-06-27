import * as vscode from 'vscode';
import { ServerManager } from './serverManager';

/**
 * WebView provider for the Correctover dashboard sidebar panel.
 */
export class DashboardProvider implements vscode.WebviewViewProvider {
  private _view?: vscode.WebviewView;
  private _refreshTimer: NodeJS.Timeout | null = null;

  constructor(
    private readonly _extensionUri: vscode.Uri,
    private readonly _serverManager: ServerManager
  ) {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };

    webviewView.webview.html = this._getHtml();

    // Handle messages from the webview
    webviewView.webview.onDidReceiveMessage(async (message) => {
      switch (message.command) {
        case 'start':
          vscode.commands.executeCommand('correctover.start');
          break;
        case 'stop':
          vscode.commands.executeCommand('correctover.stop');
          break;
        case 'restart':
          vscode.commands.executeCommand('correctover.restart');
          break;
        case 'refresh':
          await this._refreshData();
          break;
        case 'configure-providers':
          vscode.commands.executeCommand('correctover.configureProviders');
          break;
        case 'open-settings':
          vscode.commands.executeCommand('workbench.action.openSettings', 'correctover');
          break;
      }
    });

    // Auto-refresh every 10 seconds while visible
    this._startAutoRefresh();

    // Initial data load
    setTimeout(() => this._refreshData(), 500);

    webviewView.onDidDispose(() => {
      this._stopAutoRefresh();
    });
  }

  refresh(): void {
    this._refreshData();
  }

  private async _refreshData(): Promise<void> {
    if (!this._view) return;

    const mcp = this._serverManager.mcpClient;
    const state = this._serverManager.state;

    // Build status payload
    const payload: Record<string, unknown> = {
      state,
      providers: [],
      stats: null,
      health: null,
    };

    if (mcp?.ready) {
      try {
        const [healthText, statsText] = await Promise.all([
          mcp.health().catch(() => null),
          mcp.stats().catch(() => null),
        ]);
        payload.health = healthText;
        payload.stats = statsText;

        // Parse providers from health output
        if (healthText) {
          const providerLines: Array<{ name: string; model: string }> = [];
          const lines = healthText.split('\n');
          for (const line of lines) {
            const match = line.match(/✅\s+(\S+)\s+model:\s+(.+)/);
            if (match) {
              providerLines.push({ name: match[1], model: match[2].trim() });
            }
          }
          payload.providers = providerLines;
        }
      } catch {
        // Server might have stopped between check and request
      }
    }

    this._view.webview.postMessage({ command: 'update', ...payload });
  }

  private _startAutoRefresh(): void {
    this._stopAutoRefresh();
    this._refreshTimer = setInterval(() => this._refreshData(), 10000);
  }

  private _stopAutoRefresh(): void {
    if (this._refreshTimer) {
      clearInterval(this._refreshTimer);
      this._refreshTimer = null;
    }
  }

  private _getHtml(): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';" />
  <title>Correctover Dashboard</title>
  <style>
    :root {
      --bg: #0d1117;
      --bg-card: #161b22;
      --bg-hover: #1c2333;
      --border: #30363d;
      --text: #e6edf3;
      --text-muted: #8b949e;
      --green: #3fb950;
      --red: #f85149;
      --yellow: #d29922;
      --blue: #58a6ff;
      --cyan: #79c0ff;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 13px;
      padding: 12px;
      line-height: 1.5;
    }
    .section { margin-bottom: 16px; }
    .section-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 8px;
      font-weight: 600;
    }
    .card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
    }
    .card + .card { margin-top: 8px; }

    /* Status indicator */
    .status-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .status-dot {
      width: 10px; height: 10px;
      border-radius: 50%;
      display: inline-block;
      flex-shrink: 0;
    }
    .status-dot.running { background: var(--green); box-shadow: 0 0 8px var(--green); }
    .status-dot.starting { background: var(--yellow); animation: pulse 1s infinite; }
    .status-dot.error { background: var(--red); box-shadow: 0 0 8px var(--red); }
    .status-dot.stopped { background: var(--text-muted); }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.4; }
    }
    .status-label { font-weight: 600; font-size: 14px; }
    .status-text { color: var(--text-muted); font-size: 12px; }

    .btn-row { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
    .btn {
      background: #21262d;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 5px 12px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 12px;
      white-space: nowrap;
      transition: background .15s;
    }
    .btn:hover { background: #30363d; }
    .btn-primary {
      background: #238636;
      border-color: #2ea043;
      color: #fff;
    }
    .btn-primary:hover { background: #2ea043; }
    .btn-danger {
      background: #da3633;
      border-color: #f85149;
      color: #fff;
    }
    .btn-danger:hover { background: #f85149; }

    /* Provider list */
    .provider-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 6px 0;
      border-bottom: 1px solid var(--border);
      font-size: 12px;
    }
    .provider-item:last-child { border-bottom: none; }
    .provider-name { font-weight: 500; }
    .provider-model { color: var(--text-muted); font-size: 11px; }

    /* Stats grid */
    .stats-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .stat-item {
      background: rgba(255,255,255,0.03);
      border-radius: 6px;
      padding: 8px;
      text-align: center;
    }
    .stat-value {
      font-size: 18px;
      font-weight: 700;
      color: var(--cyan);
    }
    .stat-label {
      font-size: 10px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-top: 2px;
    }

    /* Validation report */
    .validation-detail {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 4px;
      margin-top: 8px;
    }
    .dimension {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11px;
      padding: 4px 6px;
      border-radius: 4px;
    }
    .dimension.pass { color: var(--green); }
    .dimension.fail { color: var(--red); }

    .empty-state {
      text-align: center;
      padding: 20px 10px;
      color: var(--text-muted);
    }
    .empty-state h3 { margin-bottom: 6px; font-size: 14px; }
    .empty-state p { font-size: 12px; line-height: 1.6; }

    .loading {
      text-align: center;
      padding: 16px;
      color: var(--text-muted);
      font-size: 12px;
    }

    .error-box {
      background: rgba(248,81,73,0.1);
      border: 1px solid rgba(248,81,73,0.3);
      border-radius: 6px;
      padding: 8px;
      color: var(--red);
      font-size: 11px;
      margin-top: 8px;
    }
  </style>
</head>
<body>
  <div id="app">
    <div class="section" id="status-section">
      <div class="section-title">Server Status</div>
      <div class="card">
        <div class="status-bar">
          <div>
            <span class="status-dot stopped" id="statusDot"></span>
            <span class="status-label" id="statusLabel">Stopped</span>
          </div>
          <span class="status-text" id="statusText">Ready to start</span>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" id="btnStart" onclick="post('start')">Start</button>
          <button class="btn btn-danger" id="btnStop" onclick="post('stop')" style="display:none">Stop</button>
          <button class="btn" id="btnRestart" onclick="post('restart')" style="display:none">Restart</button>
          <button class="btn" onclick="post('refresh')">Refresh</button>
          <button class="btn" onclick="post('configure-providers')">Configure</button>
        </div>
        <div id="errorBox" class="error-box" style="display:none"></div>
      </div>
    </div>

    <div class="section" id="stats-section" style="display:none">
      <div class="section-title">Session Statistics</div>
      <div class="card">
        <div class="stats-grid" id="statsGrid">
          <div class="stat-item"><div class="stat-value" id="statCalls">0</div><div class="stat-label">Calls</div></div>
          <div class="stat-item"><div class="stat-value" id="statPassed">0</div><div class="stat-label">Passed</div></div>
          <div class="stat-item"><div class="stat-value" id="statPassRate">0%</div><div class="stat-label">Pass Rate</div></div>
          <div class="stat-item"><div class="stat-value" id="statFailovers">0</div><div class="stat-label">Failovers</div></div>
        </div>
      </div>
    </div>

    <div class="section" id="providers-section" style="display:none">
      <div class="section-title">Active Providers</div>
      <div class="card" id="providerList"></div>
    </div>

    <div class="section" id="quick-actions">
      <div class="section-title">Quick Actions</div>
      <div class="card">
        <div class="btn-row">
          <button class="btn" onclick="post('open-settings')">⚙ Settings</button>
        </div>
      </div>
    </div>

    <div class="section" id="empty-state">
      <div class="card empty-state">
        <h3>Correctover MCP</h3>
        <p>MCP Reliability Layer for AI.<br>
        Start the server to enable real-time LLM output verification and self-healing.</p>
        <div style="margin-top:12px">
          <button class="btn btn-primary" onclick="post('start')">Start Server</button>
        </div>
      </div>
    </div>
  </div>

  <script>
    const vscode = acquireVsCodeApi();

    function post(command) {
      vscode.postMessage({ command });
    }

    window.addEventListener('message', (event) => {
      const msg = event.data;
      switch (msg.command) {
        case 'update':
          updateDashboard(msg);
          break;
      }
    });

    function updateDashboard(data) {
      // Status
      const state = data.state || 'stopped';
      const dot = document.getElementById('statusDot');
      const label = document.getElementById('statusLabel');
      const text = document.getElementById('statusText');
      const btnStart = document.getElementById('btnStart');
      const btnStop = document.getElementById('btnStop');
      const btnRestart = document.getElementById('btnRestart');
      const errorBox = document.getElementById('errorBox');
      const emptyState = document.getElementById('empty-state');

      dot.className = 'status-dot ' + state;

      switch (state) {
        case 'running':
          label.textContent = 'Running';
          text.textContent = 'Server is active';
          btnStart.style.display = 'none';
          btnStop.style.display = 'inline-block';
          btnRestart.style.display = 'inline-block';
          errorBox.style.display = 'none';
          emptyState.style.display = 'none';
          document.getElementById('stats-section').style.display = 'block';
          document.getElementById('providers-section').style.display = 'block';
          break;
        case 'starting':
          label.textContent = 'Starting...';
          text.textContent = 'Initializing MCP connection';
          btnStart.style.display = 'none';
          btnStop.style.display = 'inline-block';
          btnRestart.style.display = 'none';
          errorBox.style.display = 'none';
          break;
        case 'error':
          label.textContent = 'Error';
          text.textContent = 'Server encountered an error';
          btnStart.style.display = 'inline-block';
          btnStop.style.display = 'none';
          btnRestart.style.display = 'inline-block';
          errorBox.style.display = 'block';
          emptyState.style.display = 'none';
          break;
        default: // stopped
          label.textContent = 'Stopped';
          text.textContent = 'Server is not running';
          btnStart.style.display = 'inline-block';
          btnStop.style.display = 'none';
          btnRestart.style.display = 'none';
          errorBox.style.display = 'none';
          emptyState.style.display = 'block';
          document.getElementById('stats-section').style.display = 'none';
          document.getElementById('providers-section').style.display = 'none';
      }

      // Stats
      if (data.stats) {
        const calls = data.stats.match(/Total Calls:\s+(\d+)/);
        const passed = data.stats.match(/Validation Passed:\s+(\d+)/);
        const passRate = data.stats.match(/Validation Passed:\s+\d+ \(([\d.]+%)\)/);
        const failovers = data.stats.match(/Failovers:\s+(\d+)/);
        if (calls) document.getElementById('statCalls').textContent = calls[1];
        if (passed) document.getElementById('statPassed').textContent = passed[1];
        if (passRate) document.getElementById('statPassRate').textContent = passRate[1];
        if (failovers) document.getElementById('statFailovers').textContent = failovers[1];
      }

      // Providers
      if (data.providers && data.providers.length > 0) {
        const list = document.getElementById('providerList');
        list.innerHTML = data.providers.map(p =>
          '<div class="provider-item">' +
          '<span class="provider-name">' + p.name + '</span>' +
          '<span class="provider-model">' + p.model + '</span>' +
          '</div>'
        ).join('');
      } else if (data.state === 'running') {
        document.getElementById('providerList').innerHTML =
          '<div style="color:var(--text-muted);font-size:12px;text-align:center;padding:8px;">No providers configured. Set API keys in settings.</div>';
      }
    }

    // Request initial data
    post('refresh');
  </script>
</body>
</html>`;
  }
}
