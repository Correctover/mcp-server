# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""Correctover Sentry — Always-on cloud verification for every repair call.

Architecture:
  Every repair call goes through:
    Tier 1 (fast path, ~0μs):  In-memory signed token (5min TTL)
    Tier 2 (disk, ~1ms):       Disk-cached signed token
    Tier 3 (cloud, ~50ms):     FC /verify-repair endpoint

  If FC is unreachable, a 60-minute grace period uses the last-known-good
  cached token. After that, repairs are denied (fail-closed).

  There is NO opt-out env var for Sentry. The only config is the FC URL.
  This is ALWAYS-ON — embedded in the consume_repair() code path.

  Trust model:
    - FC signs short-lived token with HMAC-SHA256 (same secret as license keys)
    - Token is bound to: action + device_id + plan + timestamp
    - SDK caches the token and verifies the signature via _hmac_sign()
    - Compromised HMAC secret: attacker can forge tokens, but:
      (a) only for 5-minute windows, and
      (b) the next FC call will override, and
      (c) the FC can also revoke licenses independently
"""

import hashlib
import json
import os
import threading
import time
from typing import Optional, Dict, Any

# ── Config ──────────────────────────────────────────────────────────

# Hardcoded FC URL — NOT configurable via env var.
# This is compiled to .so in the PyPI wheel to prevent tampering.
# If you need to self-host, fork the repo and build from source.
_SENTRY_FC_URL = "https://license-api-correctover-hk.oss-cn-hongkong.aliyuncs.com/api/v1"

_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".correctover")
_CACHE_FILE = os.path.join(_CACHE_DIR, ".sentry_cache")

# Token refresh interval (seconds) — how often we call FC
_TOKEN_TTL = 300  # 5 minutes

# Grace period: how long a cached token is valid when FC is unreachable
_GRACE_PERIOD = 3600  # 60 minutes

# Minimum interval between FC retries on failure
_RETRY_INTERVAL = 60  # 1 minute

# SDK 版本 — 升级提醒
try:
    from correctover._version import __version__ as _SDK_VERSION
except ImportError:
    _SDK_VERSION = "unknown"

_LATEST_VERSION: Optional[str] = None       # 从 FC 获取的最新版本
_LATEST_VERSION_CHECKED: float = 0
_VERSION_CHECK_INTERVAL = 86400             # 24h PyPI 兜底刷新


def _warn_upgrade(latest: str) -> None:
    """打印升级提醒（仅一次）"""
    global _LATEST_VERSION
    if latest == _LATEST_VERSION:
        return  # 已提醒过相同版本
    _LATEST_VERSION = latest
    import sys as _sys
    _VER = _SDK_VERSION if _SDK_VERSION != "unknown" else "?"
    print(
        f"[Correctover] 新版本可用: v{latest} (当前: v{_VER})",
        file=_sys.stderr,
    )
    print(
        f"[Correctover] 升级: pip install --upgrade correctover-sdk",
        file=_sys.stderr,
    )


def _check_version_via_pypi() -> None:
    """PyPI 兜底：FC 没返回 latest_version 时直接从 PyPI 查。每24h一次。"""
    global _LATEST_VERSION_CHECKED, _LATEST_VERSION
    now = time.time()
    if now - _LATEST_VERSION_CHECKED < _VERSION_CHECK_INTERVAL:
        return
    _LATEST_VERSION_CHECKED = now
    try:
        import httpx
        resp = httpx.get(
            "https://pypi.org/pypi/correctover-sdk/json",
            timeout=5.0,
        )
        if resp.status_code == 200:
            info = resp.json().get("info", {})
            latest = info.get("version", "")
            if latest and latest != _SDK_VERSION:
                _warn_upgrade(latest)
    except Exception:
        pass


# ── Internal state ──────────────────────────────────────────────────

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None       # in-memory signed token cache
_last_fetch_time: float = 0                   # last FC call timestamp
_last_fetch_ok: bool = False                  # last FC call result


# ── Cache helpers (signed with _hmac_sign from license module) ──────

def _sign_data(data: Dict[str, Any]) -> str:
    """Sign a data dict using the license module's cache integrity function."""
    from correctover.license import _cache_sign
    clean = json.dumps(data, separators=(",", ":"), sort_keys=True)
    return _cache_sign(clean)


def _verify_signed(data: Dict[str, Any], signature: str) -> bool:
    """Verify a signed data dict."""
    from correctover.license import _cache_sign
    clean = json.dumps(data, separators=(",", ":"), sort_keys=True)
    expected = _cache_sign(clean)
    return signature == expected


def _load_cache_from_disk() -> Optional[Dict[str, Any]]:
    """Load and verify the signed cache file from disk."""
    try:
        if not os.path.exists(_CACHE_FILE):
            return None
        with open(_CACHE_FILE, "r") as f:
            raw = json.load(f)

        if not isinstance(raw, dict):
            return None

        data = raw.get("data")
        sig = raw.get("signature", "")
        if data is None or not sig:
            return None

        if not _verify_signed(data, sig):
            return None  # tampered cache

        # Check expiry
        expires_at = data.get("expires_at", 0)
        if expires_at > 0 and time.time() > expires_at:
            return None  # expired token

        return data
    except Exception:
        return None


def _save_cache_to_disk(data: Dict[str, Any]):
    """Save signed token to disk cache."""
    try:
        sig = _sign_data(data)
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_CACHE_FILE, "w") as f:
            json.dump({"data": data, "signature": sig}, f)
    except Exception:
        pass


# ── Cloud verification ──────────────────────────────────────────────

