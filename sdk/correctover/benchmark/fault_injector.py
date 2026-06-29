# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture
# Commercial Engine. Proprietary.
#
"""Correctover v4.4.2 — Fault Injector for benchmark tests.

Provides controlled fault injection to simulate API errors
without needing real API keys or network access.
"""
import time
from typing import Optional, List, Tuple, Dict, Any
from .._engine import FaultCategory


class FaultInjector:
    """Controlled fault injector. Simulates various API errors.

    Usage:
        injector = FaultInjector.repeat_pattern(
            [(FaultCategory.RATE_LIMIT, 429), (FaultCategory.SERVER_ERROR, 500)],
            repeat=100
        )
        # Then use in mock server to inject faults
    """

    def __init__(self, fault_schedule: List[Tuple[int, FaultCategory, int]]):
        """
        Args:
            fault_schedule: [(call_index, fault_category, status_code), ...]
            e.g. [(0, RATE_LIMIT, 429), (1, SERVER_ERROR, 500)]
        """
        self.schedule: Dict[int, Tuple[FaultCategory, int]] = {
            idx: (cat, code) for idx, cat, code in fault_schedule
        }
        self.call_index = 0
        self.injected_count = 0

    def should_inject(self) -> Optional[Tuple[FaultCategory, int]]:
        """Check if current call should be a fault. Returns (category, status_code) or None."""
        result = self.schedule.get(self.call_index)
        self.call_index += 1
        if result:
            self.injected_count += 1
        return result

    def reset(self):
        """Reset injector to beginning."""
        self.call_index = 0
        self.injected_count = 0

    @classmethod
    def repeat_pattern(cls, pattern: List[Tuple[FaultCategory, int]],
                       repeat: int = 1000) -> "FaultInjector":
        """Create repeating fault pattern.

        Args:
            pattern: [(FaultCategory, status_code), ...]
            repeat: How many times to repeat the pattern

        Example:
            injector = FaultInjector.repeat_pattern(
                [(FaultCategory.RATE_LIMIT, 429)], repeat=100
            )
            # Injects 100 consecutive 429 errors
        """
        schedule = []
        for r in range(repeat):
            for cat, code in pattern:
                schedule.append((r * len(pattern) + len(schedule) % len(pattern), cat, code))
        return cls(schedule)

    @classmethod
    def single_fault(cls, category: FaultCategory, status_code: int,
                     call_index: int = 0) -> "FaultInjector":
        """Inject a single fault at a specific call index."""
        return cls([(call_index, category, status_code)])

    @classmethod
    def burst(cls, category: FaultCategory, status_code: int,
              count: int = 5, start_at: int = 0) -> "FaultInjector":
        """Inject a burst of faults starting at a specific call."""
        return cls([(start_at + i, category, status_code) for i in range(count)])

    @classmethod
    def intermittent(cls, category: FaultCategory, status_code: int,
                     every_n: int = 3, total: int = 30) -> "FaultInjector":
        """Inject intermittent faults (every Nth call)."""
        return cls([(i * every_n, category, status_code) for i in range(total // every_n)])


class MockProvider:
    """Mock provider that uses FaultInjector to simulate API behavior.

    Returns success responses unless the injector says to inject a fault.
    """

    def __init__(self, name: str, success_response: str = '{"result": "ok"}',
                 injector: Optional[FaultInjector] = None):
        self.name = name
        self.success_response = success_response
        self.injector = injector
        self.call_count = 0

    async def call(self, prompt: str, model: str = "", **kwargs) -> str:
        """Simulate an API call. Returns response or raises APIError."""
        from .._engine import APIError

        self.call_count += 1

        if self.injector:
            fault = self.injector.should_inject()
            if fault:
                category, status_code = fault
                raise APIError(
                    f"Injected {category.value}: HTTP {status_code}",
                    status_code=status_code
                )

        return self.success_response

    def call_sync(self, prompt: str, model: str = "", **kwargs) -> str:
        """Synchronous wrapper."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.call(prompt, model, **kwargs))
        except RuntimeError:
            return asyncio.run(self.call(prompt, model, **kwargs))
