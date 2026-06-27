# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture
# Patent Pending. See NOTICE file for full IP attribution.
#
"""Correctover SDK — Agent stability SDK. Smart routing, auto-failover, crash recovery."""
from correctover._version import __version__
version = __version__

# 懒加载字典：所有模块延迟加载
_lazy = {
    # Core engine
    "SelfHealingEngine": ("correctover._engine", "SelfHealingEngine"),
    "CallResult": ("correctover._engine", "CallResult"),
    "ProviderConfig": ("correctover._engine", "ProviderConfig"),
    "APIError": ("correctover._engine", "APIError"),
    # Diagnoser
    "FaultCategory": ("correctover._engine", "FaultCategory"),
    "Diagnosis": ("correctover._engine", "Diagnosis"),
    "Diagnoser": ("correctover.diagnoser", "Diagnoser"),
    # HA components
    "CircuitBreaker": ("correctover._engine", "CircuitBreaker"),
    "CircuitState": ("correctover._engine", "CircuitState"),
    "RateLimiter": ("correctover._engine", "RateLimiter"),
    "Bulkhead": ("correctover._engine", "Bulkhead"),
    # Semantic topology
    "SemanticTopology": ("correctover._engine", "SemanticTopology"),
    "SemanticDomain": ("correctover._engine", "SemanticDomain"),
    "SemanticClassification": ("correctover._engine", "SemanticClassification"),
    # Flywheel
    "FlywheelLearner": ("correctover._engine", "FlywheelLearner"),
    "LearnedRule": ("correctover._engine", "LearnedRule"),
    "MetricsCollector": ("correctover._engine", "MetricsCollector"),
    # MAPE-K Trace
    "MapeKPhase": ("correctover._engine", "MapeKPhase"),
    "MapeKTrace": ("correctover._engine", "MapeKTrace"),
    # Contract Validator
    "Contract": ("correctover._engine", "Contract"),
    "ContractCheck": ("correctover._engine", "ContractCheck"),
    "ContractResult": ("correctover._engine", "ContractResult"),
    "ContractViolationError": ("correctover._engine", "ContractViolationError"),
    "SemanticBoundaryViolationError": ("correctover._engine", "SemanticBoundaryViolationError"),
    # Compatibility modules
    "HealthScorer": ("correctover.health_scorer", "HealthScorer"),
    "CostTracker": ("correctover.cost_tracker", "CostTracker"),
    "IntegrityChecker": ("correctover.integrity", "IntegrityChecker"),
    "EngineStateMachine": ("correctover.state_machine", "EngineStateMachine"),
    "CorrectoverTelemetry": ("correctover.telemetry", "CorrectoverTelemetry"),
    "TelemetryCollector": ("correctover.telemetry", "TelemetryCollector"),
    "TelemetryConfig": ("correctover.telemetry", "TelemetryConfig"),
    "run": ("correctover.run", "run"),
    "Run": ("correctover.run", "Run"),
    "RecoveryLevel": ("correctover.types", "RecoveryLevel"),
    "DiagnosisResult": ("correctover.types", "DiagnosisResult"),
    "RecoveryAction": ("correctover.types", "RecoveryAction"),
    "RoutingStrategy": ("correctover.types", "RoutingStrategy"),
    # Gateway proxy
    "GatewayConfig": ("correctover.gateway", "GatewayConfig"),
    "serve": ("correctover.gateway", "serve"),
    # License system
    "activate": ("correctover.license", "activate"),
    "verify": ("correctover.license", "verify"),
    "get_plan": ("correctover.license", "get_plan"),
    "is_pro": ("correctover.license", "is_pro"),
    "is_trial": ("correctover.license", "is_trial"),
    "is_enterprise": ("correctover.license", "is_enterprise"),
    "is_expired": ("correctover.license", "is_expired"),
    "is_device_bound": ("correctover.license", "is_device_bound"),
    "require_pro": ("correctover.license", "require_pro"),
    "days_remaining": ("correctover.license", "days_remaining"),
    "max_providers": ("correctover.license", "max_providers"),
    "max_heal_level": ("correctover.license", "max_heal_level"),
    "feature_gate": ("correctover.license", "feature_gate"),
    "watermark_enabled": ("correctover.license", "watermark_enabled"),
    "consume_repair": ("correctover.license", "consume_repair"),
    "can_repair": ("correctover.license", "can_repair"),
    "diagnose_free": ("correctover.license", "diagnose_free"),
    "plan_summary": ("correctover.license", "plan_summary"),
    "LicenseInfo": ("correctover.license", "LicenseInfo"),
    "LicenseError": ("correctover.license", "LicenseError"),
    "RepairLockedError": ("correctover.license", "RepairLockedError"),
    "LicenseExpiredError": ("correctover.license", "LicenseExpiredError"),
    "DeviceMismatchError": ("correctover.license", "DeviceMismatchError"),
    "PLAN_PRICES": ("correctover.license", "PLAN_PRICES"),
    "PLAN_LABELS": ("correctover.license", "PLAN_LABELS"),
    "REPAIR_ACTIONS": ("correctover.license", "REPAIR_ACTIONS"),
    # Device fingerprint
    "device_fingerprint": ("correctover._device", "device_fingerprint"),
    "device_info": ("correctover._device", "device_info"),
    # Stats & ROI
    "savings_report": ("correctover._stats", "savings_report"),
    "console_summary": ("correctover._stats", "console_summary"),
    "dashboard_data": ("correctover._stats", "dashboard_data"),
    "weekly_summary": ("correctover._stats", "weekly_summary"),
    "upgrade_triggers": ("correctover._stats", "upgrade_triggers"),
    # Router + Client (v5.0)
    "Client": ("correctover.client", "Client"),
    "ChatResponse": ("correctover.client", "ChatResponse"),
    "CostReport": ("correctover.client", "CostReport"),
    "Router": ("correctover.router", "Router"),
    "RoutingDecision": ("correctover.router", "RoutingDecision"),
    "Strategy": ("correctover.router", "Strategy"),
    "Complexity": ("correctover.classifier", "Complexity"),
    "classify": ("correctover.classifier", "classify"),
    # Checkpoint — Agent crash recovery (v4.3)
    "Checkpoint": ("correctover.checkpoint", "Checkpoint"),
    "StepResult": ("correctover.checkpoint", "StepResult"),
    "AgentSession": ("correctover.checkpoint", "AgentSession"),
    "RunContext": ("correctover.checkpoint", "RunContext"),
    "CheckpointStore": ("correctover.checkpoint", "CheckpointStore"),
    "FileCheckpointStore": ("correctover.checkpoint", "FileCheckpointStore"),
    "MemoryCheckpointStore": ("correctover.checkpoint", "MemoryCheckpointStore"),
    # Telemetry
    "ping": ("correctover._ping", "ping"),
    # Carbon Tracker (v4.4.2)
    "CarbonTracker": ("correctover.carbon", "CarbonTracker"),
    "estimate_wh": ("correctover.carbon", "estimate_wh"),
    "estimate_co2_kg": ("correctover.carbon", "estimate_co2_kg"),
    "MODEL_ENERGY": ("correctover.carbon", "MODEL_ENERGY"),
    "CARBON_INTENSITY_GRID": ("correctover.carbon", "CARBON_INTENSITY_GRID"),
    "DriftMonitor": ("correctover.drift", "DriftMonitor"),
    "DriftAlert": ("correctover.drift", "DriftAlert"),
    # Dashboard (v4.4.2)
    "dashboard": ("correctover.dashboard", "dashboard"),
    "stop_dashboard": ("correctover.dashboard", "stop_dashboard"),
    "dashboard_url": ("correctover.dashboard", "dashboard_url"),
    "dashboard_status": ("correctover.dashboard", "dashboard_status"),
}

