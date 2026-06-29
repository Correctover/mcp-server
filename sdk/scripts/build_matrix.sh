#!/usr/bin/env bash
# PYTHONIOENCODING=utf-8
#
# Correctover SDK — Python version matrix build script.
#
# Usage:
#   ./scripts/build_matrix.sh 3.11        # compile & build wheel for Py 3.11
#   ./scripts/build_matrix.sh 3.12        # compile & build wheel for Py 3.12
#
# Environment:
#   NEURALBRIDGE_SRC_DIR   Path to the neuralbridge-sdk checkout (default:
#                          D:/workspace/neuralbridge-sdk)
#   CORRECTOVER_VERSION    Version string baked into the wheel (default: 1.3.0)
#
# Each Python version produces a different .pyc bytecode format, so the
# caller MUST have the target Python interpreter installed.
set -euo pipefail
IFS=$'\n\t'

# ── Parse arguments ──────────────────────────────────────────────────
PY_VER="${1:-}"
if [ -z "$PY_VER" ]; then
    echo "Usage: $0 <python-version>  (e.g. 3.11 or 3.12)" >&2
    exit 1
fi

# ── Paths ────────────────────────────────────────────────────────────
HERE="$(cd "$(dirname "$0")/.." && pwd -W 2>/dev/null || cd "$(dirname "$0")/.." && pwd)"
NB_DIR="${NEURALBRIDGE_SRC_DIR:-D:/workspace/neuralbridge-sdk}"
NB_PKG="$NB_DIR/neuralbridge"
SDK_PKG="$HERE/correctover"
TMPDIR="${TMPDIR:-/tmp}/correctover-build-$(date +%s)-$$"
DIST_DIR="$HERE/dist"
VERSION="${CORRECTOVER_VERSION:-1.3.0}"

# ── Locate the target Python interpreter ─────────────────────────────
PYTHON=""
for candidate in "python${PY_VER}" "python${PY_VER//./}" "python3" "python"; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Cannot find Python $PY_VER interpreter." >&2
    exit 1
fi

# Verify the version matches
_INSTALLED_VER="$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
if [ "$_INSTALLED_VER" != "$PY_VER" ]; then
    echo "WARNING: Requested Python $PY_VER but $PYTHON reports $_INSTALLED_VER" >&2
fi

echo "============================================================"
echo " Correctover SDK v$VERSION  |  Python $PY_VER  |  $PYTHON"
echo " Source: $NB_PKG"
echo " Target: $TMPDIR"
echo "============================================================"

# ── Step 0: Clean ────────────────────────────────────────────────────
rm -rf "$TMPDIR" "$DIST_DIR"

# ── Step 1: Copy source files & replace namespace ────────────────────
echo ""
echo "[1/6] Copying .py files from NeuralBridge SDK..."
if [ ! -d "$NB_PKG" ]; then
    echo "ERROR: Source directory not found: $NB_PKG" >&2
    echo "Set NEURALBRIDGE_SRC_DIR to the neuralbridge-sdk checkout root." >&2
    exit 1
fi

# Copy via Python to handle Windows/Linux path differences
"$PYTHON" << PYEOF
import os, shutil

nb_pkg = r"$NB_PKG".replace("\\", "/")
tmpdir = r"$TMPDIR".replace("\\", "/")

for root, dirs, fnames in os.walk(nb_pkg):
    if "__pycache__" in root:
        continue
    for f in fnames:
        if not f.endswith(".py"):
            continue
        src = os.path.join(root, f).replace("\\", "/")
        rel = os.path.relpath(src, nb_pkg).replace("\\", "/")
        dst = os.path.join(tmpdir, rel).replace("\\", "/")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "r", encoding="utf-8") as fh:
            content = fh.read()
        # Namespace replacement
        for old, new in [
            ("neuralbridge", "correctover"),
            ("NeuralBridge", "Correctover"),
            ("NEURALBRIDGE", "CORRECTOVER"),
        ]:
            content = content.replace(old, new)
        # Telemetry endpoint
        content = content.replace(
            "license-api-neuralbridge-hk-rewfrmblft.cn-hongkong.fcapp.run",
            "license-api-correctover-hk.oss-cn-hongkong.aliyuncs.com",
        )
        # Fix known multi-line f-strings
        content = content.replace(
            '_print(f"\n  ✅ 修复脚本已生成: ',
            '_print(f"\\n  ✅ 修复脚本已生成: ',
        )
        content = content.replace(
            '_print(f"\n  ❌ 无法写入修复脚本: ',
            '_print(f"\\n  ❌ 无法写入修复脚本: ',
        )
        content = content.replace(
            '_print(f"\n  {\'─\' * 55}":',
            '_print(f"\\n  {\'─\' * 55}"',
        )
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"  [COPY] {rel}")

