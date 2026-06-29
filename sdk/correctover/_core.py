# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture
# Commercial Engine. Proprietary.
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

from correctover._version import __version__
from correctover.classifier import (
    Complexity, classify, COMPLEXITY_MODEL_MAP,
    MODEL_COSTS, PROVIDER_MODELS, get_cost_per_token, get_model_tier,
)

# 安全限制常量
_MAX_RETRIES = 5          # V3: 单请求最大重试次数
_MAX_PAYLOAD_SIZE = 10 * 1024 * 1024  # V2: 10MB 请求体限制



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
    sub_category: str = ""
    flywheel_matched: bool = False
    flywheel_healed: int = 0
    flywheel_failed: int = 0
    flywheel_matched: bool = False
    flywheel_failed: int = 0  # hierarchical label: "rate_limit:openai", "server_error:anthropic_overload"

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
        self._flywheel_rules = {}
        self._flywheel_healed = 0
        self._flywheel_failed = 0
        self._load_flywheel()

    def _load_flywheel(self):
        fw_path = os.path.expanduser('~/.correctover/flywheel_rules.json')
        if os.path.exists(fw_path):
            try:
                with open(fw_path) as f:
                    import json as _json
                    self._flywheel_rules = _json.load(f)
                for key, rule in self._flywheel_rules.items():
                    self._flywheel_healed += rule.get('success_count', 0)
                    self._flywheel_failed += rule.get('fail_count', 0)
            except:
                pass

    def _match_flywheel(self, category_value: str) -> tuple:
        matched = False
        healed = 0
        failed = 0
        for key, rule in self._flywheel_rules.items():
            if key.startswith(category_value):
                matched = True
                healed += rule.get('success_count', 0)
                failed += rule.get('fail_count', 0)
        return matched, healed, failed

    def flywheel_status(self) -> dict:
        total = self._flywheel_healed + self._flywheel_failed
        rate = round(self._flywheel_healed / total * 100, 1) if total > 0 else 0.0
        learned = {k: v for k, v in self._flywheel_rules.items() if k.startswith('learned:')}
        return {
            'rules': len(self._flywheel_rules),
            'healed': self._flywheel_healed,
            'failed': self._flywheel_failed,
            'rate': rate,
            'learned_rules': len(learned),
        }

    def learn(self, logs: list) -> dict:
        """Feed fault logs → auto-cluster → extract rules → persist.

        Each log: {error_type, error_code, provider, message, recovered, recovery_method}
        Rules: freq>=3 AND recovered=True AND confidence>=0.6
        Learned rules stored with 'learned:' prefix, merged into flywheel.
        """
        if not logs:
            return {'learned': 0, 'total': 0}
        from collections import defaultdict
        clusters = defaultdict(lambda: {'healed': 0, 'total': 0, 'methods': set(), 'providers': set()})

        for log in logs:
            if not isinstance(log, dict):
                continue
            etype = str(log.get('error_type', 'unknown')).lower().strip()
            ecode = log.get('error_code', 0)
            provider = str(log.get('provider', 'unknown')).lower().strip()
            recovered = bool(log.get('recovered', False))
            method = str(log.get('recovery_method', '')).lower().strip()
            msg = str(log.get('message', '')).lower()

            # Generate cluster key from error_type + error_code + provider hint
            key = etype
            if ecode and ecode in _STATUS_MAP:
                key = _STATUS_MAP[ecode].value
            elif etype in [c.value for c in FaultCategory]:
                key = etype
            # Append provider for granularity
            if provider and provider not in ('unknown', ''):
                key = f'{key}:{provider}'

            clusters[key]['total'] += 1
            if recovered:
                clusters[key]['healed'] += 1
            if method:
                clusters[key]['methods'].add(method)
            if provider:
                clusters[key]['providers'].add(provider)

        new_rules = 0
        fw_path = os.path.expanduser('~/.correctover/flywheel_rules.json')
        try:
            import json as _json
            existing = {}
            if os.path.exists(fw_path):
                with open(fw_path) as f:
                    existing = _json.load(f)
        except:
            existing = {}

        for key, cl in clusters.items():
            if cl['total'] < 3 or cl['healed'] < 1:
                continue
            conf = round(cl['healed'] / cl['total'], 2)
            if conf < 0.6:
                continue
            rule_key = f'learned:{key}'
            if rule_key in existing:
                existing[rule_key]['success_count'] += cl['healed']
                existing[rule_key]['fail_count'] += (cl['total'] - cl['healed'])
                existing[rule_key]['confidence'] = round(
                    existing[rule_key]['success_count'] / (existing[rule_key]['success_count'] + existing[rule_key]['fail_count']), 2)
                existing[rule_key]['total_observations'] = existing.get(rule_key, {}).get('total_observations', 0) + cl['total']
            else:
                existing[rule_key] = {
                    'pattern': key.split(':')[0],
                    'action': 'learned',
                    'success_count': cl['healed'],
                    'fail_count': cl['total'] - cl['healed'],
                    'confidence': conf,
                    'total_observations': cl['total'],
                    'recovery_methods': list(cl['methods']),
                    'providers': list(cl['providers']),
                    'learned_at': time.time(),
                }
                new_rules += 1
            existing[rule_key]['last_seen'] = time.time()

        # Persist
        try:
            import json as _json
            os.makedirs(os.path.dirname(fw_path), exist_ok=True)
            with open(fw_path, 'w') as f:
                _json.dump(existing, f, indent=2)
        except:
            pass

        # Reload into memory
        self._flywheel_rules = existing
        self._flywheel_healed = sum(r.get('success_count', 0) for r in existing.values())
        self._flywheel_failed = sum(r.get('fail_count', 0) for r in existing.values())

        return {'learned': new_rules, 'total': len(clusters), 'rules': len(existing)}

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

        for pat, cat, conf, retry, skip, sub in _COMPILED:
            if pat.search(raw):
                if category == FaultCategory.UNKNOWN:
                    category, confidence, should_retry, skip_to_failover = cat, conf, retry, skip
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
            if len(self._latencies) > 10000:
                self._latencies = self._latencies[-5000:]

        if len(sub_category) > 50:
            sub_category = sub_category[:50]
        if len(raw) > 500:
            raw = raw[:500]
        fw_matched, fw_healed, fw_failed = self._match_flywheel(category.value)
        return Diagnosis(
            category=category, confidence=confidence,
            should_retry=should_retry, skip_to_failover=skip_to_failover,
            retry_after=retry_after, raw_error=raw,
            sub_category=sub_category,
            flywheel_matched=fw_matched,
            flywheel_healed=fw_healed,
            flywheel_failed=fw_failed,
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
        from correctover.types import RecoveryLevel

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
        """Strategy 3: Semantic similarity — Jaccard + containment (zero dependencies).

        Uses composite scoring: Jaccard (symmetric, penalizes length mismatch) and
        containment (how much of the reference is covered by the output). The final
        score is max(jaccard, containment) — containment is more practical for LLM
        outputs where responses are typically longer than the reference.
        """
        if not output or not output.strip():
            return ContractCheck(
                strategy="similarity", passed=False, detail="empty_text",
            )

        threshold = self.similarity_threshold or 0.8
        ref = self.reference_text
        if not ref or not ref.strip():
            return ContractCheck(
                strategy="similarity", passed=True, detail="no_reference",
            )

        # Tokenize: lowercase, strip punctuation
        import re
        def _tokenize(text: str) -> set:
            clean = re.sub(r'[^\w\s]', '', text.lower())
            return set(clean.split())

        ref_tokens = _tokenize(ref)
        out_tokens = _tokenize(output)

        if not ref_tokens or not out_tokens:
            return ContractCheck(
                strategy="similarity", passed=False, detail="empty_tokens",
            )

        intersection = ref_tokens & out_tokens
        union = ref_tokens | out_tokens
        jaccard = len(intersection) / len(union) if union else 0.0
        containment = len(intersection) / len(ref_tokens) if ref_tokens else 0.0
        score = max(jaccard, containment)
        passed = score >= threshold

        return ContractCheck(
            strategy="similarity", passed=passed,
            detail=f"jaccard={jaccard:.3f} containment={containment:.3f} score={score:.3f} threshold={threshold}",
        )

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

# ── Strategy enum (was in correctover.router) ──────────
class Strategy(str, Enum):
    COST = "cost"          # Prefer cheapest model that can handle the task
    LATENCY = "latency"    # Prefer fastest provider
    QUALITY = "quality"    # Prefer best model regardless of cost


def _provider_latency(provider_state: Dict) -> float:
    """Estimate provider latency from health data. Returns ms."""
    recent = provider_state.get("recent_latencies", [])
    if recent:
        return sum(recent[-5:]) / len(recent[-5:])
    return 500.0  # default estimate


def _provider_healthy(provider_state: Dict) -> bool:
    """Check if provider is healthy enough to route to."""
    return provider_state.get("healthy", True) and not provider_state.get("circuit_open", False)


# ── RoutingDecision (was in correctover.router) ────────
class RoutingDecision:
    """Result of a routing decision."""

    __slots__ = ("provider", "model", "complexity", "tier", "strategy", "reason",
                 "estimated_co2_kg", "cost_saved_usd", "original_model")

    def __init__(
        self,
        provider: str,
        model: str,
        complexity: Complexity,
        tier: str,
        strategy: str,
        reason: str,
        estimated_co2_kg: float = 0.0,
        cost_saved_usd: float = 0.0,
        original_model: str = "",
    ):
        self.provider = provider
        self.model = model
        self.complexity = complexity
        self.tier = tier
        self.strategy = strategy
        self.reason = reason
        self.estimated_co2_kg = estimated_co2_kg
        self.cost_saved_usd = cost_saved_usd
        self.original_model = original_model

    def __repr__(self):
        return f"RoutingDecision({self.provider}/{self.model}, complexity={self.complexity.value}, tier={self.tier}, strategy={self.strategy})"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "complexity": self.complexity.value,
            "tier": self.tier,
            "strategy": self.strategy,
            "reason": self.reason,
            "estimated_co2_kg": self.estimated_co2_kg,
            "cost_saved_usd": self.cost_saved_usd,
            "original_model": self.original_model,
        }


