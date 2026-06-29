#!/usr/bin/env bash
# PYTHONIOENCODING=utf-8
#
# Correctover SDK — self-contained CI build script.
#
# Builds from the monorepo's own sdk/correctover/ source (already
# namespace-replaced).  No external checkout needed.
#
# Usage:
#   ./scripts/build_matrix.sh 3.11        # compile & build wheel for Py 3.11
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
SRC_PKG="$HERE/correctover"               # already-namespaced source
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
echo " Source: $SRC_PKG"
echo " Target: $TMPDIR"
echo "============================================================"

# ── Step 0: Clean ────────────────────────────────────────────────────
rm -rf "$TMPDIR" "$DIST_DIR"

# ── Step 1: Copy source files ────────────────────────────────────────
echo ""
echo "[1/6] Copying .py files from monorepo source..."
if [ ! -d "$SRC_PKG" ]; then
    echo "ERROR: Source directory not found: $SRC_PKG" >&2
    exit 1
fi

# Copy via Python for cross-platform path handling
"$PYTHON" << PYEOF
import os, shutil

src_pkg = r"$SRC_PKG".replace("\\", "/")
tmpdir = r"$TMPDIR".replace("\\", "/")

for root, dirs, fnames in os.walk(src_pkg):
    if "__pycache__" in root:
        continue
    for f in fnames:
        if not f.endswith(".py"):
            continue
        src = os.path.join(root, f).replace("\\", "/")
        rel = os.path.relpath(src, src_pkg).replace("\\", "/")
        dst = os.path.join(tmpdir, rel).replace("\\", "/")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  [COPY] {rel}")

print(f"  Done – source files copied to {tmpdir}")
PYEOF

# ── Step 2: Write correctover-specific source files ─────────────────
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

# _fixes2.py — from repo (sdk/_fixes2_repo.py)
FIXES2_REPO="$(dirname "$HERE")/_fixes2_repo.py"
if [ -f "$FIXES2_REPO" ]; then
    cp "$FIXES2_REPO" "$TMPDIR/_fixes2.py"
    echo "  [COPY]  _fixes2.py (from sdk/_fixes2_repo.py)"
elif [ -f "$SRC_PKG/_fixes2.py" ]; then
    cp "$SRC_PKG/_fixes2.py" "$TMPDIR/_fixes2.py"
    echo "  [COPY]  _fixes2.py (from package)"
fi

# __init__.py — from repo (has _apply_patches calls)
if [ -f "$SRC_PKG/__init__.py" ]; then
    cp "$SRC_PKG/__init__.py" "$TMPDIR/__init__.py"
    echo "  [COPY]  __init__.py (from repo)"
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
        name="$(basename "$f" | sed 's/\.cpython-[0-9][0-9]*//')"
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
        magic = data[:4]
        flags = struct.unpack('<I', data[4:8])[0]
        header = 16  # same for 3.11 and 3.12
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

# ── Step 5: Remove .py files (keep __init__.py) ──────────────────────
echo ""
echo "[5/6] Removing .py source files (keeping __init__.py)..."
find "$TMPDIR" -name '*.py' -not -name '__init__.py' -not -path '*/__pycache__/*' -delete
echo "  [OK]  Source .py files removed"

# ── Step 6: Build wheel ─────────────────────────────────────────────
echo ""
echo "[6/6] Building wheel with python -m build --no-isolation..."

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

rm -rf "$TMPDIR"
echo "  [OK]  Temporary build directory removed"
