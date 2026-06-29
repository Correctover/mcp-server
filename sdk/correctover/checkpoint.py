# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""NB Checkpoint — Agent crash recovery with automatic state persistence.

When your Agent crashes mid-execution, Checkpoint lets it resume from
the last completed step instead of starting from scratch.

Key insight: this saves API cost too. If an Agent ran 10 LLM calls and
crashed, without checkpoint you replay all 10 calls (2x cost). With
checkpoint, you only replay from the crash point.

Usage — Step API (most flexible):
    from correctover import Checkpoint

    cp = Checkpoint("research-agent")

    papers = cp.step("search", lambda: client.chat("Search quantum computing").text)
    analysis = cp.step("analyze", lambda: client.chat(f"Analyze: {papers}").text)
    report = cp.step("summarize", lambda: client.chat(f"Summarize: {analysis}").text)

    # If crashes at step 3, next run auto-resumes from step 3
    # Steps 1-2 return cached results instantly (zero API calls, zero cost)

Usage — Pipeline API (simplest):
    result = cp.pipeline([
        ("search",   lambda ctx: client.chat("Search quantum computing").text),
        ("analyze",  lambda ctx: client.chat(f"Analyze: {ctx['search']}").text),
        ("summarize", lambda ctx: client.chat(f"Summarize: {ctx['analyze']}").text),
    ])

Usage — AgentSession (Checkpoint + Client + Shield in one):
    from correctover import AgentSession

    session = AgentSession("research-agent", providers=["openai", "deepseek"])
    result = session.run([
        ("search",   "Search for the latest papers on quantum computing"),
        ("analyze",  "Analyze the key findings from the search results"),
        ("report",   "Write a concise summary report"),
    ])
"""

import json
import os
import time
import uuid
import hashlib
from typing import Any, Callable, Dict, List, Optional, Union
from pathlib import Path


# SECURITY: Checkpoint data is stored as plaintext JSON at ~/.correctover/checkpoints/
# TODO: Add AES-GCM encryption for sensitive payload (API keys, auth tokens)
# TODO: Add file permission checks (must be 600 or tighter on Unix)
# TODO: Add maximum size limit per checkpoint file


# Default checkpoint directory
_DEFAULT_DIR = os.path.expanduser("~/.correctover/checkpoints")


# ── Step Result ──────────────────────────────────────────────────

class StepResult:
    """Result of a single checkpointed step."""

    __slots__ = ("name", "value", "completed_at", "step_index",
                 "tokens_used", "cost_usd", "error")

    def __init__(
        self,
        name: str,
        value: Any = None,
        completed_at: Optional[float] = None,
        step_index: int = 0,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        error: Optional[str] = None,
    ):
        self.name = name
        self.value = value
        self.completed_at = completed_at
        self.step_index = step_index
        self.tokens_used = tokens_used
        self.cost_usd = cost_usd
        self.error = error

    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None

    def __repr__(self):
        status = "\u2713" if self.is_completed else "..."
        val_preview = str(self.value)[:60] if self.value is not None else "None"
        return f"StepResult({status} {self.name}: {val_preview})"


# ── Run Context (for pipeline) ──────────────────────────────────

class RunContext:
    """Context object passed to pipeline step functions.

    Provides access to previous step results by name.

    Usage:
        result = cp.pipeline([
            ("search",  lambda ctx: client.chat("Search quantum computing").text),
            ("analyze", lambda ctx: client.chat(f"Analyze: {ctx['search']}").text),
        ])
    """

    def __init__(self):
        self._results: Dict[str, Any] = {}

    def __getitem__(self, key: str) -> Any:
        return self._results[key]

    def __contains__(self, key: str) -> bool:
        return key in self._results

    def get(self, key: str, default: Any = None) -> Any:
        return self._results.get(key, default)

    @property
    def prev(self) -> Any:
        """Get the previous step's result."""
        if not self._results:
            return None
        return list(self._results.values())[-1]

    @property
    def all(self) -> Dict[str, Any]:
        """Get all step results as a dict."""
        return dict(self._results)

    def _set(self, key: str, value: Any):
        self._results[key] = value