def _fetch_verdict(action: str, plan: str, license_key: str) -> Optional[Dict[str, Any]]:
    """Call FC /verify-repair and return a signed token dict, or None."""
    try:
        import httpx
        from correctover._device import device_fingerprint

        device_id = device_fingerprint()
        now = int(time.time())

        resp = httpx.post(
            f"{_SENTRY_FC_URL}/verify-repair",
            json={
                "action": action,
                "plan": plan,
                "license_key": license_key,
                "device_id": device_id,
                "timestamp": now,
                "sdk_version": _SDK_VERSION,
            },
            timeout=5.0,
        )

        # ── 版本升级提醒 ──
        if resp.status_code == 200:
            data = resp.json()
            fc_latest = data.get("latest_version", "")
            if fc_latest and fc_latest != _SDK_VERSION:
                _warn_upgrade(fc_latest)
            if data.get("allowed") and data.get("token"):
                return {
                    "action": action,
                    "allowed": True,
                    "token": data["token"],
                    "expires_at": data.get("expires_at", now + _TOKEN_TTL),
                    "plan": data.get("plan", plan),
                    "fetched_at": now,
                }
        elif resp.status_code == 403:
            # Cloud explicitly denied — cache the denial
            return {
                "action": action,
                "allowed": False,
                "token": "",
                "expires_at": now + _TOKEN_TTL,
                "plan": plan,
                "fetched_at": now,
            }

        return None
    except Exception:
        return None


# ── Public API ──────────────────────────────────────────────────────

def verify_repair(action: str) -> Optional[bool]:
    """Verify if a repair action is allowed.

    Always-on: checks cloud first (with local caching).
    Never raises. Never blocks the main thread for more than a few ms.

    Returns:
      True  — repair is allowed (cloud verified or valid cached token)
      False — repair is denied (cloud denied or grace period expired)
      None  — could not determine (no cache, FC unreachable)
              Caller should fall back to local license check.
    """
    global _cache, _last_fetch_time, _last_fetch_ok

    now = time.time()

    # ── Phase 1: In-memory cache ──
    with _lock:
        if _cache is not None:
            expires_at = _cache.get("expires_at", 0)
            if expires_at > now:
                return _cache.get("allowed", False)

            # Within grace period: last-known-good still valid
            fetched_at = _cache.get("fetched_at", 0)
            if now - fetched_at < _GRACE_PERIOD:
                return _cache.get("allowed", False)

        # ── Phase 2: Disk cache ──
        if _cache is None:
            disk_cache = _load_cache_from_disk()
            if disk_cache is not None:
                _cache = disk_cache
                expires_at = _cache.get("expires_at", 0)
                if expires_at > now:
                    return _cache.get("allowed", False)
                fetched_at = _cache.get("fetched_at", 0)
                if now - fetched_at < _GRACE_PERIOD:
                    return _cache.get("allowed", False)

    # ── Phase 3: Cloud (with retry throttle) ──
    # Don't retry FC more than once per _RETRY_INTERVAL on failure
    if now - _last_fetch_time < _RETRY_INTERVAL and not _last_fetch_ok:
        with _lock:
            if _cache is not None:
                return _cache.get("allowed", False)
        return None  # no cache, FC recently down — caller decides

    # Gather context for FC call
    try:
        from correctover.license import get_plan, _get_license_key
        plan = get_plan()
        license_key = _get_license_key()
    except Exception:
        plan = "free"
        license_key = ""

    # Call FC
    verdict = _fetch_verdict(action, plan, license_key)

    with _lock:
        _last_fetch_time = now
        _last_fetch_ok = verdict is not None

        if verdict is not None:
            _cache = verdict
            _save_cache_to_disk(verdict)
            return verdict.get("allowed", False)

        # FC unreachable: check in-memory cache one more time with grace
        if _cache is not None:
            fetched_at = _cache.get("fetched_at", 0)
            if now - fetched_at < _GRACE_PERIOD:
                return _cache.get("allowed", False)

        # FC 不可达时，PyPI 兜底查最新版本
        _check_version_via_pypi()

    return None  # cloud down, no cache — let caller decide


def quick_check() -> Optional[bool]:
    """Fast non-blocking check: do we have a valid cached token?

    Never makes network calls. Returns the current cached decision,
    or None if no valid cache exists.
    """
    global _cache

    now = time.time()

    with _lock:
        if _cache is not None:
            expires_at = _cache.get("expires_at", 0)
            if expires_at > now:
                return _cache.get("allowed", False)
            fetched_at = _cache.get("fetched_at", 0)
            if now - fetched_at < _GRACE_PERIOD:
                return _cache.get("allowed", False)

        # Try disk
        disk = _load_cache_from_disk()
        if disk is not None:
            _cache = disk
            return disk.get("allowed", False)

    return None


def invalidate_cache():
    """Force cache invalidation (e.g., on license change or activation)."""
    global _cache
    with _lock:
        _cache = None
        try:
            if os.path.exists(_CACHE_FILE):
                os.remove(_CACHE_FILE)
        except Exception:
            pass


def status() -> Dict[str, Any]:
    """Return sentry status for diagnostics."""
    global _cache, _last_fetch_time, _last_fetch_ok
    with _lock:
        return {
            "cached": _cache is not None,
            "cached_allowed": _cache.get("allowed") if _cache else None,
            "cached_expires_at": _cache.get("expires_at") if _cache else None,
            "cached_fetched_at": _cache.get("fetched_at") if _cache else None,
            "last_fetch_time": _last_fetch_time,
            "last_fetch_ok": _last_fetch_ok,
            "fc_url": _SENTRY_FC_URL,
        }
