# Correctover — MCP Runtime Security

> **The runtime security layer for the MCP ecosystem.**

We build the runtime security layer for AI agent ecosystems. Correctover enforces security conformance on every MCP tool call — validating LLM outputs, blocking injection attacks, preventing credential hijacking, and auto-recovering from failures at 22μs P50 latency.

![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)
![npm](https://img.shields.io/npm/v/correctover-mcp-server?label=npm%20%7C%20correctover-mcp-server)
![npm](https://img.shields.io/npm/v/correctover?label=npm%20%7C%20correctover)
![PyPI](https://img.shields.io/pypi/v/correctover?label=pypi%20%7C%20correctover)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21234580.svg)](https://doi.org/10.5281/zenodo.21234580)

---

## What We Do

| Layer | What | Where |
|-------|------|-------|
| **Runtime Verification** | 6-dimension output validation (structure, schema, latency, cost, identity, integrity) + auto-failover | `correctover-mcp-server` |
| **Agent Governance SDK** | Synchronous interceptor-based governance — fail-closed by design | `correctover-ccs` (PyPI) |
| **Security Audits** | MCP protocol vulnerability research — CVE-class findings across 50+ implementations | [mcp-security-audits](https://github.com/Correctover/mcp-security-audits) |
| **Conformance Standard** | CCS v1.0 — formal standard for agentic runtime verification | [standards](https://github.com/Correctover/standards) |
| **Fault Taxonomy** | 215 fault types, 19 CVEs, 561 fault variants cataloged | Internal knowledge base |

---

## Real Data — Not Benchmarks

We don't simulate. We collect real API responses from production MCP servers and verify them.

### 20,000 Verified API Traces

| Dataset | Records | Size | Format |
|---------|---------|------|--------|
| CCS 20K Verification Subset | 20,000 | 18 MB | JSONL ([download](./data/Correctover-CCS-20K-Verification-Subset.jsonl)) |

**Collection methodology:**
- 43.6 minutes of continuous collection at 13.7 API calls/second
- 68.88% conformance rate (13,776 conformant / 6,224 non-conformant)
- 30% fault injection rate for stress testing
- Every record includes: request, response, latency, validation result, fault classification

**Third-party independent verification:** 120,426 conformance re-calculations by [@babyblueviper1](https://github.com/babyblueviper1) — full consistency confirmed.

The complete 20K dataset is in `./data/` — download, verify, fork, do whatever you want. No gatekeeping.

---

## Research & Publications

### CCS v1.0 — Runtime Security Conformance Standard

The first formal conformance standard defining how agent runtimes should validate tool execution results at runtime.

- **Paper:** [CCS Standard v1.0 Final (PDF)](./papers/CCS-Standard-v1.0.pdf)
- **DOI:** [10.5281/zenodo.21234580](https://doi.org/10.5281/zenodo.21234580)
- **Protocol Spec:** [RFC-001](https://github.com/Correctover/standards/blob/main/docs/RFC-001-CCS-Protocol-Specification.md) | [RFC-002](https://github.com/Correctover/standards/blob/main/docs/RFC-002-CCS-Symbol-Standard.md)

**Key findings from 20K real traces:**
- P50 validation latency: **22μs**
- Self-heal rate: **97.4%** (engine auto-retries/fails over on failed validation, then re-validates)
- Rule coverage: 88 detection rules (64 high-confidence)
- 561 distinct fault variants cataloged across all major LLM providers

### Fault Taxonomy

We maintain a living fault taxonomy derived from real-world MCP server failures:
- **215 distinct fault types** classified across 7 severity levels
- **19 CVE-class vulnerabilities** identified across MCP implementations
- Categories: RCE, SSRF, cloud credential hijacking, path traversal, output injection, privilege escalation

---

## Upstream PR Contributions

We don't just report — we fix. Our contributions go directly into major agent frameworks:

| PR | Framework | Status | What |
|----|-----------|--------|------|
| [ferro-labs#197](https://github.com/ferro-labs/ferro-labs/pull/197) | Ferro Labs | OPEN | Runtime validation integration |
| [CrewAI#6432](https://github.com/crewAIInc/crewAI/pull/6432) | CrewAI | 10 commits | GuardrailProvider — runtime governance protocol |
| [CrewAI#6411](https://github.com/crewAIInc/crewAI/pull/6411) | CrewAI | Discussion | Defining runtime verification authority |
| [agent-governance-toolkit#3347](https://github.com/microsoft/agent-governance-toolkit/pull/3347) | Microsoft | Under review | Runtime threat scanner — recursive nested-arg scanning, SSRF gaps, credential redaction, path boundary fixes |

---

## Community Validation

Real researchers using our work in production:

| Researcher | Framework | Contribution |
|-----------|-----------|-------------|
| [@pshkv](https://github.com/pshkv) (AutoGen maintainer) | AutoGen | Adopted Required(τ)⊆Supported(τ) framework for tool governance |
| [@humbl-dev](https://github.com/humbl-dev) | CrewAI | Testing two-layer governance structure |
| [@safal207](https://github.com/safal207) | CrewAI | Implemented GuardrailProvider based on our design (10 commits) |
| [@babyblueviper1](https://github.com/babyblueviper1) | Independent | 120,426 independent conformance re-calculations |
| [@Tuttotorna](https://github.com/Tuttotorna) | PHI-OMEGA | ICLR paper collaboration on runtime verification |
| [@XYG-LUNA](https://github.com/XYG-LUNA) | CrewAI | Idempotency analysis and interaction |

---

## MCP Server — Product

The runtime verification engine packaged as an MCP server for your AI tools.

### Quick Start

```bash
npm install -g correctover-mcp-server
```

Add to your `mcp.json` (Cursor, Claude Desktop, Windsurf):

```json
{
  "mcpServers": {
    "correctover": {
      "command": "correctover-mcp-server",
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

BYOK — your keys stay on your machine. No proxy, no data collection.

### How It Works

```
Your AI Tool (Cursor / Claude Desktop / Windsurf)
        │
        ▼
┌─────────────────────────────┐
│   Correctover MCP Server    │
│   ┌───────────────────────┐ │
│   │  6-Dim Validator      │ │
│   │  ├─ Structure         │ │
│   │  ├─ Schema            │ │
│   │  ├─ Latency           │ │
│   │  ├─ Cost              │ │
│   │  ├─ Identity          │ │
│   │  └─ Integrity         │ │
│   └───────────────────────┘ │
│          │                  │
│   ┌──────▼──────┐           │
│   │ Failover    │           │
│   │ Engine      │           │
│   └──────┬──────┘           │
└──────────┼──────────────────┘
           │
    ┌──────┼──────┬──────────┐
    ▼      ▼      ▼          ▼
 OpenAI  Anthropic  DeepSeek  Qwen ...
```

### Supported Providers

| Provider | Models | Env Variable |
|----------|--------|-------------|
| OpenAI | GPT-4o, GPT-4o-mini, o1 | `OPENAI_API_KEY` |
| Anthropic | Claude 3.5 Sonnet, Haiku, Opus | `ANTHROPIC_API_KEY` |
| DeepSeek | DeepSeek-V3, DeepSeek-R1 | `DEEPSEEK_API_KEY` |
| Moonshot/Kimi | Moonshot-v1 | `MOONSHOT_API_KEY` |
| Alibaba Qwen | Qwen-Max, Qwen-Plus | `DASHSCOPE_API_KEY` |
| Groq | Llama, Mixtral | `GROQ_API_KEY` |
| Together | Llama, Mistral | `TOGETHER_API_KEY` |

### Tools

| Tool | Description |
|------|-------------|
| `chat` | Verified chat — 6-dim validation + auto-failover |
| `health` | Check provider status |
| `providers` | Detailed provider configuration |
| `stats` | Session metrics: calls, pass rate, failover count |
| `validation_history` | Query recent validation results (ring buffer, 500 records) |

---

## Ecosystem Adoption

Real download numbers from public package registries (last 30 days):

| Package | Registry | Monthly Downloads |
|---------|----------|-------------------|
| correctover-mcp-server | npm | 1,564 |
| correctover | npm | 1,034 |
| correctover-ccs | npm | 400 |
| correctover | PyPI | 1,436 |
| **Total** | | **4,434/month** |

All organic growth — no paid promotion. CCS standard package seeing highest growth rate (tens of thousands percent increase from baseline).

---

## CCS SDK — Agent Governance

Python SDK for embedding governance into agent frameworks. Fail-closed by design.

```bash
pip install correctover-ccs
```

```python
from ccs import govern

@govern(policy="default")
def my_tool(args: dict) -> str:
    return "result"

# Governance evaluates BEFORE function runs
# If denied → PermissionError, function never executes
```

**Supported frameworks:** CrewAI, AutoGen, LangGraph/LangChain

```
Observer hooks (default):  governance_crash → tool EXECUTES ❌
CCS decorators (ours):     governance_crash → tool BLOCKED ✅
```

---

## Security Audit Reports

We publish detailed security audits of MCP server implementations:

→ [mcp-security-audits](https://github.com/Correctover/mcp-security-audits)

**Methodology:** Source code analysis → fault injection → runtime verification → CVE classification

**Findings to date:** 506 security findings across 3 major repositories, 5 vulnerability types confirmed cross-repo.

---

## Ecosystem & Links

| Resource | Link |
|----------|------|
| CCS Standard (paper) | [DOI: 10.5281/zenodo.21234580](https://doi.org/10.5281/zenodo.21234580) |
| CCS Standard (GitHub) | [Correctover/standards](https://github.com/Correctover/standards) |
| MCP Server (npm) | [correctover-mcp-server](https://www.npmjs.com/package/correctover-mcp-server) |
| CCS SDK (PyPI) | [correctover](https://pypi.org/project/correctover/) |
| Security Audits | [Correctover/mcp-security-audits](https://github.com/Correctover/mcp-security-audits) |
| Agent Governance | [Correctover/agent-governance-toolkit](https://github.com/Correctover/agent-governance-toolkit) (fork with PRs) |
| Glama | [correctover/mcp-server](https://glama.ai/mcp/servers/Correctover/mcp-server) |
| Protocol Spec | [standards/docs/RFC-001](https://github.com/Correctover/standards/blob/main/docs/RFC-001-CCS-Protocol-Specification.md) |
| Website | [correctover.com](https://correctover.com) |

---

## Contact

**Security reports**: wangguigui@correctover.com  
**BD / Enterprise**: wangguigui@correctover.com  
**GitHub**: [@Correctover](https://github.com/Correctover)

## License

Apache 2.0 © Correctover