__all__ = list(_lazy.keys()) + ["checkup"]


def __getattr__(name):
    """懒加载：只在首次访问时导入模块"""
    if name in _lazy:
        import importlib
        mod_path, cls_name = _lazy[name]
        mod = importlib.import_module(mod_path)
        obj = getattr(mod, cls_name)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    """返回完整的导出列表"""
    return __all__


# ── Telemetry (opt-in, default OFF) ──────────────────────────────
import os as _os
# Telemetry is OFF by default. Set CORRECTOVER_TELEMETRY=1 to enable.
# This collects anonymous usage data (version, OS, plan) to improve the SDK.
# See https://correctover.cn/docs/telemetry for details.
# Telemetry is OFF by default. Set CORRECTOVER_TELEMETRY=1 to enable.
if _os.environ.get("CORRECTOVER_TELEMETRY") != "1":
    _os.environ["CORRECTOVER_TELEMETRY"] = "0"
if not _os.environ.get("CORRECTOVER_TELEMETRY_URL"):
    _os.environ["CORRECTOVER_TELEMETRY_URL"] = "https://license-api-correctover-hk-rewfrmblft.cn-hongkong.fcapp.run/api/v1/telemetry"

# ── Auto-ping on import (only if telemetry is opted-in) ─────────
if _os.environ.get("CORRECTOVER_TELEMETRY") == "1":
    try:
        from correctover._ping import ping as _auto_ping
        _auto_ping()
    except Exception:
        pass


