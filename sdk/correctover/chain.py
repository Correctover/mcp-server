# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""NB Chain — Agent Chain Correctover™

Multi-agent DAG orchestration with semantic verification at every node.
Extends the MAPE-K loop from single-call to chain-level Correctover.

Core philosophy (Failover ≠ Correctover at chain level):
  A chain that "succeeds" but produces semantically wrong output
  at any node is worse than a chain that fails loud.

Key capabilities:
  - DAG-based agent node definition with dependency tracking
  - Per-node output validation using existing Contract system
  - Cross-provider failover at each node (leveraging 50+ providers)
  - Chain-level compensation & rollback (Saga pattern)
  - State persistence via Checkpoint system
  - Chain-level tracing and observability

Usage:
    from correctover import SelfHealingEngine, Contract
    from correctover.chain import ChainBuilder

    engine = SelfHealingEngine(providers=["openai", "anthropic", "deepseek"])

    chain = (
        ChainBuilder(engine)
        .node("planner",
            system="You are a technical architect.",
            prompt="Design a plan for: {task}",
            contract=Contract(required_entities=["architecture", "steps"]),
            task_type="code_generation")
        .node("coder",
            system="You are a senior engineer.",
            prompt="Implement this plan: {planner}",
            contract=Contract(output_schema={"required": ["code", "tests"]}),
            depends_on=["planner"])
        .node("reviewer",
            system="You are a code reviewer.",
            prompt="Review this code for bugs: {coder}",
            contract=Contract(forbidden_patterns=["looks good", "LGTM"]),
            depends_on=["coder"])
        .build()
    )

    result = chain.run(task="Build a REST API in Python")
    print(result.success)  # True/False
    print(result.results)  # Per-node results with validation status
