# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover v4.4.2 — Health Scorer (backward compatibility)."""
from ._engine import FaultCategory, Diagnoser, Diagnosis


class IntegrityChecker:
    """Quick integrity check for errors. v1.x compat.
    
    Usage:
        checker = IntegrityChecker()
        result = checker.check(error, status_code=429)
    """
    def __init__(self, provider: str = ""):
        self._provider = provider
        self._diagnoser = Diagnoser()

    def check(self, error: Exception, status_code: int = None) -> dict:
        """Diagnose an error and return structured result."""
        diag = self._diagnoser.diagnose(error, status_code)
        return {
            "category": diag.category.value,
            "sub_category": diag.sub_category,
            "confidence": diag.confidence,
            "should_retry": diag.should_retry,
            "skip_to_failover": diag.skip_to_failover,
        }


def check_integrity(error: Exception, status_code: int = None) -> dict:
    """Quick integrity check: diagnose an error and return structured result."""
    return IntegrityChecker().check(error, status_code)


__all__ = ["IntegrityChecker", "check_integrity"]

class HealthScorer:
    """Provider health scoring."""
    def __init__(self):
        self._scores = {}
    def record(self, provider: str, success: bool = True, latency_ms: float = 0):
        if provider not in self._scores:
            self._scores[provider] = {"score": 100.0, "latency": 0.0, "count": 0}
        s = self._scores[provider]
        s["score"] = max(0.0, min(100.0, s["score"] + (2.0 if success else -10.0)))
        s["latency"] = latency_ms
        s["count"] += 1
    def get_score(self, provider: str) -> float:
        return self._scores.get(provider, {"score": 100.0})["score"]
    def get_all_scores(self) -> dict:
        return self._scores
