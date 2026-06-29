# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture
# Commercial Engine. Proprietary.
#
"""Correctover v4.4.2 — Benchmark Runner.

Main entry point for running benchmark scenarios against a local mock server.

Usage:
    from correctover.benchmark import run_benchmark
    result = run_benchmark()
    print(result.summary())
"""
import asyncio
import time
import json
import sys
from typing import Optional, Dict, List

from .._engine import (
    SelfHealingEngine, ProviderConfig, APIError,
    SemanticDomain, Contract, CallResult,
    ContractViolationError, SemanticBoundaryViolationError,
    FaultCategory, MapeKPhase,
)
from .fault_injector import FaultInjector, MockProvider
from .metrics_collector import BenchmarkCollector, CallMetric, BenchmarkResult
from .scenarios import ALL_SCENARIOS, BenchmarkScenario


async def _run_mock_benchmark(scenario: BenchmarkScenario,
                               collector: BenchmarkCollector) -> BenchmarkResult:
    """Run a single benchmark scenario using a local mock HTTP server."""

    # Set up engine with mock providers
    providers = {
        "primary": ProviderConfig(
            name="primary", base_url="http://127.0.0.1:19999/v1",
            api_key="test-key",
            models=["mock-model", "mock-model-mini"],
        ),
        "fallback": ProviderConfig(
            name="fallback", base_url="http://127.0.0.1:19998/v1",
            api_key="test-key",
            models=["fallback-model"],
        ),
    }

    engine = SelfHealingEngine(providers=providers)

    # For benchmark, we bypass the HTTP layer and use a mock execute
    fault_schedule = []
    for cat, code in scenario.fault_categories:
        fault_schedule.append((0, cat, code))

    injector = FaultInjector(fault_schedule * scenario.repeat)

    # Mock the _execute method to simulate API responses
    call_idx = 0
    inject_map = {}

    def _mock_execute_sync(cfg, prompt, model, **kwargs):
        nonlocal call_idx
        call_idx += 1
        # Primary provider: inject fault on first attempt
        if cfg.name == "primary":
            fault = injector.should_inject()
            if fault:
                cat, code = fault
                raise APIError(f"Injected {cat.value}: HTTP {code}", status_code=code)
            return '{"result": "primary_response", "status": "ok"}'
        # Fallback provider: return valid or invalid based on scenario
        if scenario.name == "contract_schema" and call_idx % 3 == 0:
            return "not valid json"  # Invalid JSON for schema test
        if scenario.name == "contract_similarity" and call_idx % 3 == 0:
            return "Completely unrelated content about weather"
        if scenario.name == "cross_model_drift" and call_idx % 2 == 0:
            return "Short"  # Very short response for drift test
        return '{"result": "fallback_response", "status": "ok"}'

    async def _mock_execute(cfg, prompt, model, **kwargs):
        return _mock_execute_sync(cfg, prompt, model, **kwargs)

    # Patch the engine's execute method
    engine._execute = _mock_execute

    # Run benchmark
    for i in range(scenario.repeat):
        metric = CallMetric(
            call_index=i,
            success=False,
            heal_level="",
            semantic_domain=scenario.semantic_domain.value,
            validation_passed=None,
            latency_ms=0.0,
            fault_category="",
            mapek_phases=[],
        )
        t0 = time.perf_counter()
        try:
            result = await engine.call(
                prompt=f"Test prompt {i}",
                task_type=scenario.task_type,
                has_schema=scenario.has_schema,
                semantic_domain=scenario.semantic_domain,
                contract=scenario.contract,
            )
            metric.success = result.success
            metric.heal_level = result.heal_level
            metric.semantic_domain = result.semantic_domain
            metric.validation_passed = result.validation_passed
            metric.latency_ms = result.latency_ms
            if result.fault:
                metric.fault_category = result.fault.category.value
            if result.mapek_trace:
                metric.mapek_phases = [p[0] for p in result.mapek_trace.get("phases", [])]

        except SemanticBoundaryViolationError as e:
            metric.success = False
            metric.fault_category = "blocked_oob"
            metric.semantic_domain = "out_of_bounds"
            # OOB correctly rejected
        except ContractViolationError as e:
            metric.success = False
            metric.fault_category = "contract_violation"
            metric.validation_passed = False
        except APIError as e:
            metric.success = False
            metric.fault_category = "api_error"
        except Exception as e:
            metric.success = False
            metric.fault_category = type(e).__name__

        metric.latency_ms = (time.perf_counter() - t0) * 1000
        collector.record_call(metric)

    return collector.compile()


async def run_all_benchmarks() -> Dict[str, BenchmarkResult]:
    """Run all 6 benchmark scenarios and return results."""
    results = {}
    for scenario in ALL_SCENARIOS:
        collector = BenchmarkCollector()
        result = await _run_mock_benchmark(scenario, collector)
        results[scenario.name] = result
    return results


def run_benchmark() -> Dict[str, BenchmarkResult]:
    """Synchronous entry point for running all benchmarks."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, run_all_benchmarks())
                return future.result(timeout=60)
        else:
            return loop.run_until_complete(run_all_benchmarks())
    except RuntimeError:
        return asyncio.run(run_all_benchmarks())


def print_benchmark_report(results: Dict[str, BenchmarkResult]):
    """Print a formatted benchmark report."""
    print("\n" + "=" * 70)
    print("  Correctover v4.4.2 — Benchmark Report")
    print("  Answering Yuri's Three Questions with Data")
    print("=" * 70)

    for name, result in results.items():
        print(f"\n  ── {name} ──")
        print(result.summary())

    # Overall summary
    print("\n" + "=" * 70)
    print("  OVERALL SUMMARY")
    print("=" * 70)

    total_calls = sum(r.total_calls for r in results.values())
    total_healed = sum(r.total_self_healed for r in results.values())

    # Existence
    speedups = [r.flywheel_speedup_ratio for r in results.values() if r.flywheel_speedup_ratio > 0]
    avg_speedup = sum(speedups) / len(speedups) if speedups else 0

    # Effectiveness
    total_checks = sum(r.contract_checks_total for r in results.values())
    total_passed = sum(r.contract_passed_count for r in results.values())
    total_mutations = sum(r.silent_mutation_count for r in results.values())

    # Boundaries
    oob_rejections = sum(r.oob_correct_rejections for r in results.values())
    oob_attempts = sum(r.oob_total_attempts for r in results.values())
    strong_enforced = sum(r.strong_equiv_contract_enforced for r in results.values())
    strong_total = sum(r.strong_equiv_total for r in results.values())

    print(f"  Total benchmark calls: {total_calls}")
    print(f"  Total self-healed: {total_healed}")
    print(f"\n  Existence:  Flywheel avg speedup = {avg_speedup:.1%}")
    print(f"  Effectiveness: Contract {total_passed}/{total_checks} passed, {total_mutations} silent mutations")
    print(f"  Boundaries: OOB {oob_rejections}/{oob_attempts} correctly rejected, "
          f"Strong-equiv {strong_enforced}/{strong_total} enforced")
    print("=" * 70)


if __name__ == "__main__":
    results = run_benchmark()
    print_benchmark_report(results)
