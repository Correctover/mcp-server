# cython: docstring=False, emit_code_comments=False, language_level=3
# Copyright 2024-2026 Correctover Team
import sys
import types
import threading
import time

_CRITICAL_NAMES = frozenset([
    'is_pro', 'verify', 'activate', 'consume_repair',
    'get_plan', 'require_pro', '_HMAC_SECRET', '_hmac_sign',
    '_verify_offline', '_verify_online',
])

_snapshot_ids = {}
_snapshot_lock = threading.Lock()
_module_locked = False
_locked_class = None
_integrity_failures = 0
_last_check_time = 0
_CHECK_INTERVAL = 60  # minimum 60s between automatic checks


def _snapshot():
    global _module_locked
    try:
        import correctover.license as _lic
    except ImportError:
        return

    with _snapshot_lock:
        for name in _CRITICAL_NAMES:
            obj = _lic.__dict__.get(name)
            if obj is not None:
                _snapshot_ids[name] = id(obj)

    if not _module_locked:
        _lock_module(_lic)
        _module_locked = True


def _lock_module(mod):
    global _locked_class
    original_class = type(mod)

    class _M2(original_class):
        def __setattr__(self, name, value):
            if name in _CRITICAL_NAMES:
                _track("setattr_blocked", f"Attempted to set {name}")
                raise AttributeError(
                    f"Cannot modify '{name}' on correctover.license "
                    f"— security guard active"
                )
            return super().__setattr__(name, value)

        def __delattr__(self, name):
            if name in _CRITICAL_NAMES:
                _track("delattr_blocked", f"Attempted to delete {name}")
                raise AttributeError(
                    f"Cannot delete '{name}' on correctover.license "
                    f"— security guard active"
                )
            return super().__delattr__(name)

    try:
        mod.__class__ = _M2
        _locked_class = _M2
    except Exception:
        pass


def check() -> bool:
    """Check license module integrity.

    Detects: function replacement (id mismatch), __class__ reset,
    deletion of critical names, and pro-without-license fraud.
    """
    global _integrity_failures

    try:
        import correctover.license as _lic
    except ImportError:
        return True

    with _snapshot_lock:
        # Check 1: All critical names still exist with same id
        for name, original_id in _snapshot_ids.items():
            obj = _lic.__dict__.get(name)
            if obj is None:
                _track("name_deleted", name)
                _integrity_failures += 1
                return False
            if id(obj) != original_id:
                _track("id_mismatch", name)
                _integrity_failures += 1
                return False

    # Check 2: __class__ has not been reset
    if _locked_class is not None and type(_lic) is not _locked_class:
        _track("class_reset", "Module __class__ was reset")
        _integrity_failures += 1
        return False

    # Check 3: type(lic).__setattr__ is our custom one (not default)
    if _locked_class is not None:
        try:
            setattr_cls = getattr(type(_lic), '__setattr__', None)
            locked_setattr = getattr(_locked_class, '__setattr__', None)
            if setattr_cls is not locked_setattr:
                _track("setattr_replaced", "__setattr__ method replaced")
                _integrity_failures += 1
                return False
        except Exception:
            pass

    # Check 4: Pro without license fraud
    try:
        if _lic.is_pro() and _lic.get_plan() == 'free':
            _track("pro_without_license", "is_pro=True but plan=free")
            _integrity_failures += 1
            return False
    except Exception:
        pass

    return True


def enforce():
    """Check integrity and raise RuntimeError if tampering detected."""
    if not check():
        _track("enforce_triggered", "RuntimeError raised")
        raise RuntimeError(
            "Correctover integrity check failed — "
            "license module has been tampered with"
        )


def periodic_check() -> bool:
    """Called periodically by CloudKillGuardian. Rate-limited.

    If integrity fails multiple times, takes escalating action:
    - 1-2 failures: report to tracker
    - 3+ failures: enforce (raise RuntimeError)
    """
    global _last_check_time, _integrity_failures

    now = time.time()
    if now - _last_check_time < _CHECK_INTERVAL:
        return True  # Too soon, skip
    _last_check_time = now

    result = check()
    if not result:
        if _integrity_failures >= 3:
            # Escalating: enforce on repeated failures
            _track("escalated_enforce", f"failures={_integrity_failures}")
            enforce()
    else:
        # Reset failure counter on successful check
        _integrity_failures = 0

    return result


def _track(event_type, detail=""):
    try:
        from correctover._tracker import report_tamper
        report_tamper(event_type, detail)
    except Exception:
        pass
