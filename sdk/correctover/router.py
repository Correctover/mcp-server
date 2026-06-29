# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""Routing strategy engine — decides which provider/model to use per request.

Three built-in strategies: cost, latency, quality.
All are deterministic, no AI calls.
"""
import time
import random
from enum import Enum
from typing import List, Dict, Optional, Any

from .classifier import (
    Complexity, classify, COMPLEXITY_MODEL_MAP,
    MODEL_COSTS, PROVIDER_MODELS, get_cost_per_token, get_model_tier,
)


class Strategy(str, Enum):
    COST = "cost"          # Prefer cheapest model that can handle the task
    LATENCY = "latency"    # Prefer fastest provider
    QUALITY = "quality"    # Prefer best model regardless of cost


def _provider_latency(provider_state: Dict) -> float:
    """Estimate provider latency from health data. Returns ms."""
    recent = provider_state.get("recent_latencies", [])
    if recent:
        return sum(recent[-5:]) / len(recent[-5:])
    return 500.0  # default estimate


def _provider_healthy(provider_state: Dict) -> bool:
    """Check if provider is healthy enough to route to."""
    return provider_state.get("healthy", True) and not provider_state.get("circuit_open", False)


class Router:
    """Decides which provider and model to route a request to.

    Usage:
        router = Router(
            providers=["openai", "anthropic", "deepseek"],
            strategy="cost",
        )
        decision = router.route("Explain quantum computing")
        # → RoutingDecision(provider="deepseek", model="deepseek-chat", ...)
    """

    def __init__(
        self,
        providers: List[str],
        strategy: str = "cost",
        provider_states: Optional[Dict[str, Dict]] = None,
    ):
        self.providers = providers
        self.strategy = Strategy(strategy)
        self.provider_states = provider_states or {}

    def route(
        self,
        prompt: str,
        model: str = "auto",
        task_type: str = "",
        prefer_provider: Optional[str] = None,
    ) -> "RoutingDecision":
        """Route a request to the best provider/model.

        Args:
            prompt: The user prompt.
            model: "auto" for routing, or specific model name.
            task_type: Optional task type hint.
            prefer_provider: If set, try this provider first.

        Returns:
            RoutingDecision with chosen provider, model, and metadata.
        """
        # If user specified a concrete model, find a provider that has it
        if model != "auto":
            return self._route_concrete(model, prefer_provider)

        # Classify complexity
        complexity = classify(prompt, task_type)
        tier = COMPLEXITY_MODEL_MAP[complexity]

        # Get candidate (provider, model) pairs
        candidates = self._get_candidates(tier)

        if not candidates:
            # Fallback: try any model from any provider
            candidates = self._get_candidates("standard")

        if not candidates:
            # Last resort: first provider, first model
            if self.providers:
                p = self.providers[0]
                models = PROVIDER_MODELS.get(p, [])
                m = models[0] if models else "auto"
                return RoutingDecision(provider=p, model=m, complexity=complexity, tier=tier, strategy=self.strategy.value, reason="fallback")
            return RoutingDecision(provider="openai", model="gpt-4o", complexity=complexity, tier=tier, strategy=self.strategy.value, reason="no_provider")

        # Apply strategy
        if self.strategy == Strategy.COST:
            chosen = self._pick_cheapest(candidates)
        elif self.strategy == Strategy.LATENCY:
            chosen = self._pick_fastest(candidates)
        elif self.strategy == Strategy.QUALITY:
            chosen = self._pick_best_quality(candidates)
        else:
            chosen = candidates[0]

        provider, model_name = chosen

        # ── 碳排放 + 成本节省计算 ──
        estimated_co2_kg = 0.0
        cost_saved_usd = 0.0
        original_model = ""
        try:
            from correctover.carbon import estimate_co2_kg as _est_co2
            from correctover.classifier import get_cost_per_token
            estimated_co2_kg = _est_co2(model_name, 0, 1000)  # 估算1K output的CO2
            # 如果策略是cost优化，计算与premium模型的差异
            if self.strategy == Strategy.COST and tier != "premium":
                original_model = PROVIDER_MODELS.get("openai", ["gpt-4o"])[0]
                cost_original = get_cost_per_token(original_model, "input") * 1000
                cost_actual = get_cost_per_token(model_name, "input") * 1000
                cost_saved_usd = max(0, cost_original - cost_actual)
        except Exception:
            pass

        return RoutingDecision(
            provider=provider,
            model=model_name,
            complexity=complexity,
            tier=tier,
            strategy=self.strategy.value,
            reason=f"{self.strategy.value}_optimization",
            estimated_co2_kg=estimated_co2_kg,
            cost_saved_usd=cost_saved_usd,
            original_model=original_model,
        )

    def _route_concrete(self, model: str, prefer_provider: Optional[str] = None) -> "RoutingDecision":
        """Route to a specific model, choosing best provider."""
        # Find which providers support this model
        supporting = []
        for p in self.providers:
            models = PROVIDER_MODELS.get(p, [])
            if model in models or self._model_matches(model, models):
                supporting.append(p)

        if prefer_provider and prefer_provider in supporting:
            provider = prefer_provider
        elif supporting:
            # Pick the cheapest provider for this model
            provider = supporting[0]  # simplified
        else:
            # Model not in our list, let provider handle it
            provider = prefer_provider or (self.providers[0] if self.providers else "openai")

        return RoutingDecision(
            provider=provider,
            model=model,
            complexity=Complexity.MODERATE,
            tier=get_model_tier(model),
            strategy=self.strategy.value,
            reason="user_specified",
        )

    def _get_candidates(self, tier: str) -> List[tuple]:
        """Get (provider, model) candidates for a given tier."""
        candidates = []
        for p in self.providers:
            state = self.provider_states.get(p, {})
            if not _provider_healthy(state):
                continue
            models = PROVIDER_MODELS.get(p, [])
            for m in models:
                model_tier = get_model_tier(m)
                # For cost strategy with simple tasks, only consider mini tier
                # For quality strategy, consider standard + premium
                if self.strategy == Strategy.COST:
                    if tier == "mini" and model_tier in ("mini",):
                        candidates.append((p, m))
                    elif tier == "standard" and model_tier in ("mini", "standard"):
                        candidates.append((p, m))
                    elif tier == "premium" and model_tier in ("standard", "premium"):
                        candidates.append((p, m))
                elif self.strategy == Strategy.QUALITY:
                    if tier == "mini" and model_tier in ("mini", "standard"):
                        candidates.append((p, m))
                    elif tier == "standard" and model_tier in ("standard", "premium"):
                        candidates.append((p, m))
                    elif tier == "premium" and model_tier in ("premium",):
                        candidates.append((p, m))
                else:  # latency — consider all tiers
                    if tier == "mini" or model_tier == tier:
                        candidates.append((p, m))
        return candidates

    def _pick_cheapest(self, candidates: List[tuple]) -> tuple:
        """Pick the cheapest (provider, model) pair."""
        def cost_score(item):
            _, m = item
            info = MODEL_COSTS.get(m)
            return info["input"] + info["output"] if info else 999
        return min(candidates, key=cost_score)

    def _pick_fastest(self, candidates: List[tuple]) -> tuple:
        """Pick the provider with lowest latency."""
        def latency_score(item):
            p, m = item
            state = self.provider_states.get(p, {})
            model_latency = 100.0 if get_model_tier(m) == "mini" else 300.0
            return _provider_latency(state) + model_latency
        return min(candidates, key=latency_score)

    def _pick_best_quality(self, candidates: List[tuple]) -> tuple:
        """Pick the best quality model."""
        def quality_score(item):
            _, m = item
            tier = get_model_tier(m)
            return {"premium": 3, "standard": 2, "mini": 1}.get(tier, 0)
        return max(candidates, key=quality_score)

    @staticmethod
    def _model_matches(model: str, known_models: List[str]) -> bool:
        """Check if a requested model matches any known model pattern."""
        model_lower = model.lower()
        for km in known_models:
            if km in model_lower or model_lower in km:
                return True
        return False


class RoutingDecision:
    """Result of a routing decision."""

    __slots__ = ("provider", "model", "complexity", "tier", "strategy", "reason",
                 "estimated_co2_kg", "cost_saved_usd", "original_model")

    def __init__(
        self,
        provider: str,
        model: str,
        complexity: Complexity,
        tier: str,
        strategy: str,
        reason: str,
        estimated_co2_kg: float = 0.0,
        cost_saved_usd: float = 0.0,
        original_model: str = "",
    ):
        self.provider = provider
        self.model = model
        self.complexity = complexity
        self.tier = tier
        self.strategy = strategy
        self.reason = reason
        self.estimated_co2_kg = estimated_co2_kg
        self.cost_saved_usd = cost_saved_usd
        self.original_model = original_model

    def __repr__(self):
        return f"RoutingDecision({self.provider}/{self.model}, complexity={self.complexity.value}, tier={self.tier}, strategy={self.strategy})"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "complexity": self.complexity.value,
            "tier": self.tier,
            "strategy": self.strategy,
            "reason": self.reason,
            "estimated_co2_kg": self.estimated_co2_kg,
            "cost_saved_usd": self.cost_saved_usd,
            "original_model": self.original_model,
        }
