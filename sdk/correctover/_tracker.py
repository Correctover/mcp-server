# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
# Correctover(TM) — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover SDK — Anti-piracy tracker v1.0

Silently tracks tampering events and device fingerprints.
Reports to server in background thread. Local cache survives restarts.
"""
import os
import json
import time
import hashlib
import threading
import platform
from pathlib import Path
from typing import Optional, Dict, List

# ── Dynamic SDK version ────────────────────────────────────────────
def _get_sdk_version() -> str:
    """Read SDK version dynamically from correctover.__version__."""
    try:
        import correctover
        return getattr(correctover, '__version__', 'unknown')
    except Exception:
        return 'unknown'

# ── Configuration ─────────────────────────────────────────────────
_TRACK_URL = "https://license-api-correctover-hk.oss-cn-hongkong.aliyuncs.com/api/v1/track"
_TRACK_URL_FALLBACK = "https://api.correctover.cn/api/v1/track"
_LOCAL_DIR = Path.home() / ".correctover"
_CACHE_FILE = _LOCAL_DIR / "track.json"
_MAX_CACHE = 50

# ── Device Fingerprint ────────────────────────────────────────────
_device_id: Optional[str] = None
_env_hash: Optional[str] = None


def _get_device_id() -> str:
    global _device_id
    if _device_id:
        return _device_id
    try:
        raw = f"{platform.node()}-{platform.machine()}-{platform.system()}"
        # Try to get MAC address
        import uuid
        mac = uuid.getnode()
        raw += f"-{mac}"
    except Exception:
        raw = "unknown-device"
    _device_id = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return _device_id


def _get_env_hash() -> str:
    global _env_hash
    if _env_hash:
        return _env_hash
    try:
        env_parts = []
        _skip_patterns = ['KEY', 'SECRET', 'TOKEN', 'PASSWORD', 'PASS', 'CREDENTIAL']
        for key in sorted(os.environ.keys()):
            if any(k in key for k in ['CORRECTOVER', 'PYTHON', 'HOME', 'USER']):
                # Skip sensitive env vars
                if any(p in key.upper() for p in _skip_patterns):
                    env_parts.append(f"{key}=<redacted>")
                else:
                    env_parts.append(f"{key}={os.environ.get(key, '')}")
        _env_hash = hashlib.sha256("&".join(env_parts).encode()).hexdigest()[:16]
    except Exception:
        _env_hash = "unknown"
    return _env_hash


# ── Local Cache ───────────────────────────────────────────────────
_cache_lock = threading.Lock()


def _load_cache() -> List[Dict]:
    try:
        if _CACHE_FILE.exists():
            with open(_CACHE_FILE, 'r') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _save_cache(events: List[Dict]):
    try:
        _LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_FILE, 'w') as f:
            json.dump(events[-_MAX_CACHE:], f)
    except Exception:
        pass


# ── Server Reporting ──────────────────────────────────────────────
def _send_to_server(event: Dict):
    """Send event to tracking server in background. Only if opted-in."""
    if os.environ.get("CORRECTOVER_TELEMETRY", "0") != "1":
        return
    def _worker():
        for url in (_TRACK_URL, _TRACK_URL_FALLBACK):
            try:
                import httpx
                resp = httpx.post(url, json=event, timeout=5)
                if resp.status_code in (200, 201, 204):
                    return
            except Exception:
                continue
    t = threading.Thread(target=_worker, daemon=True)
    t.start()


# ── Public API ────────────────────────────────────────────────────
def report(event_type: str, detail: str = "") -> Dict:
    """Report a tracking event. Saves locally + sends to server."""
    event = {
        "device_id": _get_device_id(),
        "env_hash": _get_env_hash(),
        "event_type": event_type,
        "detail": detail,
        "timestamp": int(time.time()),
        "sdk_version": _get_sdk_version(),
    }

    # Save to local cache
    with _cache_lock:
        cache = _load_cache()
        cache.append(event)
        _save_cache(cache)

    # Send to server in background
    _send_to_server(event)

    return event


def report_tamper(tamper_type: str, detail: str = "") -> Dict:
    """Report a specific tampering event."""
    return report(f"tamper:{tamper_type}", detail)


def _indicators() -> List[str]:
    """Check for suspicious environment indicators."""
    results = []
    try:
        import correctover.license as lic
        # Check if guard was tampered
        if os.environ.get("GUARD_TAMPERED"):
            results.append("GUARD_TAMPERED")
        # Check integrity
        if hasattr(lic, 'is_pro') and lic.is_pro() and lic.get_plan() == 'free':
            results.append("PRO_WITHOUT_LICENSE")
        # Check for debugger
        if os.environ.get("PYTHONDEBUG"):
            results.append("DEBUGGER")
        # Check for crack tools
        for key in os.environ:
            if 'CRACK' in key.upper() or 'BYPASS' in key.upper():
                results.append(f"SUSPICIOUS_ENV:{key}")
    except Exception:
        results.append("INTEGRITY_FAILED")
    return results


def flush():
    """Send all pending local events to server."""
    with _cache_lock:
        cache = _load_cache()

    for event in cache:
        _send_to_server(event)


def status() -> Dict:
    """Return tracker status."""
    with _cache_lock:
        cache = _load_cache()

    return {
        "device_id": _get_device_id(),
        "env_hash": _get_env_hash(),
        "events_cached": len(cache),
        "indicators": _indicators(),
        "sdk_version": _get_sdk_version(),
    }