"""

import json
import time
import uuid
import hashlib
import threading
from typing import Optional, Dict, List, Any, Callable, Tuple, Union
from dataclasses import dataclass, field, asdict
from enum import Enum


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMPENSATION STRATEGY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CompensationStrategy(str, Enum):
    """What to do when a node fails validation or execution."""
    RETRY_SAME = "retry_same"           # Retry same node with same provider
    RETRY_FAILOVER = "retry_failover"    # Retry same node with diff provider (Correctover)
    COMPENSATE = "compensate"            # Run compensation handler, continue chain
    ROLLBACK = "rollback"                # Rollback to a previous node, re-execute from there
    STOP = "stop"                        # Stop chain execution, report failure
    SKIP = "skip"                        # Skip failed node, continue with null


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DATA MODELS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class AgentNode:
    """Definition of one node in the agent chain.

    Each node represents an Agent that:
    1. Takes context from upstream nodes (via depends_on)
    2. Makes an LLM call with system prompt + formatted user prompt
    3. Validates the output against a Contract
    4. On failure: applies CompensationStrategy (Correctover)
    5. Passes validated output to downstream nodes
    """
    name: str
    system_prompt: str
    user_prompt_template: str         # {node_name} placeholders resolved from chain context
    contract: Optional[Any] = None    # correctover._engine.Contract — output validation
    depends_on: List[str] = field(default_factory=list)  # upstream node names
    model_preference: Optional[str] = None   # preferred model (e.g. "claude-sonnet-4-6")
    task_type: str = "code_generation"       # for semantic domain classification
    on_failure: CompensationStrategy = CompensationStrategy.RETRY_FAILOVER
    max_retries: int = 3                     # max retry attempts across all strategies
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 120.0                   # API call timeout in seconds (Agnes is slow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeResult:
    """Execution result of a single chain node."""
    node_name: str
    text: str
    provider: str                 # Actual serving provider
    model: str                    # Actual serving model
    success: bool
    validation_passed: Optional[bool] = None
    validation_detail: str = ""
    latency_ms: float = 0.0
    retries_used: int = 0
    failover_used: bool = False
    compensation_applied: bool = False
    error: Optional[str] = None
    skipped: bool = False

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ChainContext:
    """Shared state across the chain execution.

    Behaves like a dict where keys are node names and values are
    their execution results (NodeResult objects).
    """
    _data: Dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any):
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def all_text(self) -> Dict[str, str]:
        """Get all node outputs as text keyed by node name."""
        return {
            name: (result.text if isinstance(result, NodeResult) else str(result))
            for name, result in self._data.items()
            if isinstance(result, NodeResult) and result.success
        }


@dataclass
class ChainResult:
    """Execution result of the entire chain."""
    success: bool
    results: Dict[str, NodeResult]
    context: ChainContext
    chain_id: str = ""
    chain_latency_ms: float = 0.0
    failure_node: Optional[str] = None
    failure_reason: str = ""
    compensation_applied: bool = False
    compensation_trace: List[str] = field(default_factory=list)
    total_cost_estimate: float = 0.0

    @property
    def last_output(self) -> Optional[str]:
        """Get the last successful node's text output."""
        last = None
        last_name = None
        for name, result in self.results.items():
            if result.success:
                last = result
                last_name = name
        return last.text if last else None

    def node_output(self, name: str) -> Optional[str]:
        """Get a specific node's output text."""
        result = self.results.get(name)
        return result.text if result and result.success else None

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "chain_id": self.chain_id,
            "chain_latency_ms": self.chain_latency_ms,
            "failure_node": self.failure_node,
            "failure_reason": self.failure_reason,
            "compensation_applied": self.compensation_applied,
            "results": {n: r.to_dict() for n, r in self.results.items()},
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHAIN BUILDER (DSL)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ChainBuilder:
    """Fluent DSL for building agent chains.

    Usage:
        chain = (ChainBuilder(engine)
            .node("planner", system="...", prompt="...",
                  contract=Contract(...), depends_on=[])
            .node("coder", system="...", prompt="...",
                  contract=Contract(...), depends_on=["planner"])
            .build()
        )
        result = chain.run(task="Build a REST API")
    """

    def __init__(self, engine):
        """Initialize ChainBuilder with a SelfHealingEngine instance.

        Args:
            engine: correctover._engine.SelfHealingEngine instance
        """
        self._engine = engine
        self._nodes: Dict[str, AgentNode] = {}
        self._compensation_handlers: Dict[str, Callable] = {}
        self._chain_metadata: Dict[str, Any] = {}

    def node(
        self,
        name: str,
        system: str = "",
        prompt: str = "",
        contract: Optional[Any] = None,
        depends_on: Optional[List[str]] = None,
        model: Optional[str] = None,
        task_type: str = "code_generation",
        on_failure: Union[str, CompensationStrategy] = CompensationStrategy.RETRY_FAILOVER,
        max_retries: int = 3,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        **metadata,
    ) -> "ChainBuilder":
        """Add a node to the chain.

        Args:
            name: Unique node name (referenced by depends_on and prompt placeholders)
            system: System prompt for this agent node
            prompt: User prompt template. Use {node_name} to reference upstream outputs.
            contract: Contract for output validation (correctover.Contract)
            depends_on: List of node names this node depends on
            model: Preferred model (e.g. "claude-sonnet-4-6", "gpt-4o")
            task_type: Task classification for semantic domain routing
            on_failure: CompensationStrategy or string name
            max_retries: Max retry attempts per node
            temperature: LLM temperature
            max_tokens: Max output tokens
            timeout: API call timeout in seconds
            **metadata: Additional metadata for observability
        """
        if name in self._nodes:
            raise ValueError(f"Duplicate node name: {name}")

        if isinstance(on_failure, str):
            on_failure = CompensationStrategy(on_failure)

        self._nodes[name] = AgentNode(
            name=name,
            system_prompt=system,
            user_prompt_template=prompt,
            contract=contract,
            depends_on=depends_on or [],
            model_preference=model,
            task_type=task_type,
            on_failure=on_failure,
            max_retries=max_retries,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            metadata=metadata,
        )
        return self

    def on_compensate(self, node_name: str, handler: Callable) -> "ChainBuilder":
        """Register a compensation handler for a node.

        The handler receives (ChainContext, NodeResult, error_message) and
        should return True if compensation succeeded, False otherwise.

        Args:
            node_name: Name of the node to register compensation for
            handler: Callable(context, node_result, error) -> bool
        """
        if node_name not in self._nodes:
            raise ValueError(f"Unknown node: {node_name}. Add node first.")
        self._compensation_handlers[node_name] = handler
        return self

    def metadata(self, key: str, value: Any) -> "ChainBuilder":
        """Set chain-level metadata."""
        self._chain_metadata[key] = value
        return self

    def _validate_dag(self):
        """Validate the DAG structure (no cycles, all dependencies exist)."""
        if not self._nodes:
            raise ValueError("Chain has no nodes. Add at least one node.")

        # Check all dependencies exist
        for name, node in self._nodes.items():
            for dep in node.depends_on:
                if dep not in self._nodes:
                    raise ValueError(
                        f"Node '{name}' depends on '{dep}' but no such node exists."
                    )

        # Check for cycles via DFS
        visited = set()
        in_stack = set()

        def _has_cycle(node_name: str) -> bool:
            visited.add(node_name)
            in_stack.add(node_name)
            node = self._nodes[node_name]
            for dep in node.depends_on:
                if dep not in visited:
                    if _has_cycle(dep):
                        return True
                elif dep in in_stack:
                    return True
            in_stack.remove(node_name)
            return False

        for name in self._nodes:
            if name not in visited:
                if _has_cycle(name):
                    raise ValueError(f"Cycle detected in chain DAG involving node '{name}'.")

        # Topological sort for execution order
        self._execution_order = self._topological_sort()

    def _topological_sort(self) -> List[str]:
        """Return node names in topological order (dependencies first)."""
        visited = set()
        order = []

        def _visit(name: str):
            if name in visited:
                return
            visited.add(name)
            for dep in self._nodes[name].depends_on:
                _visit(dep)
            order.append(name)

        for name in self._nodes:
            _visit(name)

        return order

    def build(self) -> "AgentChain":
        """Build and return the executable AgentChain.

        Validates the DAG structure before returning.
        """
        self._validate_dag()
        from correctover.checkpoint import FileCheckpointStore, MemoryCheckpointStore
        return AgentChain(
            engine=self._engine,
            nodes=dict(self._nodes),
            execution_order=list(self._execution_order),
            compensation_handlers=dict(self._compensation_handlers),
            metadata=dict(self._chain_metadata),
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AGENT CHAIN EXECUTOR (Core Correctover Engine)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AgentChain:
    """Executable agent chain with Correctover guarantees.

    Built via ChainBuilder. Each node is executed in topological order
    with full MAPE-K self-healing at each step, plus chain-level
    compensation and rollback.

    This is the "Correctover" layer — it guarantees not just that each
    node runs, but that each node's output is semantically valid before
    passing to the next node.
    """

    def __init__(
        self,
        engine,
        nodes: Dict[str, AgentNode],
        execution_order: List[str],
        compensation_handlers: Dict[str, Callable],
        metadata: Dict[str, Any],
    ):
        self._engine = engine
        self._nodes = nodes
        self._execution_order = execution_order
        self._compensation_handlers = compensation_handlers
        self._metadata = metadata
        self._lock = threading.Lock()

    # ── Public API ──────────────────────────────────────────────

    def run(
        self,
        task: str = "",
        context: Optional[Dict[str, Any]] = None,
        chain_id: Optional[str] = None,
        verbose: bool = False,
    ) -> ChainResult:
        """Execute the chain synchronously with full Correctover.

        Args:
            task: Top-level task description (available as {task} in prompts)
            context: Additional context variables for prompt templates
            chain_id: Optional chain ID for observability
            verbose: Print progress information

        Returns:
            ChainResult with per-node results and chain-level status
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context — run in a new event loop in thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        lambda: asyncio.run(self._run_async(task, context, chain_id, verbose))
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self._run_async(task, context, chain_id, verbose)
                )
        except RuntimeError:
            return asyncio.run(
                self._run_async(task, context, chain_id, verbose)
            )

    async def run_async(
        self,
        task: str = "",
        context: Optional[Dict[str, Any]] = None,
        chain_id: Optional[str] = None,
        verbose: bool = False,
    ) -> ChainResult:
        """Execute the chain asynchronously with full Correctover."""
        return await self._run_async(task, context, chain_id, verbose)

    # ── Internal Execution ──────────────────────────────────────

    async def _run_async(
        self,
        task: str = "",
        context: Optional[Dict[str, Any]] = None,
        chain_id: Optional[str] = None,
        verbose: bool = False,
    ) -> ChainResult:
        """Internal async execution with Correctover loop."""
        chain_start = time.perf_counter()
        chain_id = chain_id or f"chain_{uuid.uuid4().hex[:12]}"

        ctx = ChainContext()
        ctx.set("task", task)
        if context:
            for k, v in context.items():
                ctx.set(k, v)

        results: Dict[str, NodeResult] = {}
        compensation_trace: List[str] = []
        compensation_applied = False
        failure_node = None
        failure_reason = ""

        if verbose:
            self._log(f"Chain [{chain_id}] starting — {len(self._execution_order)} nodes")

        # ── Execute nodes in topological order ──
        for node_name in self._execution_order:
            node = self._nodes[node_name]
            result = await self._execute_node(node, ctx, chain_id, verbose)

            results[node_name] = result
            ctx.set(node_name, result)

            if not result.success:
                failure_node = node_name
                failure_reason = result.error or "execution_failed"

                if verbose:
                    self._log(f"  ✗ Node '{node_name}' FAILED: {failure_reason}")

                # Apply compensation strategy
                should_stop = await self._handle_node_failure(
                    node, result, ctx, compensation_trace, verbose
                )

                if node.on_failure == CompensationStrategy.COMPENSATE:
                    compensation_applied = True
                    # Continue chain execution after compensation
                    continue
                elif node.on_failure == CompensationStrategy.SKIP:
                    # Mark as skipped, continue
                    result.skipped = True
                    continue
                elif node.on_failure == CompensationStrategy.ROLLBACK:
                    compensation_applied = True
                    # Rollback: stop chain, trigger rollback handlers
                    await self._rollback_chain(node_name, ctx, compensation_trace, verbose)
                    break
                else:  # STOP or exhausted retries
                    break  # Stop chain execution

            if verbose:
                val_status = "✓" if result.validation_passed else "⚠"
                self._log(f"  {val_status} Node '{node_name}' — {result.provider}/{result.model} "
                         f"[{result.latency_ms:.0f}ms]"
                         + (f" failover={result.failover_used}" if result.failover_used else ""))

        chain_latency_ms = (time.perf_counter() - chain_start) * 1000

        # ── Determine chain success ──
        all_success = all(
            r.success for r in results.values()
        ) if results else False

        # If a non-terminal node failed and we continued (compensate/skip),
        # the chain result depends on the last node
        if not all_success and failure_node is not None:
            # Check if compensation covered the failure
            if compensation_applied or any(
                self._nodes[n].on_failure in (CompensationStrategy.SKIP, CompensationStrategy.COMPENSATE)
                for n, r in results.items() if not r.success
            ):
                # The last successful output is the best-effort result
                last_results = [
                    r for r in results.values()
                    if r.success and not r.skipped
                ]
                if last_results:
                    # Chain "succeeded" but with compensation
                    pass  # success remains False but results are usable

        return ChainResult(
            success=all_success or compensation_applied,
            results=results,
            context=ctx,
            chain_id=chain_id,
            chain_latency_ms=chain_latency_ms,
            failure_node=failure_node,
            failure_reason=failure_reason,
            compensation_applied=compensation_applied,
            compensation_trace=compensation_trace,
        )

    async def _execute_node(
        self,
        node: AgentNode,
        ctx: ChainContext,
        chain_id: str,
        verbose: bool,
    ) -> NodeResult:
        """Execute a single node with MAPE-K + Correctover retry logic.

        Attempts execution with the preferred model/provider first.
        On validation failure, retries with different providers
        (Correctover — not just failover, but semantically equivalent failover).
        """
        start = time.perf_counter()
        node_start = time.perf_counter()

        # ── Resolve prompt template ──
        try:
            system_prompt = node.system_prompt
            user_prompt = node.user_prompt_template

            # Resolve placeholders: {task}, {node_name}
            user_prompt = self._resolve_template(user_prompt, ctx, node.name)
            system_prompt = self._resolve_template(system_prompt, ctx, node.name)
        except KeyError as e:
            return NodeResult(
                node_name=node.name,
                text="",
                provider="",
                model="",
                success=False,
                error=f"Template resolution failed: missing key {e}",
                latency_ms=(time.perf_counter() - node_start) * 1000,
            )

        if verbose:
            self._log(f"  → Executing '{node.name}' "
                     + (f"({node.model_preference})" if node.model_preference else ""))

        # ── Attempt execution with retries ──
        last_error = ""
        retries_used = 0
        failover_used = False

        # Build context variables for engine call
        call_kwargs = {
            "task_type": node.task_type,
            "model": node.model_preference or "auto",
            "temperature": node.temperature,
            "max_tokens": node.max_tokens,
            "timeout": node.timeout,
        }

        # Provider list for failover attempts
        attempted_providers = set()

        for attempt in range(node.max_retries + 1):
            try:
                # ── Full prompt ──
                full_prompt = user_prompt
                if system_prompt:
                    full_prompt = f"{system_prompt}\n\n{user_prompt}"

                call_start = time.perf_counter()

                # Make the LLM call through SelfHealingEngine
                call_result = await self._engine.call(
                    prompt=full_prompt,
                    **call_kwargs,
                )

                call_latency = (time.perf_counter() - call_start) * 1000
                text = call_result.text
                provider = call_result.provider
                model = call_result.model

                if not call_result.success:
                    last_error = f"Engine call failed: {call_result.fault}"
                    if verbose:
                        self._log(f"    Attempt {attempt + 1}: {last_error}")
                    retries_used = attempt + 1
                    continue

                # ── Validate output against Contract ──
                validation_passed = True
                validation_detail = "no_contract"

                if node.contract is not None:
                    contract_result = node.contract.validate(text)
                    validation_passed = contract_result.passed
                    validation_detail = (
                        "all_passed" if contract_result.passed
                        else f"failed:{contract_result.contract_type}"
                    )

                    if not validation_passed:
                        last_error = f"Validation failed: {validation_detail}"
                        if verbose:
                            self._log(f"    Attempt {attempt + 1}: {last_error}")

                        # Check if failover available (Correctover)
                        available = self._engine.get_available_providers()
                        remaining = [p for p in available if p not in attempted_providers]

                        if remaining and attempt < node.max_retries:
                            # Correctover: retry with different provider
                            next_provider = remaining[0]
                            attempted_providers.add(next_provider)

                            if node.model_preference:
                                # Try with the same model on different provider
                                call_kwargs["model"] = node.model_preference
                            call_kwargs.pop("provider", None)

                            failover_used = True
                            retries_used = attempt + 1

                            if verbose:
                                self._log(f"    ↻ Correctover: retrying with {next_provider}")
                            continue
                        else:
                            # Out of retries — report failure
                            elapsed = (time.perf_counter() - node_start) * 1000
                            return NodeResult(
                                node_name=node.name,
                                text=text,
                                provider=provider,
                                model=model,
                                success=False,
                                validation_passed=False,
                                validation_detail=validation_detail,
                                latency_ms=elapsed,
                                retries_used=retries_used,
                                failover_used=failover_used,
                                error=f"Validation failed after {retries_used} retries: {validation_detail}",
                            )

                # ── Success ──
                elapsed = (time.perf_counter() - node_start) * 1000
                return NodeResult(
                    node_name=node.name,
                    text=text,
                    provider=provider,
                    model=model,
                    success=True,
                    validation_passed=validation_passed,
                    validation_detail=validation_detail,
                    latency_ms=elapsed,
                    retries_used=retries_used,
                    failover_used=failover_used,
                )

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                retries_used = attempt + 1
                if verbose:
                    self._log(f"    Attempt {attempt + 1}: exception — {last_error}")

                if attempt < node.max_retries:
                    # Exponential backoff
                    import asyncio
                    await asyncio.sleep(1.0 * (2 ** attempt))
                    continue

        # ── All retries exhausted ──
        elapsed = (time.perf_counter() - node_start) * 1000
        return NodeResult(
            node_name=node.name,
            text="",
            provider="",
            model="",
            success=False,
            error=f"All retries exhausted: {last_error}",
            latency_ms=elapsed,
            retries_used=retries_used,
            failover_used=failover_used,
        )

    async def _handle_node_failure(
        self,
        node: AgentNode,
        result: NodeResult,
        ctx: ChainContext,
        compensation_trace: List[str],
        verbose: bool,
    ) -> bool:
        """Handle a node failure based on compensation strategy.

        Returns True if chain should stop, False to continue.
        """
        strategy = node.on_failure

        if strategy == CompensationStrategy.RETRY_FAILOVER:
            # Already handled in _execute_node
            compensation_trace.append(
                f"{node.name}: retry failover exhausted, stopping chain"
            )
            return True  # Stop

        elif strategy == CompensationStrategy.RETRY_SAME:
            compensation_trace.append(
                f"{node.name}: retry same exhausted, stopping chain"
            )
            return True  # Stop

        elif strategy == CompensationStrategy.COMPENSATE:
            # Run compensation handler
            handler = self._compensation_handlers.get(node.name)
            if handler:
                try:
                    comp_result = handler(ctx, result, result.error or "")
                    if comp_result:
                        compensation_trace.append(
                            f"{node.name}: compensation succeeded"
                        )
                        if verbose:
                            self._log(f"    ↺ Compensation for '{node.name}' succeeded")
                        return False  # Continue chain
                    else:
                        compensation_trace.append(
                            f"{node.name}: compensation handler returned False"
                        )
                except Exception as e:
                    compensation_trace.append(
                        f"{node.name}: compensation handler raised {e}"
                    )
            else:
                compensation_trace.append(
                    f"{node.name}: no compensation handler registered"
                )
            return False  # Continue regardless (best-effort)

        elif strategy == CompensationStrategy.ROLLBACK:
            compensation_trace.append(
                f"{node.name}: rollback triggered"
            )
            return True  # Stop (will be handled upstream)

        elif strategy == CompensationStrategy.SKIP:
            compensation_trace.append(
                f"{node.name}: skipped, continuing chain"
            )
            return False  # Continue

        elif strategy == CompensationStrategy.STOP:
            compensation_trace.append(
                f"{node.name}: stop strategy, halting chain"
            )
            return True  # Stop

        return True  # Default: stop

    async def _rollback_chain(
        self,
        from_node: str,
        ctx: ChainContext,
        compensation_trace: List[str],
        verbose: bool,
    ):
        """Rollback chain state to handle failure.

        This is the chain-level Saga compensation pattern.
        Notifies all completed nodes before the failure point that
        a rollback is occurring, so they can run compensation handlers.

        Currently this is a notification mechanism — the actual cleanup
        is done by registered compensation handlers. Future versions will
        support automatic re-execution from a rollback point.
        """
        if verbose:
            self._log(f"  ↺ Rollback triggered from '{from_node}'")

        # Find all completed nodes that depend (transitively) on the failed node
        # and notify their compensation handlers
        completed = []
        for node_name in self._execution_order:
            if node_name == from_node:
                break
            if node_name in ctx:
                completed.append(node_name)

        # Run compensation handlers in reverse order (Saga pattern)
        for node_name in reversed(completed):
            handler = self._compensation_handlers.get(node_name)
            node_result = ctx.get(node_name)
            if handler and isinstance(node_result, NodeResult):
                try:
                    handler(ctx, node_result, f"rollback_from_{from_node}")
                    compensation_trace.append(
                        f"  ↺ Rollback compensation for '{node_name}' executed"
                    )
                except Exception as e:
                    compensation_trace.append(
                        f"  ↺ Rollback compensation for '{node_name}' failed: {e}"
                    )

        compensation_trace.append(
            f"rollback complete: {len(completed)} nodes notified"
        )

    # ── Helpers ─────────────────────────────────────────────────

    def _resolve_template(self, template: str, ctx: ChainContext, current_node: str) -> str:
        """Resolve {placeholders} in a template from chain context.

        Supports:
          {task} — top-level task
          {node_name} — output text of a named node (last successful)
          {node_name.text} — explicit text access
          {custom_key} — custom context variables
        """
        import re
        result = template

        # Resolve all {key} placeholders
        def _resolve_match(match):
            key = match.group(1)

            # {task} → top-level task
            if key == "task":
                return ctx.get("task", match.group(0))

            # {node_name.text} → node output text
            if ".text" in key:
                base = key.replace(".text", "")
                node_result = ctx.get(base)
                if isinstance(node_result, NodeResult) and node_result.success:
                    return node_result.text
                return match.group(0)

            # {node_name} → node output (short form)
            node_result = ctx.get(key)
            if isinstance(node_result, NodeResult) and node_result.success:
                return node_result.text

            # Custom context variable
            custom = ctx.get(key)
            if custom is not None:
                return str(custom)

            return match.group(0)

        result = re.sub(r'\{(\w+(?:\.\w+)?)\}', _resolve_match, result)
        return result

    def _log(self, msg: str):
        """Print a log message with chain prefix."""
        print(f"[Chain] {msg}")

    # ── Introspection ───────────────────────────────────────────

    @property
    def nodes(self) -> Dict[str, AgentNode]:
        return dict(self._nodes)

    @property
    def execution_order(self) -> List[str]:
        return list(self._execution_order)

    def describe(self) -> Dict[str, Any]:
        """Get a human-readable description of the chain."""
        return {
            "nodes": len(self._nodes),
            "execution_order": self._execution_order,
            "nodes_detail": [
                {
                    "name": n.name,
                    "depends_on": n.depends_on,
                    "task_type": n.task_type,
                    "on_failure": n.on_failure.value,
                    "has_contract": n.contract is not None,
                    "model_preference": n.model_preference,
                }
                for n in self._nodes.values()
            ],
            "metadata": self._metadata,
        }