print(f"  Done – source files copied to {tmpdir}")
PYEOF

# ── Step 2: Create / overwrite correctover-specific files ────────────
echo ""
echo "[2/6] Creating correctover-specific source files..."

# _version.py
cat > "$TMPDIR/_version.py" << EOF
# Copyright 2024-2026 Correctover Team
# Proprietary Commercial License
"""Version info for Correctover SDK."""
__version__ = "$VERSION"
version = __version__
EOF
echo "  [CREATE] _version.py (v$VERSION)"

# _fixes2.py
if [ -f "$SDK_PKG/_fixes2.py" ]; then
    cp "$SDK_PKG/_fixes2.py" "$TMPDIR/_fixes2.py"
    echo "  [COPY]  _fixes2.py (from repo)"
else
    echo "  [WARN]  _fixes2.py not found in package, create minimal..."
    cat > "$TMPDIR/_fixes2.py" << 'PYEOF'
import time as _time
import logging as _logging
_logger = _logging.getLogger("correctover._fixes2")

def _patch_5xx_short_circuit(engine_module):
    SelfHealingEngine = engine_module.SelfHealingEngine
    APIError = engine_module.APIError
    FaultCategory = engine_module.FaultCategory
    _counter = {}
    _threshold = 3
    _cooldown = 60.0
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
                _logger.warning("5xx short-circuit for %s (%d)", provider, entry["count"])
        else:
            _counter.pop(provider, None)
        return _orig_record(self, provider, error)
    SelfHealingEngine._record_failure = _patched_record
    _orig_get = SelfHealingEngine._get_provider
    def _patched_get(self, name):
        entry = _counter.get(name)
        if entry and entry["count"] >= _threshold and _time.time() < entry["until"]:
            raise APIError(f"Provider {name!r} short-circuited", status_code=503,
                           fault_category=FaultCategory.PROVIDER_UNAVAILABLE)
        return _orig_get(self, name)
    SelfHealingEngine._get_provider = _patched_get
    return _counter

def _patch_latency_validation(engine_module):
    SelfHealingEngine = engine_module.SelfHealingEngine
    _samples = {}
    _window = 20
    _warn_ms = 5000.0
    _orig_call = engine_module.SelfHealingEngine.call
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
                meta["latency_warning"] = f"provider={provider} avg={avg:.0f}ms"
        return result
    engine_module.SelfHealingEngine.call = _patched_call
    return _samples

def _apply_patches():
    import correctover._engine as _eng_mod
    _patch_5xx_short_circuit(_eng_mod)
    _patch_latency_validation(_eng_mod)
    _logger.debug("_fixes2 patches applied")
PYEOF
    echo "  [CREATE] _fixes2.py (embedded fallback)"
fi

# __init__.py — use the repo version which already has both apply_patches calls
if [ -f "$SDK_PKG/__init__.py" ]; then
    cp "$SDK_PKG/__init__.py" "$TMPDIR/__init__.py"
    echo "  [COPY]  __init__.py (from repo)"
else
    echo "  [WARN]  __init__.py not found in repo!" >&2
fi

# ── Step 3: Compile .py → .pyc ──────────────────────────────────────
echo ""
echo "[3/6] Compiling .py -> .pyc with Python $PY_VER..."