# ── Router (was in correctover.router) ─────────────────
class Router:
    """Decides which provider and model to route a request to.

    Usage:
        router = Router(
            providers=["openai", "anthropic", "deepseek"],
            strategy="cost",
        )
        decision = router.route("Explain quantum computing")
        # → RoutingDecision(provider="deepseek", model="deepseek-chat", ...)
    """

    def __init__(
        self,
        providers: List[str],
        strategy: str = "cost",
        provider_states: Optional[Dict[str, Dict]] = None,
    ):
        self.providers = providers
        self.strategy = Strategy(strategy)
        self.provider_states = provider_states or {}

    def route(
        self,
        prompt: str,
        model: str = "auto",
        task_type: str = "",
        prefer_provider: Optional[str] = None,
    ) -> "RoutingDecision":
        """Route a request to the best provider/model.

        Args:
            prompt: The user prompt.
            model: "auto" for routing, or specific model name.
            task_type: Optional task type hint.
            prefer_provider: If set, try this provider first.

        Returns:
            RoutingDecision with chosen provider, model, and metadata.
        """
        # If user specified a concrete model, find a provider that has it
        if model != "auto":
            return self._route_concrete(model, prefer_provider)

        # Classify complexity
        complexity = classify(prompt, task_type)
        tier = COMPLEXITY_MODEL_MAP[complexity]

        # Get candidate (provider, model) pairs
        candidates = self._get_candidates(tier)

        if not candidates:
            # Fallback: try any model from any provider
            candidates = self._get_candidates("standard")

        if not candidates:
            # Last resort: first provider, first model
            if self.providers:
                p = self.providers[0]
                models = PROVIDER_MODELS.get(p, [])
                m = models[0] if models else "auto"
                return RoutingDecision(provider=p, model=m, complexity=complexity, tier=tier, strategy=self.strategy.value, reason="fallback")
            return RoutingDecision(provider="openai", model="gpt-4o", complexity=complexity, tier=tier, strategy=self.strategy.value, reason="no_provider")

        # Apply strategy
        if self.strategy == Strategy.COST:
            chosen = self._pick_cheapest(candidates)
        elif self.strategy == Strategy.LATENCY:
            chosen = self._pick_fastest(candidates)
        elif self.strategy == Strategy.QUALITY:
            chosen = self._pick_best_quality(candidates)
        else:
            chosen = candidates[0]

        provider, model_name = chosen

        # ── 碳排放 + 成本节省计算 ──
        estimated_co2_kg = 0.0
        cost_saved_usd = 0.0
        original_model = ""
        try:
            from correctover.carbon import estimate_co2_kg as _est_co2
            estimated_co2_kg = _est_co2(model_name, 0, 1000)  # 估算1K output的CO2
            # 如果策略是cost优化，计算与premium模型的差异
            if self.strategy == Strategy.COST and tier != "premium":
                original_model = PROVIDER_MODELS.get("openai", ["gpt-4o"])[0]
                cost_original = get_cost_per_token(original_model, "input") * 1000
                cost_actual = get_cost_per_token(model_name, "input") * 1000
                cost_saved_usd = max(0, cost_original - cost_actual)
        except Exception:
            pass

        return RoutingDecision(
            provider=provider,
            model=model_name,
            complexity=complexity,
            tier=tier,
            strategy=self.strategy.value,
            reason=f"{self.strategy.value}_optimization",
            estimated_co2_kg=estimated_co2_kg,
            cost_saved_usd=cost_saved_usd,
            original_model=original_model,
        )

    def _route_concrete(self, model: str, prefer_provider: Optional[str] = None) -> "RoutingDecision":
        """Route to a specific model, choosing best provider."""
        # Find which providers support this model
        supporting = []
        for p in self.providers:
            models = PROVIDER_MODELS.get(p, [])
            if model in models or self._model_matches(model, models):
                supporting.append(p)

        if prefer_provider and prefer_provider in supporting:
            provider = prefer_provider
        elif supporting:
            # Pick the cheapest provider for this model
            provider = supporting[0]  # simplified
        else:
            # Model not in our list, let provider handle it
            provider = prefer_provider or (self.providers[0] if self.providers else "openai")

        return RoutingDecision(
            provider=provider,
            model=model,
            complexity=Complexity.MODERATE,
            tier=get_model_tier(model),
            strategy=self.strategy.value,
            reason="user_specified",
        )

    def _get_candidates(self, tier: str) -> List[tuple]:
        """Get (provider, model) candidates for a given tier."""
        candidates = []
        for p in self.providers:
            state = self.provider_states.get(p, {})
            if not _provider_healthy(state):
                continue
            models = PROVIDER_MODELS.get(p, [])
            for m in models:
                model_tier = get_model_tier(m)
                # For cost strategy with simple tasks, only consider mini tier
                # For quality strategy, consider standard + premium
                if self.strategy == Strategy.COST:
                    if tier == "mini" and model_tier in ("mini",):
                        candidates.append((p, m))
                    elif tier == "standard" and model_tier in ("mini", "standard"):
                        candidates.append((p, m))
                    elif tier == "premium" and model_tier in ("standard", "premium"):
                        candidates.append((p, m))
                elif self.strategy == Strategy.QUALITY:
                    if tier == "mini" and model_tier in ("mini", "standard"):
                        candidates.append((p, m))
                    elif tier == "standard" and model_tier in ("standard", "premium"):
                        candidates.append((p, m))
                    elif tier == "premium" and model_tier in ("premium",):
                        candidates.append((p, m))
                else:  # latency — consider all tiers
                    if tier == "mini" or model_tier == tier:
                        candidates.append((p, m))
        return candidates

    def _pick_cheapest(self, candidates: List[tuple]) -> tuple:
        """Pick the cheapest (provider, model) pair."""
        def cost_score(item):
            _, m = item
            info = MODEL_COSTS.get(m)
            return info["input"] + info["output"] if info else 999
        return min(candidates, key=cost_score)

    def _pick_fastest(self, candidates: List[tuple]) -> tuple:
        """Pick the provider with lowest latency."""
        def latency_score(item):
            p, m = item
            state = self.provider_states.get(p, {})
            model_latency = 100.0 if get_model_tier(m) == "mini" else 300.0
            return _provider_latency(state) + model_latency
        return min(candidates, key=latency_score)

    def _pick_best_quality(self, candidates: List[tuple]) -> tuple:
        """Pick the best quality model."""
        def quality_score(item):
            _, m = item
            tier = get_model_tier(m)
            return {"premium": 3, "standard": 2, "mini": 1}.get(tier, 0)
        return max(candidates, key=quality_score)

    @staticmethod
    def _model_matches(model: str, known_models: List[str]) -> bool:
        """Check if a requested model matches any known model pattern."""
        model_lower = model.lower()
        for km in known_models:
            if km in model_lower or model_lower in km:
                return True
        return False


