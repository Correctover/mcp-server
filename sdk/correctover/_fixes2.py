# Copyright 2024-2026 Correctover Team
# Proprietary Commercial License
"""Correctover SDK — Runtime patches v2 for compiled module bugs.

Patches applied:
  1. 5xx short-circuit -- Track consecutive 5xx errors per provider.
     After N consecutive 5xx, short-circuit that provider for a cooldown
     period to avoid pointless retries of a failing upstream.
  2. Latency validation -- Track average response latency per provider.
     When the rolling average exceeds the configurable threshold, flag
     the provider as degraded through CallResult._metadata.

These patches are applied at import time via __init__.py and are
transparent to end users.  Fixes apply to the compiled _engine module.
"""
import time as _time
import logging as _logging

_logger = _logging.getLogger("correctover._fixes2")


def _patch_5xx_short_circuit(engine_module):
    """Monkey-patch SelfHealingEngine for 5xx short-circuit.

    Maintains a per-provider counter of consecutive HTTP 5xx errors.
    Once the threshold (default 3) is hit, the provider is short-circuited
    for a cooldown period (default 60 s).  Non-5xx errors reset the
    counter.
    """
    SelfHealingEngine = engine_module.SelfHealingEngine
    CallResult = engine_module.CallResult
    APIError = engine_module.APIError
    FaultCategory = engine_module.FaultCategory

    # ── internal state ──────────────────────────────────────────
    _counter = {}         # provider -> {"count": int, "until": float}
    _threshold = 3
    _cooldown = 60.0

    # ── patch _record_failure to count 5xx ──────────────────────
    _orig_record = SelfHealingEngine._record_failure

    def _patched_record(self, provider, error):
        status = getattr(error, "status_code", None) or getattr(error, "http_status", None)
        if status and 500 <= int(status) < 600:
            now = _time.time()
            entry = _counter.setdefault(provider, {"count": 0, "until": 0})
            if now >= entry["until"]:
                entry["count"] = 0
            entry["count"] += 1
            if entry["count"] >= _threshold:
                entry["until"] = now + _cooldown
                _logger.warning(
                    "5xx short-circuit activated for %s "
                    "(%d consecutive, cooldown=%.0fs)",
                    provider, entry["count"], _cooldown,
                )
        else:
            # success or non-5xx error -> confidence restored
            _counter.pop(provider, None)
        return _orig_record(self, provider, error)

    SelfHealingEngine._record_failure = _patched_record

    # ── patch _get_provider to honour short-circuit ─────────────
    _orig_get = SelfHealingEngine._get_provider

    def _patched_get(self, name):
        entry = _counter.get(name)
        if entry and entry["count"] >= _threshold and _time.time() < entry["until"]:
            raise APIError(
                f"Provider {name!r} short-circuited "
                f"({entry['count']} consecutive 5xx)",
                status_code=503,
                fault_category=FaultCategory.PROVIDER_UNAVAILABLE,
            )
        return _orig_get(self, name)

    SelfHealingEngine._get_provider = _patched_get

    return _counter


def _patch_latency_validation(engine_module):
    """Monkey-patch SelfHealingEngine.call for latency validation.

    Tracks a rolling average of response times per provider.  When the
    average exceeds *latency_threshold_ms* (default 5000) the module
    attaches a ``latency_warning`` key to ``CallResult._metadata`` so
    that callers or higher-level orchestrators can act on it.
    """
    SelfHealingEngine = engine_module.SelfHealingEngine

    _samples = {}          # provider -> [elapsed_ms, ...]
    _window = 20
    _warn_ms = 5000.0

    _orig_call = SelfHealingEngine.call

    async def _patched_call(self, prompt, **kwargs):
        start = _time.monotonic()
        result = await _orig_call(self, prompt, **kwargs)
        elapsed_ms = (_time.monotonic() - start) * 1000

        provider = getattr(result, "provider", None) or "unknown"
        samples = _samples.setdefault(provider, [])
        samples.append(elapsed_ms)
        if len(samples) > _window:
            samples.pop(0)

        avg = sum(samples) / len(samples)
        if avg > _warn_ms:
            meta = getattr(result, "_metadata", None)
            if meta is not None:
                meta["latency_warning"] = (
                    f"provider={provider} avg_latency={avg:.0f}ms "
                    f"threshold={_warn_ms:.0f}ms"
                )
        return result

    SelfHealingEngine.call = _patched_call
    return _samples


def _apply_patches():
    """Apply both patches (5xx short-circuit + latency validation)."""
    try:
        from correctover._engine import _engine as _eng_mod
    except ImportError:
        # Direct import of the compiled module
        import correctover._engine as _eng_mod

    _patch_5xx_short_circuit(_eng_mod)
    _patch_latency_validation(_eng_mod)
    _logger.debug("_fixes2 patches applied: 5xx short-circuit + latency validation")
