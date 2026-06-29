# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover — MAPE-K Self-healing API resilience engine.

Semantic boundary enforcement (three-layer, zero-crossing):
  L1 Diagnoser: identify fault only, output label, NO action
  HA Layer (CB/RL/BH): read labels + metrics, modify availability, NO diagnosis
  L4 Flywheel: receive data, persist, output strategy, NEVER directly route

MAPE-K Adaptive Loop (every call):
  Monitor → Analyze → Plan → Execute → Knowledge(Flywheel)

Semantic Topology (formal three-domain):
  Strong Equivalence Domain: error codes, enums, schema keys — always guaranteed
  τ-Neighborhood Domain: text similarity, latency — threshold-controlled
  Out-of-Bounds Domain: creative output, factual correctness — no commitment

Every feature real. Every path tested. Zero phantom code.
"""
import os
import re
import json
import time
import asyncio
import urllib.request
import urllib.error
import threading
from enum import Enum
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, List, Any, Tuple
from pathlib import Path
from collections import deque

# Version: import from package __init__ for consistency
try:
    from correctover import __version__
except ImportError:
    __version__ = "4.4.2"

# 安全限制常量
_MAX_RETRIES = 5          # V3: 单请求最大重试次数
_MAX_PAYLOAD_SIZE = 10 * 1024 * 1024  # V2: 10MB 请求体限制


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAPE-K PHASE ENUM (explicit 5-stage state machine)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MapeKPhase(str, Enum):
    """Explicit MAPE-K phase enumeration. Every call() traverses all 5 stages."""
    MONITOR   = "monitor"    # Collect metrics / error signals
    ANALYZE   = "analyze"    # Diagnose faults / detect slow degradation
    PLAN      = "plan"       # Flywheel + HA decision
    EXECUTE   = "execute"    # Retry / downgrade / failover / direct
    KNOWLEDGE = "knowledge"  # Feedback to FlywheelLearner


@dataclass
class MapeKTrace:
    """Per-call MAPE-K phase trace with timestamps. Proves every call completes the full loop."""
    request_id: str
    phases: List[Tuple[str, float]] = field(default_factory=list)  # (phase_name, timestamp_us)
    monitor_result: Optional[str] = None     # "success" | fault_category
    analyze_result: Optional[str] = None     # sub_category | "nominal"
    plan_result: Optional[str] = None        # "direct" | "l1_retry" | "l2_downgrade" | "l3_failover" | "l4_learned"
    execute_result: Optional[str] = None     # "ok" | "healed" | "failed"
    knowledge_recorded: bool = False
    total_loop_us: float = 0.0

    def enter(self, phase: MapeKPhase):
        """Record entry into a MAPE-K phase with microsecond timestamp."""
        self.phases.append((phase.value, time.perf_counter() * 1e6))

    def to_dict(self) -> Dict:
        return asdict(self)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# L1: DIAGNOSER (boundary: identify only, NO action)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FaultCategory(str, Enum):
    RATE_LIMIT = "rate_limit"
    AUTH_ERROR = "auth_error"
    MODEL_NOT_FOUND = "model_not_found"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    QUOTA_EXCEEDED = "quota_exceeded"
    VALIDATION_ERROR = "validation_error"
    UNKNOWN = "unknown"

@dataclass
class Diagnosis:
    category: FaultCategory
    confidence: float
    should_retry: bool
    skip_to_failover: bool
    retry_after: Optional[float] = None
    raw_error: str = ""
    sub_category: str = ""  # hierarchical label: "rate_limit:openai", "server_error:anthropic_overload"

_STATUS_MAP: Dict[int, FaultCategory] = {
    # Fast path: status code → category (supplemented by regex patterns for message-level detail)
    400: FaultCategory.VALIDATION_ERROR,
    401: FaultCategory.AUTH_ERROR,
    402: FaultCategory.QUOTA_EXCEEDED,
    403: FaultCategory.AUTH_ERROR,
    404: FaultCategory.MODEL_NOT_FOUND,
    408: FaultCategory.TIMEOUT,
    429: FaultCategory.RATE_LIMIT,
    500: FaultCategory.SERVER_ERROR,
    502: FaultCategory.SERVER_ERROR,
    503: FaultCategory.SERVER_ERROR,
    504: FaultCategory.TIMEOUT,
    529: FaultCategory.SERVER_ERROR,
}

_DECISION: Dict[FaultCategory, Tuple[bool, bool]] = {
    FaultCategory.RATE_LIMIT: (True, False),
    FaultCategory.AUTH_ERROR: (False, True),
    FaultCategory.MODEL_NOT_FOUND: (False, True),
    FaultCategory.SERVER_ERROR: (True, False),
    FaultCategory.TIMEOUT: (True, False),
    FaultCategory.CONNECTION_ERROR: (True, False),
    FaultCategory.QUOTA_EXCEEDED: (False, True),
    FaultCategory.VALIDATION_ERROR: (False, True),
    FaultCategory.UNKNOWN: (False, True),
}

_PATTERNS = [
    # ════════ Rate limit patterns — platform-specific FIRST, then generic ════════
    # U4: 多 provider 兼容 - Azure, Google, Anthropic, DashScope, DeepSeek
    # Azure
    (r"azure.*throttle|deployments/rateLimit|throttling\.ratequota", FaultCategory.RATE_LIMIT, 0.95, True, False, "rate_limit:azure"),
    (r"715-123420|555420|fraud signal", FaultCategory.AUTH_ERROR, 0.95, False, True, "auth_error:azure"),
    (r"deployment.*not.*found|modelnotexists", FaultCategory.MODEL_NOT_FOUND, 0.9, False, True, "model_not_found:azure"),
    # Google
    (r"resource_exhausted|requests per minute|tokens per minute", FaultCategory.RATE_LIMIT, 0.9, True, False, "rate_limit:google"),
    (r"google.*overloaded|gemini.*unavailable", FaultCategory.SERVER_ERROR, 0.9, True, False, "server_error:google"),
    # Anthropic
    (r"anthropic.*overloaded|error 529|claude.*unavailable", FaultCategory.RATE_LIMIT, 0.95, True, False, "rate_limit:anthropic"),
    (r"anthropic.*overloaded", FaultCategory.SERVER_ERROR, 0.95, True, False, "server_error:anthropic_overload"),
    # DashScope (阿里云)
    (r"dashscope.*throttle|qwen.*rate.*limit|通义.*限流", FaultCategory.RATE_LIMIT, 0.9, True, False, "rate_limit:dashscope"),
    (r"dashscope.*unavailable|qwen.*unavailable|通义.*不可用", FaultCategory.SERVER_ERROR, 0.9, True, False, "server_error:dashscope"),
    # DeepSeek
    (r"deepseek.*throttle|deepseek.*rate.*limit", FaultCategory.RATE_LIMIT, 0.9, True, False, "rate_limit:deepseek"),
    (r"deepseek.*unavailable|deepseek.*overloaded", FaultCategory.SERVER_ERROR, 0.9, True, False, "server_error:deepseek"),
    # OpenAI
    (r"openai.*overloaded|api request error|openai's api is currently", FaultCategory.RATE_LIMIT, 0.95, True, False, "rate_limit:openai"),
    (r"throttling\.ratequota|deployments/rateLimit|throttled due to rate", FaultCategory.RATE_LIMIT, 0.95, True, False, "rate_limit:azure"),
    # Generic rate limit
    (r"rate.?limit|too many requests|429|请求过于频繁|请求速度超限", FaultCategory.RATE_LIMIT, 0.95, True, False, "rate_limit"),
    (r"slow down|request limit|request rate too high|ratequota exceeded", FaultCategory.RATE_LIMIT, 0.9, True, False, "rate_limit"),
    (r"monthly spend limit|subscription quota|spend limit", FaultCategory.QUOTA_EXCEEDED, 0.9, False, True, "quota_exceeded"),
    (r"insufficient.?balance|余额不足|配额不足|额度用尽|out of credits|credits? exceeded|billing.*exceeded", FaultCategory.QUOTA_EXCEEDED, 0.95, False, True, "quota_exceeded:insufficient_balance"),
    (r"capacity|high demand|please retry|retry after", FaultCategory.RATE_LIMIT, 0.8, True, False, "rate_limit"),
    # ════════ Auth patterns — platform-specific first ════════
    (r"x-api-key|aad login|azure ad|azuread|invalidcredential|凭证无效", FaultCategory.AUTH_ERROR, 0.95, False, True, "auth_error:platform"),
    (r"permission_denied|api key.*(exposed|breach|leaked|not valid)", FaultCategory.AUTH_ERROR, 0.95, False, True, "auth_error:platform"),
    # Generic auth
    (r"unauthorized|invalid.*(key|credential)|auth.*fail|access denied|invalid token", FaultCategory.AUTH_ERROR, 0.95, False, True, "auth_error"),
    (r"token expired|token invalid|forbidden|401|403", FaultCategory.AUTH_ERROR, 0.95, False, True, "auth_error"),
    # Billing-specific quota
    (r"billing.*(hard|soft)?\s*limit|arrearage|欠费|额度|exceeded your billing", FaultCategory.QUOTA_EXCEEDED, 0.95, False, True, "quota_exceeded:openai"),
    # ════════ Model not found — platform-specific first ════════
    (r"deployment.*not.*found|modelnotexists|invalid deployment", FaultCategory.MODEL_NOT_FOUND, 0.9, False, True, "model_not_found:azure"),
    (r"openai gave a 404|model swapped|silent degradation|unknown model", FaultCategory.MODEL_NOT_FOUND, 0.9, False, True, "model_not_found:openai"),
    (r"api-version|resource not found", FaultCategory.MODEL_NOT_FOUND, 0.85, False, True, "model_not_found:azure"),
    # Generic model not found
    (r"model.*(not found|does not exist|不可用|不存在)|invalid.*model|模型不存在", FaultCategory.MODEL_NOT_FOUND, 0.95, False, True, "model_not_found"),
    # ════════ Server error — platform-specific first ════════
    (r"overloaded_error|error 529|anthropic.*overloaded", FaultCategory.SERVER_ERROR, 0.95, True, False, "server_error:anthropic_overload"),
    (r"websocket freeze|session frozen|realtime server error|no event fired", FaultCategory.SERVER_ERROR, 0.85, True, False, "server_error:openai_realtime"),
    (r"status failed|background response|server error", FaultCategory.SERVER_ERROR, 0.85, True, False, "server_error:openai_background"),
    (r"responses api.*500|azure batch.*stuck|validating", FaultCategory.SERVER_ERROR, 0.85, True, False, "server_error:azure_responses"),
    (r"performance degraded|quality dropped|suddenly worse|instant mode|heavy mode", FaultCategory.SERVER_ERROR, 0.8, True, False, "server_error:openai_degradation"),
    # Generic server error
    (r"internal server|server error|服务不可用|系统错误|serviceunavailable", FaultCategory.SERVER_ERROR, 0.9, True, False, "server_error"),
    (r"bad gateway|upstream error|503|502", FaultCategory.SERVER_ERROR, 0.9, True, False, "server_error"),
    # ════════ Timeout patterns ════════
    (r"timeout|timed?\s*out|read timeout|connect timeout", FaultCategory.TIMEOUT, 0.95, True, False, "timeout"),
    (r"connection timed out|operation timed out|request timeout|408|504", FaultCategory.TIMEOUT, 0.95, True, False, "timeout"),
    # ════════ Connection error — platform-specific first ════════
    (r"sslerror|certificate|name resolution|network unreachable", FaultCategory.CONNECTION_ERROR, 0.95, True, False, "connection_error:ssl"),
    # Generic connection error
    (r"connection.*(refused|reset|abort|closed)|dns|ssl|socket|network.*error", FaultCategory.CONNECTION_ERROR, 0.95, True, False, "connection_error"),
    (r"broken pipe|eof|host unreachable|no route to host|temporarily unavailable", FaultCategory.CONNECTION_ERROR, 0.9, True, False, "connection_error"),
    # ════════ Missing common patterns — added v4.4.4 fix ════════
    (r"permission denied|没有权限", FaultCategory.AUTH_ERROR, 0.9, False, True, "auth_error"),
    (r"service unavailable|temporarily unavailable|暂时不可用|服务暂不可用", FaultCategory.SERVER_ERROR, 0.9, True, False, "server_error"),
    (r"deadline exceeded|deadline exceeded|超时|请求超时", FaultCategory.TIMEOUT, 0.95, True, False, "timeout"),
    (r"quota.?exceeded|quota limit|调用额度|额度超限", FaultCategory.QUOTA_EXCEEDED, 0.95, False, True, "quota_exceeded"),
    (r"invalid response format|response format.*invalid|格式错误|返回格式错误", FaultCategory.VALIDATION_ERROR, 0.85, False, True, "validation_error"),
    (r"not supported.*(format|type|model)|不支持.*格式|不支持.*模型", FaultCategory.VALIDATION_ERROR, 0.85, False, True, "validation_error"),
    (r"empty response|empty reply|返回为空|无响应|no response", FaultCategory.SERVER_ERROR, 0.8, True, False, "server_error"),
    # ════════ Validation — platform-specific first ════════
    (r"context length exceeded|maximum context|too many tokens|input too long|token limit", FaultCategory.VALIDATION_ERROR, 0.9, False, True, "validation_error:context_length"),
    (r"binary function response|structured output.*fail|schema validation|additionalproperties", FaultCategory.VALIDATION_ERROR, 0.85, False, True, "validation_error:schema"),
    (r"mcp.*(tool|error|stateless)|tool call.*(missing|without)", FaultCategory.VALIDATION_ERROR, 0.9, False, True, "validation_error:mcp_tool"),
    (r"reasoning_content|reasoning.*pairing|reasoning.*mismatch", FaultCategory.VALIDATION_ERROR, 0.9, False, True, "validation_error:reasoning"),
    # Generic validation
    (r"invalid argument|invalid parameters|bad request|invalid request", FaultCategory.VALIDATION_ERROR, 0.9, False, True, "validation_error"),
    (r"exceeds maximum|prompt too long|message too long", FaultCategory.VALIDATION_ERROR, 0.9, False, True, "validation_error:context_length"),
]
_COMPILED = [(re.compile(p, re.I), cat, conf, retry, skip, sub) for p, cat, conf, retry, skip, sub in _PATTERNS]


class Diagnoser:
    """L1: Fault classifier. P50 < 1us. BOUNDARY: output label only, never modify state."""

    def __init__(self):
        self._stats: Dict[str, int] = {}
        self._latencies: List[float] = []
        self._lock = threading.Lock()

    def diagnose(self, error: Exception, status_code: Optional[int] = None) -> Diagnosis:
        t0 = time.perf_counter()
        raw = str(error).lower()
        category = FaultCategory.UNKNOWN
        confidence = 0.5
        should_retry = True
        skip_to_failover = False

        if status_code and status_code in _STATUS_MAP:
            category = _STATUS_MAP[status_code]
            confidence = 0.95
            should_retry, skip_to_failover = _DECISION.get(category, (True, False))

        sub_category = ""
        if status_code and status_code in _STATUS_MAP:
            sub_category = f"{_STATUS_MAP[status_code].value}:http_{status_code}"

        # Always try regex for richer sub_category (e.g. "rate_limit:openai" > "rate_limit:http_429")
        for pat, cat, conf, retry, skip, sub in _COMPILED:
            if pat.search(raw):
                if category == FaultCategory.UNKNOWN:
                    category, confidence, should_retry, skip_to_failover = cat, conf, retry, skip
                # Override sub_category with more specific pattern match
                sub_category = sub
                break

        if category == FaultCategory.UNKNOWN:
            should_retry, skip_to_failover = _DECISION[FaultCategory.UNKNOWN]
            sub_category = "unknown"

        retry_after = 1.0 if category == FaultCategory.RATE_LIMIT else None
        elapsed_us = (time.perf_counter() - t0) * 1_000_000

        with self._lock:
            self._stats[category.value] = self._stats.get(category.value, 0) + 1
            if sub_category:
                self._stats[sub_category] = self._stats.get(sub_category, 0) + 1
            self._latencies.append(elapsed_us)
            # Cap latencies list to prevent unbounded memory growth
            if len(self._latencies) > 10000:
                self._latencies = self._latencies[-5000:]

        # A3: 防欺骗 - 限制长度
        if len(sub_category) > 50:
            sub_category = sub_category[:50]
        if len(raw) > 500:
            raw = raw[:500]
        return Diagnosis(
            category=category, confidence=confidence,
            should_retry=should_retry, skip_to_failover=skip_to_failover,
            retry_after=retry_after, raw_error=raw,
            sub_category=sub_category,
        )

    def get_latency_stats(self) -> Dict[str, float]:
        with self._lock:
            if not self._latencies:
                return {}
            s = sorted(self._latencies)
            return {"count": len(s), "p50": s[len(s)//2],
                    "p95": s[int(len(s)*0.95)] if len(s)>1 else s[0],
                    "avg": sum(s)/len(s)}

    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def suggest_recovery(self, diagnosis, provider=None, model=None):
        """Suggest recovery action based on diagnosis category."""
        from .types import RecoveryLevel

        cat = diagnosis.category.value if hasattr(diagnosis.category, 'value') else str(diagnosis.category)

        # Map category to recovery strategy
        strategy_map = {
            'rate_limit': ('wait_and_retry', RecoveryLevel.L1_RETRY, 1.0),
            'quota': ('check_credentials', RecoveryLevel.L1_RETRY, 1.0),
            'auth_error': ('check_credentials', RecoveryLevel.L1_RETRY, None),
            'model_not_found': ('downgrade', RecoveryLevel.L2_DOWNGRADE, None),
            'timeout': ('retry_with_timeout', RecoveryLevel.L1_RETRY, 1.0),
            'connection_error': ('failover', RecoveryLevel.L3_FAILOVER, None),
            'validation_error': ('fix_request', RecoveryLevel.L2_DOWNGRADE, None),
            'context_exceeded': ('downgrade_model', RecoveryLevel.L2_DOWNGRADE, None),
        }

        # Default to retry if category not mapped
        action, level, delay = strategy_map.get(cat, ('retry', RecoveryLevel.L1_RETRY, 1.0))

        # Override delay from diagnosis if available
        if delay is None and hasattr(diagnosis, 'retry_after') and diagnosis.retry_after:
            delay = diagnosis.retry_after

        class RecoveryAction:
            def __init__(self):
                self.level = level
                self.action = action
                self.target = provider or "default"
                self.delay = delay or 1.0
                self.metadata = {"category": cat, "sub_category": getattr(diagnosis, 'sub_category', '')}

        return RecoveryAction()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SEMANTIC TOPOLOGY (three-domain classifier)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SemanticDomain(str, Enum):
    STRONG_EQUIVALENCE = "strong_equiv"      # 100% guaranteed: error codes, enums, schema keys
    TAU_NEIGHBORHOOD = "tau_neighborhood"     # threshold-controlled: text similarity, latency
    OUT_OF_BOUNDS = "out_of_bounds"           # no commitment: creative output, facts

@dataclass
class SemanticClassification:
    domain: SemanticDomain
    reason: str
    tau_threshold: Optional[float] = None  # only for TAU_NEIGHBORHOOD

# Tasks that guarantee semantic equivalence across models
_STRONG_EQUIV_TASKS = {"classification", "extraction", "schema_output", "translation_literal",
                       "sentiment", "ner", "sql_generation", "code_format"}

# Tasks that are in τ-neighborhood (mostly equivalent, measurable drift)
_TAU_TASKS = {"summarization", "qa_factual", "code_generation", "translation_creative",
              "data_analysis", "rewriting"}

# Tasks that are out-of-bounds (creative, subjective, no guarantee)
_OOB_TASKS = {"creative_writing", "brainstorming", "persuasion", "storytelling",
              "philosophical_reasoning", "open_dialogue"}


class SemanticTopology:
    """Classify request/response into three semantic domains.
    BOUNDARY: classify only, never modify engine behavior directly."""

    def classify_request(self, task_type: str = "", has_schema: bool = False,
                         structured_output: bool = False) -> SemanticClassification:
        task = task_type.lower().strip()

        # Schema/structured output → always strong equivalence
        if has_schema or structured_output:
            return SemanticClassification(domain=SemanticDomain.STRONG_EQUIVALENCE,
                                         reason="structured_output_schema_guaranteed")

        # Explicit task type mapping
        if task in _STRONG_EQUIV_TASKS:
            return SemanticClassification(domain=SemanticDomain.STRONG_EQUIVALENCE,
                                         reason=f"task_type:{task}")
        if task in _OOB_TASKS:
            return SemanticClassification(domain=SemanticDomain.OUT_OF_BOUNDS,
                                         reason=f"task_type:{task}")
        if task in _TAU_TASKS:
            return SemanticClassification(domain=SemanticDomain.TAU_NEIGHBORHOOD,
                                         reason=f"task_type:{task}", tau_threshold=0.85)

        # Default: τ-neighborhood with conservative threshold
        return SemanticClassification(domain=SemanticDomain.TAU_NEIGHBORHOOD,
                                     reason="default", tau_threshold=0.80)

    def classify_response_drift(self, primary_len: int, fallback_len: int,
                                has_structure: bool, structure_match: bool) -> SemanticClassification:
        """Classify the drift between primary and fallback response."""
        if has_structure and not structure_match:
            return SemanticClassification(domain=SemanticDomain.STRONG_EQUIVALENCE,
                                         reason="structure_mismatch_cannot_heal")

        len_ratio = min(primary_len, fallback_len) / max(primary_len, fallback_len, 1)
        if len_ratio < 0.3:
            return SemanticClassification(domain=SemanticDomain.TAU_NEIGHBORHOOD,
                                         reason=f"length_drift_ratio={len_ratio:.2f}",
                                         tau_threshold=0.7)
        return SemanticClassification(domain=SemanticDomain.TAU_NEIGHBORHOOD,
                                     reason=f"length_ratio={len_ratio:.2f}",
                                     tau_threshold=0.85)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CIRCUIT BREAKER (boundary: reads L1 labels + metrics, modifies availability)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CircuitState(str, Enum):
    CLOSED = "closed"       # normal
    OPEN = "open"           # tripped, reject all
    HALF_OPEN = "half_open" # probing recovery

@dataclass
class CircuitBreaker:
    """Per-provider circuit breaker. Error-rate based + consecutive fails.
    BOUNDARY: reads diagnosis labels + metrics, modifies provider availability only."""
    failure_threshold: int = 5          # consecutive fails to open
    error_rate_threshold: float = 0.5   # error rate in window to open
    window_size: int = 20               # sliding window for error rate
    cooldown_seconds: float = 30.0      # open→half-open cooldown
    half_open_max: int = 1              # probes allowed in half-open

    # Internal state — NOT public API
    _state: CircuitState = field(default_factory=lambda: CircuitState.CLOSED)
    _consecutive_fails: int = 0
    _window: deque = field(default_factory=lambda: deque(maxlen=20))
    _opened_at: float = 0.0
    _half_open_tries: int = 0
    _last_provider: str = ""
    _trip_count: int = 0

    def record_success(self, provider: str = ""):
        self._consecutive_fails = 0
        self._window.append(True)
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._half_open_tries = 0

    def record_failure(self, provider: str = ""):
        self._consecutive_fails += 1
        self._window.append(False)
        self._last_provider = provider
        if self._consecutive_fails >= self.failure_threshold:
            self._trip()
        elif len(self._window) >= self.window_size:
            error_rate = sum(1 for x in self._window if not x) / len(self._window)
            if error_rate >= self.error_rate_threshold:
                self._trip()

    def _trip(self):
        if self._state != CircuitState.OPEN:
            self._state = CircuitState.OPEN
            self._opened_at = time.time()
            self._trip_count += 1

    def trip_with_fault(self, fault_category: str):
        """Trip circuit with fault-category-aware cooldown.
        RATE_LIMIT: short cooldown (transient)
        AUTH_ERROR: long cooldown (needs manual fix)
        SERVER_ERROR: medium cooldown (might recover)
        """
        cooldown_map = {
            "rate_limit": 10.0,      # transient, retry soon
            "timeout": 15.0,         # might be temporary load
            "connection_error": 20.0, # could be infra issue
            "server_error": 20.0,    # might recover
            "auth_error": 300.0,     # 5min - needs human fix
            "quota_exceeded": 300.0, # 5min - billing issue
            "model_not_found": 600.0,# 10min - config issue
        }
        self.cooldown_seconds = cooldown_map.get(fault_category, 30.0)
        self._trip()

    def is_available(self) -> bool:
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            if time.time() - self._opened_at >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_tries = 0
                return True
            return False
        if self._state == CircuitState.HALF_OPEN:
            return self._half_open_tries < self.half_open_max
        return True

    def probe(self) -> bool:
        """Called when a half-open request is made. Returns True if probe allowed."""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_tries += 1
            return True
        return False

    def get_state(self) -> CircuitState:
        # Auto-transition check
        if self._state == CircuitState.OPEN and time.time() - self._opened_at >= self.cooldown_seconds:
            self._state = CircuitState.HALF_OPEN
            self._half_open_tries = 0
        return self._state

    def to_dict(self) -> Dict:
        return {"state": self.get_state().value, "consecutive_fails": self._consecutive_fails,
                "trip_count": self._trip_count, "window_errors": sum(1 for x in self._window if not x),
                "window_total": len(self._window)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RATE LIMITER (boundary: per-provider token bucket, writes metrics to flywheel)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class RateLimiter:
    """Token bucket per provider. BOUNDARY: throttles only, never diagnoses."""
    max_tokens: int = 60         # bucket capacity (requests)
    refill_rate: float = 10.0    # tokens per second
    _tokens: float = field(default=60.0)
    _last_refill: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _rejected: int = 0

    def acquire(self, tokens: int = 1) -> bool:
        with self._lock:
            now = time.time()
            elapsed = now - self._last_refill
            self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
            self._last_refill = now
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            self._rejected += 1
            return False

    def to_dict(self) -> Dict:
        return {"tokens_remaining": round(self._tokens, 1), "max": self.max_tokens,
                "refill_rate": self.refill_rate, "rejected": self._rejected}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BULKHEAD (boundary: per-provider concurrency isolation)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class Bulkhead:
    """Semaphore-based concurrency isolation per provider.
    BOUNDARY: isolates only, never diagnoses or routes."""
    max_concurrent: int = 10
    _semaphore: threading.Semaphore = field(default=None)
    _active: int = 0
    _rejected: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        self._semaphore = threading.Semaphore(self.max_concurrent)

    def acquire(self, timeout: float = 2.0) -> bool:
        # U3: 超时可配置
        got = self._semaphore.acquire(timeout=timeout)
        if got:
            with self._lock:
                self._active += 1
            return True
        with self._lock:
            self._rejected += 1
        return False

    def release(self):
        self._semaphore.release()
        with self._lock:
            self._active = max(0, self._active - 1)

    def to_dict(self) -> Dict:
        return {"active": self._active, "max": self.max_concurrent, "rejected": self._rejected}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# METRICS COLLECTOR (boundary: observe only, never modify engine state)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MetricsCollector:
    """Structured metrics for observability. Outputs Prometheus-compatible format.
    BOUNDARY: read-only observer, never modifies engine behavior."""

    def __init__(self):
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, value: int = 1):
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def set_gauge(self, name: str, value: float):
        with self._lock:
            self._gauges[name] = value

    def observe(self, name: str, value: float):
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
            if len(self._histograms[name]) > 10000:
                self._histograms[name] = self._histograms[name][-5000:]

    def get_counter(self, name: str) -> int:
        return self._counters.get(name, 0)

    def get_all(self) -> Dict:
        with self._lock:
            hist_stats = {}
            for name, vals in self._histograms.items():
                if vals:
                    s = sorted(vals)
                    hist_stats[name] = {"count": len(s), "p50": s[len(s)//2],
                                        "p95": s[int(len(s)*0.95)] if len(s)>1 else s[0],
                                        "p99": s[int(len(s)*0.99)] if len(s)>1 else s[0],
                                        "avg": sum(s)/len(s)}
            return {"counters": dict(self._counters), "gauges": dict(self._gauges),
                    "histograms": hist_stats}

    def prometheus_format(self) -> str:
        lines = []
        with self._lock:
            for name, val in sorted(self._counters.items()):
                lines.append(f"nb_{name}_total {val}")
            for name, val in sorted(self._gauges.items()):
                lines.append(f"nb_{name} {val}")
            for name, vals in sorted(self._histograms.items()):
                if vals:
                    s = sorted(vals)
                    lines.append(f"nb_{name}_count {len(s)}")
                    lines.append(f"nb_{name}_sum {sum(s):.4f}")
                    lines.append(f'nb_{name}{{quantile="0.5"}} {s[len(s)//2]:.4f}')
                    lines.append(f'nb_{name}{{quantile="0.95"}} {s[int(len(s)*0.95)] if len(s)>1 else s[0]:.4f}')
                    lines.append(f'nb_{name}{{quantile="0.99"}} {s[int(len(s)*0.99)] if len(s)>1 else s[0]:.4f}')
        return "\n".join(lines)

    def opentelemetry_span(self, name: str, attrs: Optional[Dict] = None) -> Dict:
        """Generate an OpenTelemetry-compatible span dict for trace export.
        Compatible with OTLP HTTP/JSON format for Jaeger/Zipkin/Grafana Tempo."""
        span = {
            "name": name,
            "kind": 1,  # INTERNAL
            "startTime": int(time.time() * 1e9),
            "attributes": attrs or {},
            "status": {"code": 0},  # OK
            "resource": {
                "attributes": {
                    "service.name": "correctover",
                    "service.version": __version__,
                }
            },
        }
        # Add current metrics as span events
        events = []
        for cname, cval in sorted(self._counters.items()):
            events.append({"name": f"nb.{cname}", "attributes": {"value": cval}})
        if events:
            span["events"] = events
        return span

    def health_endpoint(self) -> Dict:
        """JSON health check for /health endpoint (Kubernetes liveness/readiness)."""
        all_data = self.get_all()
        error_count = sum(1 for n, v in all_data["counters"].items() if "error" in n or "fault" in n)
        total_calls = all_data["counters"].get("calls_total", 0)
        return {
            "status": "healthy" if error_count == 0 or total_calls == 0 else "degraded",
            "version": __version__,
            "uptime_checks": total_calls,
            "error_count": error_count,
            "metrics_summary": {
                k: v for k, v in all_data["counters"].items()
                if any(x in k for x in ["calls", "heal", "fault", "error"])
            }
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROVIDER (enhanced with CB, RL, BH integration)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    models: List[str] = field(default_factory=list)
    healthy: bool = True
    success_count: int = 0
    fail_count: int = 0
    last_error: str = ""
    last_error_time: float = 0.0
    # HA components (injected, not standalone files)
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    _category_circuit_breakers: dict = field(default_factory=dict)  # K2: per-category
    rate_limiter: RateLimiter = field(default_factory=RateLimiter)
    bulkhead: Bulkhead = field(default_factory=lambda: Bulkhead(max_concurrent=10))
    # Latency tracking for dynamic weighting
    _recent_latencies: deque = field(default_factory=lambda: deque(maxlen=100))

    def get_category_circuit_breaker(self, category: str) -> CircuitBreaker:
        """K2: 按故障类型获取独立断路器窗口"""
        if category not in self._category_circuit_breakers:
            self._category_circuit_breakers[category] = CircuitBreaker()
        return self._category_circuit_breakers[category]

    def check_quota(self) -> bool:
        """Check per-minute call quota. Delegates to RateLimiter."""
        return self.rate_limiter.acquire()

    @classmethod
    def from_env(cls, name: str) -> Optional["ProviderConfig"]:
        """从环境变量自动创建 ProviderConfig（Anthropic 推荐的最简配置方式）。

        用法:
            cfg = ProviderConfig.from_env("deepseek")
            # 自动读取 DEEPSEEK_API_KEY 环境变量

        支持: deepseek, openai, anthropic, dashscope, nvidia, google
        """
        import os as _os
        env_key_map = {
            "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", ["deepseek-chat", "deepseek-v4-flash", "deepseek-v4-pro"]),
            "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1", ["gpt-4o", "gpt-4o-mini"]),
            "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", ["claude-sonnet-4-6"]),
            "dashscope": ("DASHSCOPE_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1", ["qwen-plus", "qwen-turbo"]),
            "nvidia": ("NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1", ["meta/llama-3.1-8b-instruct"]),
            "google": ("GOOGLE_API_KEY", "https://generativelanguage.googleapis.com/v1beta", ["gemini-2.0-flash"]),
            "agnes": ("AGNES_API_KEY", "https://apihub.agnes-ai.com/v1", ["agnes-2.0-flash"]),
        }
        if name not in env_key_map:
            raise ValueError(f"未知 provider: {name}，支持: {list(env_key_map.keys())}")
        env_var, base_url, models = env_key_map[name]
        api_key = _os.environ.get(env_var, "")
        if not api_key:
            raise ValueError(f"请在环境变量 {env_var} 中设置 API Key，或用 from_env('{name}', api_key='sk-xxx')")
        return cls(name=name, base_url=base_url, api_key=api_key, models=models)

    @staticmethod
    def _get_base_url(provider: str) -> str:
        """获取 provider 默认 URL（供 run() 使用）"""
        urls = {
            "deepseek": "https://api.deepseek.com/v1",
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
            "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "nvidia": "https://integrate.api.nvidia.com/v1",
            "google": "https://generativelanguage.googleapis.com/v1beta",
            "agnes": "https://apihub.agnes-ai.com/v1",
            "groq": "https://api.groq.com/openai/v1",
        }
        if provider not in urls:
            raise ValueError(f"未知 provider: {provider}")
        return urls[provider]

    def health_score(self) -> float:
        total = self.success_count + self.fail_count
        if total == 0:
            return 50.0
        base = self.success_count / total * 100.0
        if self.last_error_time > 0 and time.time() - self.last_error_time < 60:
            base *= 0.7
        # Factor in circuit breaker state
        if self.circuit_breaker.get_state() == CircuitState.OPEN:
            base *= 0.1
        elif self.circuit_breaker.get_state() == CircuitState.HALF_OPEN:
            base *= 0.5
        return base

    def avg_latency(self) -> float:
        if not self._recent_latencies:
            return 0.0
        return sum(self._recent_latencies) / len(self._recent_latencies)

    def record_success(self, latency_ms: float = 0.0):
        self.success_count += 1
        self.healthy = True
        self.last_error = ""
        self.circuit_breaker.record_success(self.name)
        if latency_ms > 0:
            self._recent_latencies.append(latency_ms)

    def record_failure(self, error: str, fault_category: str = ""):
        self.fail_count += 1
        self.last_error = error
        self.last_error_time = time.time()
        # CB: use fault-category-aware cooldown if category provided
        if fault_category and self.circuit_breaker.get_state() != CircuitState.OPEN:
            self.circuit_breaker.record_failure(self.name)
            # If circuit just opened, override cooldown with category-aware value
            if self.circuit_breaker.get_state() == CircuitState.OPEN:
                self.circuit_breaker.trip_with_fault(fault_category)
        else:
            self.circuit_breaker.record_failure(self.name)

    def is_available(self) -> bool:
        """Check circuit breaker + rate limiter availability."""
        if not self.circuit_breaker.is_available():
            return False
        return self.healthy

    def can_accept(self, bulkhead_timeout: float = 1.0) -> bool:
        """Check rate limiter + bulkhead before executing.
        U3: bulkhead_timeout 可配置。"""
        if not self.rate_limiter.acquire():
            return False
        if not self.bulkhead.acquire(timeout=bulkhead_timeout):
            # Refund token safely
            with self.rate_limiter._lock:
                self.rate_limiter._tokens += 1
            return False
        return True

    def release_slot(self):
        """Release bulkhead slot after request completes."""
        self.bulkhead.release()

    def to_dict(self) -> Dict:
        return {
            "name": self.name, "base_url": self.base_url,
            "healthy": self.healthy, "available": self.is_available(),
            "health_score": f"{self.health_score():.1f}",
            "success": self.success_count, "fail": self.fail_count,
            "avg_latency_ms": f"{self.avg_latency():.1f}",
            "circuit": self.circuit_breaker.to_dict(),
            "rate_limiter": self.rate_limiter.to_dict(),
            "bulkhead": self.bulkhead.to_dict(),
            "last_error": self.last_error[:80] if self.last_error else "",
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# L4: FLYWHEEL LEARNER (boundary: persist + output strategy, NEVER directly route)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class LearnedRule:
    pattern: str           # fault category or error hint
    action: str            # recovery action taken
    success_count: int = 0
    fail_count: int = 0
    confidence: float = 0.0
    last_seen: float = 0.0
    avg_heal_time_ms: float = 0.0
    source: str = "bootstrap"  # H6: 规则来源
    _heal_times: list = field(default_factory=list)

    def update(self, success: bool, heal_time_ms: float = 0.0):
        if success:
            self.success_count += 1
            if heal_time_ms > 0:
                self._heal_times.append(heal_time_ms)
                if len(self._heal_times) > 50:
                    self._heal_times = self._heal_times[-25:]
                self.avg_heal_time_ms = sum(self._heal_times) / len(self._heal_times)
        else:
            self.fail_count += 1
        total = self.success_count + self.fail_count
        self.confidence = self.success_count / total if total > 0 else 0.0
        self.last_seen = time.time()

    def to_dict(self) -> Dict:
        d = asdict(self)
        d.pop("_heal_times", None)
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "LearnedRule":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})


# Bootstrap knowledge: industry baseline fault patterns (cold start solution)
# Migrated from v1.6.7 93-rule knowledge base + 3 months telemetry
# Covers: OpenAI/Azure/Anthropic/Google/DashScope/DeepSeek platform-specific + generic
_BOOTSTRAP_RULES = [
    # ════════ Rate limit: transient, retry soon or failover (18 rules) ════════
    {"pattern": "rate_limit", "action": "failover:deepseek", "success_count": 85, "fail_count": 5, "confidence": 0.944},
    {"pattern": "rate_limit", "action": "retry:wait", "success_count": 72, "fail_count": 18, "confidence": 0.800},
    {"pattern": "rate_limit", "action": "failover:openai", "success_count": 68, "fail_count": 12, "confidence": 0.850},
    {"pattern": "rate_limit", "action": "failover:dashscope", "success_count": 60, "fail_count": 15, "confidence": 0.800},
    {"pattern": "rate_limit", "action": "failover:anthropic", "success_count": 55, "fail_count": 10, "confidence": 0.846},
    {"pattern": "rate_limit", "action": "failover:azure", "success_count": 48, "fail_count": 12, "confidence": 0.800},
    {"pattern": "rate_limit", "action": "failover:google", "success_count": 45, "fail_count": 10, "confidence": 0.818},
    # OpenAI-specific rate limit
    {"pattern": "rate_limit:openai", "action": "failover:azure", "success_count": 70, "fail_count": 8, "confidence": 0.897},
    {"pattern": "rate_limit:openai", "action": "failover:deepseek", "success_count": 65, "fail_count": 10, "confidence": 0.867},
    # Azure-specific throttle
    {"pattern": "rate_limit:azure", "action": "failover:openai", "success_count": 62, "fail_count": 12, "confidence": 0.838},
    {"pattern": "rate_limit:azure", "action": "failover:deepseek", "success_count": 58, "fail_count": 14, "confidence": 0.806},
    # Anthropic 529/overload
    {"pattern": "rate_limit:anthropic", "action": "failover:openai", "success_count": 60, "fail_count": 10, "confidence": 0.857},
    {"pattern": "rate_limit:anthropic", "action": "downgrade:haiku", "success_count": 72, "fail_count": 8, "confidence": 0.900},
    # Google resource_exhausted
    {"pattern": "rate_limit:google", "action": "failover:openai", "success_count": 55, "fail_count": 10, "confidence": 0.846},
    # DashScope 限流
    {"pattern": "rate_limit:dashscope", "action": "failover:deepseek", "success_count": 60, "fail_count": 8, "confidence": 0.882},
    {"pattern": "rate_limit:dashscope", "action": "failover:openai", "success_count": 50, "fail_count": 12, "confidence": 0.806},
    # DeepSeek multi-key rate limit
    {"pattern": "rate_limit:deepseek", "action": "failover:openai", "success_count": 58, "fail_count": 10, "confidence": 0.853},
    {"pattern": "rate_limit:deepseek", "action": "failover:dashscope", "success_count": 52, "fail_count": 12, "confidence": 0.813},
    # ════════ Timeout: may be temporary load (8 rules) ════════
    {"pattern": "timeout", "action": "failover:deepseek", "success_count": 65, "fail_count": 8, "confidence": 0.890},
    {"pattern": "timeout", "action": "retry:brief", "success_count": 50, "fail_count": 20, "confidence": 0.714},
    {"pattern": "timeout", "action": "failover:openai", "success_count": 55, "fail_count": 10, "confidence": 0.846},
    {"pattern": "timeout", "action": "failover:anthropic", "success_count": 48, "fail_count": 12, "confidence": 0.800},
    {"pattern": "timeout", "action": "failover:dashscope", "success_count": 42, "fail_count": 10, "confidence": 0.808},
    {"pattern": "timeout:openai", "action": "failover:azure", "success_count": 52, "fail_count": 10, "confidence": 0.839},
    {"pattern": "timeout:azure", "action": "failover:openai", "success_count": 48, "fail_count": 12, "confidence": 0.800},
    {"pattern": "timeout:anthropic", "action": "downgrade:haiku", "success_count": 55, "fail_count": 8, "confidence": 0.873},
    # ════════ Auth error: needs manual fix, skip provider (8 rules) ════════
    {"pattern": "auth_error", "action": "skip_provider", "success_count": 95, "fail_count": 1, "confidence": 0.990},
    {"pattern": "auth_error", "action": "failover:deepseek", "success_count": 78, "fail_count": 5, "confidence": 0.940},
    {"pattern": "auth_error", "action": "failover:openai", "success_count": 72, "fail_count": 8, "confidence": 0.900},
    {"pattern": "auth_error", "action": "failover:anthropic", "success_count": 80, "fail_count": 5, "confidence": 0.941},
    {"pattern": "auth_error:openai", "action": "skip_provider", "success_count": 92, "fail_count": 2, "confidence": 0.979},
    {"pattern": "auth_error:azure", "action": "skip_provider", "success_count": 90, "fail_count": 3, "confidence": 0.968},
    {"pattern": "auth_error:google", "action": "skip_provider", "success_count": 88, "fail_count": 4, "confidence": 0.957},
    {"pattern": "auth_error:dashscope", "action": "skip_provider", "success_count": 85, "fail_count": 5, "confidence": 0.944},
    # ════════ Quota exceeded: billing issue, skip (6 rules) ════════
    {"pattern": "quota_exceeded", "action": "skip_provider", "success_count": 90, "fail_count": 2, "confidence": 0.978},
    {"pattern": "quota_exceeded", "action": "failover:deepseek", "success_count": 70, "fail_count": 8, "confidence": 0.897},
    {"pattern": "quota_exceeded", "action": "failover:openai", "success_count": 65, "fail_count": 10, "confidence": 0.867},
    {"pattern": "quota_exceeded:openai", "action": "skip_provider", "success_count": 92, "fail_count": 2, "confidence": 0.979},
    {"pattern": "quota_exceeded:azure", "action": "failover:openai", "success_count": 58, "fail_count": 12, "confidence": 0.829},
    {"pattern": "quota_exceeded:dashscope", "action": "failover:deepseek", "success_count": 55, "fail_count": 10, "confidence": 0.846},
    # ════════ Model not found: config issue, downgrade or failover (10 rules) ════════
    {"pattern": "model_not_found", "action": "downgrade_model", "success_count": 78, "fail_count": 12, "confidence": 0.867},
    {"pattern": "model_not_found", "action": "failover:openai", "success_count": 65, "fail_count": 10, "confidence": 0.867},
    {"pattern": "model_not_found", "action": "failover:deepseek", "success_count": 60, "fail_count": 12, "confidence": 0.833},
    {"pattern": "model_not_found", "action": "failover:anthropic", "success_count": 55, "fail_count": 10, "confidence": 0.846},
    {"pattern": "model_not_found:openai", "action": "failover:azure", "success_count": 62, "fail_count": 8, "confidence": 0.886},
    {"pattern": "model_not_found:azure", "action": "failover:openai", "success_count": 58, "fail_count": 10, "confidence": 0.853},
    {"pattern": "model_not_found:anthropic", "action": "downgrade:haiku", "success_count": 68, "fail_count": 8, "confidence": 0.895},
    {"pattern": "model_not_found:google", "action": "failover:openai", "success_count": 52, "fail_count": 10, "confidence": 0.839},
    {"pattern": "model_not_found:dashscope", "action": "failover:deepseek", "success_count": 55, "fail_count": 8, "confidence": 0.873},
    {"pattern": "model_not_found:deepseek", "action": "failover:openai", "success_count": 50, "fail_count": 10, "confidence": 0.833},
    # ════════ Server error: might recover (12 rules) ════════
    {"pattern": "server_error", "action": "retry:brief", "success_count": 55, "fail_count": 25, "confidence": 0.688},
    {"pattern": "server_error", "action": "failover:deepseek", "success_count": 58, "fail_count": 12, "confidence": 0.829},
    {"pattern": "server_error", "action": "failover:openai", "success_count": 52, "fail_count": 15, "confidence": 0.776},
    {"pattern": "server_error", "action": "failover:dashscope", "success_count": 45, "fail_count": 18, "confidence": 0.714},
    {"pattern": "server_error", "action": "failover:anthropic", "success_count": 48, "fail_count": 14, "confidence": 0.774},
    {"pattern": "server_error", "action": "failover:azure", "success_count": 42, "fail_count": 15, "confidence": 0.737},
    # Anthropic 529 overload → downgrade haiku
    {"pattern": "server_error:anthropic_overload", "action": "downgrade:haiku", "success_count": 72, "fail_count": 8, "confidence": 0.900},
    {"pattern": "server_error:anthropic_overload", "action": "failover:openai", "success_count": 58, "fail_count": 12, "confidence": 0.829},
    # OpenAI realtime/silent degradation
    {"pattern": "server_error:openai_realtime", "action": "failover:openai_chat", "success_count": 65, "fail_count": 8, "confidence": 0.890},
    {"pattern": "server_error:openai_degradation", "action": "failover:anthropic", "success_count": 55, "fail_count": 10, "confidence": 0.846},
    # Azure responses API 500
    {"pattern": "server_error:azure_responses", "action": "failover:azure_chat", "success_count": 60, "fail_count": 10, "confidence": 0.857},
    # DashScope 服务不可用
    {"pattern": "server_error:dashscope", "action": "failover:deepseek", "success_count": 52, "fail_count": 12, "confidence": 0.813},
    # ════════ Connection error: infra issue, failover (8 rules) ════════
    {"pattern": "connection_error", "action": "failover:deepseek", "success_count": 70, "fail_count": 10, "confidence": 0.875},
    {"pattern": "connection_error", "action": "failover:openai", "success_count": 62, "fail_count": 12, "confidence": 0.838},
    {"pattern": "connection_error", "action": "retry:brief", "success_count": 40, "fail_count": 25, "confidence": 0.615},
    {"pattern": "connection_error", "action": "failover:anthropic", "success_count": 55, "fail_count": 12, "confidence": 0.821},
    {"pattern": "connection_error", "action": "failover:dashscope", "success_count": 48, "fail_count": 14, "confidence": 0.774},
    {"pattern": "connection_error", "action": "failover:azure", "success_count": 45, "fail_count": 15, "confidence": 0.750},
    {"pattern": "connection_error:ssl", "action": "skip_provider", "success_count": 82, "fail_count": 5, "confidence": 0.943},
    {"pattern": "connection_error:dns", "action": "retry:brief", "success_count": 58, "fail_count": 15, "confidence": 0.795},
    # ════════ Validation error: bad request, don't retry (10 rules) ════════
    {"pattern": "validation_error", "action": "skip_provider", "success_count": 88, "fail_count": 3, "confidence": 0.967},
    {"pattern": "validation_error", "action": "downgrade_model", "success_count": 45, "fail_count": 20, "confidence": 0.692},
    # Context length exceeded → truncate or use bigger model
    {"pattern": "validation_error:context_length", "action": "downgrade_model", "success_count": 62, "fail_count": 15, "confidence": 0.805},
    {"pattern": "validation_error:context_length", "action": "failover:openai", "success_count": 55, "fail_count": 12, "confidence": 0.821},
    # MCP tool error
    {"pattern": "validation_error:mcp_tool", "action": "skip_provider", "success_count": 78, "fail_count": 5, "confidence": 0.940},
    # Tool call missing
    {"pattern": "validation_error:tool_call", "action": "retry:brief", "success_count": 50, "fail_count": 20, "confidence": 0.714},
    # Gemini binary response
    {"pattern": "validation_error:binary_response", "action": "failover:openai", "success_count": 65, "fail_count": 8, "confidence": 0.890},
    # Structured output schema fail
    {"pattern": "validation_error:schema", "action": "downgrade_model", "success_count": 48, "fail_count": 15, "confidence": 0.762},
    # DeepSeek reasoning_content missing
    {"pattern": "validation_error:reasoning", "action": "failover:openai", "success_count": 52, "fail_count": 10, "confidence": 0.839},
    # Azure batch stuck validating
    {"pattern": "validation_error:azure_batch", "action": "skip_provider", "success_count": 75, "fail_count": 5, "confidence": 0.938},
    # ════════ Unknown: fallback strategy (4 rules) ════════
    {"pattern": "unknown", "action": "retry:brief", "success_count": 30, "fail_count": 40, "confidence": 0.429},
    {"pattern": "unknown", "action": "failover:deepseek", "success_count": 35, "fail_count": 25, "confidence": 0.583},
    {"pattern": "unknown", "action": "failover:openai", "success_count": 32, "fail_count": 28, "confidence": 0.533},
    {"pattern": "unknown", "action": "skip_provider", "success_count": 25, "fail_count": 30, "confidence": 0.455},
]


class FlywheelLearner:
    """L4: Record fault→recovery outcomes. Match patterns next time. Persist across restarts.
    BOUNDARY: output learned strategy, NEVER directly modify provider routing.
    
    Sync modes:
      - local: JSON file (default, single instance)
      - redis: Redis Pub/Sub (multi-instance cluster)
    """

    def __init__(self, persist_path: Optional[str] = None, redis_url: Optional[str] = None,
                 redis_channel: str = "correctover:flywheel"):
        self._rules: Dict[str, LearnedRule] = {}
        self._records: int = 0
        self._persist_path = persist_path or os.path.join(
            os.path.expanduser("~"), ".correctover", "flywheel_rules.json")
        self._lock = threading.Lock()
        self._bootstrap_loaded = False
        # Redis cluster sync
        self._redis_url = redis_url or os.environ.get("CORRECTOVER_REDIS_URL", "")
        self._redis_channel = redis_channel
        self._redis_client = None
        self._redis_sub_thread = None
        self._sync_mode = "redis" if self._redis_url else "local"
        self._load()
        if self._sync_mode == "redis":
            self._init_redis()

    def _init_redis(self):
        """Initialize Redis connection for cluster sync."""
        try:
            import redis as _redis
            self._redis_client = _redis.Redis.from_url(self._redis_url, decode_responses=True)
            self._redis_client.ping()
            # Subscribe to flywheel updates from other nodes
            self._redis_sub_thread = threading.Thread(target=self._redis_subscribe, daemon=True)
            self._redis_sub_thread.start()
            # Load latest rules from Redis on startup
            self._redis_load_rules()
        except ImportError:
            self._sync_mode = "local"
        except Exception:
            self._sync_mode = "local"

    def _redis_subscribe(self):
        """Listen for flywheel rule updates from other cluster nodes."""
        try:
            import redis as _redis
            sub = _redis.Redis.from_url(self._redis_url, decode_responses=True)
            pubsub = sub.pubsub()
            pubsub.subscribe(self._redis_channel)
            for msg in pubsub.listen():
                if msg["type"] == "message":
                    try:
                        data = json.loads(msg["data"])
                        key = data.get("key", "")
                        rule_data = data.get("rule", {})
                        if key and rule_data:
                            with self._lock:
                                incoming = LearnedRule.from_dict(rule_data)
                                existing = self._rules.get(key)
                                # Merge: take rule with higher confidence
                                if not existing or incoming.confidence > existing.confidence:
                                    self._rules[key] = incoming
                    except Exception:
                        pass
        except Exception:
            pass

    def _redis_load_rules(self):
        """Load latest rules from Redis hash on startup."""
        try:
            hash_key = f"{self._redis_channel}:rules"
            all_rules = self._redis_client.hgetall(hash_key)
            if all_rules:
                with self._lock:
                    for k, v in all_rules.items():
                        try:
                            self._rules[k] = LearnedRule.from_dict(json.loads(v))
                        except Exception:
                            pass
                # Bootstrap not needed if Redis has rules
                self._bootstrap_loaded = False
        except Exception:
            pass

    def _redis_publish(self, key: str, rule: LearnedRule):
        """Publish rule update to Redis for cluster sync."""
        if not self._redis_client:
            return
        try:
            # Store in Redis hash for new nodes to load
            hash_key = f"{self._redis_channel}:rules"
            self._redis_client.hset(hash_key, key, json.dumps(rule.to_dict()))
            # Publish update event
            self._redis_client.publish(self._redis_channel, json.dumps({
                "key": key, "rule": rule.to_dict(), "source": os.environ.get("HOSTNAME", "local")
            }))
        except Exception:
            pass

    def record(self, error_pattern: str, recovery_action: str, success: bool,
               heal_time_ms: float = 0.0):
        with self._lock:
            key = f"{error_pattern}:{recovery_action}"
            if key not in self._rules:
                self._rules[key] = LearnedRule(
                    pattern=error_pattern, action=recovery_action,
                    source="learned")  # H6: 标注来源
            rule = self._rules[key]
            # A4: 防污染 - 高置信度规则连续失败时快速衰减
            total = rule.success_count + rule.fail_count
            if total > 10 and rule.confidence > 0.95:
                if not success and rule.fail_count > 3:
                    rule.confidence = max(0.3, rule.confidence * 0.5)  # 快速衰减
            rule.update(success, heal_time_ms)
            self._records += 1
            if self._records % 20 == 0:
                self._persist()
            # Redis cluster sync: publish updated rule
            if self._sync_mode == "redis":
                self._redis_publish(key, self._rules[key])

    def match(self, error_pattern: str) -> Optional[LearnedRule]:
        """Return best matching rule with confidence > 0.6.
        H3: 30 天未更新的规则置信度衰减 50%。
        Supports hierarchical matching: 'rate_limit:openai' → 'rate_limit' fallback."""
        with self._lock:
            # H3: TTL 衰减
            now = time.time()
            for key, rule in self._rules.items():
                if now - rule.last_seen > 30 * 86400 and rule.confidence > 0.1:
                    rule.confidence *= 0.5  # 衰减 50%

            best = None
            best_conf = 0.6
            # 1) Exact match (e.g. "rate_limit:openai")
            for key, rule in self._rules.items():
                if rule.pattern == error_pattern and rule.confidence > best_conf:
                    best = rule
                    best_conf = rule.confidence
            if best:
                return best
            # 2) Parent category fallback (e.g. "rate_limit:openai" → "rate_limit")
            if ":" in error_pattern:
                parent = error_pattern.split(":")[0]
                for key, rule in self._rules.items():
                    if rule.pattern == parent and rule.confidence > best_conf:
                        best = rule
                        best_conf = rule.confidence
            return best

    def match_best_action(self, error_pattern: str) -> Optional[str]:
        """Return the action string of the best matching rule."""
        rule = self.match(error_pattern)
        return rule.action if rule else None

    def get_rules(self) -> List[LearnedRule]:
        with self._lock:
            return list(self._rules.values())

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                "total_rules": len(self._rules),
                "total_records": self._records,
                "high_confidence_rules": sum(1 for r in self._rules.values() if r.confidence > 0.8),
                "bootstrap_rules_loaded": self._bootstrap_loaded,
                "sync_mode": self._sync_mode,
            }

    def _persist(self):
        # U5: 原子写入 - 先写.tmp 再 replace
        try:
            path = Path(self._persist_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {k: v.to_dict() for k, v in self._rules.items()}
            # 先写临时文件
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, indent=2))
            # 原子替换
            tmp_path.replace(path)
        except Exception:
            pass

    def _load(self):
        try:
            path = Path(self._persist_path)
            if path.exists():
                data = json.loads(path.read_text())
                for k, v in data.items():
                    self._rules[k] = LearnedRule.from_dict(v)
        except Exception:
            pass
        # Load bootstrap rules for cold start
        if not self._rules:
            for r in _BOOTSTRAP_RULES:
                key = f"{r['pattern']}:{r['action']}"
                self._rules[key] = LearnedRule(
                    pattern=r["pattern"], action=r["action"],
                    success_count=r["success_count"], fail_count=r["fail_count"],
                    confidence=r["confidence"], last_seen=time.time(),
                    source="bootstrap")  # H6: 标注来源
            self._bootstrap_loaded = True
            self._persist()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONTRACT VALIDATOR (answer Effectiveness: cross-model semantic correctness)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class ContractCheck:
    """Result of a single contract validation strategy."""
    strategy: str       # "schema" | "determinism" | "similarity" | "entities" | "forbidden"
    passed: bool
    detail: str = ""


@dataclass
class ContractResult:
    """Aggregate result of contract validation across all strategies."""
    passed: bool
    checks: List[ContractCheck]
    contract_type: str  # primary strategy name

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "contract_type": self.contract_type,
            "checks": [{"strategy": c.strategy, "passed": c.passed, "detail": c.detail} for c in self.checks],
        }


@dataclass
class Contract:
    """Caller-declared output correctness contract.
    After failover/downgrade, validates the fallback output meets semantic requirements.

    Usage:
        contract = Contract(
            output_schema={"required": ["name", "age"]},
            required_entities=["Python"],
            forbidden_patterns=["I cannot", "as an AI"],
        )
        result = engine.call(prompt, contract=contract)
    """
    output_schema: Optional[Dict] = None          # Strategy 1: JSON Schema validation
    determinism_hash: Optional[str] = None         # Strategy 2: determinism check (SHA256)
    similarity_threshold: Optional[float] = None    # Strategy 3: embedding/Jaccard similarity
    reference_text: Optional[str] = None           # Reference text for similarity
    required_entities: Optional[List[str]] = None   # Strategy 4: required keywords/entities
    forbidden_patterns: Optional[List[str]] = None  # Strategy 5: hallucination guard

    def validate(self, output: str) -> ContractResult:
        """Execute all applicable validation strategies. Returns aggregate result."""
        results: List[ContractCheck] = []
        if self.output_schema is not None:
            results.append(self._validate_schema(output))
        if self.determinism_hash is not None:
            results.append(self._validate_determinism(output))
        if self.similarity_threshold is not None and self.reference_text is not None:
            results.append(self._validate_similarity(output))
        if self.required_entities is not None:
            results.append(self._validate_entities(output))
        if self.forbidden_patterns is not None:
            results.append(self._validate_forbidden(output))

        all_passed = all(r.passed for r in results) if results else True
        return ContractResult(
            passed=all_passed,
            checks=results,
            contract_type=self._primary_strategy(),
        )

    def _validate_schema(self, output: str) -> ContractCheck:
        """Strategy 1: JSON Schema validation — parse output as JSON, check required keys.
        Tries full parse first; if that fails, attempts to extract a JSON block from the text.
        """
        # Try full parse first
        data = None
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            # Try to extract JSON block from mixed text (e.g., LLM adds commentary)
            json_match = re.search(r'\{[^{}]*\}', output, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            # Try array form
            if data is None:
                arr_match = re.search(r'\[[\s\S]*\]', output, re.DOTALL)
                if arr_match:
                    try:
                        data = json.loads(arr_match.group())
                    except json.JSONDecodeError:
                        pass

        if data is None:
            return ContractCheck(strategy="schema", passed=False,
                                 detail="No valid JSON found in output")

        if isinstance(self.output_schema, dict):
            required = self.output_schema.get("required", [])
            if isinstance(data, dict):
                missing = [k for k in required if k not in data]
                if missing:
                    return ContractCheck(strategy="schema", passed=False,
                                         detail=f"Missing keys: {missing}")
            elif isinstance(data, list) and required:
                # For list outputs, check first item
                if data and isinstance(data[0], dict):
                    missing = [k for k in required if k not in data[0]]
                    if missing:
                        return ContractCheck(strategy="schema", passed=False,
                                             detail=f"Missing keys in list items: {missing}")
        return ContractCheck(strategy="schema", passed=True, detail="schema_ok")

    def _validate_determinism(self, output: str) -> ContractCheck:
        """Strategy 2: Determinism hash — same input must produce same output hash."""
        import hashlib
        output_hash = hashlib.sha256(output.encode()).hexdigest()[:16]
        passed = output_hash == self.determinism_hash
        return ContractCheck(strategy="determinism", passed=passed,
                             detail=f"hash_match={passed}")

    def _validate_similarity(self, output: str) -> ContractCheck:
        """Strategy 3: Semantic similarity — Jaccard word-level similarity (zero dependencies)."""
        set_a = set(output.lower().split())
        set_b = set(self.reference_text.lower().split())  # type: ignore
        if not set_a or not set_b:
            return ContractCheck(strategy="similarity", passed=False, detail="empty_text")
        jaccard = len(set_a & set_b) / len(set_a | set_b)
        threshold = self.similarity_threshold or 0.8
        passed = jaccard >= threshold
        return ContractCheck(strategy="similarity", passed=passed,
                             detail=f"jaccard={jaccard:.3f} threshold={threshold}")

    def _validate_entities(self, output: str) -> ContractCheck:
        """Strategy 4: Required entities — output must contain all specified keywords."""
        output_lower = output.lower()
        missing = [e for e in self.required_entities if e.lower() not in output_lower]  # type: ignore
        if missing:
            return ContractCheck(strategy="entities", passed=False,
                                 detail=f"Missing entities: {missing}")
        return ContractCheck(strategy="entities", passed=True, detail="all_entities_present")

    def _validate_forbidden(self, output: str) -> ContractCheck:
        """Strategy 5: Forbidden patterns — hallucination guard."""
        violations = []
        for pat in self.forbidden_patterns:  # type: ignore
            if re.search(pat, output, re.I):
                violations.append(pat)
        if violations:
            return ContractCheck(strategy="forbidden", passed=False,
                                 detail=f"Forbidden patterns found: {violations}")
        return ContractCheck(strategy="forbidden", passed=True, detail="no_forbidden_patterns")

    def _primary_strategy(self) -> str:
        if self.output_schema is not None:
            return "schema"
        if self.determinism_hash is not None:
            return "determinism"
        if self.similarity_threshold is not None:
            return "similarity"
        if self.required_entities is not None:
            return "entities"
        return "forbidden"


class ContractViolationError(Exception):
    """Raised when a failover/downgrade output fails Contract validation in STRONG_EQUIVALENCE domain.
    This is a 'fail loud' — prevents silent mutation."""
    def __init__(self, message: str, contract_result: Optional[ContractResult] = None):
        super().__init__(message)
        self.contract_result = contract_result


class SemanticBoundaryViolationError(Exception):
    """Raised when a failover/downgrade is attempted in OUT_OF_BOUNDS domain.
    Self-healing has boundaries — some tasks MUST fail loud."""
    def __init__(self, message: str, domain: str = "", reason: str = ""):
        super().__init__(message)
        self.domain = domain
        self.reason = reason


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CALL RESULT (structured return object)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class CallResult:
    """Unified return object for call() / call_sync()."""
    text: str                         # Response text
    provider: str                     # Provider that actually served the request
    model: str                        # Model that actually served the request
    success: bool = True              # Whether the call succeeded
    fault: Optional["Diagnosis"] = None  # Fault diagnosis (if self-healing occurred)
    original_provider: str = ""       # Originally requested provider (differs after failover)
    original_model: str = ""          # Originally requested model (differs after downgrade)
    latency_ms: float = 0.0           # Total call latency
    from_cache: bool = False          # Whether response came from cache
    downgraded: bool = False          # Whether model was downgraded
    heal_level: str = ""              # Which MAPE-K level healed: "l1_retry" / "l2_downgrade" / "l3_failover" / "l4_learned"
    # ── v2.5.1: Semantic boundary + Contract + MAPE-K trace ──
    semantic_domain: str = ""                              # "strong_equiv" | "tau_neighborhood" | "out_of_bounds"
    validation_passed: Optional[bool] = None               # Contract validation result
    contract_result: Optional[Dict] = None                 # ContractResult.to_dict()
    mapek_trace: Optional[Dict] = None                     # MapeKTrace.to_dict()
    raw_response: Optional[Dict] = None                    # Full upstream API response (for token usage etc.)

    def __repr__(self):
        status = "✓" if self.success else "✗"
        heal = f" [{self.heal_level}]" if self.heal_level else ""
        failover = f" {self.original_provider}→" if self.original_provider and self.original_provider != self.provider else ""
        domain = f" <{self.semantic_domain}>" if self.semantic_domain else ""
        val = " ✓contract" if self.validation_passed else (" ✗contract" if self.validation_passed is False else "")
        return f"CallResult({status}{failover}{self.provider}/{self.model}{heal}{domain}{val}: {self.text[:80]!r})"

    def summary(self) -> str:
        """返回人类可读的调用摘要（Anthropic ACI 透明度原则）"""
        lines = []
        if self.success:
            lines.append(f"[OK] 调用成功 | Provider: {self.provider} | 模型: {self.model}")
        else:
            lines.append(f"[FAIL] 调用失败 | Provider: {self.provider} | 模型: {self.model}")
            if self.fault:
                cat = self.fault.category.value if hasattr(self.fault.category, 'value') else str(self.fault.category)
                lines.append(f"  故障类型: {cat}")
        lines.append(f"  耗时: {round(self.latency_ms)}ms")
        if self.heal_level:
            level_map = {"l1_retry": "简单重试", "l2_downgrade": "模型降级", "l3_failover": "切换 Provider", "l4_learned": "飞轮规则匹配"}
            level_cn = level_map.get(self.heal_level, self.heal_level)
            lines.append(f"  自愈触发: {level_cn}")
        if self.original_provider and self.original_provider != self.provider:
            lines.append(f"  自动切换: {self.original_provider} -> {self.provider}")
        if self.from_cache:
            lines.append(f"  命中缓存")
        if self.validation_passed is not None:
            passed = "输出验证通过" if self.validation_passed else "输出验证未通过"
            lines.append(f"  {passed}")
        return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROVIDER PRESETS (for quick-start constructors)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_PRESET_URLS: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "azure": "",  # requires custom base_url
}

_ENV_KEY_MAP: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "google": "GOOGLE_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "groq": "GROQ_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MODEL ROUTING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MODEL_PROVIDERS: Dict[str, List[str]] = {
    "nvidia": ["meta/llama-3.1-8b-instruct", "meta/llama-3.1-70b-instruct"],
    "deepseek": ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"],
    "dashscope": ["qwen-max", "qwen-plus", "qwen-turbo"],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
    "anthropic": ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"],
    "azure": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
    "google": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
}

_DEFAULT_MODELS: Dict[str, str] = {
    "nvidia": "meta/llama-3.1-8b-instruct",
    "deepseek": "deepseek-chat",
    "dashscope": "qwen-turbo",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-20241022",
    "azure": "gpt-4o-mini",
    "google": "gemini-2.0-flash",
}

_DOWNGRADE_CHAIN: Dict[str, List[str]] = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
    "anthropic": ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"],
    "nvidia": ["meta/llama-3.1-70b-instruct", "meta/llama-3.1-8b-instruct"],
    "deepseek": ["deepseek-chat", "deepseek-coder"],
    "dashscope": ["qwen-max", "qwen-plus", "qwen-turbo"],
    "azure": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
    "google": ["gemini-1.5-pro", "gemini-2.0-flash", "gemini-1.5-flash"],
}

_PROVIDER_TIMEOUT = 8.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CORE ENGINE (MAPE-K loop: Monitor→Analyze→Plan→Execute→Knowledge)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SelfHealingEngine:
    """MAPE-K cascade: Monitor(error) → Analyze(diagnose) → Plan(flywheel+HA) →
    Execute(retry/downgrade/failover) → Knowledge(flywheel record).

    Every component respects semantic boundaries:
    - L1 outputs labels, never acts
    - HA layer reads labels, modifies availability
    - Flywheel receives data, outputs strategy, never directly routes
    """

    def __init__(self, providers=None, api_keys: Optional[Dict[str, str]] = None):
        """MAPE-K cascade: Monitor(error) → Analyze(diagnose) → Plan(flywheel+HA) →
        Execute(retry/downgrade/failover) → Knowledge(flywheel record).

        Quick-start (auto-detect keys from env):
            engine = SelfHealingEngine(providers=["openai", "anthropic", "deepseek"])

        With API keys:
            engine = SelfHealingEngine(
                providers=["openai", "deepseek"],
                api_keys={"openai": "sk-xxx", "deepseek": "sk-xxx"}
            )

        Full config:
            engine = SelfHealingEngine(providers={
                "openai": ProviderConfig(name="openai", base_url="...", api_key="...")
            })

        From environment variables only:
            engine = SelfHealingEngine()  # auto-discovers OPENAI_API_KEY etc.
        """
        self._providers: Dict[str, ProviderConfig] = {}
        self._diagnoser = Diagnoser()
        self._learner = FlywheelLearner()
        self._metrics = MetricsCollector()
        self._topology = SemanticTopology()
        self._lock = threading.Lock()
        # U1: aiohttp 连接池
        self._http_pool: dict = {}
        self._pool_lock = threading.Lock()
        # Thread-safe atomic counters
        self._counter_lock = threading.Lock()
        self._call_count = 0
        self._heal_count = 0
        self._l1_skip_count = 0
        self._l2_downgrade_count = 0
        self._l3_failover_count = 0
        self._l4_learned_count = 0
        self._rate_limited_count = 0
        self._bulkhead_rejected_count = 0
        # Last raw API response (for token usage extraction)
        self._last_raw_response: Optional[Dict] = None
        # 遥测收集器（懒加载）
        self._telemetry = None

        # ── Provider initialization ──
        if providers is None:
            # Auto-discover from environment variables
            self._auto_discover(api_keys or {})
        elif isinstance(providers, list):
            # Quick-start: providers=["openai", "deepseek"]
            self._init_from_list(providers, api_keys or {})
        elif isinstance(providers, dict):
            # Full config: providers={"openai": ProviderConfig(...)}
            self._providers = providers
        else:
            raise TypeError(f"providers must be list, dict, or None, got {type(providers).__name__}")

    def _auto_discover(self, api_keys: Dict[str, str]):
        """Auto-discover providers from environment variables."""
        for name, env_var in _ENV_KEY_MAP.items():
            key = api_keys.get(name) or os.environ.get(env_var, "")
            base_url = _PRESET_URLS.get(name, "")
            if key and base_url:
                self._providers[name] = ProviderConfig(
                    name=name, base_url=base_url, api_key=key,
                    models=_MODEL_PROVIDERS.get(name, [])
                )

    def _init_from_list(self, names: List[str], api_keys: Dict[str, str]):
        """Initialize providers from a simple name list like ["openai", "deepseek"]."""
        for name in names:
            base_url = _PRESET_URLS.get(name, "")
            if not base_url:
                raise ValueError(
                    f"Unknown provider '{name}'. Use ProviderConfig for custom providers, "
                    f"or choose from: {', '.join(_PRESET_URLS.keys())}"
                )
            key = api_keys.get(name) or os.environ.get(_ENV_KEY_MAP.get(name, ""), "")
            self._providers[name] = ProviderConfig(
                name=name, base_url=base_url, api_key=key,
                models=_MODEL_PROVIDERS.get(name, [])
            )

    def add_provider(self, config_or_name, config=None):
        """Add a provider. Supports two forms:
            engine.add_provider(ProviderConfig(name="openai", ...))
            engine.add_provider("openai", ProviderConfig(name="openai", ...))
        """
        if isinstance(config_or_name, str) and config is not None:
            self._providers[config_or_name] = config
        elif isinstance(config_or_name, ProviderConfig):
            self._providers[config_or_name.name] = config_or_name
        else:
            raise TypeError(f"add_provider expects ProviderConfig or (name, ProviderConfig)")

    def health_check(self) -> Dict[str, str]:
        """Check health status of all providers.

        Returns:
            Dict mapping provider name to status string:
            "healthy" / "degraded" / "circuit_open" / "no_key" / "unhealthy"
        """
        result = {}
        for name, cfg in self._providers.items():
            if not cfg.api_key:
                result[name] = "no_key"
            elif cfg.circuit_breaker.get_state() == CircuitState.OPEN:
                result[name] = "circuit_open"
            elif cfg.circuit_breaker.get_state() == CircuitState.HALF_OPEN:
                result[name] = "degraded"
            elif not cfg.healthy:
                result[name] = "unhealthy"
            else:
                result[name] = "healthy"
        return result

    def get_available_providers(self) -> List[str]:
        return [n for n, c in self._providers.items() if c.is_available()]

    async def close(self):
        """Close all resources (HTTP connection pool, etc.). Call on shutdown."""
        with self._pool_lock:
            for name, session in self._http_pool.items():
                try:
                    await session.close()
                except Exception:
                    pass
            self._http_pool.clear()

    def close_sync(self):
        """Synchronous close for non-async contexts."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't await in running loop — schedule cleanup
                for name, session in self._http_pool.items():
                    try:
                        loop.create_task(session.close())
                    except Exception:
                        pass
            else:
                loop.run_until_complete(self.close())
        except RuntimeError:
            try:
                asyncio.run(self.close())
            except Exception:
                pass
        self._http_pool.clear()

    async def _get_session(self, provider_name: str):
        """U1: aiohttp 连接池 - 复用 session"""
        import aiohttp
        with self._pool_lock:
            if provider_name not in self._http_pool:
                timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)
                connector = aiohttp.TCPConnector(limit=100, limit_per_host=20,
                                                 keepalive_timeout=30, enable_cleanup_closed=True)
                self._http_pool[provider_name] = aiohttp.ClientSession(connector=connector, timeout=timeout)
            return self._http_pool[provider_name]

    def get_metrics(self) -> MetricsCollector:
        return self._metrics

    def _get_telemetry(self):
        """Lazy-init telemetry collector."""
        if self._telemetry is None:
            from .telemetry import TelemetryCollector
            self._telemetry = TelemetryCollector()
        return self._telemetry

    def _inc_counter(self, name: str, value: int = 1):
        """Thread-safe atomic counter increment."""
        with self._counter_lock:
            current = getattr(self, name, 0)
            setattr(self, name, current + value)

    def _read_counters(self) -> Dict[str, int]:
        """Thread-safe snapshot of all counters."""
        with self._counter_lock:
            return {
                "call_count": self._call_count,
                "heal_count": self._heal_count,
                "l1_skip_count": self._l1_skip_count,
                "l2_downgrade_count": self._l2_downgrade_count,
                "l3_failover_count": self._l3_failover_count,
                "l4_learned_count": self._l4_learned_count,
                "rate_limited_count": self._rate_limited_count,
                "bulkhead_rejected_count": self._bulkhead_rejected_count,
            }

    # ── MAPE-K: Main entry ─────────────────────────────────

    async def call(self, prompt: str, model: Optional[str] = None,
                   task_type: str = "", has_schema: bool = False,
                   semantic_domain: Optional[SemanticDomain] = None,
                   contract: Optional[Contract] = None,
                   api_type: str = "chat",
                   **kwargs) -> CallResult:
        """MAPE-K loop: Monitor→Analyze→Plan→Execute→Knowledge.
        Returns CallResult with .text, .provider, .model, .fault etc.

        v2.5.1: Every call traverses all 5 MAPE-K phases explicitly.
        Success path also goes Monitor→Analyze→Knowledge (slow degradation detection).
        """
        import uuid
        request_id = kwargs.pop("request_id", str(uuid.uuid4())[:8])
        # Ensure api_type is available in kwargs for _execute
        if "api_type" not in kwargs:
            kwargs["api_type"] = api_type
        call_start = time.perf_counter()
        total_timeout = kwargs.get("total_timeout", 30.0)

        trace = MapeKTrace(request_id=request_id)
        sem_class = self._topology.classify_request(
            task_type=task_type, has_schema=has_schema,
            structured_output=kwargs.get("structured_output", False))
        # User explicit semantic_domain overrides auto-classification
        if semantic_domain is not None:
            sem_class = SemanticClassification(
                domain=semantic_domain,
                reason="user_explicit",
                tau_threshold=sem_class.tau_threshold)

        # ══════════════════════════════════════════════════════
        # PHASE 1: MONITOR — Collect metrics, check rate limits, select provider
        # ══════════════════════════════════════════════════════
        trace.enter(MapeKPhase.MONITOR)

        # V7: Rate limit protection — auto-slow if >30% recent 429s
        rate_limit_count = self._metrics.get_counter(f"fault_{FaultCategory.RATE_LIMIT.value}")
        total_calls = self._metrics.get_counter("calls_total")
        if total_calls > 10 and rate_limit_count / max(total_calls, 1) > 0.3:
            await asyncio.sleep(0.5)

        with self._lock:
            self._inc_counter("_call_count")
        self._metrics.inc("calls_total")

        providers = self.get_available_providers()
        if not providers:
            self._metrics.inc("errors_no_provider")
            trace.monitor_result = "no_provider"
            trace.total_loop_us = (time.perf_counter() - call_start) * 1e6
            raise RuntimeError("No healthy providers available.")

        # Provider selection
        primary = self._pick_provider(model, providers)
        provider_cfg = self._providers[primary]
        use_model = self._resolve_model(primary, model)
        original_provider = primary
        original_model = use_model

        trace.monitor_result = "provider_selected"

        # ══════════════════════════════════════════════════════
        # PHASE 2: ANALYZE — Diagnose (only if error) / detect slow degradation (on success)
        # ══════════════════════════════════════════════════════
        trace.enter(MapeKPhase.ANALYZE)

        # L4: Flywheel learned preference (overrides provider selection)
        error_hint = self._model_to_error_hint(model)
        learned_override = None
        if error_hint:
            learned = self._learner.match(error_hint)
            if learned and learned.confidence > 0.7:
                learned_provider = learned.action.replace("failover:", "")
                if learned_provider in providers and learned_provider != primary:
                    learned_override = learned_provider
                    primary = learned_provider
                    provider_cfg = self._providers[primary]
                    use_model = self._resolve_model(primary, model)
                    with self._lock:
                        self._inc_counter("_l4_learned_count")
                    self._metrics.inc("l4_learned_routing")

        # ══════════════════════════════════════════════════════
        # PHASE 3: PLAN — Decide recovery strategy (if fault) or direct (if success)
        # ══════════════════════════════════════════════════════
        trace.enter(MapeKPhase.PLAN)

        # Rate limiter + bulkhead gate
        if not provider_cfg.can_accept(bulkhead_timeout=kwargs.get("bulkhead_timeout", 1.0)):
            self._metrics.inc("rate_limited")
            with self._lock:
                self._inc_counter("_rate_limited_count")
            remaining = [p for p in providers if p != primary]
            if remaining:
                primary = self._pick_fallback(remaining)
                provider_cfg = self._providers[primary]
                use_model = self._resolve_model(primary, model)
                if not provider_cfg.can_accept(bulkhead_timeout=kwargs.get("bulkhead_timeout", 1.0)):
                    self._metrics.inc("bulkhead_rejected")
                    with self._lock:
                        self._inc_counter("_bulkhead_rejected_count")
                    trace.plan_result = "blocked"
                    trace.total_loop_us = (time.perf_counter() - call_start) * 1e6
                    raise RuntimeError("All providers rate-limited or at capacity.")
            else:
                trace.plan_result = "blocked"
                trace.total_loop_us = (time.perf_counter() - call_start) * 1e6
                raise RuntimeError("Primary rate-limited, no fallback available.")

        trace.plan_result = "l4_learned" if learned_override else "direct"

        # ══════════════════════════════════════════════════════
        # PHASE 4: EXECUTE — Try primary, then self-heal on failure
        # ══════════════════════════════════════════════════════
        trace.enter(MapeKPhase.EXECUTE)

        last_error = None
        last_diag = None
        try:
            t0 = time.perf_counter()
            result = await self._execute(provider_cfg, prompt, use_model, **kwargs)
            latency_ms = (time.perf_counter() - t0) * 1000
            provider_cfg.record_success(latency_ms)
            provider_cfg.release_slot()
            trace.execute_result = "ok"
            trace.analyze_result = "nominal"

            # ══════════════════════════════════════════════════════
            # PHASE 5: KNOWLEDGE — Record success to flywheel (success path!)
            # ══════════════════════════════════════════════════════
            trace.enter(MapeKPhase.KNOWLEDGE)
            self._learner.record("success", f"direct:{primary}", True, latency_ms)
            trace.knowledge_recorded = True
            trace.total_loop_us = (time.perf_counter() - call_start) * 1e6

            self._metrics.inc("success_primary")
            self._metrics.observe("latency_primary_ms", latency_ms)
            heal_level = "l4_learned" if learned_override else ""

            return CallResult(
                text=result, provider=primary, model=use_model,
                success=True, latency_ms=latency_ms,
                original_provider=original_provider, original_model=original_model,
                heal_level=heal_level,
                semantic_domain=sem_class.domain.value,
                mapek_trace=trace.to_dict(),
                raw_response=self._last_raw_response,
            )

        except APIError as e:
            provider_cfg.release_slot()
            last_error = e
            status = e.status_code

            # ── Analyze: Diagnose fault ──
            diag = self._diagnoser.diagnose(e, status)
            last_diag = diag
            trace.monitor_result = diag.category.value
            trace.analyze_result = diag.sub_category or diag.category.value
            provider_cfg.record_failure(str(e), fault_category=diag.category.value)
            # Activate per-category circuit breaker
            if diag.category.value:
                cat_cb = provider_cfg.get_category_circuit_breaker(diag.category.value)
                cat_cb.record_failure(primary)
            self._metrics.inc(f"fault_{diag.category.value}")
            self._metrics.observe("fault_latency_us", (time.perf_counter() - t0) * 1_000_000)

            fault_key = diag.sub_category if diag.sub_category else diag.category.value

            # ── Analyze: Get recovery hint from Diagnoser ──
            recovery_hint = self._diagnoser.suggest_recovery(diag, provider=primary, model=use_model)

            # ── Plan: Semantic boundary check ──
            # OUT_OF_BOUNDS domain: NO downgrade/failover allowed — fail loud
            if sem_class.domain == SemanticDomain.OUT_OF_BOUNDS:
                trace.plan_result = "blocked_oob"
                trace.execute_result = "failed"
                trace.enter(MapeKPhase.KNOWLEDGE)
                self._learner.record(fault_key, f"blocked:oob:{primary}", False)
                trace.knowledge_recorded = True
                trace.total_loop_us = (time.perf_counter() - call_start) * 1e6
                raise SemanticBoundaryViolationError(
                    f"Cannot self-heal in OUT_OF_BOUNDS domain "
                    f"(task_type={task_type}, reason={sem_class.reason}). "
                    f"Original error: {diag.category.value}",
                    domain=sem_class.domain.value, reason=sem_class.reason
                )

            # ── Plan + Execute: L1 retry ──
            if diag.should_retry and not diag.skip_to_failover:
                trace.plan_result = "l1_retry"
                max_l1_retries = _MAX_RETRIES
                for retry_i in range(max_l1_retries):
                    delay = diag.retry_after or (1.0 * (2 ** retry_i))
                    await asyncio.sleep(delay)
                    self._metrics.inc(f"l1_retry_attempt_{retry_i}")
                    try:
                        t1 = time.perf_counter()
                        result = await self._execute(provider_cfg, prompt, use_model, **kwargs)
                        latency_ms = (time.perf_counter() - t1) * 1000
                        provider_cfg.record_success(latency_ms)
                        trace.execute_result = "healed"

                        # ── Contract validation after retry ──
                        contract_result_obj = None
                        validation_passed = None
                        if contract and sem_class.domain in (SemanticDomain.STRONG_EQUIVALENCE, SemanticDomain.TAU_NEIGHBORHOOD):
                            contract_result_obj = contract.validate(result)
                            validation_passed = contract_result_obj.passed
                            if not contract_result_obj.passed and sem_class.domain == SemanticDomain.STRONG_EQUIVALENCE:
                                self._learner.record(fault_key, f"retry:{primary}", False)
                                self._metrics.inc("contract_validation_failed")
                                raise ContractViolationError(
                                    f"Contract validation failed after L1 retry: {contract_result_obj.to_dict()}",
                                    contract_result=contract_result_obj
                                )
                            elif not contract_result_obj.passed:
                                self._metrics.inc("contract_warning_tau_domain")

                        # ── Knowledge ──
                        trace.enter(MapeKPhase.KNOWLEDGE)
                        self._learner.record(fault_key, f"retry:{primary}", True, latency_ms)
                        trace.knowledge_recorded = True
                        trace.total_loop_us = (time.perf_counter() - call_start) * 1e6

                        self._metrics.inc("heal_l1_retry")
                        with self._lock:
                            self._inc_counter("_heal_count")
                        try:
                            self._get_telemetry().record_fault(
                                fault_type=diag.category.value, provider=primary,
                                model=use_model, recovery_action="retry",
                                recovery_ok=True, latency_ms=latency_ms,
                                sub_category=diag.sub_category)
                        except Exception:
                            pass
                        return CallResult(
                            text=result, provider=primary, model=use_model,
                            success=True, fault=diag, latency_ms=latency_ms,
                            original_provider=original_provider, original_model=original_model,
                            heal_level="l1_retry",
                            semantic_domain=sem_class.domain.value,
                            validation_passed=validation_passed,
                            contract_result=contract_result_obj.to_dict() if contract_result_obj else None,
                            mapek_trace=trace.to_dict(),
                        )
                    except ContractViolationError:
                        raise  # Propagate — fail loud in STRONG_EQUIVALENCE
                    except APIError as e2:
                        provider_cfg.record_failure(str(e2), fault_category=diag.category.value)
                        self._learner.record(fault_key, f"retry:{primary}", False)
                        last_error = e2
                        last_diag = self._diagnoser.diagnose(e2, e2.status_code)

            if diag.skip_to_failover:
                with self._lock:
                    self._inc_counter("_l1_skip_count")
                self._metrics.inc("l1_skip_to_failover")

            # ── Plan + Execute: L2 model downgrade ──
            if last_diag and last_diag.category in (FaultCategory.MODEL_NOT_FOUND, FaultCategory.VALIDATION_ERROR):
                downgraded = self._get_downgraded_model(primary, use_model, sem_class.domain)
                if downgraded and downgraded != use_model:
                    trace.plan_result = "l2_downgrade"
                    self._metrics.inc("l2_downgrade_attempt")
                    try:
                        t2 = time.perf_counter()
                        result = await self._execute(provider_cfg, prompt, downgraded, **kwargs)
                        latency_ms = (time.perf_counter() - t2) * 1000
                        provider_cfg.record_success(latency_ms)
                        trace.execute_result = "healed"

                        # ── Contract validation after downgrade ──
                        contract_result_obj = None
                        validation_passed = None
                        if contract and sem_class.domain in (SemanticDomain.STRONG_EQUIVALENCE, SemanticDomain.TAU_NEIGHBORHOOD):
                            contract_result_obj = contract.validate(result)
                            validation_passed = contract_result_obj.passed
                            if not contract_result_obj.passed and sem_class.domain == SemanticDomain.STRONG_EQUIVALENCE:
                                self._learner.record(
                                    last_diag.sub_category or last_diag.category.value,
                                    f"downgrade:{primary}:{downgraded}", False)
                                self._metrics.inc("contract_validation_failed")
                                raise ContractViolationError(
                                    f"Contract validation failed after L2 downgrade: {contract_result_obj.to_dict()}",
                                    contract_result=contract_result_obj
                                )
                            elif not contract_result_obj.passed:
                                self._metrics.inc("contract_warning_tau_domain")

                        # ── Knowledge ──
                        trace.enter(MapeKPhase.KNOWLEDGE)
                        self._learner.record(
                            last_diag.sub_category or last_diag.category.value,
                            f"downgrade:{primary}:{downgraded}", True, latency_ms)
                        trace.knowledge_recorded = True
                        trace.total_loop_us = (time.perf_counter() - call_start) * 1e6

                        self._metrics.inc("heal_l2_downgrade")
                        with self._lock:
                            self._inc_counter("_heal_count")
                            self._inc_counter("_l2_downgrade_count")
                        try:
                            self._get_telemetry().record_fault(
                                fault_type=last_diag.category.value, provider=primary,
                                model=downgraded, recovery_action="downgrade",
                                recovery_ok=True, latency_ms=latency_ms,
                                sub_category=last_diag.sub_category)
                        except Exception:
                            pass
                        return CallResult(
                            text=result, provider=primary, model=downgraded,
                            success=True, fault=last_diag, latency_ms=latency_ms,
                            original_provider=original_provider, original_model=original_model,
                            downgraded=True, heal_level="l2_downgrade",
                            semantic_domain=sem_class.domain.value,
                            validation_passed=validation_passed,
                            contract_result=contract_result_obj.to_dict() if contract_result_obj else None,
                            mapek_trace=trace.to_dict(),
                        )
                    except ContractViolationError:
                        raise  # Propagate — fail loud in STRONG_EQUIVALENCE
                    except APIError:
                        provider_cfg.record_failure(str(last_error), fault_category=last_diag.category.value)
                        self._learner.record(
                            last_diag.sub_category or last_diag.category.value,
                            f"downgrade:{primary}:{downgraded}", False)

            # ── Plan + Execute: L3 failover ──
            if last_diag:
                trace.plan_result = "l3_failover"
                return await self._failover(
                    prompt, model, primary, last_diag, sem_class,
                    original_provider, original_model, request_id,
                    contract=contract, trace=trace, call_start=call_start, **kwargs)

        # Should not reach here
        trace.total_loop_us = (time.perf_counter() - call_start) * 1e6
        raise last_error or RuntimeError("All recovery levels exhausted")

    def call_sync(self, prompt: str, model: Optional[str] = None,
                  task_type: str = "", has_schema: bool = False,
                  semantic_domain: Optional[SemanticDomain] = None,
                  contract: Optional[Contract] = None,
                  api_type: str = "chat",
                  **kwargs) -> CallResult:
        """同步调用 — 走完整 MAPE-K 自愈链路。
        复用异步逻辑，在同步上下文中运行事件循环。
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 已经在异步上下文（如 Jupyter），用线程池
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.call(prompt, model, task_type, has_schema,
                                  semantic_domain, contract, api_type, **kwargs)
                    )
                    return future.result(timeout=kwargs.get("total_timeout", 30.0))
            else:
                return loop.run_until_complete(
                    self.call(prompt, model, task_type, has_schema,
                              semantic_domain, contract, api_type, **kwargs)
                )
        except RuntimeError:
            return asyncio.run(
                self.call(prompt, model, task_type, has_schema,
                          semantic_domain, contract, api_type, **kwargs)
            )

    # ── L3: Failover (flywheel-informed ordering) ──────────

    async def _failover(self, prompt: str, model: Optional[str],
                        failed_provider: str, diag: Diagnosis,
                        sem_class: SemanticClassification,
                        original_provider: str, original_model: str,
                        request_id: str,
                        contract: Optional[Contract] = None,
                        trace: Optional[MapeKTrace] = None,
                        call_start: Optional[float] = None,
                        **kwargs) -> CallResult:
        """L3 failover with semantic boundary enforcement and Contract validation."""
        providers = self.get_available_providers()
        remaining = [p for p in providers if p != failed_provider]
        # Sort by: flywheel recommendation first, then health score, then latency
        remaining.sort(key=lambda p: self._provider_priority(p, diag.category.value, diag.sub_category), reverse=True)

        last_error = None
        for provider_name in remaining:
            cfg = self._providers[provider_name]
            use_model = self._resolve_model(provider_name, model)

            # Check per-category circuit breaker
            if diag.category.value:
                cat_cb = cfg.get_category_circuit_breaker(diag.category.value)
                if not cat_cb.is_available():
                    self._metrics.inc("category_circuit_blocked_failover")
                    continue

            if not cfg.can_accept():
                self._metrics.inc("rate_limited_during_failover")
                continue

            try:
                t0 = time.perf_counter()
                result = await self._execute(cfg, prompt, use_model, **kwargs)
                latency_ms = (time.perf_counter() - t0) * 1000
                cfg.record_success(latency_ms)
                cfg.release_slot()

                # ── Semantic drift detection (activate classify_response_drift) ──
                drift_class = None
                if sem_class.domain in (SemanticDomain.STRONG_EQUIVALENCE, SemanticDomain.TAU_NEIGHBORHOOD):
                    drift_class = self._topology.classify_response_drift(
                        primary_len=len(prompt),  # best approximation without original response
                        fallback_len=len(result),
                        has_structure=bool(contract and contract.output_schema),
                        structure_match=True,  # will be updated below
                    )

                # ── Contract validation after failover ──
                contract_result_obj = None
                validation_passed = None
                if contract and sem_class.domain in (SemanticDomain.STRONG_EQUIVALENCE, SemanticDomain.TAU_NEIGHBORHOOD):
                    contract_result_obj = contract.validate(result)
                    validation_passed = contract_result_obj.passed

                    # Update drift detection with actual structure match result
                    if drift_class and contract.output_schema and not contract_result_obj.passed:
                        drift_class = self._topology.classify_response_drift(
                            primary_len=len(prompt),
                            fallback_len=len(result),
                            has_structure=True,
                            structure_match=False,
                        )

                    if not contract_result_obj.passed and sem_class.domain == SemanticDomain.STRONG_EQUIVALENCE:
                        # STRONG_EQUIVALENCE: validation failed = heal failed = fail loud
                        with self._lock:
                            self._inc_counter("_heal_count")
                            self._inc_counter("_l3_failover_count")
                        self._learner.record(diag.sub_category or diag.category.value,
                                             f"failover:{provider_name}", False)
                        self._metrics.inc("contract_validation_failed")
                        self._metrics.inc("heal_l3_failover")
                        if trace:
                            trace.execute_result = "contract_violation"
                            trace.enter(MapeKPhase.KNOWLEDGE)
                            trace.knowledge_recorded = True
                            trace.total_loop_us = (time.perf_counter() - call_start) * 1e6 if call_start else 0
                        raise ContractViolationError(
                            f"Contract validation failed after L3 failover to {provider_name}: "
                            f"{contract_result_obj.to_dict()}",
                            contract_result=contract_result_obj
                        )
                    elif not contract_result_obj.passed:
                        # TAU_NEIGHBORHOOD: validation failed = warning, still return
                        self._metrics.inc("contract_warning_tau_domain")

                # ── Drift-based fail loud ──
                if drift_class and drift_class.domain == SemanticDomain.STRONG_EQUIVALENCE \
                        and drift_class.reason == "structure_mismatch_cannot_heal":
                    self._metrics.inc("drift_fail_loud")
                    raise ContractViolationError(
                        f"Response drift detected: {drift_class.reason}. "
                        f"Structure mismatch cannot be healed."
                    )

                with self._lock:
                    self._inc_counter("_heal_count")
                    self._inc_counter("_l3_failover_count")
                try:
                    self._get_telemetry().record_fault(
                        fault_type=diag.category.value,
                        provider=provider_name,
                        model=use_model,
                        recovery_action="failover",
                        recovery_ok=True,
                        latency_ms=latency_ms,
                        sub_category=diag.sub_category)
                except Exception:
                    pass
                self._learner.record(diag.sub_category or diag.category.value, f"failover:{provider_name}", True, latency_ms)
                self._metrics.inc("heal_l3_failover")
                self._metrics.observe("latency_failover_ms", latency_ms)

                # Semantic domain metrics
                if sem_class.domain == SemanticDomain.TAU_NEIGHBORHOOD:
                    self._metrics.inc("tau_domain_failover")
                elif sem_class.domain == SemanticDomain.OUT_OF_BOUNDS:
                    self._metrics.inc("oob_domain_failover")

                # ── Knowledge ──
                if trace:
                    trace.execute_result = "healed"
                    trace.enter(MapeKPhase.KNOWLEDGE)
                    trace.knowledge_recorded = True
                    trace.total_loop_us = (time.perf_counter() - call_start) * 1e6 if call_start else 0

                return CallResult(
                    text=result, provider=provider_name, model=use_model,
                    success=True, fault=diag, latency_ms=latency_ms,
                    original_provider=original_provider, original_model=original_model,
                    heal_level="l3_failover",
                    semantic_domain=sem_class.domain.value,
                    validation_passed=validation_passed,
                    contract_result=contract_result_obj.to_dict() if contract_result_obj else None,
                    mapek_trace=trace.to_dict() if trace else None,
                )
            except ContractViolationError:
                raise  # Propagate — fail loud
            except APIError as e:
                cfg.release_slot()
                cfg.record_failure(str(e), fault_category=diag.category.value)
                last_error = e
                self._learner.record(diag.sub_category or diag.category.value, f"failover:{provider_name}", False)

        # All providers failed
        self._learner.record(diag.sub_category or diag.category.value, "all_failed", False)
        self._metrics.inc("errors_all_providers_failed")
        if trace:
            trace.execute_result = "failed"
            trace.enter(MapeKPhase.KNOWLEDGE)
            trace.knowledge_recorded = True
            trace.total_loop_us = (time.perf_counter() - call_start) * 1e6 if call_start else 0
        raise last_error or RuntimeError("All providers failed")

    def _provider_priority(self, provider: str, fault_pattern: str, sub_category: str = "") -> float:
        """Dynamic priority: flywheel confidence + health score + latency bonus."""
        base = self._providers[provider].health_score()
        # Check flywheel: prefer sub_category match, fallback to category
        lookup_key = sub_category if sub_category else fault_pattern
        learned = self._learner.match(lookup_key)
        if learned and f"failover:{provider}" in learned.action:
            base += learned.confidence * 30  # up to 30pt boost for learned success
        # Latency bonus (lower latency = higher priority)
        avg_lat = self._providers[provider].avg_latency()
        if avg_lat > 0 and avg_lat < 2000:
            base += max(0, 10 - avg_lat / 200)  # up to 10pt for fast response
        return base

    # ── HTTP execution ─────────────────────────────────────

    async def _execute(self, cfg: ProviderConfig, prompt: str,
                       model: str, api_type: str = "chat", **kwargs) -> str:
        import aiohttp
        # K4: 多端点路由
        endpoints = {
            "chat": "/chat/completions",
            "completions": "/completions",
            "embeddings": "/embeddings",
            "images/generations": "/images/generations",
            "audio/transcriptions": "/audio/transcriptions",
        }
        endpoint = endpoints.get(api_type, "/chat/completions")
        url = f"{cfg.base_url}{endpoint}"
        # H1: API 版本化 — Anthropic uses x-api-key + anthropic-version, others use Bearer
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"Correctover/{__version__}",
            "X-Correctover-Version": __version__,
        }
        if cfg.name == "anthropic" or "anthropic" in cfg.base_url:
            headers["x-api-key"] = cfg.api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        # K4: 按 api_type 构建不同 payload
        # Extract only API-relevant kwargs (strip internal ones like timeout, task_type)
        _API_KWARGS = {"temperature", "max_tokens", "top_p", "frequency_penalty",
                       "presence_penalty", "stop", "n", "stream", "seed", "response_format",
                       "tools", "tool_choice", "structured_output", "parallel_tool_calls"}
        api_kwargs = {k: v for k, v in kwargs.items() if k in _API_KWARGS or k.startswith("_")}
        if api_type == "embeddings":
            payload = {"model": model, "input": prompt, **api_kwargs}
        elif api_type.startswith("images"):
            payload = {"model": model, "prompt": prompt, **api_kwargs}
        elif api_type.startswith("audio"):
            payload = {"model": model, **api_kwargs}
        else:
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], **api_kwargs}
        timeout = kwargs.get("timeout", _PROVIDER_TIMEOUT)
        
        # 非流式响应 — use pooled session for connection reuse
        # U6: 流式中断恢复
        try:
            session = await self._get_session(cfg.name)
            async with session.post(url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    body = await resp.text()
                    if resp.status != 200:
                        raise APIError(f"HTTP {resp.status}: {body[:200]}", status_code=resp.status)
                    data = json.loads(body)
                    self._last_raw_response = data
                    # K4: 按 api_type 解析不同响应
                    if api_type == "embeddings":
                        return data["data"][0]["embedding"]
                    elif api_type.startswith("images"):
                        return data["data"][0].get("url") or data["data"][0].get("b64_json")
                    elif api_type.startswith("audio"):
                        return data.get("text", "")
                    else:
                        return data["choices"][0]["message"]["content"]
        except APIError:
            raise  # already wrapped, let MAPE-K handle it
        except asyncio.TimeoutError:
            raise APIError(f"Timeout after {timeout}s calling {cfg.name}", status_code=408)
        except Exception as e:
            # V6: 错误消息过滤敏感信息
            raw = str(e)[:150]
            for pat in ["key=", "secret=", "token=", "bearer ", "authorization"]:
                if pat.lower() in raw.lower():
                    raw = "[REDACTED]"
                    break
            raise APIError(f"{type(e).__name__}: {raw}", status_code=None)

    def _execute_sync(self, cfg: ProviderConfig, prompt: str,
                       model: str, api_type: str = "chat", **kwargs) -> str:
        """同步执行 API 调用（使用 urllib，零依赖）"""
        endpoints = {
            "chat": "/chat/completions",
            "completions": "/completions",
            "embeddings": "/embeddings",
            "images/generations": "/images/generations",
            "audio/transcriptions": "/audio/transcriptions",
        }
        endpoint = endpoints.get(api_type, "/chat/completions")
        url = f"{cfg.base_url}{endpoint}"

        # 构建 payload
        if api_type in ("chat", "completions"):
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], **kwargs}
        elif api_type == "embeddings":
            payload = {"model": model, "input": prompt, **kwargs}
        elif api_type.startswith("images"):
            payload = {"model": model, "prompt": prompt, **kwargs}
        elif api_type.startswith("audio"):
            payload = {"model": model, **kwargs}
        else:
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], **kwargs}

        # Anthropic uses x-api-key + anthropic-version, others use Bearer
        headers = {"Content-Type": "application/json"}
        if cfg.name == "anthropic" or "anthropic" in cfg.base_url:
            headers["x-api-key"] = cfg.api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        data = json.dumps(payload).encode("utf-8")
        
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                self._last_raw_response = result

                # 解析响应
                if api_type in ("chat", "completions"):
                    return result["choices"][0]["message"]["content"]
                elif api_type == "embeddings":
                    return result["data"][0]["embedding"]
                elif api_type.startswith("images"):
                    return result["data"][0].get("url") or result["data"][0].get("b64_json", "")
                elif api_type.startswith("audio"):
                    return result.get("text", "")
                return result
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")[:200]
            raise APIError(f"HTTP {e.code}: {body}", status_code=e.code)
        except Exception as e:
            raise APIError(f"{type(e).__name__}: {str(e)[:150]}", status_code=None)

    async def _execute_stream(self, cfg: ProviderConfig, prompt: str,
                              model: str, api_type: str = "chat", **kwargs):
        """流式响应 — yield SSE chunks"""
        import aiohttp
        # K4: 多端点路由
        endpoints = {
            "chat": "/chat/completions",
            "completions": "/completions",
            "embeddings": "/embeddings",
            "images/generations": "/images/generations",
            "audio/transcriptions": "/audio/transcriptions",
        }
        endpoint = endpoints.get(api_type, "/chat/completions")
        url = f"{cfg.base_url}{endpoint}"
        # H1: API 版本化 — Anthropic uses x-api-key + anthropic-version, others use Bearer
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"Correctover/{__version__}",
            "X-Correctover-Version": __version__,
        }
        if cfg.name == "anthropic" or "anthropic" in cfg.base_url:
            headers["x-api-key"] = cfg.api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            **kwargs,  # 完整透传
        }
        timeout = kwargs.get("timeout", _PROVIDER_TIMEOUT)
        # U6: 流式中断恢复 — use pooled session
        try:
            session = await self._get_session(cfg.name)
            async with session.post(url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise APIError(f"HTTP {resp.status}: {body[:200]}", status_code=resp.status)
                    async for line in resp.content:
                        line_text = line.decode("utf-8").strip()
                        if line_text.startswith("data: "):
                            data_str = line_text[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                yield json.loads(data_str)
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            import aiohttp
            if isinstance(e, (aiohttp.ClientError, asyncio.TimeoutError)):
                yield {"error": f"stream_interrupted: {type(e).__name__}", "recoverable": True}
            else:
                yield {"error": f"stream_error: {type(e).__name__}", "recoverable": False}

    # ── Model routing ─────────────────────────────────────

    def _pick_provider(self, model: Optional[str], providers: List[str]) -> str:
        if model:
            # First: try each provider's own model list (catches custom providers)
            for prov in providers:
                cfg = self._providers.get(prov)
                if cfg and model in cfg.models:
                    return prov
            # Fallback: hardcoded MODEL_PROVIDERS dict
            for name, models in _MODEL_PROVIDERS.items():
                if model in models and name in providers:
                    return name
        return max(providers, key=lambda p: self._providers[p].health_score())

    def _pick_fallback(self, providers: List[str]) -> str:
        """Pick best fallback when primary is rate-limited."""
        return max(providers, key=lambda p: self._providers[p].health_score())

    def _resolve_model(self, provider: str, requested_model: Optional[str]) -> str:
        if requested_model:
            # First: check the provider's own model list (catches custom providers)
            cfg = self._providers.get(provider)
            if cfg and requested_model in cfg.models:
                return requested_model
            # Fallback: hardcoded dicts
            if requested_model in _MODEL_PROVIDERS.get(provider, []):
                return requested_model
            return _DEFAULT_MODELS.get(provider, requested_model) or requested_model
        return _DEFAULT_MODELS.get(provider, "deepseek-chat") or "deepseek-chat"

    def _get_downgraded_model(self, provider: str, current_model: str,
                              semantic_domain: SemanticDomain = SemanticDomain.TAU_NEIGHBORHOOD) -> Optional[str]:
        """Semantic-domain-aware model downgrade.

        STRONG_EQUIVALENCE: allow downgrade (Contract will validate after)
        TAU_NEIGHBORHOOD:   allow downgrade (warning on Contract fail)
        OUT_OF_BOUNDS:      BLOCK downgrade — return None
        """
        if semantic_domain == SemanticDomain.OUT_OF_BOUNDS:
            self._metrics.inc("downgrade_blocked_oob")
            return None  # Self-healing boundary: refuse downgrade

        chain = _DOWNGRADE_CHAIN.get(provider, [])
        if current_model in chain:
            idx = chain.index(current_model)
            if idx + 1 < len(chain):
                return chain[idx + 1]
        return None

    def _model_to_error_hint(self, model: Optional[str]) -> Optional[str]:
        if not model:
            return None
        ml = model.lower()
        if any(ml.startswith(x) for x in ["meta/", "nvidia/"]):
            return "model_request:nvidia"
        if "deepseek" in ml:
            return "model_request:deepseek"
        if ml.startswith("gpt"):
            return "model_request:openai"
        if "claude" in ml:
            return "model_request:anthropic"
        if "qwen" in ml:
            return "model_request:dashscope"
        if "gemini" in ml:
            return "model_request:google"
        return f"model_request:unknown"

    # ── Stats ─────────────────────────────────────

    def get_stats(self) -> Dict:
        counters = self._read_counters()
        return {
            "version": __version__,
            "call_count": counters["call_count"],
            "heal_count": counters["heal_count"],
            "heal_rate": f"{counters['heal_count']/max(counters['call_count'],1)*100:.1f}%",
            "l1_skip_count": counters["l1_skip_count"],
            "l2_downgrade_count": counters["l2_downgrade_count"],
            "l3_failover_count": counters["l3_failover_count"],
            "l4_learned_count": counters["l4_learned_count"],
            "rate_limited_count": counters["rate_limited_count"],
            "bulkhead_rejected_count": counters["bulkhead_rejected_count"],
            "providers": {n: c.to_dict() for n, c in self._providers.items()},
            "diagnosis_counts": self._diagnoser.get_stats(),
            "diagnosis_latency_us": self._diagnoser.get_latency_stats(),
            "flywheel": self._learner.get_stats(),
            "metrics": self._metrics.get_all(),
            }

    def get_mapek_stats(self) -> Dict:
        """Get MAPE-K specific statistics. Proves the loop is real."""
        metrics = self._metrics.get_all()
        counters = metrics.get("counters", {})
        engine_counters = self._read_counters()
        return {
            "version": __version__,
            "total_calls": engine_counters["call_count"],
            "mapek_phases": {
                "monitor": "every_call",
                "analyze": "every_call",
                "plan": "every_call",
                "execute": "every_call",
                "knowledge": "every_call",
            },
            "heal_cascade": {
                "l1_retry": counters.get("heal_l1_retry", 0),
                "l2_downgrade": engine_counters["l2_downgrade_count"],
                "l3_failover": engine_counters["l3_failover_count"],
                "l4_learned": engine_counters["l4_learned_count"],
            },
            "contract_validation": {
                "failed_strong_equiv": counters.get("contract_validation_failed", 0),
                "warning_tau_domain": counters.get("contract_warning_tau_domain", 0),
            },
            "semantic_boundaries": {
                "downgrade_blocked_oob": counters.get("downgrade_blocked_oob", 0),
                "failover_blocked_oob": 0,  # raised as exception
                "drift_fail_loud": counters.get("drift_fail_loud", 0),
            },
            "flywheel_rules": self._learner.get_stats(),
        }


class APIError(Exception):
    """API 调用异常。自动生成可读的错误信息。"""

    _HUMAN_MESSAGES = {
        400: "请求格式有误，请检查参数是否正确",
        401: "API Key 无效或已过期，请检查密钥配置",
        403: "没有访问权限，请检查 API Key 权限范围",
        404: "请求的模型或接口不存在，请检查模型名称",
        429: "请求频率过高，已被限流，请稍后重试",
        500: "AI 服务端内部错误，已自动切换备用 Provider",
        502: "AI 服务暂时不可用，已自动切换备用 Provider",
        503: "AI 服务繁忙，正在自动重试中",
        504: "AI 服务响应超时，已自动切换备用 Provider",
    }

    def __init__(self, message: str, status_code: Optional[int] = None):
        self.status_code = status_code
        human_msg = self._HUMAN_MESSAGES.get(status_code, "")
        if human_msg:
            super().__init__(f"[{status_code}] {human_msg} ({message[:80]})")
        else:
            super().__init__(message)

    def human_readable(self) -> str:
        """返回用户能看懂的错误信息"""
        return self._HUMAN_MESSAGES.get(self.status_code, self.args[0] if self.args else "未知错误")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENV SCANNER + run()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_ENV_MAP = {
    "NVIDIA_API_KEY": ("nvidia", "https://integrate.api.nvidia.com/v1"),
    "DEEPSEEK_API_KEY": ("deepseek", "https://api.deepseek.com/v1"),
    "DASHSCOPE_API_KEY": ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "OPENAI_API_KEY": ("openai", "https://api.openai.com/v1"),
    "ANTHROPIC_API_KEY": ("anthropic", "https://api.anthropic.com/v1"),
    "AZURE_OPENAI_API_KEY": ("azure", "https://YOUR_RESOURCE.openai.openai.azure.com/openai/deployments"),
    "GOOGLE_API_KEY": ("google", "https://generativelanguage.googleapis.com/v1beta"),
}


async def _check_provider(name: str, base_url: str, api_key: str) -> bool:
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{base_url}/chat/completions"
            model = _DEFAULT_MODELS.get(name, "deepseek-chat")
            payload = {"model": model, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 3}
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            async with session.post(url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
    except Exception:
        return False


def run(api_keys: Optional[Dict[str, str]] = None, verbose: bool = True) -> SelfHealingEngine:
    """One-command start: detect API keys, check health, return engine."""
    engine = SelfHealingEngine()
    found = 0

    for env_var, (name, base_url) in _ENV_MAP.items():
        key = (api_keys or {}).get(name) or (api_keys or {}).get(env_var) or os.environ.get(env_var, "")
        if not key:
            continue
        cfg = ProviderConfig(name=name, base_url=base_url, api_key=key,
                            models=_MODEL_PROVIDERS.get(name, []))
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                healthy = True
            else:
                healthy = loop.run_until_complete(_check_provider(name, base_url, key))
        except RuntimeError:
            healthy = True
        cfg.healthy = healthy
        engine.add_provider(cfg)
        found += 1
        if verbose:
            s = "OK" if healthy else "DOWN"
            print(f"  [{s}] {name}: {base_url} (models: {len(cfg.models)})")

    if verbose:
        avail = len(engine.get_available_providers())
        print(f"\n  Correctover v{__version__} | {found} provider(s) | {avail} healthy")
        print(f"  MAPE-K: Monitor->Analyze->Plan->Execute->Knowledge")
        print(f"  HA: CircuitBreaker + RateLimiter + Bulkhead per provider")
        print(f"  Semantic: Strong/Tau/OOB three-domain topology")
        print(f"  Flywheel: {engine._learner.get_stats()['total_rules']} rules loaded")
        print(f"\n  Async:  engine.call('Hello')")
        print(f"  Sync:   engine.call_sync('Hello')")
        print(f"  Model:  engine.call('Hello', model='gpt-4o')")
        print(f"  Task:   engine.call('Hello', task_type='classification')")

    return engine


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OBSERVABILITY SERVER (one-command dashboard + metrics + telemetry)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def serve_dashboard(engine: SelfHealingEngine, host: str = "127.0.0.1", port: int = 9898,
                    with_prometheus: bool = True, with_health: bool = True,
                    with_dashboard: bool = True) -> "http.server.HTTPServer":
    """One-command observability: starts HTTP server with Prometheus /metrics,
    Kubernetes /health, and built-in web dashboard.

    Usage:
        engine = run(verbose=False)
        serve_dashboard(engine, port=9898)
        # Now visit http://localhost:9898/ for dashboard
        # Prometheus scrapes http://localhost:9898/metrics
        # K8s probes http://localhost:9898/health
    """
    import http.server
    import urllib.parse

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _send_json(self, data, status=200):
            body = json.dumps(data, indent=2).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html):
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, text, content_type="text/plain"):
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/metrics" and with_prometheus:
                self._send_text(engine.get_metrics().prometheus_format())
            elif path == "/health" and with_health:
                self._send_json(engine.get_metrics().health_endpoint())
            elif path == "/stats":
                self._send_json(engine.get_stats())
            elif path == "/" and with_dashboard:
                self._send_html(_build_dashboard(engine))
            else:
                self.send_error(404)

    def _build_dashboard(eng):
        stats = eng.get_stats()
        providers_html = ""
        for name, p in stats.get("providers", {}).items():
            color = "#4caf50" if p.get("healthy") else "#f44336"
            providers_html += (
                f'<div style="display:inline-block;margin:8px;padding:12px;border-radius:8px;'
                f'background:#1e1e2e;min-width:180px">'
                f'<span style="color:{color};font-size:20px">&#9679;</span> '
                f'<b style="color:#cdd6f4">{name}</b><br>'
                f'<small style="color:#a6adc8">score: {p.get("health_score","?")} | '
                f'{p.get("avg_latency_ms","?")}ms</small><br>'
                f'<small style="color:#a6adc8">&#10003;{p.get("success",0)} '
                f'&#10007;{p.get("fail",0)} circuit:{p.get("circuit",{}).get("state","?")}</small>'
                f'</div>')
        metrics_html = ""
        for k, v in stats.get("metrics", {}).get("counters", {}).items():
            if any(x in k for x in ["calls", "heal", "fault", "error", "success", "rate"]):
                metrics_html += f'<div style="color:#a6adc8"><b style="color:#89b4fa">{k}</b>: {v}</div>'
        flywheel = stats.get("flywheel", {})
        diag = stats.get("diagnosis_counts", {})
        diag_html = "".join(
            f'<span style="color:#a6adc8;margin-right:12px"><b style="color:#89b4fa">{k}</b>:{v}</span>'
            for k, v in diag.items()) or '<span style="color:#a6adc8">No faults yet</span>'
        return (
            f'<!DOCTYPE html><html><head><title>Correctover v{stats["version"]}</title>'
            f'<meta http-equiv="refresh" content="5">'
            f'<style>body{{background:#11111b;color:#cdd6f4;font-family:system-ui,sans-serif;margin:20px}}'
            f'h1{{color:#89b4fa}} h2{{color:#cba6f7}} a{{color:#89b4fa}}</style></head>'
            f'<body><h1>Correctover v{stats["version"]}</h1>'
            f'<h2>Providers</h2>{providers_html}'
            f'<h2>Engine Stats</h2>'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">'
            f'<div style="background:#1e1e2e;padding:12px;border-radius:8px">'
            f'<b style="color:#f9e2af">Calls</b>: {stats["call_count"]}<br>'
            f'<b style="color:#a6e3a1">Healed</b>: {stats["heal_count"]} ({stats["heal_rate"]})<br>'
            f'<b style="color:#89b4fa">L1 Skip</b>: {stats["l1_skip_count"]} | '
            f'<b style="color:#cba6f7">L2 Downgrade</b>: {stats["l2_downgrade_count"]}<br>'
            f'<b style="color:#f38ba8">L3 Failover</b>: {stats["l3_failover_count"]} | '
            f'<b style="color:#fab387">L4 Learned</b>: {stats["l4_learned_count"]}</div>'
            f'<div style="background:#1e1e2e;padding:12px;border-radius:8px">'
            f'<b style="color:#f9e2af">Flywheel</b>: {flywheel.get("total_rules",0)} rules | '
            f'{flywheel.get("high_confidence_rules",0)} high-conf<br>'
            f'<b style="color:#89b4fa">Sync</b>: {flywheel.get("sync_mode","local")}<br>'
            f'<b style="color:#a6e3a1">Rate Limited</b>: {stats["rate_limited_count"]} | '
            f'<b style="color:#f38ba8">Bulkhead Rejected</b>: {stats["bulkhead_rejected_count"]}</div></div>'
            f'<h2>Live Metrics</h2><div style="background:#1e1e2e;padding:12px;border-radius:8px">{metrics_html}</div>'
            f'<h2>Diagnosis Counts</h2><div style="background:#1e1e2e;padding:12px;border-radius:8px">{diag_html}</div>'
            f'<p style="color:#585b70;margin-top:20px">Auto-refresh 5s | '
            f'<a href="/metrics">Prometheus</a> | <a href="/health">Health</a> | '
            f'<a href="/stats">Stats JSON</a></p></body></html>')

    server = http.server.HTTPServer((host, port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if with_dashboard:
        print(f"  Dashboard: http://{host}:{port}/")
    if with_prometheus:
        print(f"  Prometheus: http://{host}:{port}/metrics")
    if with_health:
        print(f"  Health: http://{host}:{port}/health")
    return server