COMPILE_OK=$("$PYTHON" -c "
import os, py_compile, sys

pkg = r'$TMPDIR'.replace('\\\\', '/')
ok = fail = 0
for root, dirs, files in os.walk(pkg):
    for f in files:
        if not f.endswith('.py'):
            continue
        if f == '__init__.py':
            continue   # keep __init__.py as source
        path = os.path.join(root, f)
        try:
            py_compile.compile(path, doraise=True)
            ok += 1
        except py_compile.PyCompileError as e:
            print(f'  [FAIL] {f}: {e}', file=sys.stderr)
            fail += 1
print(f'OK={ok} FAIL={fail}', flush=True)
if fail:
    sys.exit(1)
" 2>&1)
echo "  $COMPILE_OK"

# Move .pyc from __pycache__ subdirs to package dir level
find "$TMPDIR" -name '__pycache__' -type d | while read -r pc; do
    parent="$(dirname "$pc")"
    for f in "$pc"/*.pyc; do
        [ -f "$f" ] || continue
        name="$(basename "$f" | sed 's/\.cpython-[0-9][0-9]*//')"  # strip cpython-311/312
        cp "$f" "$parent/$name"
    done
    rm -rf "$pc"
done
echo "  [OK]  .pyc files moved from __pycache__"

# ── Step 4: Strip absolute paths from .pyc ───────────────────────────
echo ""
echo "[4/6] Stripping absolute paths from .pyc..."
export CORRECTOVER_BUILD_TMPDIR="$TMPDIR"
"$PYTHON" << 'PYEOF'
import os, marshal, struct

pkg = os.environ["CORRECTOVER_BUILD_TMPDIR"]

def strip_code(obj, visited=None):
    """Recursively replace co_filename with basename-only."""
    if visited is None:
        visited = set()
    # Avoid infinite recursion on cyclic code objects
    obj_id = id(obj)
    if obj_id in visited:
        return obj
    visited.add(obj_id)

    changed = False
    fname = os.path.basename(obj.co_filename)
    if obj.co_filename != fname:
        obj = obj.replace(co_filename=fname)
        changed = True

    new_consts = []
    for c in obj.co_consts:
        if hasattr(c, 'co_code'):  # nested code object
            c = strip_code(c, visited)
        new_consts.append(c)
    if new_consts != list(obj.co_consts):
        obj = obj.replace(co_consts=tuple(new_consts))
        changed = True

    return obj


for root, dirs, files in os.walk(pkg):
    for fn in files:
        if not fn.endswith('.pyc'):
            continue
        fpath = os.path.join(root, fn)
        with open(fpath, 'rb') as fh:
            data = fh.read()
        # Parse header — format shared by 3.11 and 3.12
        magic = data[:4]
        flags = struct.unpack('<I', data[4:8])[0]
        if flags & 0x1:
            header = 16   # magic(4) + flags(4) + hash(8)
        else:
            header = 16   # magic(4) + flags(4) + timestamp(4) + size(4)
        body = data[header:]
        try:
            code = marshal.loads(body)
        except Exception:
            continue
        code = strip_code(code)
        new_body = marshal.dumps(code)
        with open(fpath, 'wb') as fh:
            fh.write(data[:header] + new_body)
        print(f"  [STRIP] {fn}")
PYEOF

# ── Step 5: Remove .py files (keep __init__.py, keep _fixes2.py) ─────
echo ""
echo "[5/6] Removing .py source files (keeping __init__.py)..."
find "$TMPDIR" -name '*.py' -not -name '__init__.py' -not -path '*/__pycache__/*' -delete
echo "  [OK]  Source .py files removed"

# ── Step 6: Build wheel ─────────────────────────────────────────────
echo ""
echo "[6/6] Building wheel with python -m build --no-isolation..."

# Create a minimal pyproject.toml in the temp build dir
cat > "$TMPDIR/pyproject.toml" << EOF
[build-system]
requires = ["setuptools>=64,<75"]
build-backend = "setuptools.build_meta"

[project]
name = "correctover"
version = "$VERSION"
description = "Correctover — Protocol-level contract validation with automatic verified failover for LLM APIs."
readme = "README.md"
requires-python = ">=$PY_VER"
license = {text = "Proprietary Commercial License — see LICENSE"}
keywords = ["llm", "self-healing", "failover", "circuit-breaker", "api-resilience", "correctover", "semantic-verification"]
authors = [{name = "Correctover Team", email = "team@correctover.com"}]
classifiers = [
    "Development Status :: 5 - Production/Stable",
    "Intended Audience :: Developers",
    "License :: Other/Proprietary License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Topic :: Software Development :: Libraries :: Python Modules",
]
dependencies = ["httpx>=0.24.0", "aiohttp>=3.8.0"]

[tool.setuptools.packages.find]
include = ["correctover*"]

[tool.setuptools.package-data]
correctover = ["*.pyc"]

[project.urls]
Homepage = "https://correctover.com"
EOF

# Create minimal README and LICENSE
cat > "$TMPDIR/README.md" << 'EOF'
# Correctover SDK

**Failure is not fatal.** Protocol-level contract validation with automatic
verified failover for LLM APIs.

## Install

```bash
pip install correctover
```

## License

Proprietary Commercial License. See LICENSE file.
EOF

cat > "$TMPDIR/LICENSE" << EOF
CORRECTOVER SDK — PROPRIETARY COMMERCIAL LICENSE
Copyright (c) 2024-2026 Correctover Team. All rights reserved.

This software is NOT open source. It is distributed as compiled
bytecode only. Redistribution requires a valid commercial license.
EOF

# Build
cd "$TMPDIR"
"$PYTHON" -m build --no-isolation --wheel 2>&1
cd "$HERE"

# Collect wheel
mkdir -p "$DIST_DIR"
if [ -d "$TMPDIR/dist" ]; then
    cp "$TMPDIR"/dist/*.whl "$DIST_DIR/"
    echo ""
    echo "=== BUILD COMPLETE ==="
    ls -lh "$DIST_DIR"/*.whl 2>/dev/null
else
    echo "  [FAIL] No dist/ directory created by build" >&2
    exit 1
fi

# Cleanup temp
rm -rf "$TMPDIR"
echo "  [OK]  Temporary build directory removed"
