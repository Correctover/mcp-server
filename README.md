# Correctover MCP Server

<p align="center">
  <strong>The Runtime Agent Governance Layer for Enterprise AI</strong><br/>
  <em>Reliability is table stakes. Governance is the moat.</em>
</p>

<p align="center">
  <a href="#installation"><img src="https://img.shields.io/badge/install-1%20line%20JSON-blue" alt="Install"></a>
  <a href="https://github.com/Correctover/mcp-server/stargazers"><img src="https://img.shields.io/github/stars/Correctover/mcp-server" alt="Stars"></a>
  <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"></a>
</p>

---

## What is this?

Correctover is the **Runtime Agent Governance layer for AI** — the first MCP-native system that verifies every LLM response in real-time and enforces **policy**: what an agent can do, which providers it can talk to, what outputs are acceptable, and what to do when things go wrong.

While every other MCP server connects your AI tools to data sources, Correctover sits in the **execution path** — not just routing messages but guaranteeing the correctness of what comes back.

```
Your AI Tool (Cursor/Claude Desktop/Windsurf)
        │
        ▼
┌─────────────────────────────────────────┐
│  Correctover — Runtime Agent Governance │
│                                         │
│  ① Route → picks best provider          │
│  ② Execute → calls LLM API             │
│  ③ Verify → 6-dimension check          │  ← Reliability layer
│  ④ Heal → auto-fix or failover          │
│  ⑤ Audit → log every decision           │  ← Governance layer
│  ⑥ Enforce → RBAC / policy / quota      │  ← Compliance layer
│                                         │
└─────────────────────────────────────────┘
        │
        ▼
  LLM Providers (OpenAI / Anthropic / DeepSeek / ...)
```

> **Failover ≠ Correctover.** Failover switches providers. Correctover switches *and verifies the output is correct before delivering it* — then logs the entire chain as an auditable event.

> AI is at the inflection point from "functional demo" to "enterprise production". Correctover is the **trust layer** that makes this migration possible — solving the #1 blocker CTOs cite for not deploying AI agents at scale.

## Why you need this

AI APIs don't just fail with HTTP 500. The worst failures are **silent**:

- Response looks valid but contains hallucinated data
- JSON output is truncated mid-object
- Provider silently degrades output quality over time
- Token usage spikes without warning

**Correctover catches all of these.** Every response passes through 6-dimension validation:

| Dimension | What it checks |
|-----------|---------------|
| **Structure** | Response has valid choices and non-empty content |
| **Schema** | Finish reason is valid, output format is complete |
| **Latency** | Response time within acceptable bounds |
| **Cost** | Token usage is reasonable (no runaway billing) |
| **Identity** | Response role is correct (assistant, not system/user) |
| **Integrity** | No truncation, no broken JSON, no incomplete data |

If validation fails, Correctover **automatically retries or fails over** to another provider — and validates again. This is not simple retry. This is **verified failover**.

> **Failover ≠ Correctover.** Failover switches providers. Correctover switches *and verifies the output is correct before delivering it*.

## MCP Protocol Compatibility

This server implements the **Model Context Protocol** specification version `2025-11-25`, using JSON-RPC 2.0 over stdio transport.

The protocol layer uses an adapter pattern — adding new transport types (WebSocket, gRPC) in the future will not affect the core validation engine. We track MCP specification updates closely and test compatibility on every protocol version release.

**Supported features:**
- ✅ JSON-RPC 2.0 over stdio
- ✅ `initialize` / `tools/list` / `tools/call` / `notifications`
- ✅ Multi-tool support (chat, verify, providers, health)
- 🔜 WebSocket transport (planned)
- 🔜 Streaming tool results (planned)

## Installation

### One-line JSON config

