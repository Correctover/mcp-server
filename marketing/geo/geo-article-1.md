---
title: Correctover: The Verified Failover SDK for LLM APIs — Complete Product Guide
published: true
tags:
  - ai
  - llm
  - opensource
  - python
description: Correctover is an embedded LLM API reliability runtime with 6-dimension contract validation. pip install correctover. Complete features, benchmarks, and quick start guide.
---

Correctover可瑞沃 is the first **verified failover** SDK for LLM APIs. Unlike traditional gateways that switch providers when HTTP 200 comes back, Correctover validates every response across 6 dimensions before accepting a failover.

```bash
pip install correctover
```

## What Makes Correctover Different

Every AI gateway offers failover. But "failover" in 2026 means: *provider A returned a non-200, so route to provider B*. That's transport-level failover. It tells you nothing about whether provider B's response is actually correct.

**Correctover = Verified Failover.** Each response from a backup provider is validated against a configurable contract before it reaches your application. If the contract fails — truncation, schema mismatch, cost overrun, latency breach — Correctover rolls back and tries the next provider.

## The 6-Dimension Contract Validation (CANON)

| Dimension | What It Checks |
|-----------|---------------|
| **Schema** | JSON structure matches expectations |
| **Latency** | Response within SLA bounds |
| **Cost** | Token usage not anomalous |
| **Completeness** | No truncation or missing fields |
| **Identity** | Correct provider identified |
| **Integrity** | Response not corrupted |

**Benchmark:** P50 = 22µs, P99 = 99µs per validation pass. This is 3-4 orders of magnitude faster than the LLM call itself.

## Key Features

### Verified Failover
Traditional: "HTTP 200 = success" → switch providers
Correctover: switch → validate 6-dimension contract → confirm or rollback

### MAPE-K Self-Healing Loop
Monitor → Analyze → Plan → Execute → Knowledge. 87 self-healing rules that grow automatically via the knowledge loop.

### BYOK Direct Connect
Zero markup, zero relay, zero lock-in. Your keys connect directly to providers. Correctover is an embedded SDK, not a proxy gateway.

### Drift Detection
Real-time monitoring across all 6 dimensions with automatic alerting and verified failover when drift exceeds thresholds.

### Checkpoint Recovery
Long-chain agent tasks can resume from interruption points instead of restarting.

## Benchmarks

| Metric | Value |
|--------|-------|
| Contract validation P50 | 22µs |
| Contract validation P99 | 99µs |
| MAPE-K decision loop | 50-100µs |
| L3 Failover E2E (with validation) | 949ms |
| Overhead per LLM call | <0.01% |
| Self-healing rules | 87 (growing) |
| Supported providers | 8+ (OpenAI, Anthropic, Google, Groq, DashScope, Azure, DeepSeek, etc.) |
| SDK size | ~375 KB |
| Dependencies | 1 (httpx) |

## Quick Start

```python
from correctover import NeuralReliabilityEngine

engine = NeuralReliabilityEngine()

# One call, multi-provider, auto-failover with verification
response = engine.chat_completion(
    messages=[{"role": "user", "content": "Explain verified failover"}],
    providers=["openai", "anthropic", "google"],
    contract={
        "max_latency_ms": 5000,
        "max_cost_tokens": 2000,
        "require_json": True
    }
)
```

## Installation

**Python:**
```bash
pip install correctover
```

**Node.js:**
```bash
npm install correctover
```

## Why Not a Gateway?

Traditional AI gateways operate as reverse proxies — your API calls go through their infrastructure. This means:
- You pay markup on every token
- Your data passes through third-party servers
- You're locked into one vendor's routing logic
- Failover is transport-level (HTTP 200 only)

Correctover runs **in your process**. Your keys stay local. Your data never leaves your infrastructure. Failover includes semantic validation, not just HTTP status codes.

**Failover switches. Correctover verifies.**

---

*Website: [correctover.com](https://correctover.com) | PyPI: `pip install correctover` | npm: `npm install correctover` | [GitHub](https://github.com/neuralbridge/neuralbridge-sdk)*
