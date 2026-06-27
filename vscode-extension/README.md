# Correctover MCP — VS Code Extension

**The MCP Reliability Layer for AI.** Real-time LLM output verification and self-healing, running directly inside VS Code.

## Features

- **MCP Server Lifecycle** — Start, stop, and restart the Correctover MCP server from the command palette
- **Real-time Dashboard** — Sidebar panel showing server status, active providers, and session statistics
- **Provider Configuration** — Configure API keys (OpenAI, Anthropic, DeepSeek, and 6 more providers) directly in VS Code settings
- **Status Bar** — At-a-glance server status and call statistics
- **6-Dimension Output Validation** — Every LLM response is verified for structure, schema, latency, cost, identity, and integrity
- **Auto-Failover** — If validation fails, automatically retry or fail over to another provider
- **Built-in MCP Integration** — Registers with VS Code's MCP tool system (VS Code 1.95+)

## Quick Start

1. Install the extension
2. Open the Command Palette (`Ctrl+Shift+P`) and run **Correctover: Start MCP Server**
3. Configure at least one API key in VS Code settings (`correctover.*Key`)
4. Open the **Correctover** sidebar to see the dashboard

## Requirements

- **VS Code 1.95+** — The extension uses the latest VS Code API features
- **correctover-mcp-server binary** — The Go MCP server. Either:
  - Download the pre-built binary from [GitHub Releases](https://github.com/Correctover/mcp-server/releases)
  - Build from source: `go build -o correctover-server .` in the mcp-server repo
  - Set the path in settings: `correctover.serverPath`

## Available Commands

| Command | Description |
|---------|-------------|
| `Correctover: Start MCP Server` | Start the Correctover MCP server |
| `Correctover: Stop MCP Server` | Stop the running server |
| `Correctover: Restart MCP Server` | Restart the server |
| `Correctover: Open Dashboard` | Open the Correctover sidebar |
| `Correctover: Check Provider Health` | Show health status of all providers |
| `Correctover: Show Session Stats` | Display session statistics |
| `Correctover: Configure Providers` | Open provider settings |

## Extension Settings

| Setting | Description |
|---------|-------------|
| `correctover.serverPath` | Path to the correctover-mcp-server binary |
| `correctover.autoStart` | Auto-start server when VS Code launches |
| `correctover.*Key` | API keys for each supported LLM provider |
| `correctover.*BaseUrl` | Base URL overrides for proxies/mirrors |
| `correctover.enableMcpIntegration` | Register with VS Code's built-in MCP system |

## Supported Providers

OpenAI · Anthropic · DeepSeek · Moonshot · Zhipu AI · Alibaba Qwen · SiliconFlow · Groq · Together AI

## License

Apache-2.0