# ── First-run checkup ────────────────────────────────────────────
def checkup():
    """手动触发体检 (重新检测所有 provider 和连通性)."""
    from correctover._checkup import force_run
    force_run()

try:
    from correctover._checkup import run as _checkup_run
    _checkup_run()
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════
# SECURITY LAYER — All logic lives in _security.so (compiled)
# ══════════════════════════════════════════════════════════════════

# ── Step 1: Initialize tracker (silent, non-blocking) ──────────
try:
    # [FIXED] tracker only loaded when telemetry explicitly opted in
    if _os.environ.get('CORRECTOVER_TELEMETRY') == '1':
        from correctover._tracker import report as _track_report
        from correctover._tracker import flush as _track_flush
    else:
        _track_report = None
        _track_flush = None
except ImportError as _e:
    _track_report = None
    _track_flush = None
    import sys as _sys
    if "cpython" in str(_e).lower() or "magic" in str(_e).lower():
        print(f"[Correctover] WARNING: _tracker module incompatible with Python {_sys.version_info.major}.{_sys.version_info.minor}. "
              f"Security tracking disabled. Reinstall from source: pip install --no-binary correctover-sdk correctover-sdk", file=_sys.stderr)
except Exception:
    _track_report = None
    _track_flush = None


# ── Step 2-5: Security init — removed in Open Core v5.7.0 ─────


# ── Step 6: Flush pending tracker events ───────────────────────
try:
    if _track_flush:
        _track_flush()
except Exception:
    pass


# ── Step 7: Cloud Kill-Switch — removed in Open Core v5.7.0 ────


# ══════════════════════════════════════════════════════════════════
# Anthropic 推荐：最简一行调用（Less is More + ACI 设计原则）
# ══════════════════════════════════════════════════════════════════

def run(prompt="", provider="", **kwargs):
    """一行代码调用 AI，自动配置、自动自愈。

    Anthropic《构建高效的 Agents》核心原则：
    - Less is More：从最简单开始，一行代码
    - 好的 ACI 设计：用户不需要了解内部细节

    用法:
        import correctover as nb
        result = nb.run("你好")          # 自动读环境变量
        print(result.summary())           # 透明度：看到完整调用链

    环境变量: DEEPSEEK_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, DASHSCOPE_API_KEY
    """
    import asyncio, os
    from correctover._engine import SelfHealingEngine, ProviderConfig

    engine = SelfHealingEngine()
    api_key = kwargs.pop("api_key", "") or os.environ.get("CUSTOM_API_KEY", "")
    candidates = [provider] if provider else ["deepseek", "openai", "anthropic", "dashscope", "agnes"]

    for p in candidates:
        env_key = api_key or os.environ.get(f"{p.upper()}_API_KEY", "")
        if not env_key:
            continue
        try:
            cfg = ProviderConfig(name=p, base_url=ProviderConfig._get_base_url(p), api_key=env_key)
            engine.add_provider(cfg)
        except Exception:
            continue
        break

    if prompt:
        return asyncio.run(engine.call(prompt, **kwargs))
    return engine
