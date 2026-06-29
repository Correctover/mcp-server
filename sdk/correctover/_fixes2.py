# Copyright 2024-2026 Correctover Team
# Proprietary Commercial License
"""Correctover SDK — Runtime patches v2 for compiled module bugs.

Patches applied:
  1. 5xx short-circuit -- Track consecutive 5xx errors per provider.
     After N consecutive 5xx, short-circuit that provider for a cooldown
     period to avoid pointless retries of a failing upstream.
  2. Latency validation -- Track average response latency per provider.
     When the rolling average exceeds the configurable threshold, attach
     a latency_warning to CallResult._metadata.

These patches are applied at import time via __init__.py and are
transparent to end users.  Fixes apply to the compiled _engine module.
"""
import time as _time
import logging as _logging

_logger = _logging.getLogger("correctover._fixes2")


def _patch_5xx_short_circuit(engine_module):
    """Monkey-patch SelfHealingEngine for 5xx short-circuit.

    Hooks into _failover (the actual failure dispatch method) to
    track consecutive 5xx errors per provider.  Once the threshold
    (default 3) is reached the provider is short-circuited for a
    cooldown period (default 60 s).

    Hooks into _pick_provider to honour the short-circuit state.
    """
    SelfHealingEngine = engine_module.SelfHealingEngine
    FaultCategory = engine_module.FaultCategory

    # ── internal state ──────────────────────────────────────────
    _counter = {}         # provider -> {"count": int, "until": float}
    _threshold = 3
    _cooldown = 60.0

    # ── helper: extract HTTP status from a Diagnosis ─────────────
    def _get_http_status(diag):
        """Extract HTTP status code from Diagnosis.raw_error if present."""
        raw = getattr(diag, "raw_error", None)
        if raw is None:
            return None
        # raw_error could be an exception, a dict, or a string
        if isinstance(raw, dict):
            return raw.get("status_code") or raw.get("status")
        if isinstance(raw, BaseException):
            return getattr(raw, "status_code", None) or getattr(raw, "http_status", None)
        return None

    # ── patch _failover to count 5xx ────────────────────────────
    _orig_failover = SelfHealingEngine._failover

    def _patched_failover(self, prompt, model, failed_provider, diag,
                          sem_class, original_provider, original_model,
                          request_id, contract=None, trace=None,
                          call_start=None, **kwargs):
        status = _get_http_status(diag)
        if status and 500 <= int(status) < 600:
            now = _time.time()
            entry = _counter.setdefault(failed_provider, {"count": 0, "until": 0})
            if now >= entry["until"]:
                entry["count"] = 0
            entry["count"] += 1
            if entry["count"] >= _threshold:
                entry["until"] = now + _cooldown
                _logger.warning(
                    "5xx short-circuit activated for %s "
                    "(%d consecutive, cooldown=%.0fs)",
                    failed_provider, entry["count"], _cooldown,
                )
        else:
            # non-5xx -> restore confidence
            _counter.pop(failed_provider, None)
        return _orig_failover(self, prompt, model, failed_provider, diag,
                              sem_class, original_provider, original_model,
                              request_id, contract, trace, call_start, **kwargs)

    SelfHealingEngine._failover = _patched_failover

    # ── patch _pick_provider to honour short-circuit ────────────
    _orig_pick = SelfHealingEngine._pick_provider

    def _patched_pick(self, candidates):
        """Filter out short-circuited providers from candidate list."""
        now = _time.time()
        filtered = []
        for p in candidates:
            entry = _counter.get(p)
            if entry and entry["count"] >= _threshold and now < entry["until"]:
                continue  # skip short-circuited provider
            filtered.append(p)
        # If all providers are short-circuited, fall back to original
        if not filtered:
            filtered = candidates
            _logger.warning("All providers short-circuited, forcing fallback")
        return _orig_pick(self, filtered)

    SelfHealingEngine._pick_provider = _patched_pick

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

    async def _patched_call(self, prompt, model=None, task_type="",
                            has_schema=False, semantic_domain=None,
                            contract=None, api_type="chat", **kwargs):
        start = _time.monotonic()
        result = await _orig_call(self, prompt, model, task_type,
                                  has_schema, semantic_domain,
                                  contract, api_type, **kwargs)
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


def _patch_enforce(engine_module):
    """Wrapper: apply both patches and return their state objects."""
    ctr = _patch_5xx_short_circuit(engine_module)
    samples = _patch_latency_validation(engine_module)
    return {"5xx_counter": ctr, "latency_samples": samples}


def _apply_patches():
    """Apply both patches (5xx short-circuit + latency validation).

    Catches and logs errors so a patching failure never breaks import.
    """
    try:
        from correctover._engine import _engine as _eng_mod
    except ImportError:
        import correctover._engine as _eng_mod

    try:
        _patch_5xx_short_circuit(_eng_mod)
        _logger.debug("5xx short-circuit patch applied")
    except Exception as exc:
        _logger.warning("5xx short-circuit patch failed: %s", exc)

    try:
        _patch_latency_validation(_eng_mod)
        _logger.debug("Latency validation patch applied")
    except Exception as exc:
        _logger.warning("Latency validation patch failed: %s", exc)