# ═══════════════════════════════════════════════════════════════════
# Compiled License Gate — embedded in _core.pyd
# ═══════════════════════════════════════════════════════════════════
# This is the SOURCE OF TRUTH for all license enforcement.
# license.py is a thin wrapper that delegates here.
# Even if license.py is deleted/replaced, the engine hot path
# imports consume_repair DIRECTLY from this compiled module.
# ═══════════════════════════════════════════════════════════════════

class LicenseError(Exception):
    """Raised when a Pro feature is used without a valid license."""
    pass

class DeviceMismatchError(LicenseError):
    """Raised when license is bound to a different device."""
    pass

class RepairLockedError(LicenseError):
    """Raised when repair is attempted on Free plan (diagnosis free, repair paid)."""
    pass

class LicenseExpiredError(LicenseError):
    """Raised when license has expired — auto-stop repair."""
    pass

# Plan constants (single source of truth)
PLAN_NONE = "none"
PLAN_FREE = PLAN_NONE
PLAN_PRO = "pro"
PLAN_ENTERPRISE = "enterprise"
PLAN_TRIAL = "trial"
PLAN_PROFESSIONAL = "professional"
PLAN_ENTERPRISE_CUSTOM = "enterprise_custom"
PLAN_MONTHLY = "monthly"
PLAN_LIFETIME = "lifetime"

