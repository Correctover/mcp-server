# Correctover MCP Server

> **The first MCP server that verifies AI outputs in real-time.**

Correctover sits between your AI tool (Cursor, Claude Desktop, Windsurf) and LLM providers, validating every response across **6 dimensions** with automatic self-healing failover.

![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)
![npm](https://img.shields.io/npm/v/correctover-mcp-server)
![Node](https://img.shields.io/badge/node-%3E%3D18-green.svg)
![Glama](https://glama.ai/mcp/servers/Correctover/mcp-server/badge)

## What It Does

When an LLM returns a response, Correctover validates it in real-time:

| Dimension | What It Checks |
|-----------|---------------|
| **Structure** | JSON/YAML well-formedness, required fields present |
| **Schema** | Type correctness, enum compliance, nested object validation |
| **Latency** | Response time within SLA thresholds |
| **Cost** | Token usage and cost within budget limits |
| **Identity** | Output matches expected model/provider identity |
| **Integrity** | No content tampering, hash verification |

If any dimension fails, the engine **auto-retries or fails over** to another provider — then validates again. Every response that reaches your application has passed all 6 checks.

## Quick Start

### Install via npm

```bash
npm install -g correctover-mcp-server
```

### Configure your AI tool

Add to your `mcp.json` (Cursor, Claude Desktop, Windsurf):

```json
{
  "mcpServers": {
    "correctover": {
      "command": "correctover-mcp-server",
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "DEEPSEEK_API_KEY": "sk-..."
      }
    }
  }
}
```

That's it. BYOK (Bring Your Own Key) — your keys stay on your machine. No proxy, no data collection.

## Supported Providers

| Provider | Models | Env Variable |
|----------|--------|-------------|
| OpenAI | GPT-4o, GPT-4o-mini, o1 | `OPENAI_API_KEY` |
| Anthropic | Claude 3.5 Sonnet, Haiku, Opus | `ANTHROPIC_API_KEY` |
| DeepSeek | DeepSeek-V3, DeepSeek-R1 | `DEEPSEEK_API_KEY` |
| Moonshot/Kimi | Moonshot-v1 | `MOONSHOT_API_KEY` |
| Alibaba Qwen | Qwen-Max, Qwen-Plus | `DASHSCOPE_API_KEY` |
| Zhipu/GLM | GLM-4 | `ZHIPU_API_KEY` |
| SiliconFlow | Multiple open models | `SILICONFLOW_API_KEY` |
| Groq | Llama, Mixtral | `GROQ_API_KEY` |
| Together | Llama, Mistral | `TOGETHER_API_KEY` |

Set at least one API key. Correctover auto-detects configured providers.

## Tools

### `chat` — Verified Chat
Send a message to any LLM with automatic 6-dimension validation. Routes through the best provider, validates output, self-heals on failure.

```json
{
  "messages": [{"role": "user", "content": "Generate a JSON config"}],
  "model": "auto"
}
```

**Response includes:**
- The LLM output text
- A validation report showing which dimensions passed/failed
- Failover count (if any)

### `health` — Health Check
Check which providers are configured and ready before starting work.

### `providers` — Provider Details
See detailed configuration for all supported providers (base URLs, models, status).

### `stats` — Session Statistics
Review session metrics: total calls, validation pass rate, failover count, active providers, server version.

### `validation_history` — Validation Records
Query recent validation results with pagination (ring buffer, 500 records). Each record includes provider, model, latency, pass/fail status, score, and failure reasons.

## Prompts

| Prompt | Description |
|--------|-------------|
| `verify-output` | Verify AI-generated content for correctness across 6 dimensions |
| `compare-providers` | Compare responses from multiple providers on the same prompt |
| `reliability-audit` | Run a comprehensive reliability audit on your provider setup |

## How It Works

```
Your AI Tool (Cursor/Claude Desktop)
        │
        ▼
┌─────────────────────────┐
│   Correctover MCP       │
│   ┌───────────────────┐ │
│   │ 6-Dim Validator   │ │
│   │ ┌─ Structure      │ │
│   │ ├─ Schema         │ │
│   │ ├─ Latency        │ │
│   │ ├─ Cost           │ │
│   │ ├─ Identity       │ │
│   │ └─ Integrity      │ │
│   └───────────────────┘ │
│          │              │
│   ┌──────▼──────┐       │
│   │ Failover    │       │
│   │ Engine      │       │
│   └──────┬──────┘       │
└──────────┼──────────────┘
           │
    ┌──────┼──────┬────────┐
    ▼      ▼      ▼        ▼
 OpenAI  Anthropic  DeepSeek  Qwen ...
```

1. **Route** → Select best provider by priority and health
2. **Call** → Send request to LLM provider
3. **Validate** → Run 6-dimension checks on response
4. **Pass?** → If yes, return to your AI tool
5. **Fail?** → Auto-retry or failover to next provider → Go to step 2

## Failover ≠ Correctover

Simple failover just switches providers when one goes down. Correctover switches **and verifies the output is correct** before delivering it. Every response passes through 6-dimension validation — if it fails, the engine auto-retries or fails over, then re-validates.

## Configuration

### Custom Base URLs

For API proxies or compatible endpoints:

```json
{
  "env": {
    "OPENAI_API_KEY": "your-key",
    "OPENAI_BASE_URL": "https://your-proxy.example.com/v1"
  }
}
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | No* | OpenAI API key |
| `ANTHROPIC_API_KEY` | No* | Anthropic API key |
| `DEEPSEEK_API_KEY` | No* | DeepSeek API key |
| `MOONSHOT_API_KEY` | No* | Moonshot/Kimi API key |
| `DASHSCOPE_API_KEY` | No* | Alibaba DashScope (Qwen) |
| `ZHIPU_API_KEY` | No* | Zhipu/GLM API key |
| `SILICONFLOW_API_KEY` | No* | SiliconFlow API key |
| `GROQ_API_KEY` | No* | Groq API key |
| `TOGETHER_API_KEY` | No* | Together AI API key |

*At least one API key is required.

## System Requirements

- Node.js ≥ 18.0.0
- Platform: Linux (amd64/arm64), macOS (amd64/arm64), Windows (amd64)
- The npm installer automatically downloads the correct binary for your platform

## Links

- **Protocol Spec**: [Correctover/standards](https://github.com/Correctover/standards) (CC BY 4.0)
- **npm Package**: [correctover-mcp-server](https://www.npmjs.com/package/correctover-mcp-server)
- **Glama**: [correctover/mcp-server](https://glama.ai/mcp/servers/Correctover/mcp-server)
- **Website**: [correctover.com](https://correctover.com)
- **Issues**: [GitHub Issues](https://github.com/Correctover/mcp-server/issues)

## License

Apache 2.0 © Correctover
