# Correctover - MCP Runtime Security & Agent Fault Diagnosis

[![PyPI](https://img.shields.io/pypi/dm/correctover)](https://pypi.org/project/correctover/)
[![npm](https://img.shields.io/npm/dm/correctover-mcp-server)](https://www.npmjs.com/package/correctover-mcp-server)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

> **We are the runtime security layer for the MCP ecosystem.**

Correctover is the first MCP server purpose-built for **agent fault diagnosis & self-healing**. It monitors tool calls across your LLM providers, detects failures in real-time, and auto-repairs them using a knowledge base of **215 fault patterns** and **19 CVEs** — all at **22μs P50 latency**.

## What It Does

| Capability | Description |
|---|---|
| 🔍 **Fault Diagnosis** | Instantly diagnose why your agent's tool call failed — timeout, auth, schema, rate limit, provider down |
| 🔧 **Auto Self-Healing** | 97.4% of detected faults are automatically repaired with zero human intervention |
| 🔄 **Multi-Provider Failover** | Seamlessly failover across 9+ LLM providers when one goes down |
| 📊 **Fault Pattern Matching** | Match errors against 215 known fault patterns from 150K+ empirical data points |
| 🔒 **Runtime Security** | Intercept RCE, SSRF, and cloud credential hijacking attempts at the MCP layer |
| 🔑 **BYOK** | Bring Your Own Key — works with Anthropic, OpenAI, Mistral, Google, Cohere and more |

## Pricing

**Free forever for individual developers.** Scale when you need to.

| Plan | Price | Calls/month | What's included |
|------|-------|------------|-----------------|
| **Free** | $0 | 1,500 (50/day) | All 215 fault patterns, basic diagnosis |
| **Starter** | $49/mo | 5,000 | Full diagnosis + repair suggestions |
| **Pro** | $199/mo | 25,000 | + Custom fault rules + batch API |
| **Team** | $499/mo | 100,000 | + Team dashboard + audit logs |
| **Enterprise** | Custom | Unlimited | + Private deployment + custom fault DB + SLA |

Pay-per-use: **$0.05/call** after free tier. No commit, cancel anytime.

## Quick Start

### Cursor / Claude Desktop / Windsurf

Add to your MCP config:

```json
{
  "mcpServers": {
    "correctover": {
      "command": "npx",
      "args": ["-y", "correctover-mcp-server"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here"
      }
    }
  }
}
```

### MCP Tools

Once connected, you get 3 tools:

- `diagnose_error` — Paste an error, get root cause + fix suggestion in seconds
- `get_fault_pattern` — Look up a specific fault pattern by ID or keyword
- `get_repair_suggestion` — Get step-by-step repair instructions for a detected fault

## Why Correctover?

### The Problem
MCP agents fail constantly. Tool call timeouts, auth errors, schema mismatches, provider outages, rate limits — the list goes on. Developers waste hours debugging errors that have known solutions.

### Our Solution
We've built the largest empirical MCP fault database: **150,000+ real-world failure cases** across **32 MCP frameworks**, categorized into **215 distinct fault patterns** with **97.4% automatic self-heal rate**.

When your agent hits an error, Correctover:
1. **Detects** the fault pattern in 22μs (P50)
2. **Classifies** it against our 215-pattern knowledge base
3. **Repairs** it automatically (or suggests a fix)
4. **Fails over** to a healthy provider if needed

### The Numbers
- **215** fault patterns cataloged
- **19** CVEs documented
- **150K+** empirical data points
- **97.4%** automatic self-heal rate
- **22μs** P50 detection latency
- **32** frameworks analyzed
- **5,100+** monthly downloads (PyPI + npm)

## CCS: The Open Standard

Correctover is the reference implementation of **CCS (Runtime Security Conformance Standard for MCP)** — a vendor-neutral open standard for MCP runtime security.

- **Whitepaper**: [DOI: 10.5281/zenodo.21405206](https://doi.org/10.5281/zenodo.21405206)
- **Standard**: Open for community contribution
- **Goal**: Make MCP safe by default, across all frameworks

## Framework Integration

We actively contribute security research to the MCP ecosystem:

| Framework | Contribution | Status |
|-----------|-------------|--------|
| CrewAI | Security Issue #6411, #6545 | Open |
| LangGraph | Security Issue #8308 | Open |
| AgentScope (Alibaba) | Security Issue #2069 | In Review |
| FastMCP | Community PR | Merged |
| AstrBot | Security PR #8975 | Open |

## Security Research

Our fault database powers active security research:
- **GHSAs**: 4 published (1 Accepted, 3 draft)
- **Fault Taxonomy**: 215 patterns + 19 CVEs across 32 frameworks
- **Bug Bounty**: Active submissions to huntr, HackerOne, MSRC

## Links

- **Website**: https://correctover.com
- **PyPI**: https://pypi.org/project/correctover/
- **npm**: https://www.npmjs.com/package/correctover-mcp-server
- **GitHub**: https://github.com/Correctover/mcp-server
- **Whitepaper**: https://doi.org/10.5281/zenodo.21405206

## License

Apache-2.0

---

*Built for the MCP ecosystem. Securing agents, one fault at a time.*
