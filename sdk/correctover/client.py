# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""Correctover Client — the unified interface for LLM routing + self-healing.

Usage:
    import correctover as nb

    client = nb.Client(
        providers=["openai", "anthropic", "deepseek"],
        strategy="cost",
    )

    # Auto-route: NB picks the best provider/model
    response = client.chat("Hello!", model="auto")

    # Manual: specify model
    response = client.chat("Complex task", model="gpt-4o")

    # Check costs
    print(client.costs.summary())
"""
import os
import time
from typing import Optional, Dict, List, Any

import re
from .router import Router, Strategy
from .classifier import (
    Complexity, classify, MODEL_COSTS, PROVIDER_MODELS,
    get_cost_per_token, get_model_tier,
)


class Client:
    """Unified Correctover client with routing + self-healing.

    Combines smart routing (which provider/model to use) with
    self-healing (what to do when it fails) in one interface.

    Args:
        providers: List of provider names (e.g. ["openai", "anthropic"]).
        strategy: Routing strategy — "cost", "latency", or "quality".
        api_keys: Optional dict of {provider: api_key}. Auto-detected from env if not set.
        license_key: Optional license key for Pro features.
    """

    def __init__(
        self,
        providers: List[str],
        strategy: str = "cost",
        api_keys: Optional[Dict[str, str]] = None,
        license_key: Optional[str] = None,
    ):
        self.providers = providers
        self.strategy = strategy
        self._api_keys = api_keys or {}
        self._license_key = license_key or os.environ.get("CORRECTOVER_LICENSE_KEY", "")

        # Auto-detect API keys from environment
        env_key_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "google": "GOOGLE_API_KEY",
            "dashscope": "DASHSCOPE_API_KEY",
            "azure": "AZURE_OPENAI_API_KEY",
            "nvidia": "NVIDIA_API_KEY",
            "groq": "GROQ_API_KEY",
        }
        for p in providers:
            if p not in self._api_keys:
                env_var = env_key_map.get(p, f"{p.upper()}_API_KEY")
                key = os.environ.get(env_var, "")
                if key:
                    self._api_keys[p] = key

        # Initialize router
        self._router = Router(providers=providers, strategy=strategy)

        # Initialize engine (lazy)
        self._engine = None

        # Cost tracking
        self.costs = CostReport()

        # Call stats
        self._stats = {"total_calls": 0, "routed_calls": 0, "healed_calls": 0}

    def chat(
        self,
        prompt: str,
        model: str = "auto",
        task_type: str = "",
        strategy: Optional[str] = None,
        **kwargs,
    ) -> "ChatResponse":
        """Send a chat request with automatic routing and self-healing.

        Args:
            prompt: The user prompt.
            model: "auto" for smart routing, or a specific model name.
            task_type: Optional hint (e.g. "extraction", "creative_writing").
            strategy: Override routing strategy for this call.
            **kwargs: Additional arguments passed to the engine.

        Returns:
            ChatResponse with text, provider, model, cost, etc.
        """
        self._stats["total_calls"] += 1

        # Route the request
        if strategy:
            router = Router(providers=self.providers, strategy=strategy)
        else:
            router = self._router

        decision = router.route(prompt, model=model, task_type=task_type)
        self._stats["routed_calls"] += 1

        # Execute via SelfHealingEngine
        engine = self._get_engine()
        start_time = time.time()

        try:
            result = engine.call_sync(
                prompt,
                model=decision.model,
                task_type=task_type,
                **kwargs,
            )
            elapsed_ms = (time.time() - start_time) * 1000

            # Track cost
            actual_model = result.model or decision.model
            actual_provider = result.provider or decision.provider
            inp_tokens = len(prompt.split()) * 2  # rough estimate
            out_tokens = len((result.text or "").split()) * 2
            self.costs.record(
                provider=actual_provider,
                model=actual_model,
                input_tokens=inp_tokens,
                output_tokens=out_tokens,
                latency_ms=elapsed_ms,
                complexity=decision.complexity.value,
                healed=result.heal_level is not None,
            )

            # ── Carbon tracking ──
            try:
                from correctover.carbon import get_carbon_tracker
                ct = get_carbon_tracker()
                ct.record_call(actual_provider, actual_model, inp_tokens, out_tokens, elapsed_ms)
                if decision.cost_saved_usd > 0 and decision.original_model:
                    ct.record_routing_savings(decision.original_model, actual_model, inp_tokens, out_tokens)
            except Exception:
                pass

            # ── Drift monitoring ──
            try:
                from correctover.drift import get_drift_monitor
                dm = get_drift_monitor()
                dm.observe_call(actual_provider, actual_model, elapsed_ms, out_tokens, success=True)
                dm.observe_routing_decision(decision.strategy, actual_provider, actual_model)
            except Exception:
                pass

            if result.heal_level:
                self._stats["healed_calls"] += 1

            return ChatResponse(
                text=result.text or "",
                provider=actual_provider,
                model=actual_model,
                success=result.success,
                heal_level=result.heal_level,
                latency_ms=elapsed_ms,
                complexity=decision.complexity,
                routing=decision,
                raw_result=result,
            )

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            self.costs.record(
                provider=decision.provider,
                model=decision.model,
                input_tokens=0,
                output_tokens=0,
                latency_ms=elapsed_ms,
                complexity=decision.complexity.value,
                failed=True,
            )
            # ── Carbon waste tracking (429/failure = wasted GPU) ──
            try:
                from correctover.carbon import get_carbon_tracker
                get_carbon_tracker().record_call(decision.provider, decision.model, 0, 0, elapsed_ms, avoided=True)
            except Exception:
                pass
            # ── Drift monitoring (failure) ──
            try:
                from correctover.drift import get_drift_monitor
                get_drift_monitor().observe_call(decision.provider, decision.model, elapsed_ms, 0, success=False, error_type=type(e).__name__)
            except Exception:
                pass
            return ChatResponse(
                text="",
                provider=decision.provider,
                model=decision.model,
                success=False,
                heal_level=None,
                latency_ms=elapsed_ms,
                complexity=decision.complexity,
                routing=decision,
                error=_sanitize_error(e),
            )

    def _get_engine(self):
        """Lazy-init the SelfHealingEngine."""
        if self._engine is None:
            from . import SelfHealingEngine
            self._engine = SelfHealingEngine(providers=self.providers)
        return self._engine

    def status(self) -> Dict[str, Any]:
        """Get client status: routing info, costs, health, carbon."""
        result = {
            "providers": self.providers,
            "strategy": self.strategy,
            "stats": self._stats,
            "costs": self.costs.summary(),
        }
        try:
            from correctover.carbon import get_carbon_tracker
            result["carbon"] = get_carbon_tracker().report()
        except Exception:
            pass
        try:
            from correctover.drift import get_drift_monitor
            result["drift"] = get_drift_monitor().status()
        except Exception:
            pass
        return result


def _sanitize_error(e: Exception) -> str:
    """Sanitize exception to avoid leaking API keys."""
    msg = str(e)
    msg = re.sub(r'(sk-[a-zA-Z0-9]{20,})', 'sk-...', msg)
    msg = re.sub(r'(Bearer\s+)[a-zA-Z0-9._-]+', r'Bearer ***', msg, flags=re.I)
    msg = re.sub(r'(Authorization:\s*)[^\r\n]+', r'Authorization: ***', msg, flags=re.I)
    return msg

class ChatResponse:
    """Response from a Client.chat() call."""

    __slots__ = (
        "text", "provider", "model", "success", "heal_level",
        "latency_ms", "complexity", "routing", "error", "raw_result",
    )

    def __init__(
        self,
        text: str,
        provider: str,
        model: str,
        success: bool,
        heal_level: Optional[str] = None,
        latency_ms: float = 0.0,
        complexity: Optional[Complexity] = None,
        routing: Optional[Any] = None,
        error: Optional[str] = None,
        raw_result: Optional[Any] = None,
    ):
        self.text = text
        self.provider = provider
        self.model = model
        self.success = success
        self.heal_level = heal_level
        self.latency_ms = latency_ms
        self.complexity = complexity
        self.routing = routing
        self.error = error
        self.raw_result = raw_result

    def __repr__(self):
        status = "✓" if self.success else "✗"
        heal = f" [{self.heal_level}]" if self.heal_level else ""
        return f"ChatResponse({status} {self.provider}/{self.model}{heal}, {self.latency_ms:.0f}ms)"

    def __str__(self):
        return self.text


class CostReport:
    """Track API costs with savings comparison."""

    def __init__(self):
        self._records = []

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0.0,
        complexity: str = "moderate",
        healed: bool = False,
        failed: bool = False,
    ):
        """Record a call's cost data."""
        # Actual cost
        input_cost = input_tokens * get_cost_per_token(model, "input")
        output_cost = output_tokens * get_cost_per_token(model, "output")
        actual_cost = input_cost + output_cost

        # What it would have cost with the most expensive option
        # Assume "premium" model as comparison baseline
        premium_input = 3.00 / 1_000_000  # ~claude-sonnet-4 input rate
        premium_output = 15.00 / 1_000_000
        baseline_cost = input_tokens * premium_input + output_tokens * premium_output

        self._records.append({
            "ts": time.time(),
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "actual_cost": actual_cost,
            "baseline_cost": baseline_cost,
            "savings": max(0, baseline_cost - actual_cost),
            "latency_ms": latency_ms,
            "complexity": complexity,
            "healed": healed,
            "failed": failed,
        })

    @property
    def total_usd(self) -> float:
        return sum(r["actual_cost"] for r in self._records)

    @property
    def total_savings(self) -> float:
        return sum(r["savings"] for r in self._records)

    @property
    def total_tokens(self) -> int:
        return sum(r["input_tokens"] + r["output_tokens"] for r in self._records)

    @property
    def call_count(self) -> int:
        return len(self._records)

    @property
    def savings_pct(self) -> float:
        baseline = sum(r["baseline_cost"] for r in self._records)
        return (self.total_savings / baseline * 100) if baseline > 0 else 0.0

    def by_provider(self) -> Dict[str, Dict]:
        """Breakdown by provider."""
        result = {}
        for r in self._records:
            p = r["provider"]
            if p not in result:
                result[p] = {"calls": 0, "cost": 0.0, "tokens": 0, "healed": 0}
            result[p]["calls"] += 1
            result[p]["cost"] += r["actual_cost"]
            result[p]["tokens"] += r["input_tokens"] + r["output_tokens"]
            if r["healed"]:
                result[p]["healed"] += 1
        return result

    def summary(self) -> Dict[str, Any]:
        """Full cost summary."""
        return {
            "total_calls": self.call_count,
            "total_cost_usd": round(self.total_usd, 4),
            "total_savings_usd": round(self.total_savings, 4),
            "savings_pct": round(self.savings_pct, 1),
            "total_tokens": self.total_tokens,
            "by_provider": self.by_provider(),
        }

    def monthly_report(self) -> str:
        """Human-readable monthly cost report."""
        s = self.summary()
        lines = [
            f"📊 Correctover Monthly Cost Report",
            f"{'─' * 40}",
            f"  Total calls:    {s['total_calls']}",
            f"  Total cost:     ${s['total_cost_usd']:.2f}",
            f"  Savings:        ${s['total_savings_usd']:.2f} ({s['savings_pct']}%)",
            f"  Total tokens:   {s['total_tokens']:,}",
            f"",
            f"  By Provider:",
        ]
        for p, data in s["by_provider"].items():
            lines.append(f"    {p:12s}  {data['calls']:4d} calls  ${data['cost']:.2f}  {data['tokens']:,} tokens")
        return "\n".join(lines)
