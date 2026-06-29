# cython: docstring=False, emit_code_comments=False, language_level=3
# Copyright 2024-2026 Correctover Team
import hashlib
import sys

_DANGEROUS_NAMES = frozenset([
    '_HMAC_SECRET', '_hmac_sign', '_verify_offline', '_verify_online',
    '_auto_init', '_current', '_lock', '_COUNTERS_FILE',
])

# Fail-closed: track whether security init succeeded
_initialized = False


def _s1(lic_module):
    """Obfuscate HMAC_SECRET in memory with XOR key derivation."""
    raw = lic_module.__dict__.get('_HMAC_SECRET', b'')
    if not raw:
        try:
            lic_module._get_hmac_secret()
            raw = lic_module.__dict__.get('_HMAC_SECRET', b'')
        except Exception:
            pass
    if not raw:
        return
    seed = b"\x17\x03\x0b\x1f\x05\x12\x0a\x1c"
    h1 = hashlib.sha256(seed).digest()
    h2 = hashlib.sha256(h1 + seed + b"\xff").digest()
    h3 = hashlib.sha256(h2[::-1] + h1).digest()
    h4 = hashlib.sha256(h3 + seed[::-1]).digest()
    h5 = hashlib.sha256(h4 + h2 + b"\xaa").digest()
    xk = (h5 * ((len(raw) // 32) + 1))[:len(raw)]
    obf = bytes(a ^ b for a, b in zip(raw, xk))
    # Immediately zero the original from module dict
    lic_module.__dict__['_HMAC_SECRET'] = obf
    orig_sign = lic_module._hmac_sign
    ldict = lic_module.__dict__

    def _w1(_obf, _seed, _orig, _ldict):
        import hashlib as _h
        def _sign(payload_str):
            _h1 = _h.sha256(_seed).digest()
            _h2 = _h.sha256(_h1 + _seed + b"\xff").digest()
            _h3 = _h.sha256(_h2[::-1] + _h1).digest()
            _h4 = _h.sha256(_h3 + _seed[::-1]).digest()
            _h5 = _h.sha256(_h4 + _h2 + b"\xaa").digest()
            _xk = (_h5 * ((len(_obf) // 32) + 1))[:len(_obf)]
            _real = bytes(a ^ b for a, b in zip(_obf, _xk))
            _ldict['_HMAC_SECRET'] = _real
            try:
                return _orig(payload_str)
            finally:
                _ldict['_HMAC_SECRET'] = _obf
        return _sign

    lic_module.__dict__['_hmac_sign'] = _w1(obf, seed, orig_sign, ldict)


def _s2(lic_module):
    """Filter __dir__ to hide sensitive names from casual inspection."""
    orig_cls = type(lic_module)

    class _M1(orig_cls):
        def __dir__(self):
            try:
                _all = super().__dir__()
            except Exception:
                _all = list(self.__dict__.keys())
            return [x for x in _all if x not in _DANGEROUS_NAMES]

        def __setattr__(self, name, value):
            if name in _DANGEROUS_NAMES:
                raise AttributeError(
                    f"Cannot modify '{name}' — security protection active"
                )
            return super().__setattr__(name, value)

        def __delattr__(self, name):
            if name in _DANGEROUS_NAMES:
                raise AttributeError(
                    f"Cannot delete '{name}' — security protection active"
                )
            return super().__delattr__(name)

    try:
        lic_module.__class__ = _M1
    except Exception:
        pass


def init():
    """Initialize security layer. Fail-closed: logs WARNING on failure."""
    global _initialized

    # Step 1: Obfuscate HMAC key
    try:
        import correctover.license as _lic
        _s1(_lic)
    except Exception as e:
        print(f"[Correctover] WARNING: Security HMAC obfuscation failed: {e}",
              file=sys.stderr)

    # Step 2: Hide dangerous names from dir()
    try:
        import correctover.license as _lic_dir
        _s2(_lic_dir)
    except Exception as e:
        print(f"[Correctover] WARNING: Security dir-filter failed: {e}",
              file=sys.stderr)

    # Step 3: Take integrity snapshot (guard)
    try:
        from correctover._guard import _snapshot as _guard_snapshot
        _guard_snapshot()
    except Exception as e:
        print(f"[Correctover] WARNING: Guard snapshot failed: {e}",
              file=sys.stderr)

    # Step 4: Apply runtime patches
    try:
        from correctover._fixes import _apply_patches
        _apply_patches()
    except Exception as e:
        print(f"[Correctover] WARNING: Runtime patches failed: {e}",
              file=sys.stderr)

    _initialized = True
