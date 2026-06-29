# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture
# Commercial Engine. Proprietary.
#
"""Correctover v4.4.2 — Predefined Benchmark Scenarios.

6 scenarios answering Yuri's three questions with quantifiable results:
1. flywheel_speedup — Proves MAPE-K learns (Existence)
2. contract_schema — Proves Contract catches structural errors (Effectiveness)
3. contract_similarity — Proves Contract catches semantic drift (Effectiveness)
4. oob_boundary — Proves OUT_OF_BOUNDS blocks self-healing (Boundaries)
5. strong_equiv_enforcement — Proves STRONG_EQUIVALENCE enforces Contract (Boundaries)
6. cross_model_drift — Proves classify_response_drift detects drift (Boundaries)
"""
from .._engine import FaultCategory, SemanticDomain, Contract


class BenchmarkScenario:
    """A benchmark scenario with a name, description, and configuration."""

    def __init__(self, name: str, description: str,
                 fault_categories: list,
                 semantic_domain: SemanticDomain = SemanticDomain.TAU_NEIGHBORHOOD,
                 contract: Contract = None,
                 repeat: int = 100,
                 task_type: str = "",
                 has_schema: bool = False):
        self.name = name
        self.description = description
        self.fault_categories = fault_categories
        self.semantic_domain = semantic_domain
        self.contract = contract
        self.repeat = repeat
        self.task_type = task_type
        self.has_schema = has_schema


# ── Scenario 1: Flywheel Speedup (Existence) ──

flywheel_speedup = BenchmarkScenario(
    name="flywheel_speedup",
    description="Inject repeated rate_limit faults. Proves Nth recovery is faster than 1st via L4 learned routing.",
    fault_categories=[(FaultCategory.RATE_LIMIT, 429)],
    semantic_domain=SemanticDomain.TAU_NEIGHBORHOOD,
    contract=None,
    repeat=100,
    task_type="chat",
)

# ── Scenario 2: Contract Schema Validation (Effectiveness) ──

contract_schema = BenchmarkScenario(
    name="contract_schema",
    description="Failover produces invalid JSON. Contract with output_schema catches it.",
    fault_categories=[(FaultCategory.SERVER_ERROR, 500)],
    semantic_domain=SemanticDomain.STRONG_EQUIVALENCE,
    contract=Contract(output_schema={"required": ["result", "status"]}),
    repeat=50,
    task_type="extraction",
    has_schema=True,
)

# ── Scenario 3: Contract Similarity Validation (Effectiveness) ──

contract_similarity = BenchmarkScenario(
    name="contract_similarity",
    description="Failover produces unrelated content. Contract with similarity_threshold catches drift.",
    fault_categories=[(FaultCategory.SERVER_ERROR, 500)],
    semantic_domain=SemanticDomain.TAU_NEIGHBORHOOD,
    contract=Contract(similarity_threshold=0.6, reference_text="Python is a programming language"),
    repeat=50,
    task_type="qa",
)

# ── Scenario 4: OUT_OF_BOUNDS Boundary (Boundaries) ──

oob_boundary = BenchmarkScenario(
    name="oob_boundary",
    description="OUT_OF_BOUNDS domain + fault → must raise SemanticBoundaryViolationError, no self-healing.",
    fault_categories=[(FaultCategory.RATE_LIMIT, 429), (FaultCategory.SERVER_ERROR, 500)],
    semantic_domain=SemanticDomain.OUT_OF_BOUNDS,
    contract=None,
    repeat=50,
    task_type="creative_writing",
)

# ── Scenario 5: STRONG_EQUIVALENCE Contract Enforcement (Boundaries) ──

strong_equiv_enforcement = BenchmarkScenario(
    name="strong_equiv_enforcement",
    description="STRONG_EQUIVALENCE domain + failover + bad output → ContractViolationError (fail loud).",
    fault_categories=[(FaultCategory.RATE_LIMIT, 429)],
    semantic_domain=SemanticDomain.STRONG_EQUIVALENCE,
    contract=Contract(
        output_schema={"required": ["name", "score"]},
        required_entities=["classification"],
    ),
    repeat=50,
    task_type="classification",
    has_schema=True,
)

# ── Scenario 6: Cross-Model Drift Detection (Boundaries) ──

cross_model_drift = BenchmarkScenario(
    name="cross_model_drift",
    description="Model downgrade produces very different output length. classify_response_drift detects drift.",
    fault_categories=[(FaultCategory.MODEL_NOT_FOUND, 404)],
    semantic_domain=SemanticDomain.TAU_NEIGHBORHOOD,
    contract=Contract(similarity_threshold=0.5, reference_text="The answer involves machine learning algorithms."),
    repeat=50,
    task_type="qa",
)

ALL_SCENARIOS = [
    flywheel_speedup,
    contract_schema,
    contract_similarity,
    oob_boundary,
    strong_equiv_enforcement,
    cross_model_drift,
]