Add to your MCP client config (e.g., `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "correctover": {
      "command": "npx",
      "args": ["-y", "correctover-mcp-server"],
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "DEEPSEEK_API_KEY": "sk-...",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

That's it. No servers to deploy. No dependencies to install. No configuration files to manage.

### Build from source

```bash
git clone https://github.com/Correctover/mcp-server.git
cd mcp-server
go build -o correctover-mcp-server .

# Then in your MCP config:
# "command": "/path/to/correctover-mcp-server"
```

### VS Code Extension

Install the Correctover VS Code extension for a native editor experience:

1. Download the `.vsix` from the [releases page](https://github.com/Correctover/mcp-server/releases) or build from source
2. In VS Code, press `Ctrl+Shift+P` → `Extensions: Install from VSIX...`
3. Select `correctover-vscode-1.0.0.vsix`
4. Open the Command Palette and run **Correctover: Start MCP Server**
5. Configure API keys in VS Code settings (`correctover.*Key`)
6. Open the **Correctover** sidebar to see the real-time dashboard

**Features:**
- Start/stop/restart the MCP server from the command palette
- Real-time dashboard with health, stats, and provider status
- Status bar indicators
- Configure providers directly in VS Code settings
- Auto-start on launch (configurable)

> Source: [vscode-extension/](vscode-extension/)

## Supported Providers

Configure providers via environment variables. Only configured providers are active.

| Provider | API Key Env | Base URL Override | Default Model |
|----------|------------|-------------------|---------------|
| OpenAI | `OPENAI_API_KEY` | `OPENAI_BASE_URL` | gpt-4o-mini |
| Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL` | claude-3-haiku-20240307 |
| DeepSeek | `DEEPSEEK_API_KEY` | `DEEPSEEK_BASE_URL` | deepseek-chat |
| Moonshot | `MOONSHOT_API_KEY` | `MOONSHOT_BASE_URL` | moonshot-v1-8k |
| Zhipu AI | `ZHIPU_API_KEY` | `ZHIPU_BASE_URL` | glm-4-flash |
| Alibaba Qwen | `DASHSCOPE_API_KEY` | `DASHSCOPE_BASE_URL` | qwen-turbo |
| SiliconFlow | `SILICONFLOW_API_KEY` | `SILICONFLOW_BASE_URL` | deepseek-ai/DeepSeek-V3 |
| Groq | `GROQ_API_KEY` | `GROQ_BASE_URL` | llama-3.1-8b-instant |
| Together AI | `TOGETHER_API_KEY` | `TOGETHER_BASE_URL` | meta-llama/Llama-3-8b-chat-hf |

> **Proxy/Mirror support:** Each provider's base URL can be overridden via `{PROVIDER}_BASE_URL` environment variable. Perfect for self-hosted proxies, API gateways, or regional mirrors (e.g. `OPENAI_BASE_URL=https://your-proxy.com/v1`).

**BYOK (Bring Your Own Key):** Your API keys stay on your machine. Correctover connects directly to providers — no proxy, no middleman, no data leakage.

## Tools

### `chat`

Send a chat message with automatic verification and self-healing.

**Parameters:**
- `messages` (required): Conversation messages in OpenAI format
- `model`: Model name or `"auto"` for automatic selection
- `provider`: Force a specific provider
- `temperature`: Sampling temperature
- `max_tokens`: Maximum response tokens
- `system_prompt`: System prompt to prepend

**Returns:** The LLM response + a validation report showing which dimensions passed/failed.

### `health`

Check which providers are active and ready.

### `providers`

List all supported providers with configuration details.

### `stats`

Show session statistics: total calls, validation pass rate, failover count.

## Example Output

Every `chat` call returns a validation report:

```
╔══════════════════════════════════════╗
║   Correctover Validation Report     ║
╠══════════════════════════════════════╣
║ Provider: deepseek                  ║
║ Latency:  847ms                     ║
║ Model:    deepseek-chat             ║
║ Score:    6/6                       ║
║ Passed:   true                      ║
╠══════════════════════════════════════╣
║ ✅ structure  PASS                   ║
║ ✅ schema     PASS                   ║
║ ✅ latency    PASS                   ║
║ ✅ cost       PASS                   ║
║ ✅ identity   PASS                   ║
║ ✅ integrity  PASS                   ║
╠══════════════════════════════════════╣
║ ✓ All dimensions passed              ║
╚══════════════════════════════════════╝
```

## How it works

1. **Route** — Selects the best available provider based on priority and health
2. **Execute** — Sends the request to the selected provider
3. **Verify** — Validates the response across 6 dimensions
4. **Heal** — If validation fails: auto-retries with same provider, or fails over to next provider, then re-validates
5. **Deliver** — Returns the verified response with a full validation report

This is the **MAPE-K control loop** (Monitor-Analyze-Plan-Execute-Knowledge) applied to LLM API reliability, running in real-time at sub-millisecond decision overhead.

## Who is this for?

- **Developers** who use Cursor/Claude Desktop and want more reliable AI responses
- **Teams** building AI-powered applications who need output guarantees
- **Enterprises** in regulated industries (finance, legal, healthcare) where AI output errors have real consequences
- **Anyone** tired of silently wrong AI outputs breaking their workflow

## FAQ

**Q: How is this different from LiteLLM / OpenRouter?**
A: They route requests. We route + verify outputs. Think of it as the difference between a delivery service and a delivery service with quality inspection.

**Q: Do you store my API keys?**
A: No. Keys stay on your machine. We connect directly to providers. Zero proxy, zero data collection.

**Q: Does this work with Cursor?**
A: Yes. Add the JSON config above to `~/.cursor/mcp.json` and restart Cursor. Done.

**Q: What if I only have one provider?**
A: Still works. You get 6-dimension validation on every response. Failover kicks in when you add more providers later.

## Enterprise Roadmap

Correctover follows an **Open Core** model. The MCP protocol, provider verification, and core validation engine are open source. Enterprise features are designed for regulated industries (finance, legal, healthcare) and large-scale deployments.

| Feature | Open Source | Enterprise |
|---------|:-----------:|:----------:|
| 6-dimension validation (structure/schema/latency/cost/identity/integrity) | ✅ | ✅ |
| Auto-failover across 9+ providers | ✅ | ✅ |
| BYOK — keys stay on your machine | ✅ | ✅ |
| MCP protocol (stdio) | ✅ | ✅ |
| **Audit Ledger** — every Agent call, interception, and fix logged as compliance-ready events | — | ✅ |
| **Multi-tenant RBAC** — prevent Confused Deputy attacks per Agent scope | — | ✅ |
| **Private validation model** — on-premises verification without data leaving your VPC | — | ✅ |
| **Drift database** — aggregated production failure patterns across 100K+ calls | — | ✅ |
| **WebSocket transport** — real-time streaming with validation | — | ✅ |
| **SLA guarantee** — 99.9% uptime, dedicated support | — | ✅ |
| **Custom validation rules** — domain-specific contracts (HIPAA, SOC2, PCI) | — | ✅ |

> **Why Open Core works for you:** Developers get the best open-source validation engine. CTOs get the audit trail and compliance they need to approve AI in production. No feature crippling. No bait-and-switch. Clear boundaries.

## Data Moat

Every Correctover deployment collects **anonymized drift patterns** — which providers fail on which inputs, which validation dimensions trigger most often, which failover strategies succeed. Over time, this dataset becomes a unique asset: the **largest known corpus of LLM production failure patterns**.

This data directly informs:
- **Predictive failover** — before a provider fails, Correctover knows it's trending toward failure
- **Benchmark accuracy** — real-world reliability scores, not synthetic benchmarks
- **Industry reports** — the *2026 MCP Production-Grade Security White Paper* (coming Q3 2026)

Enterprise deployments can opt out of telemetry entirely. The data moat is powered by opt-in telemetry from the open-source tier.

## Sponsor

If Correctover saves you from a silent AI failure, consider supporting:

- ☕ **$5/month** — Thank you + priority issue responses
- 🚀 **$29/month** — Private Discord + monthly update briefings
- 🏢 **$99/month** — Enterprise sponsor, logo on README

**[→ Sponsor on GitHub](https://github.com/sponsors/Correctover)**

## Need Help Integrating?

For team deployments, custom validation rules, or dedicated support:

📧 **hello@correctover.com**

## License & Commercial

This project is **Apache 2.0** licensed for the core MCP protocol and provider implementation. The license verification system (`license/` package) enables commercial features:

| Plan | Price | Providers | Features |
|------|-------|-----------|----------|
| **Free** | $0 | Up to 2 | Unlimited chat + auto-failover + 6-dimension validation |
| **Pro** | $99/yr | Unlimited | All 9+ providers, priority support |
| **Enterprise** | $1,499/mo | Unlimited | Private deployment, SLA, custom validation rules |

### Pro Activation

```bash
# Set your Pro/Enterprise license key
export CORRECTOVER_LICENSE_KEY="CV-PRO-<base64_payload.hmac_signature>"

# Or with custom HMAC secret (for self-built binaries)
export CORRECTOVER_HMAC_KEY="your-hmac-secret"
```

The server prints your current plan on startup and enforces provider limits at runtime.
License verification is offline (HMAC-SHA256) with optional device fingerprint binding.
No data is sent to external servers — your privacy is preserved.

**Get a license:** hello@correctover.com

---

## Project Map

```
correctover/
├── main.go               # MCP Server 入口
├── go.mod                # Go 模块
├── smithery.yaml         # Smithery 部署
├── glama.json            # Glama.ai 注册
│
├── license/              # License 验证系统
├── mcp/                  # MCP 协议实现
├── provider/             # 9 LLM Provider 管理
├── validator/            # 6 维契约验证
├── registry/             # MCP Registry 配置
├── sdk/                  # Python SDK（编译分发版）
├── vscode-extension/     # VS Code Extension
├── web/                  # Web Demo（地球可视化/控制台）
├── video/                # Remotion 品牌宣传视频
├── marketing/            # BD 营销内容（文章/邮件/社媒/GEO）
│   ├── articles/         #   博客文章
│   ├── emails/           #   BD 获客邮件
│   ├── social/           #   社交媒体
│   ├── geo/              #   GEO 优化
│   └── scripts/          #   自动化脚本
├── docs/                 # 技术文档 & API 示例
├── scripts/              # CI/构建脚本
└── .github/workflows/    # GitHub Actions
```

---

<p align="center">
  <strong>Because failover switches. Correctover verifies.™</strong>
</p>
