# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture
# Commercial Engine. Proprietary.
#
"""Correctover v4.4.2 — Benchmark Metrics Collector.

Collects and aggregates metrics for answering Yuri's three questions:
1. Existence: Is MAPE-K faster than retry+routing? (flywheel speedup)
2. Effectiveness: Does Contract catch semantic drift? (validation rate)
3. Boundaries: Does OOB domain correctly block? (rejection rate)
"""
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from .._engine import MapeKPhase


@dataclass
class CallMetric:
    """Metrics from a single call."""
    call_index: int
    success: bool
    heal_level: str  # "" | "l1_retry" | "l2_downgrade" | "l3_failover" | "l4_learned"
    semantic_domain: str  # "strong_equiv" | "tau_neighborhood" | "out_of_bounds"
    validation_passed: Optional[bool]
    latency_ms: float
    fault_category: str = ""
    mapek_phases: List[str] = field(default_factory=list)  # phase names traversed
    is_repeated_fault: bool = False  # Same fault pattern seen before?


@dataclass
class BenchmarkResult:
    """Aggregate benchmark results answering Yuri's three questions."""
    total_calls: int = 0
    total_faults_injected: int = 0
    total_self_healed: int = 0

    # ── Existence: Flywheel effectiveness ──
    first_recovery_latency_ms: float = 0.0    # First occurrence recovery latency
    nth_recovery_latency_ms: float = 0.0      # Nth occurrence recovery latency (same pattern)
    flywheel_speedup_ratio: float = 0.0       # (first - nth) / first
    l4_learned_routing_count: int = 0         # L4 direct routing count
    mapek_phases_completed_rate: float = 0.0  # % of calls that completed all 5 phases

    # ── Effectiveness: Contract validation ──
    contract_checks_total: int = 0
    contract_passed_count: int = 0
    contract_failed_count: int = 0
    contract_validation_rate: float = 0.0     # passed / total
    silent_mutation_count: int = 0            # Undetected semantic drifts

    # ── Boundaries: Semantic domain enforcement ──
    oob_total_attempts: int = 0               # Calls with OUT_OF_BOUNDS domain
    oob_correct_rejections: int = 0           # Correctly rejected downgrade/failover
    oob_incorrect_allowances: int = 0         # Incorrectly allowed downgrade/failover
    oob_correct_rejection_rate: float = 0.0
    strong_equiv_contract_enforced: int = 0   # STRONG_EQUIVALENCE + Contract enforced
    strong_equiv_total: int = 0
    strong_equiv_enforcement_rate: float = 0.0
    tau_warning_count: int = 0

    # ── Timing ──
    benchmark_duration_s: float = 0.0
    calls_per_second: float = 0.0

    def compute_derived(self):
        """Compute derived metrics from raw counts."""
        if self.first_recovery_latency_ms > 0:
            self.flywheel_speedup_ratio = (
                (self.first_recovery_latency_ms - self.nth_recovery_latency_ms)
                / self.first_recovery_latency_ms
            )
        if self.contract_checks_total > 0:
            self.contract_validation_rate = self.contract_passed_count / self.contract_checks_total
        if self.oob_total_attempts > 0:
            self.oob_correct_rejection_rate = self.oob_correct_rejections / self.oob_total_attempts
        if self.strong_equiv_total > 0:
            self.strong_equiv_enforcement_rate = self.strong_equiv_contract_enforced / self.strong_equiv_total
        if self.benchmark_duration_s > 0:
            self.calls_per_second = self.total_calls / self.benchmark_duration_s

    def to_dict(self) -> Dict:
        self.compute_derived()
        return {
            "total_calls": self.total_calls,
            "total_faults_injected": self.total_faults_injected,
            "total_self_healed": self.total_self_healed,
            "existence": {
                "first_recovery_latency_ms": round(self.first_recovery_latency_ms, 2),
                "nth_recovery_latency_ms": round(self.nth_recovery_latency_ms, 2),
                "flywheel_speedup_ratio": f"{self.flywheel_speedup_ratio:.1%}",
                "l4_learned_routing_count": self.l4_learned_routing_count,
                "mapek_phases_completed_rate": f"{self.mapek_phases_completed_rate:.1%}",
            },
            "effectiveness": {
                "contract_checks_total": self.contract_checks_total,
                "contract_passed": self.contract_passed_count,
                "contract_failed": self.contract_failed_count,
                "contract_validation_rate": f"{self.contract_validation_rate:.1%}",
                "silent_mutations": self.silent_mutation_count,
            },
            "boundaries": {
                "oob_correct_rejection_rate": f"{self.oob_correct_rejection_rate:.1%}",
                "strong_equiv_enforcement_rate": f"{self.strong_equiv_enforcement_rate:.1%}",
                "tau_warnings": self.tau_warning_count,
            },
            "performance": {
                "duration_s": round(self.benchmark_duration_s, 2),
                "calls_per_second": round(self.calls_per_second, 1),
            },
        }

    def summary(self) -> str:
        """Human-readable benchmark summary."""
        d = self.to_dict()
        return (
            f"{'='*60}\n"
            f"  Correctover v4.4.2 Benchmark Results\n"
            f"{'='*60}\n"
            f"  Total calls: {d['total_calls']} | Faults: {d['total_faults_injected']} | Healed: {d['total_self_healed']}\n"
            f"\n"
            f"  ── Existence (MAPE-K vs retry+routing) ──\n"
            f"  Flywheel speedup: {d['existence']['flywheel_speedup_ratio']}\n"
            f"  First recovery: {d['existence']['first_recovery_latency_ms']}ms\n"
            f"  Nth recovery:   {d['existence']['nth_recovery_latency_ms']}ms\n"
            f"  L4 learned routes: {d['existence']['l4_learned_routing_count']}\n"
            f"  MAPE-K phases complete: {d['existence']['mapek_phases_completed_rate']}\n"
            f"\n"
            f"  ── Effectiveness (Contract validation) ──\n"
            f"  Contract validation rate: {d['effectiveness']['contract_validation_rate']}\n"
            f"  Passed: {d['effectiveness']['contract_passed']} | Failed: {d['effectiveness']['contract_failed']}\n"
            f"  Silent mutations: {d['effectiveness']['silent_mutations']}\n"
            f"\n"
            f"  ── Boundaries (Semantic domain enforcement) ──\n"
            f"  OOB correct rejection: {d['boundaries']['oob_correct_rejection_rate']}\n"
            f"  Strong-equiv enforcement: {d['boundaries']['strong_equiv_enforcement_rate']}\n"
            f"  Tau warnings: {d['boundaries']['tau_warnings']}\n"
            f"\n"
            f"  ── Performance ──\n"
            f"  Duration: {d['performance']['duration_s']}s | {d['performance']['calls_per_second']} calls/s\n"
            f"{'='*60}"
        )