_PRO_PLANS = {PLAN_PRO, PLAN_ENTERPRISE, PLAN_TRIAL,
              PLAN_PROFESSIONAL, PLAN_ENTERPRISE_CUSTOM,
              PLAN_MONTHLY, PLAN_LIFETIME}

_REPAIR_ACTIONS = {
    "diagnosis":       False,  # 诊断 — 永远免费
    "auto_retry":      True,   # L1 重试 — 修复
    "model_fallback":  True,   # L2 降级切换 — 修复
    "failover":        True,   # L3 Failover — 修复
    "cache_hit":       False,  # 缓存命中 — 免费
}

# Global license state (THE authoritative copy)
_license_lock = threading.Lock()
_license_current = None  # dict with keys: plan, valid, expires_at, customer, device_bound

def license_set_state(plan: str, valid: bool, expires_at: int = 0,
                       customer: str = "", device_bound: bool = False) -> None:
    """Set current license state. Called by license.py on activate/verify."""
    global _license_current
    with _license_lock:
        _license_current = {
            "plan": plan,
            "valid": valid,
            "expires_at": expires_at,
            "customer": customer,
            "device_bound": device_bound,
        }

def license_get_state() -> dict:
    """Get current license state."""
    with _license_lock:
        if _license_current is None:
            return {"plan": PLAN_NONE, "valid": False, "expires_at": 0,
                    "customer": "", "device_bound": False}
        # Check expiry before returning
        cur = _license_current
        if cur.get("expires_at", 0) > 0 and time.time() > cur["expires_at"]:
            cur["valid"] = False
        return dict(cur)  # return a copy

def _require_licensed() -> bool:
    """Compiled gate: check if current license is active.

    Returns True if licensed (Pro or higher, not expired).
    This runs inside _core.pyd — compiled, not editable by users.
    """
    state = license_get_state()
    if not state["valid"]:
        return False
    if state["plan"] not in _PRO_PLANS:
        return False
    return True

def consume_repair(action: str) -> bool:
    """Compiled gate: check if a repair action is allowed.

    This is called by the engine on EVERY repair action.
    Even if license.py is replaced, this compiled check still runs.

    Args:
        action: repair action name (auto_retry, model_fallback, failover)

    Returns:
        True if allowed

    Raises:
        RepairLockedError: if not licensed
    """
    is_repair = _REPAIR_ACTIONS.get(action, True)
    if not is_repair:
        return True  # Diagnosis/cache hit — always allowed

    # Compiled license check
    state = license_get_state()
    if not state["valid"] or state["plan"] not in _PRO_PLANS:
        raise RepairLockedError(
            f"Repair locked — requires active Pro/Enterprise license. "
            f"Current: {state['plan']} | valid: {state['valid']}"
        )
    return True
