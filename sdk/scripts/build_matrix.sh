#!/usr/bin/env bash
# PYTHONIOENCODING=utf-8
#
# Correctover SDK — Python version matrix build script.
#
# Builds from correctover package source (sdk/correctover/).
# No vendoring needed — the namespace-replaced source is tracked in git.
#
# Usage:
#   ./scripts/build_matrix.sh 3.12        # compile & build wheel for Py 3.12
#
# Environment:
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
SRC_PKG="$HERE/correctover"                # canonical correctover source
TMPDIR="${TMPDIR:-/tmp}/correctover-build-$(date +%s)-$$"
DIST_DIR="$HERE/dist"
VERSION="${CORRECTOVER_VERSION:-1.3.0}"

# Python tag — prevents pip from installing .pyc wheels on wrong version
# e.g. "cp312" for Python 3.12
PY_TAG="cp${PY_VER//./}"

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
echo " Source: $SRC_PKG"
echo " Tag:    $PY_TAG"
echo " Target: $TMPDIR"
echo "============================================================"

# ── Step 0: Clean ────────────────────────────────────────────────────
rm -rf "$TMPDIR" "$DIST_DIR"

# ── Step 1: Copy source to temp dir ─────────────────────────────────
echo ""
echo "[1/5] Copying source files from $SRC_PKG..."
if [ ! -d "$SRC_PKG" ]; then
    echo "ERROR: Source not found: $SRC_PKG" >&2
    exit 1
fi

mkdir -p "$TMPDIR"
cp -r "$SRC_PKG"/* "$TMPDIR/"
# Remove __pycache__ from the copy
find "$TMPDIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
echo "  [COPY] Source copied to $TMPDIR"

# ── Step 2: Override correctover-specific files ────────────────────
echo ""
echo "[2/5] Overriding version and patches..."

# _version.py with build version
cat > "$TMPDIR/_version.py" << EOF
# Copyright 2024-2026 Correctover Team
# Proprietary Commercial License
"""Version info for Correctover SDK."""
__version__ = "$VERSION"
version = __version__
EOF
echo "  [OVERRIDE] _version.py (v$VERSION)"

echo "  [OK]  Using _fixes2.py from source (already tracked in correctover/)"
echo "  [OK]  Using __init__.py from source (with _apply_patches calls)"

# ── Step 3: Compile .py → .pyc ──────────────────────────────────────
echo ""
echo "[3/5] Compiling .py -> .pyc with Python $PY_VER..."

COMPILE_OK=$("$PYTHON" -c "
import os, py_compile, sys

pkg = r'$TMPDIR'.replace('\\\\', '/')
ok = fail = 0
for root, dirs, files in os.walk(pkg):
    for f in files:
        if not f.endswith('.py'):
            continue
        if f == '__init__.py':
            continue
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

# Move .pyc from __pycache__
find "$TMPDIR" -name '__pycache__' -type d | while read -r pc; do
    parent="$(dirname "$pc")"
    for f in "$pc"/*.pyc; do
        [ -f "$f" ] || continue
        name="$(basename "$f" | sed 's/\.cpython-[0-9][0-9]*//')"
        cp "$f" "$parent/$name"
    done
    rm -rf "$pc"
done
echo "  [OK]  .pyc files moved from __pycache__"

# ── Step 4: Strip paths from .pyc ────────────────────────────────────
echo ""
echo "[4/5] Stripping absolute paths from .pyc..."
export CORRECTOVER_BUILD_TMPDIR="$TMPDIR"
"$PYTHON" << 'PYEOF'
import os, marshal, struct

pkg = os.environ["CORRECTOVER_BUILD_TMPDIR"]

def strip_code(obj, visited=None):
    if visited is None:
        visited = set()
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
        if hasattr(c, 'co_code'):
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
        flags = struct.unpack('<I', data[4:8])[0]
        header = 16
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

# ── Step 5: Build wheel ─────────────────────────────────────────────
echo ""
echo "[5/5] Building wheel..."
find "$TMPDIR" -name '*.py' -not -name '__init__.py' -delete
echo "  [OK]  Source .py files removed (keeping __init__.py)"

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
keywords = ["llm", "self-healing", "failover", "correctover", "semantic-verification"]
authors = [{name = "Correctover Team", email = "team@correctover.com"}]
classifiers = [
    "Development Status :: 5 - Production/Stable",
    "Intended Audience :: Developers",
    "License :: Other/Proprietary License",
    "Operating System :: OS Independent",
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

cd "$TMPDIR"
"$PYTHON" -m build --no-isolation --wheel 2>&1
cd "$HERE"

# ── Collect wheel with correct python tag ──────────────────────────
mkdir -p "$DIST_DIR"
if [ -d "$TMPDIR/dist" ]; then
    for whl in "$TMPDIR"/dist/*.whl; do
        base="$(basename "$whl")"
        # correctover-1.3.0-py3-none-any.whl -> correctover-1.3.0-cp312-none-any.whl
        fixed="${base/py3/$PY_TAG}"
        cp "$whl" "$DIST_DIR/$fixed"
        echo "  [OUT] $fixed ($(du -h "$DIST_DIR/$fixed" | cut -f1))"
    done
    echo ""
    echo "=== BUILD COMPLETE ==="
else
    echo "  [FAIL] No dist/ directory created by build" >&2
    exit 1
fi

rm -rf "$TMPDIR"
echo "  [OK]  Temporary build directory removed"
