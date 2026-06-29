# Correctover MCP — VS Code Extension

<p align="center">
  <strong>🧠 The MCP Reliability Layer for AI</strong><br/>
  <em>Validate, verify, and self-heal every LLM response — automatically.</em>
</p>

<p align="center">
  <a href="https://github.com/Correctover/mcp-server/releases/tag/correctover-vscode-v1.0.0">
    <img src="https://img.shields.io/github/v/release/Correctover/mcp-server?filter=correctover-vscode-*&label=VSIX%20Release&color=00E5FF" alt="VSIX Release">
  </a>
  <a href="https://github.com/Correctover/mcp-server">
    <img src="https://img.shields.io/github/stars/Correctover/mcp-server?style=flat&label=GitHub%20Stars" alt="Stars">
  </a>
  <a href="https://opensource.org/licenses/Apache-2.0">
    <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License">
  </a>
</p>

---

## ✨ Features

### 🔄 MCP Server Lifecycle
Start, stop, and restart the Correctover MCP server directly from VS Code's command palette. No terminal needed.

### 📊 Real-time Dashboard
Sidebar panel showing:
- Server status and health
- Active LLM providers and their models
- Session statistics: total calls, pass rate, failover count
- 6-dimension validation report

### 🔑 9 Provider Configuration
Configure API keys in VS Code settings for all major LLM providers:
- **OpenAI** · **Anthropic** · **DeepSeek** · **Moonshot** · **Zhipu AI**
- **Alibaba Qwen** · **SiliconFlow** · **Groq** · **Together AI**

Proxy/mirror support via base URL overrides.

### 🛡️ 6-Dimension Output Validation
Every LLM response is verified before it reaches you:

| Dimension    | What it checks                              |
|--------------|---------------------------------------------|
| **Structure**  | Valid choices and non-empty content         |
| **Schema**     | Valid finish reason, complete output        |
| **Latency**    | Response time within bounds                 |
| **Cost**       | Token usage is reasonable                   |
| **Identity**   | Correct response role (assistant)           |
| **Integrity**  | No truncation, no broken JSON               |

### ⚡ Auto-Failover
If validation fails: automatically retries with the same provider, or fails over to another provider — and re-validates.

> **Failover ≠ Correctover.** Failover switches providers. Correctover switches *and verifies the output is correct before delivering it*.

### 🔌 Built-in MCP Integration
Registers with VS Code's native MCP tool system (VS Code 1.95+). Your AI tools can call Correctover directly.

---

## 🚀 Quick Start

### Prerequisites
- **VS Code 1.95+**
- **correctover-mcp-server binary** — The Go MCP server

### Install the Extension

**Option A: Install from VSIX (recommended — no VS Marketplace account needed)**

1. Download `correctover-vscode-1.0.0.vsix` from [GitHub Releases](https://github.com/Correctover/mcp-server/releases/tag/correctover-vscode-v1.0.0)
2. Open VS Code → Extensions view (`Ctrl+Shift+X`)
3. Click `...` → **Install from VSIX...**
4. Select the downloaded file

**Option B: VS Marketplace** (publisher registration pending — coming soon)

### Install the Server Binary

**Option A: Download pre-built binary**
```bash
# Download from GitHub Releases
curl -LO https://github.com/Correctover/mcp-server/releases/latest/download/correctover-windows-amd64.exe
# Rename to correctover-server.exe and place in PATH
```

**Option B: Build from source**
```bash
git clone https://github.com/Correctover/mcp-server.git
cd mcp-server
go build -o correctover-server.exe .
```

**Option C: Set custom path**
Set `correctover.serverPath` in VS Code settings to your binary location.

### Configure API Keys
1. Open VS Code Settings (`Ctrl+,`)
2. Search for `correctover.openaiKey` (or any provider)
3. Enter your API key(s)
4. Only configured providers will be active

### Start the Server
1. Press `Ctrl+Shift+P` to open the Command Palette
2. Run **Correctover: Start MCP Server**
3. Open the **Correctover** sidebar to see the dashboard

---

## 📖 Available Commands

| Command | Description |
|---------|-------------|
| `Correctover: Start MCP Server` | Start the Correctover MCP server |
| `Correctover: Stop MCP Server` | Stop the running server |
| `Correctover: Restart MCP Server` | Restart the server |
| `Correctover: Open Dashboard` | Open the Correctover sidebar |
| `Correctover: Check Provider Health` | Show health status of all providers |
| `Correctover: Show Session Stats` | Display session statistics |
| `Correctover: Configure Providers` | Open provider settings |

---

## ⚙️ Extension Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `correctover.serverPath` | Path to the MCP server binary | Auto-detect |
| `correctover.autoStart` | Auto-start server on launch | `false` |
| `correctover.*Key` | API keys for LLM providers | `""` |
| `correctover.*BaseUrl` | Base URL overrides for proxies | `""` |
| `correctover.enableMcpIntegration` | Register with VS Code MCP system | `true` |

---

## 📊 Example Dashboard

When running, the sidebar dashboard shows:

```
┌─ Correctover Dashboard ─────────────────┐
│ ● Running    Server is active            │
│                                          │
│ Session Statistics:                      │
│   Calls: 42  │  Passed: 41  │  97.6%    │
│   Failovers: 1                           │
│                                          │
│ Active Providers:                        │
│   ✅ openai        model: gpt-4o-mini    │
│   ✅ deepseek      model: deepseek-chat  │
│   ✅ anthropic     model: claude-3-haiku │
└──────────────────────────────────────────┘
```

---

## 🏢 Commercial Use

The VS Code extension is **free** (Apache 2.0). It connects to the Correctover MCP server which validates LLM outputs using your own API keys.

For teams needing:
- Custom validation rules
- Advanced self-healing strategies  
- SLA guarantees
- On-premise deployment

→ **[correctover.com](https://correctover.com)**

---

## 🔗 Resources

- **[GitHub Repository](https://github.com/Correctover/mcp-server)** — Source code, issues, releases
- **[Correctover Website](https://correctover.com)** — Product info, pricing, enterprise
- **[Documentation](https://github.com/Correctover/mcp-server/tree/main/docs)** — API examples, architecture docs
- **[Sponsor](https://github.com/sponsors/Correctover)** — Support development

---

## 📝 License

Apache 2.0 — See [LICENSE.txt](LICENSE.txt) for details.

<p align="center">
  <sub>Because failover switches. Correctover verifies.™</sub>
</p>
