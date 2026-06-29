# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover v4.4.2 — Compliant Telemetry System.

Architecture: Dual-channel fault intelligence.

Channel 1: LOCAL FLYWHEEL (always on, zero network, zero privacy concern)
  - FlywheelLearner records fault→recovery pairs locally
  - 100% in-process, no data leaves the machine
  - This is how the MAPE-K loop evolves — no telemetry needed

Channel 2: COMMUNITY TELEMETRY (opt-in, fully anonymized, GDPR/CCPA compliant)
  - Sends only anonymized statistical summaries (no raw error text, no API keys)
  - Purpose: help Correctover team improve SDK (which providers fail most, etc.)
  - Requires explicit CORRECTOVER_TELEMETRY=1 to activate
  - Data schema is documented below for full transparency

Privacy guarantees when enabled:
  - NO raw error messages (only fault category + sub_category enum values)
  - NO API keys or key fragments (HMAC removed — was using key for signing!)
  - NO user identifiers (anonymous instance_id, rotates every 24h)
  - NO prompt or response content
  - NO provider-specific URLs or model names longer than 16 chars
  - User can inspect all data via telemetry.inspect_queue() before it's sent
  - User can export/delete via telemetry.export_data() / telemetry.clear()
"""
import json
import hashlib
import threading
import time
import os
import urllib.request
import urllib.error
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from ._engine import MetricsCollector, __version__


# ── Anonymization Layer ──────────────────────────────────────

def _anon_instance_id() -> str:
    """Generate an anonymous instance ID that rotates every 24h.
    Not traceable to any user — just helps deduplicate in aggregate."""
    day = int(time.time()) // 86400  # changes daily
    machine_hint = os.environ.get("CORRECTOVER_INSTANCE_ID", "")
    if machine_hint:
        return hashlib.sha256(f"{day}:{machine_hint}".encode()).hexdigest()[:12]
    return hashlib.sha256(f"{day}:anon".encode()).hexdigest()[:12]


def _anon_provider(provider: str) -> str:
    """Anonymize provider name — keep category, remove specifics."""
    # Only keep known provider names (no custom URLs leaking)
    KNOWN = {"openai", "anthropic", "deepseek", "nvidia", "dashscope", "google", "azure"}
    return provider if provider in KNOWN else "custom"


def _sanitize_event(event: Dict) -> Dict:
    """Strip any PII or sensitive data from an event before queueing."""
    clean = {}
    for key in ("fault_type", "sub_category", "recovery_action", "recovery_ok",
                "sdk_version", "latency_ms"):
        if key in event:
            clean[key] = event[key]

    # Anonymize provider
    if "provider" in event:
        clean["provider"] = _anon_provider(event["provider"])

    # Truncate model name (prevent leaking custom model paths)
    if "model" in event:
        m = str(event["model"])
        clean["model"] = m[:16] if len(m) > 16 else m

    # Instance ID (rotates daily, not traceable)
    clean["instance_id"] = _anon_instance_id()
    clean["sdk_version"] = __version__
    clean["ts"] = time.time()

    # NEVER include: error_message, api_key, signature, raw_error, prompt, content
    return clean


# ── Configuration ─────────────────────────────────────────────

@dataclass
class TelemetryConfig:
    """Configuration for telemetry collection.

    Privacy-first: telemetry is OFF by default.
    Set CORRECTOVER_TELEMETRY=1 or pass enabled=True to opt in.

    All data is anonymized before leaving the process.
    Call inspect_queue() to see exactly what would be sent.
    """
    endpoint: str = None
    batch_size: int = 50
    flush_interval: float = 30.0
    enabled: bool = False
    timeout_seconds: float = 3.0

    def __post_init__(self):
        if self.endpoint is None:
            self.endpoint = os.environ.get(
                "CORRECTOVER_TELEMETRY_URL",
                "https://telemetreceiver-correctover-fqarqvcdlt.cn-hangzhou.fcapp.run/api/v1/telemetry"
            )


# ── Telemetry Collector ──────────────────────────────────────

class TelemetryCollector:
    """Compliant fault telemetry: anonymized, opt-in, inspectable.

    How it works:
      1. Engine records fault events locally (FlywheelLearner — always on)
      2. If telemetry is enabled, a sanitized copy is queued for upload
      3. Before upload, user can inspect_queue() to verify no PII
      4. Upload is fire-and-forget: 3s timeout, silent failure, never blocks

    Enable:
      export CORRECTOVER_TELEMETRY=1
      # OR
      TelemetryCollector(config=TelemetryConfig(enabled=True))

    Inspect:
      tc = engine._get_telemetry()
      print(tc.inspect_queue())  # see exactly what would be sent
      tc.clear()                 # clear queue if you don't want to send
      tc.export_data()           # export all queued data as JSON
    """
    def __init__(self, endpoint: str = None,
                 batch_size: int = 50, flush_interval: float = 30.0,
                 config: Optional[TelemetryConfig] = None):
        _default_endpoint = os.environ.get(
            "CORRECTOVER_TELEMETRY_URL",
            "https://telemetreceiver-correctover-fqarqvcdlt.cn-hangzhou.fcapp.run/api/v1/telemetry"
        )
        if config is not None:
            self._endpoint = config.endpoint or _default_endpoint
            self._batch_size = config.batch_size
            self._flush_interval = config.flush_interval
            # Enable only if BOTH config.enabled=True AND env var is "1"
            self._enabled = config.enabled and os.environ.get("CORRECTOVER_TELEMETRY", "0") == "1"
        else:
            self._endpoint = endpoint or _default_endpoint
            self._batch_size = batch_size
            self._flush_interval = flush_interval
            self._enabled = os.environ.get("CORRECTOVER_TELEMETRY", "0") == "1"

        self._queue: List[Dict] = []
        self._sent_count: int = 0
        self._lock = threading.Lock()
        self._last_flush = time.time()
        from concurrent.futures import ThreadPoolExecutor
        self._executor = ThreadPoolExecutor(max_workers=2)
        if self._enabled:
            self._thread = threading.Thread(target=self._flush_loop, daemon=True)
            self._thread.start()

    def record_fault(self, fault_type: str, provider: str, model: str = "",
                     recovery_action: str = "", recovery_ok: bool = False,
                     latency_ms: float = 0.0, api_key: str = "", **kwargs):
        """Record a fault event. If telemetry is enabled, a sanitized copy is queued.

        Note: api_key parameter is accepted for API compatibility but NEVER stored
        or transmitted. The v1.x HMAC signing is removed — it was using the API
        key as a signing secret, which is a security risk.
        """
        if not self._enabled:
            return
        # Build raw event
        raw = {
            "fault_type": fault_type,
            "provider": provider,
            "model": model,
            "recovery_action": recovery_action,
            "recovery_ok": recovery_ok,
            "latency_ms": latency_ms,
        }
        # Include sub_category from kwargs if present
        if "sub_category" in kwargs:
            raw["sub_category"] = kwargs["sub_category"]

        # Sanitize: strip PII, anonymize, truncate
        clean = _sanitize_event(raw)

        with self._lock:
            self._queue.append(clean)
            if len(self._queue) > 500:
                self._queue = self._queue[-250:]
            if len(self._queue) >= self._batch_size:
                self._flush()

    def inspect_queue(self) -> List[Dict]:
        """Return a copy of the current queue for user inspection.
        This lets users verify no PII is being sent before it leaves the process."""
        with self._lock:
            return list(self._queue)

    def clear(self):
        """Clear the queue. Use if you inspect and don't want to send."""
        with self._lock:
            self._queue.clear()

    def export_data(self) -> str:
        """Export all queued data as JSON string. For user transparency."""
        with self._lock:
            return json.dumps(self._queue, indent=2, ensure_ascii=False)

    def _flush(self):
        # Respect opt-in: only send if CORRECTOVER_TELEMETRY=1
        if os.environ.get("CORRECTOVER_TELEMETRY", "0") != "1":
            self._queue.clear()
            return
        if not self._queue:
            return
        batch = self._queue[:]
        self._queue.clear()
        self._last_flush = time.time()
        self._executor.submit(self._send_batch, batch)

    def _send_batch(self, batch: List[Dict]):
        """Send with retry + disk cache fallback."""
        for attempt in range(3):
            try:
                data = json.dumps(batch).encode("utf-8")
                req = urllib.request.Request(
                    self._endpoint,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                resp = urllib.request.urlopen(req, timeout=3)
                if resp.status == 200:
                    with self._lock:
                        self._sent_count += len(batch)
                    return
            except Exception:
                if attempt < 2:
                    time.sleep(1 * (attempt + 1))
        self._save_to_disk_cache(batch)

    def _save_to_disk_cache(self, batch: List[Dict]):
        """Disk cache fallback — only stores sanitized data."""
        try:
            cache_dir = os.path.join(os.path.expanduser("~"), ".correctover", "telemetry_cache")
            os.makedirs(cache_dir, exist_ok=True)
            cache_file = os.path.join(cache_dir, f"cache_{int(time.time())}.json")
            with open(cache_file, "w") as f:
                json.dump(batch, f)
        except Exception:
            pass

    def _flush_loop(self):
        while self._enabled:
            time.sleep(self._flush_interval)
            with self._lock:
                if self._queue:
                    self._flush()

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                "enabled": self._enabled,
                "pending": len(self._queue),
                "sent_total": self._sent_count,
                "endpoint": self._endpoint if self._enabled else "(disabled)",
                "privacy": "anonymized" if self._enabled else "off",
            }


# ── Backward-compatible wrapper ──────────────────────────────

class CorrectoverTelemetry:
    """Backward-compatible telemetry class. Alias for TelemetryCollector."""
    def __init__(self, endpoint: str = None,
                 batch_size: int = 50, flush_interval: float = 30.0,
                 config: Optional[TelemetryConfig] = None):
        self._collector = TelemetryCollector(
            endpoint=endpoint, batch_size=batch_size,
            flush_interval=flush_interval, config=config)

    def record_fault(self, fault_type: str, provider: str, model: str = "",
                     recovery_action: str = "", recovery_ok: bool = False,
                     latency_ms: float = 0.0, **kwargs):
        return self._collector.record_fault(
            fault_type=fault_type, provider=provider, model=model,
            recovery_action=recovery_action, recovery_ok=recovery_ok,
            latency_ms=latency_ms, **kwargs)

    def inspect_queue(self) -> List[Dict]:
        return self._collector.inspect_queue()

    def clear(self):
        self._collector.clear()

    def export_data(self) -> str:
        return self._collector.export_data()

    def get_stats(self) -> Dict:
        return self._collector.get_stats()


__all__ = ["MetricsCollector", "CorrectoverTelemetry", "TelemetryCollector", "TelemetryConfig"]
