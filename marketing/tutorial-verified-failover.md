---
title: >-
  Setting Up Verified Failover in 5 Minutes: A Step-by-Step Guide
published: false
tags:
  - tutorial
  - ai
  - llm
  - python
  - failover
canonical_url: https://correctover.com
description: >-
  A practical 5-minute tutorial: install Correctover, configure multi-provider
  failover with contract validation, and see the difference between
  transport-level and verified failover.
---

This tutorial walks through setting up **verified failover** for your LLM API calls using Correctover. No proxy, no SaaS, no configuration files — just Python and your existing API keys.

## What You'll Build

By the end of this tutorial, you'll have a script that:

1. Makes LLM API calls through multiple providers
2. Automatically fails over when a provider errors
3. **Validates every failover response across 6 dimensions** before accepting it
4. Logs exactly what happened when a response fails validation

## Step 1: Install

```bash
pip install correctover
```

That's it. One dependency. The SDK is ~375KB with only `httpx` as a dependency.

```bash
# Verify installation
python -c "import correctover; print(correctover.__version__)"
# Output: 1.1.0
```

## Step 2: Set Your API Keys

Correctover works with your existing provider API keys. No key relay, no markup:

```bash
export OPENAI_API_KEY="sk-..."
export DEEPSEEK_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Step 3: Configure the Engine

Create a file called `verified_chat.py`:

```python
from correctover import CorrectoverEngine

# The engine wraps your multi-provider setup
engine = CorrectoverEngine(
    providers=[
        "openai/gpt-4o",
        "deepseek/deepseek-chat",
        "anthropic/claude-sonnet-4",
    ],
    # Define what "correct" means for your use case
    contract_validation={
        # Response must match this structure
        "structure": True,
        # Response must arrive within 10 seconds
        "latency_sla_ms": 10000,
        # Token usage within expected range
        "cost_budget_tokens": (50, 2000),
        # Verify the model field matches what was requested
        "verify_identity": True,
    }
)
```

The key insight here is `contract_validation`. This is what separates verified failover from transport-level failover. Each dimension is a check that the response must pass before Correctover accepts it.

## Step 4: Make Your First Call

```python
response = engine.run("What is the difference between TCP and UDP?")

print(f"Response: {response.text}")
print(f"Provider: {response.provider}")
print(f"Model: {response.model}")
print(f"Latency: {response.latency_ms}ms")
print(f"Cost: {response.total_tokens} tokens")
```

Run it:

```bash
python verified_chat.py
```

If the primary provider (OpenAI) is healthy, you'll see output like:

```
Response: TCP is connection-oriented while UDP is connectionless...
Provider: openai
Model: gpt-4o
Latency: 843ms
Cost: 156 tokens
```

## Step 5: See Verified Failover in Action

Now let's see what happens when a provider fails. Let's force a failure by using an invalid API key:

```python
import os
os.environ["OPENAI_API_KEY"] = "sk-invalid"

engine = CorrectoverEngine(
    providers=["openai/gpt-4o", "deepseek/deepseek-chat"],
    contract_validation={
        "latency_sla_ms": 10000,
        "verify_identity": True,
    }
)

response = engine.run("Explain DNS in one sentence")
print(f"Provider: {response.provider}")
print(f"Response: {response.text}")
```

Output:

```
Provider: deepseek
Response: DNS translates domain names to IP addresses...
```

Correctover automatically detected the OpenAI failure, failed over to DeepSeek, validated the response, and returned it. One seamless call.

## Step 6: The Validation Difference

Here's where verified failover matters. Let's simulate a scenario where the backup provider returns a response that looks valid but is technically wrong:

```python
response = engine.run("What is 2+2?")

# Transport-level failover: HTTP 200 → accepted
# Verified failover: HTTP 200 → 6-dimension validation → accepted only if all pass

print(f"Validation results:")
for check, result in response.validation_results.items():
    status = "PASS" if result.passed else "FAIL"
    print(f"  {check}: {status} ({result.detail})")
```

When all 6 dimensions pass, you get a response you can trust. When any dimension fails, Correctover rolls back and tries the next provider — never a silent wrong answer.

## Complete Example

Here's a complete script you can copy-paste:

```python
#!/usr/bin/env python3
"""Verified failover demo — run with: python verified_demo.py"""
import os
from correctover import CorrectoverEngine

# Configure
engine = CorrectoverEngine(
    providers=["openai/gpt-4o", "deepseek/deepseek-chat", "anthropic/claude-sonnet-4"],
    contract_validation={
        "latency_sla_ms": 15000,
        "cost_budget_tokens": (50, 3000),
        "verify_identity": True,
        "structure": True,
    }
)

# Run
prompt = "Explain the CAP theorem in 3 sentences."
response = engine.run(prompt)

# Results
print(f"Provider: {response.provider}")
print(f"Model: {response.model}")
print(f"Latency: {response.latency_ms}ms")
print(f"Tokens: {response.total_tokens}")
print(f"Response: {response.text[:200]}...")
print(f"Verified: {'✅' if response.verified else '❌'}")
```

## What You Didn't Need

- ❌ No proxy server to deploy
- ❌ No database to configure
- ❌ No YAML config files
- ❌ No sidecar containers
- ❌ No token budget to pre-purchase

One pip install. Your keys. Your data. Verified responses.

## Next Steps

- **Check the docs**: [correctover.com](https://correctover.com)
- **Explore the API**: The SDK exposes 100+ public APIs for fine-grained control
- **Go to production**: Add contract validation that matches your specific schema, latency SLAs, and cost budgets

---

*Correctover可瑞沃 — Enterprise AI Reliability Infrastructure. `pip install correctover` | Verified failover in 5 minutes.*
