# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover v4.4.2 — Integrity Checker (delegates to Diagnoser + Contract)."""
from ._engine import Diagnoser, Contract, ContractResult


class IntegrityChecker:
    """Check API call integrity. Delegates to Diagnoser for fault checking
    and Contract for output validation.

    Usage:
        checker = IntegrityChecker(provider="openai")
        result = checker.check(error=exception, status_code=429)
        is_ok = checker.verify(response_text, contract=my_contract)
    """
    def __init__(self, provider: str = None):
        self._provider = provider
        self._diagnoser = Diagnoser()

    def check(self, error: Exception = None, status_code: int = None) -> dict:
        """Check if an error indicates an integrity issue."""
        if error is None:
            return {"ok": True}
        diag = self._diagnoser.diagnose(error, status_code)
        return {
            "ok": False,
            "category": diag.category.value,
            "confidence": diag.confidence,
            "sub_category": diag.sub_category,
            "should_retry": diag.should_retry,
            "skip_to_failover": diag.skip_to_failover,
        }

    def verify(self, response, contract: Contract = None) -> bool:
        """Verify response integrity using Contract validation.

        Args:
            response: The response text to verify
            contract: Optional Contract to validate against.
                     If None, only checks response is non-empty string.

        Returns:
            True if response passes all checks, False otherwise.
        """
        if not response or not isinstance(response, str):
            return False
        if contract is not None:
            result = contract.validate(response)
            return result.passed
        return True


__all__ = ["IntegrityChecker"]