# ── Storage Backends ─────────────────────────────────────────────

class CheckpointStore:
    """Abstract base for checkpoint storage backends."""

    def save_step(self, agent_id: str, step: StepResult) -> None:
        raise NotImplementedError

    def load_step(self, agent_id: str, step_name: str) -> Optional[StepResult]:
        raise NotImplementedError

    def load_all_steps(self, agent_id: str) -> Dict[str, StepResult]:
        raise NotImplementedError

    def latest_completed_step(self, agent_id: str) -> Optional[str]:
        raise NotImplementedError

    def clear(self, agent_id: str) -> bool:
        raise NotImplementedError

    def list_agents(self) -> List[str]:
        raise NotImplementedError


class FileCheckpointStore(CheckpointStore):
    """File-based checkpoint storage in ~/.correctover/checkpoints/.

    Each agent gets a JSON file with all step results.
    Thread-safe via atomic writes.
    """

    def __init__(self, directory: Optional[str] = None):
        self.directory = Path(directory or _DEFAULT_DIR)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, agent_id: str) -> Path:
        safe_id = hashlib.sha256(agent_id.encode()).hexdigest()[:16]
        # Keep original name (sanitized) for readability
        readable = agent_id.replace("/", "_").replace("\\", "_").replace(" ", "_")[:48]
        return self.directory / f"{safe_id}_{readable}.json"

    def _read(self, agent_id: str) -> Dict:
        path = self._path(agent_id)
        if not path.exists():
            return {"agent_id": agent_id, "created_at": time.time(), "steps": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"agent_id": agent_id, "created_at": time.time(), "steps": {}}

    def _write(self, agent_id: str, data: Dict) -> None:
        path = self._path(agent_id)
        data["updated_at"] = time.time()
        # Atomic write: write to temp, then rename
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        tmp.replace(path)

    def save_step(self, agent_id: str, step: StepResult) -> None:
        data = self._read(agent_id)
        data["steps"][step.name] = {
            "value": step.value,
            "completed_at": step.completed_at,
            "step_index": step.step_index,
            "tokens_used": step.tokens_used,
            "cost_usd": step.cost_usd,
            "error": step.error,
        }
        self._write(agent_id, data)

    def load_step(self, agent_id: str, step_name: str) -> Optional[StepResult]:
        data = self._read(agent_id)
        step_data = data.get("steps", {}).get(step_name)
        if not step_data:
            return None
        return StepResult(
            name=step_name,
            value=step_data.get("value"),
            completed_at=step_data.get("completed_at"),
            step_index=step_data.get("step_index", 0),
            tokens_used=step_data.get("tokens_used", 0),
            cost_usd=step_data.get("cost_usd", 0.0),
            error=step_data.get("error"),
        )

    def load_all_steps(self, agent_id: str) -> Dict[str, StepResult]:
        data = self._read(agent_id)
        result = {}
        for name, sd in data.get("steps", {}).items():
            result[name] = StepResult(
                name=name,
                value=sd.get("value"),
                completed_at=sd.get("completed_at"),
                step_index=sd.get("step_index", 0),
                tokens_used=sd.get("tokens_used", 0),
                cost_usd=sd.get("cost_usd", 0.0),
                error=sd.get("error"),
            )
        return result

    def latest_completed_step(self, agent_id: str) -> Optional[str]:
        steps = self.load_all_steps(agent_id)
        completed = [(s.step_index, s.name) for s in steps.values() if s.is_completed]
        if not completed:
            return None
        completed.sort(key=lambda x: x[0])
        return completed[-1][1]

    def clear(self, agent_id: str) -> bool:
        path = self._path(agent_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_agents(self) -> List[str]:
        agents = []
        for f in self.directory.glob("*.json"):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
                    if "agent_id" in data:
                        agents.append(data["agent_id"])
            except (json.JSONDecodeError, IOError):
                continue
        return sorted(agents)


class MemoryCheckpointStore(CheckpointStore):
    """In-memory checkpoint storage (for testing)."""

    def __init__(self):
        self._data: Dict[str, Dict] = {}

    def save_step(self, agent_id: str, step: StepResult) -> None:
        if agent_id not in self._data:
            self._data[agent_id] = {"steps": {}}
        self._data[agent_id]["steps"][step.name] = {
            "value": step.value,
            "completed_at": step.completed_at,
            "step_index": step.step_index,
            "tokens_used": step.tokens_used,
            "cost_usd": step.cost_usd,
            "error": step.error,
        }

    def load_step(self, agent_id: str, step_name: str) -> Optional[StepResult]:
        sd = self._data.get(agent_id, {}).get("steps", {}).get(step_name)
        if not sd:
            return None
        return StepResult(
            name=step_name,
            value=sd.get("value"),
            completed_at=sd.get("completed_at"),
            step_index=sd.get("step_index", 0),
            tokens_used=sd.get("tokens_used", 0),
            cost_usd=sd.get("cost_usd", 0.0),
            error=sd.get("error"),
        )

    def load_all_steps(self, agent_id: str) -> Dict[str, StepResult]:
        result = {}
        for name, sd in self._data.get(agent_id, {}).get("steps", {}).items():
            result[name] = StepResult(
                name=name,
                value=sd.get("value"),
                completed_at=sd.get("completed_at"),
                step_index=sd.get("step_index", 0),
                tokens_used=sd.get("tokens_used", 0),
                cost_usd=sd.get("cost_usd", 0.0),
                error=sd.get("error"),
            )
        return result

    def latest_completed_step(self, agent_id: str) -> Optional[str]:
        steps = self.load_all_steps(agent_id)
        completed = [(s.step_index, s.name) for s in steps.values() if s.is_completed]
        if not completed:
            return None
        completed.sort()
        return completed[-1][1]

    def clear(self, agent_id: str) -> bool:
        if agent_id in self._data:
            del self._data[agent_id]
            return True
        return False

    def list_agents(self) -> List[str]:
        return sorted(self._data.keys())


# ── Serialization Helper ─────────────────────────────────────────

def _pack_value(result: Any) -> Any:
    """Convert a step result to a JSON-serializable format.

    Handles common Correctover types automatically:
    - ChatResponse → .text (string)
    - dict/list/str/int/float/bool → as-is
    - objects with .text → .text
    - everything else → str()
    """
    if result is None:
        return None

    # Already JSON-serializable
    if isinstance(result, (str, int, float, bool, list, dict)):
        return result

    # ChatResponse-like objects (has .text attribute)
    if hasattr(result, "text") and callable(getattr(type(result), "__repr__", None)):
        text = getattr(result, "text", None)
        if text is not None:
            return text

    # Fallback: string representation
    return str(result)


# ── Checkpoint Core ──────────────────────────────────────────────

class Checkpoint:
    """Agent checkpoint manager — crash recovery for multi-step agents.

    When an Agent crashes mid-execution, Checkpoint lets it resume from
    the last completed step instead of starting from scratch.

    Key features:
    - Automatic state persistence after each step
    - Crash recovery: resume from last checkpoint on next run
    - Cost savings: no re-execution of completed steps (zero API calls)
    - Zero AI calls for checkpoint management
    - Framework-agnostic: works with any Agent framework

    Usage:
        from correctover import Checkpoint

        cp = Checkpoint("research-agent")

        # Each step is auto-saved. On resume, completed steps return cached results.
        papers = cp.step("search", lambda: client.chat("Search quantum computing").text)
        analysis = cp.step("analyze", lambda: client.chat(f"Analyze: {papers}").text)
        report = cp.step("summarize", lambda: client.chat(f"Summarize: {analysis}").text)

        # If crashes at step 3, next run auto-resumes from step 3
        # Steps 1-2 return cached results (no API calls, no cost)

    Or use the pipeline API for sequential agents:

        result = cp.pipeline([
            ("search",   lambda ctx: client.chat("Search quantum computing").text),
            ("analyze",  lambda ctx: client.chat(f"Analyze: {ctx['search']}").text),
            ("summarize", lambda ctx: client.chat(f"Summarize: {ctx['analyze']}").text),
        ])
    """

    def __init__(
        self,
        agent_id: str,
        store: Optional[CheckpointStore] = None,
        auto_persist: bool = True,
    ):
        """Initialize a Checkpoint manager.

        Args:
            agent_id: Unique identifier for this agent (e.g. "research-agent").
            store: Storage backend. Defaults to FileCheckpointStore.
            auto_persist: If True, auto-save after each step.
        """
        self.agent_id = agent_id
        self.store = store or FileCheckpointStore()
        self.auto_persist = auto_persist
        self._step_counter = 0
        self._run_id = uuid.uuid4().hex[:8]
        self._skipped = 0  # Track how many steps were skipped (resume)

    def step(
        self,
        name: str,
        fn: Callable,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
    ) -> Any:
        """Execute a step with auto-checkpoint.

        If this step was completed in a previous run (crash recovery),
        return the cached result without re-executing the function.

        Args:
            name: Unique step name within this agent (e.g. "search").
            fn: Callable that executes the step. Must return a JSON-serializable
                value, or a ChatResponse object (auto-converted to .text).
            tokens_used: Optional token count for cost tracking.
            cost_usd: Optional cost for cost tracking.

        Returns:
            The step's return value. On resume, returns the cached value.
        """
        # Check if step already completed (crash recovery)
        cached = self.store.load_step(self.agent_id, name)
        if cached and cached.is_completed:
            self._step_counter = max(self._step_counter, cached.step_index + 1)
            self._skipped += 1
            return cached.value

        # Execute the step
        try:
            result = fn()
        except Exception as e:
            # Step failed — mark as failed but don't save completed state
            # On next run, this step will be re-executed
            raise

        # Pack result for storage
        stored_value = _pack_value(result)

        # Save checkpoint
        step_result = StepResult(
            name=name,
            value=stored_value,
            completed_at=time.time(),
            step_index=self._step_counter,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
        )

        if self.auto_persist:
            self.store.save_step(self.agent_id, step_result)

        self._step_counter += 1

        # Return the stored value (consistent type between first-run and resume)
        return stored_value

    def pipeline(
        self,
        steps: List[tuple],
    ) -> Any:
        """Run a pipeline of steps with auto-checkpoint between each.

        Each step function receives a RunContext with access to previous
        step results by name.

        Args:
            steps: List of (name, callable) tuples. Each callable receives
                   a RunContext object. Use ctx['step_name'] to access
                   previous results, or ctx.prev for the last result.

        Returns:
            The result of the last step.

        Example:
            result = cp.pipeline([
                ("search",  lambda ctx: client.chat("Search").text),
                ("analyze", lambda ctx: client.chat(f"Analyze: {ctx['search']}").text),
                ("report",  lambda ctx: client.chat(f"Report: {ctx.prev}").text),
            ])
        """
        ctx = RunContext()

        # Load any previously completed steps into context
        all_steps = self.store.load_all_steps(self.agent_id)
        for name, step_result in all_steps.items():
            if step_result.is_completed:
                ctx._set(name, step_result.value)
                self._step_counter = max(self._step_counter, step_result.step_index + 1)

        # Execute pipeline
        for name, fn in steps:
            result = self.step(name, lambda: fn(ctx))
            ctx._set(name, result)

        # Return last step's result
        return ctx.prev if steps else None

    def mark_step(
        self,
        name: str,
        value: Any,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Manually save a checkpoint for a step (without executing a function).

        Useful when you want fine-grained control over when checkpoints are saved.

        Args:
            name: Step name.
            value: The value to save.
            tokens_used: Optional token count.
            cost_usd: Optional cost.
        """
        stored_value = _pack_value(value)
        step_result = StepResult(
            name=name,
            value=stored_value,
            completed_at=time.time(),
            step_index=self._step_counter,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
        )
        if self.auto_persist:
            self.store.save_step(self.agent_id, step_result)
        self._step_counter += 1

    def status(self) -> Dict[str, Any]:
        """Get checkpoint status for this agent.

        Returns:
            Dict with agent_id, step counts, cost, and per-step details.
        """
        all_steps = self.store.load_all_steps(self.agent_id)
        completed = [s for s in all_steps.values() if s.is_completed]
        total_tokens = sum(s.tokens_used for s in completed)
        total_cost = sum(s.cost_usd for s in completed)

        # Calculate saved cost (from skipped steps on resume)
        steps_saved = self._skipped

        # ── Carbon savings from checkpoint resume ──
        carbon_savings = {}
        if steps_saved > 0:
            try:
                from correctover.carbon import get_carbon_tracker
                ct = get_carbon_tracker()
                avg_tokens_per_step = total_tokens // max(len(completed), 1)
                ct.record_checkpoint_savings(steps_saved=steps_saved, tokens_per_step=avg_tokens_per_step)
                carbon_savings = {
                    "steps_saved": steps_saved,
                    "tokens_saved": steps_saved * avg_tokens_per_step,
                    "co2_saved_kg": round(ct.saved_co2_kg, 6),
                    "wh_saved": round(ct.saved_wh, 4),
                }
            except Exception:
                carbon_savings = {"steps_saved": steps_saved, "co2_tracking": "unavailable"}

        return {
            "agent_id": self.agent_id,
            "run_id": self._run_id,
            "steps_completed": len(completed),
            "steps_total": len(all_steps),
            "steps_skipped_this_run": steps_saved,
            "total_tokens_used": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "carbon_savings": carbon_savings,
            "steps": {
                name: {
                    "completed": s.is_completed,
                    "completed_at": s.completed_at,
                    "tokens_used": s.tokens_used,
                    "cost_usd": s.cost_usd,
                    "error": s.error,
                }
                for name, s in all_steps.items()
            },
        }

    def history(self) -> List[Dict]:
        """Get execution history (all completed steps, ordered by step index).

        Returns:
            List of dicts with step metadata.
        """
        all_steps = self.store.load_all_steps(self.agent_id)
        completed = [
            {
                "step": s.step_index,
                "name": s.name,
                "completed_at": s.completed_at,
                "tokens_used": s.tokens_used,
                "cost_usd": s.cost_usd,
                "value_preview": str(s.value)[:100] if s.value is not None else None,
            }
            for s in all_steps.values()
            if s.is_completed
        ]
        completed.sort(key=lambda x: x["step"])
        return completed

    def reset(self) -> bool:
        """Clear all checkpoints for this agent.

        Returns:
            True if checkpoints were cleared, False if none existed.
        """
        self._step_counter = 0
        self._skipped = 0
        return self.store.clear(self.agent_id)

    def resume_info(self) -> Optional[Dict]:
        """Get info about where to resume (if previous run crashed).

        Returns:
            Dict with resume info, or None if no previous state.
        """
        all_steps = self.store.load_all_steps(self.agent_id)
        if not all_steps:
            return None

        completed = sorted(
            [(s.step_index, s.name, s.completed_at) for s in all_steps.values() if s.is_completed],
            key=lambda x: x[0],
        )

        if not completed:
            return {
                "agent_id": self.agent_id,
                "has_state": True,
                "resume_from": "beginning",
                "completed_steps": 0,
                "message": "No steps completed. Will start from beginning.",
            }

        last_step = completed[-1]
        return {
            "agent_id": self.agent_id,
            "has_state": True,
            "resume_from_step": last_step[1],
            "resume_from_index": last_step[0] + 1,
            "completed_steps": len(completed),
            "last_completed_at": last_step[2],
            "message": f"Will resume after step '{last_step[1]}' (step {last_step[0] + 1}).",
        }


# ── Agent Session (high-level) ───────────────────────────────────

class AgentSession:
    """High-level Agent session combining Checkpoint + Client + Shield.

    The simplest way to add crash recovery to your Agent.

    Usage:
        from correctover import AgentSession

        session = AgentSession(
            "research-agent",
            providers=["openai", "deepseek"],
            strategy="cost",
        )

        result = session.run([
            ("search",  "Search for the latest papers on quantum computing"),
            ("analyze", "Analyze the key findings"),
            ("report",  "Write a concise summary report"),
        ])

        # If crashes at step 2, next call auto-resumes from step 2

    Or with an existing Client:

        client = nb.Client(providers=["openai", "deepseek"], strategy="cost")
        session = AgentSession("my-agent", client=client)

        result = session.run([
            ("search",  "Search quantum computing"),
            ("analyze", "Analyze findings"),
        ])
    """

    def __init__(
        self,
        agent_id: str,
        providers: Optional[List[str]] = None,
        strategy: str = "cost",
        client: Optional[Any] = None,
        store: Optional[CheckpointStore] = None,
    ):
        """Initialize an AgentSession.

        Args:
            agent_id: Unique identifier for this agent.
            providers: List of provider names (e.g. ["openai", "deepseek"]).
            strategy: Routing strategy — "cost", "latency", or "quality".
            client: Optional pre-configured nb.Client instance.
            store: Optional checkpoint storage backend.
        """
        self.agent_id = agent_id
        self._client = client
        self._providers = providers or []
        self._strategy = strategy
        self._cp = Checkpoint(agent_id, store=store)
        self._client_initialized = client is not None

    def _get_client(self):
        """Lazy-init Client if not provided."""
        if not self._client_initialized:
            from .client import Client
            self._client = Client(providers=self._providers, strategy=self._strategy)
            self._client_initialized = True
        return self._client

    def run(
        self,
        steps: List[tuple],
        model: str = "auto",
    ) -> Any:
        """Run a sequence of prompts with auto-checkpoint.

        Each step is a (name, prompt) tuple. If the Agent crashes, the
        next call to run() will resume from the last completed step.

        Args:
            steps: List of (step_name, prompt_text) tuples.
            model: Model to use — "auto" for smart routing, or specific model.

        Returns:
            The text result of the last step.
        """
        client = self._get_client()
        ctx = RunContext()

        # Load previously completed steps
        all_steps = self._cp.store.load_all_steps(self.agent_id)
        for name, step_result in all_steps.items():
            if step_result.is_completed:
                ctx._set(name, step_result.value)

        # Execute pipeline
        for name, prompt in steps:
            # Inject previous step results into prompt
            formatted = prompt
            for key, val in ctx.all.items():
                placeholder = f"{{{{{key}}}}}"  # {{key}}
                if placeholder in formatted:
                    formatted = formatted.replace(placeholder, str(val))

            result = self._cp.step(name, lambda p=formatted: self._call_llm(client, p, model))
            ctx._set(name, result)

        # Return last step result
        last_name = steps[-1][0] if steps else None
        return ctx.get(last_name)

    def _call_llm(self, client, prompt, model):
        """Make an LLM call and return the text result."""
        try:
            response = client.chat(prompt, model=model)
            # Extract text for checkpoint storage
            return response.text if hasattr(response, "text") else str(response)
        except Exception as e:
            # Let the exception propagate — step won't be saved as completed
            raise

    def status(self) -> Dict[str, Any]:
        """Get session status including checkpoint and client info."""
        cp_status = self._cp.status()
        if self._client_initialized and self._client:
            cp_status["client"] = self._client.status()
        return cp_status

    def resume_info(self) -> Optional[Dict]:
        """Get info about where to resume after a crash."""
        return self._cp.resume_info()

    def reset(self) -> bool:
        """Reset session (clear all checkpoints)."""
        return self._cp.reset()

    @property
    def checkpoint(self) -> Checkpoint:
        """Access the underlying Checkpoint object for advanced usage."""
        return self._cp
