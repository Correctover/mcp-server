# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover v4.4.2 — Public type aliases (backward compatibility)."""
from enum import Enum
from dataclasses import dataclass
from typing import Optional

from ._engine import (
    FaultCategory, Diagnosis, APIError, ProviderConfig,
    SelfHealingEngine, CircuitBreaker, CircuitState,
    RateLimiter, Bulkhead, SemanticDomain, SemanticClassification,
    SemanticTopology, LearnedRule, FlywheelLearner, MetricsCollector, Diagnoser,
    # v2.5.1 additions
    MapeKPhase, MapeKTrace,
    Contract, ContractCheck, ContractResult,
    ContractViolationError, SemanticBoundaryViolationError,
    CallResult,
)

ErrorCategory = FaultCategory

class RecoveryLevel(str, Enum):
    L1_RETRY = "l1_retry"
    L2_DOWNGRADE = "l2_downgrade"
    L3_FAILOVER = "l3_failover"
    L4_LEARNED = "l4_learned"
    NONE = "none"

@dataclass
class DiagnosisResult:
    category: FaultCategory
    confidence: float
    should_retry: bool
    skip_to_failover: bool
    retry_after: Optional[float] = None
    raw_error: str = ""
    sub_category: str = ""
    recovery_level: RecoveryLevel = RecoveryLevel.NONE

    @classmethod
    def from_diagnosis(cls, d: Diagnosis) -> "DiagnosisResult":
        level = RecoveryLevel.L3_FAILOVER if d.skip_to_failover else (RecoveryLevel.L1_RETRY if d.should_retry else RecoveryLevel.NONE)
        return cls(category=d.category, confidence=d.confidence, should_retry=d.should_retry, skip_to_failover=d.skip_to_failover, retry_after=d.retry_after, raw_error=d.raw_error, sub_category=d.sub_category, recovery_level=level)

class RecoveryAction(str, Enum):
    RETRY = "retry"
    WAIT_AND_RETRY = "wait_and_retry"
    DOWNGRADE = "downgrade"
    FAILOVER = "failover"
    SKIP_PROVIDER = "skip_provider"
    CHECK_CREDENTIALS = "check_credentials"
    FIX_REQUEST = "fix_request"
    NONE = "none"

class RoutingStrategy(str, Enum):
    PRIORITY = "priority"
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    LEAST_LATENCY = "least_latency"
    HEALTH_BASED = "health_based"
    FLYWHEEL = "flywheel"
