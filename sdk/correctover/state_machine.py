# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover v4.4.2 — State Machine (MAPE-K aware lifecycle)."""
from ._engine import CircuitBreaker, CircuitState, FlywheelLearner
import time
from typing import List, Tuple, Optional


class EngineStateMachine:
    """MAPE-K aware state machine for the engine lifecycle.

    States: uninitialized → ready → active ↔ degraded → failed

    Tracks transitions with timestamps for observability.
    MAPE-K phases are tracked per-call via MapeKTrace, not here.
    This machine tracks the *engine-level* lifecycle.

    Usage:
        sm = EngineStateMachine()
        sm.transition("ready", trigger="configure")
        sm.transition("active", trigger="first_call")
        if sm.is_healthy():
            print("Engine is running")
    """
    STATES = ["uninitialized", "ready", "active", "degraded", "failed"]

    TRANSITIONS = {
        ("uninitialized", "ready"): "configure",
        ("ready", "active"): "first_call",
        ("active", "degraded"): "fault_detected",
        ("degraded", "active"): "heal_succeeded",
        ("degraded", "failed"): "heal_failed",
        ("failed", "degraded"): "partial_recovery",
        ("active", "active"): "successful_call",
        ("ready", "ready"): "reconfigure",
    }

    def __init__(self, engine=None):
        self._state = "uninitialized"
        self._engine = engine
        self._transition_log: List[Tuple[str, str, float, str]] = []

    def transition(self, new_state: str, trigger: str = ""):
        """Transition to a new state. Validates against TRANSITIONS dict."""
        if new_state not in self.STATES:
            return  # invalid state, ignore
        # Validate transition is allowed (skip self-transitions like reconfigure)
        key = (self._state, new_state)
        if key not in self.TRANSITIONS:
            # Allow self-transitions only if explicitly defined
            return
        self._transition_log.append((self._state, new_state, time.time(), trigger))
        self._state = new_state

    @property
    def state(self) -> str:
        return self._state

    def is_healthy(self) -> bool:
        return self._state in ("ready", "active")

    def is_degraded(self) -> bool:
        return self._state == "degraded"

    def is_failed(self) -> bool:
        return self._state == "failed"

    def get_transition_log(self) -> List[Tuple[str, str, float, str]]:
        """Get full transition history: [(from, to, timestamp, trigger), ...]"""
        return list(self._transition_log)

    def get_stats(self) -> dict:
        return {
            "state": self._state,
            "healthy": self.is_healthy(),
            "transition_count": len(self._transition_log),
            "last_trigger": self._transition_log[-1][3] if self._transition_log else "",
        }


__all__ = ["CircuitBreaker", "CircuitState", "FlywheelLearner", "EngineStateMachine"]
