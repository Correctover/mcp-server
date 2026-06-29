# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover v4.4.2 — Health Scorer (backward compatibility).

In v2.5.1, health scoring is integrated into ProviderConfig.health_score().
This module provides the HealthScorer class for v1.x compat.
"""
from ._engine import ProviderConfig


class HealthScorer:
    """Score provider health (0-100). Delegates to ProviderConfig.health_score().
    
    Usage (v1.x compat):
        scorer = HealthScorer()
        score = scorer.score(provider_config)
        scores = scorer.score_all([provider1, provider2])
    """
    def __init__(self):
        pass

    def score(self, provider: ProviderConfig) -> float:
        """Compute health score for a provider (0-100)."""
        return provider.health_score()

    def score_all(self, providers: list) -> dict:
        """Score all providers, return {name: score}."""
        return {p.name: p.health_score() for p in providers}


def health_score(provider: ProviderConfig) -> float:
    """Compute health score for a provider (0-100). Functional API."""
    return provider.health_score()


__all__ = ["HealthScorer", "health_score", "ProviderConfig"]

class CostTracker:
    """Track API costs per provider."""
    def __init__(self, daily_budget: float = None, monthly_budget: float = None, provider: str = None, api_key: str = None):
        self.daily_budget = daily_budget
        self.monthly_budget = monthly_budget
        self._provider = provider
        self._api_key = api_key
        self._calls = []
    def record_call(self, provider: str, model: str, tokens: int, cost_usd: float):
        self._calls.append({"provider": provider, "model": model, "tokens": tokens, "cost": cost_usd})
    def record(self, provider: str, model: str, input_tokens: int = 0, output_tokens: int = 0, cost_usd: float = 0.0, **kw):
        self._calls.append({"provider": provider, "model": model, "input_tokens": input_tokens, "output_tokens": output_tokens, "cost": cost_usd})
    @property
    def total_usd(self) -> float:
        return sum(c.get("cost", 0) for c in self._calls)
    @property
    def total_tokens(self) -> int:
        return sum(c.get("tokens", c.get("input_tokens", 0) + c.get("output_tokens", 0)) for c in self._calls)
    def get_daily_cost(self, provider: str = None) -> float:
        return 0.0
    def get_monthly_cost(self, provider: str = None) -> float:
        return 0.0