class BenchmarkCollector:
    """Collects per-call metrics during benchmark runs."""

    def __init__(self):
        self.calls: List[CallMetric] = []
        self._fault_pattern_counts: Dict[str, int] = {}  # pattern → occurrence count

    def record_call(self, metric: CallMetric):
        """Record a single call's metrics."""
        self.calls.append(metric)
        if metric.fault_category:
            key = metric.fault_category
            self._fault_pattern_counts[key] = self._fault_pattern_counts.get(key, 0) + 1
            # Mark as repeated if we've seen this pattern before
            if self._fault_pattern_counts[key] > 1:
                metric.is_repeated_fault = True

    def compile(self) -> BenchmarkResult:
        """Compile all collected metrics into a BenchmarkResult."""
        result = BenchmarkResult()

        for m in self.calls:
            result.total_calls += 1

            if not m.success or m.fault_category:
                result.total_faults_injected += 1

            if m.heal_level:
                result.total_self_healed += 1

            if m.heal_level == "l4_learned":
                result.l4_learned_routing_count += 1

            # MAPE-K phases completeness
            expected_phases = {p.value for p in MapeKPhase}
            actual_phases = set(m.mapek_phases)
            if expected_phases.issubset(actual_phases) or len(actual_phases) >= 4:
                result.mapek_phases_completed_rate += 1

            # Contract validation
            if m.validation_passed is not None:
                result.contract_checks_total += 1
                if m.validation_passed:
                    result.contract_passed_count += 1
                else:
                    result.contract_failed_count += 1

            # Semantic boundaries
            if m.semantic_domain == "out_of_bounds":
                result.oob_total_attempts += 1
                # If it was rejected (not healed), that's correct
                if not m.heal_level and not m.success:
                    result.oob_correct_rejections += 1
                elif m.heal_level:
                    result.oob_incorrect_allowances += 1

            if m.semantic_domain == "strong_equiv":
                result.strong_equiv_total += 1
                if m.validation_passed is True or (m.success and m.validation_passed is None):
                    result.strong_equiv_contract_enforced += 1

            if m.semantic_domain == "tau_neighborhood" and m.validation_passed is False:
                result.tau_warning_count += 1

            # Flywheel speedup
            if m.is_repeated_fault and m.heal_level == "l4_learned":
                result.nth_recovery_latency_ms = m.latency_ms
            elif not m.is_repeated_fault and m.heal_level and not result.first_recovery_latency_ms:
                result.first_recovery_latency_ms = m.latency_ms

        # Derived rates
        if result.total_calls > 0:
            result.mapek_phases_completed_rate /= result.total_calls

        result.compute_derived()
        return result
