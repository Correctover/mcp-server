#!/usr/bin/env python3
"""Build correctover SDK using a temp directory (preserves source).

Builds from sdk/correctover/ (canonical source tracked in git).
"""
import os, sys, shutil, py_compile, subprocess, glob, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_PKG = os.path.join(HERE, "correctover")
VERSION = os.environ.get("CORRECTOVER_VERSION", "1.3.0")
PYTHON = sys.executable

TMPDIR = tempfile.mkdtemp(prefix="correctover-build-")
TMP_PKG = os.path.join(TMPDIR, "correctover")
DIST_DIR = os.path.join(HERE, "dist")

print(f"Correctover SDK v{VERSION}")
print(f"  Source: {SRC_PKG}")
print(f"  Temp: {TMPDIR}")
print(f"  Python: {PYTHON}")
print()

# Step 1: Copy source to temp dir
print("[1/5] Copying source files...")
if not os.path.isdir(SRC_PKG):
    print(f"  [FAIL] Source not found: {SRC_PKG}")
    sys.exit(1)

os.makedirs(TMP_PKG, exist_ok=True)
for item in os.listdir(SRC_PKG):
    src = os.path.join(SRC_PKG, item)
    dst = os.path.join(TMP_PKG, item)
    if item == "__pycache__":
        continue
    if os.path.isdir(src):
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    else:
        shutil.copy2(src, dst)
# Clean __pycache__ from temp
for root, dirs, files in os.walk(TMP_PKG):
    if "__pycache__" in root:
        shutil.rmtree(root)
print("  [COPY] Done")

# Step 2: Override _version.py
print()
print("[2/5] Overriding _version.py...")
with open(os.path.join(TMP_PKG, "_version.py"), "w") as f:
    f.write(
        '# Copyright 2024-2026 Correctover Team\n'
        '# Proprietary Commercial License\n'
        '"""Version info for Correctover SDK."""\n'
        f'__version__ = "{VERSION}"\n'
        'version = __version__\n'
    )
print(f"  [OVERRIDE] _version.py (v{VERSION})")

# Step 3: Compile .py -> .pyc
print()
print("[3/5] Compiling .py -> .pyc...")
compiled = failed = 0
for root, dirs, files in os.walk(TMP_PKG):
    for f in files:
        if not f.endswith(".py") or f == "__init__.py":
            continue
        path = os.path.join(root, f)
        try:
            py_compile.compile(path, doraise=True)
            compiled += 1
        except py_compile.PyCompileError as e:
            print(f"  [FAIL] {f}: {e}")
            failed += 1
print(f"  Compiled: {compiled}, Failed: {failed}")
if failed:
    shutil.rmtree(TMPDIR)
    sys.exit(1)

# Move .pyc from __pycache__
for root, dirs, files in os.walk(TMP_PKG):
    pycache = os.path.join(root, "__pycache__")
    if os.path.isdir(pycache):
        for f in os.listdir(pycache):
            if f.endswith(".pyc"):
                name = f.split(".")[0] + ".pyc"
                shutil.copy2(os.path.join(pycache, f), os.path.join(root, name))
        shutil.rmtree(pycache)
print("  [OK]  .pyc files moved from __pycache__")

# Strip absolute paths from .pyc
import marshal, struct
print("  [STRIP] Removing absolute paths from .pyc...")

def _strip_code(obj, visited=None):
    if visited is None:
        visited = set()
    if id(obj) in visited:
        return obj
    visited.add(id(obj))
    fname = os.path.basename(obj.co_filename)
    if obj.co_filename != fname:
        obj = obj.replace(co_filename=fname)
    new_consts = []
    for c in obj.co_consts:
        if hasattr(c, "co_code"):
            c = _strip_code(c, visited)
        new_consts.append(c)
    if new_consts != list(obj.co_consts):
        obj = obj.replace(co_consts=tuple(new_consts))
    return obj

for root, dirs, files in os.walk(TMP_PKG):
    for fn in files:
        if not fn.endswith(".pyc"):
            continue
        fpath = os.path.join(root, fn)
        with open(fpath, "rb") as fh:
            data = fh.read()
        try:
            code = marshal.loads(data[16:])
        except Exception:
            continue
        code = _strip_code(code)
        with open(fpath, "wb") as fh:
            fh.write(data[:16] + marshal.dumps(code))

# Step 4: Remove source .py (keep __init__.py)
print()
print("[4/5] Removing .py source (keeping __init__.py)...")
for root, dirs, files in os.walk(TMP_PKG):
    for f in files:
        if f.endswith(".py") and f != "__init__.py":
            os.remove(os.path.join(root, f))
pyc_count = sum(1 for _, _, fs in os.walk(TMP_PKG) for f in fs if f.endswith(".pyc"))
print(f"  [OK]  {pyc_count} compiled .pyc files")

# Step 5: Build wheel
print()
print("[5/5] Building wheel...")
if os.path.exists(DIST_DIR):
    shutil.rmtree(DIST_DIR)

pyproject = f"""[build-system]
requires = ["setuptools>=64,<75"]
build-backend = "setuptools.build_meta"

[project]
name = "correctover"
version = "{VERSION}"
description = "Correctover — Protocol-level contract validation with automatic verified failover for LLM APIs."
readme = "README.md"
requires-python = ">=3.12"
license = {{text = "Proprietary Commercial License"}}
keywords = ["llm", "self-healing", "failover", "correctover"]
authors = [{{name = "Correctover Team", email = "team@correctover.com"}}]
classifiers = [
    "Development Status :: 5 - Production/Stable",
    "Intended Audience :: Developers",
    "License :: Other/Proprietary License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]
dependencies = ["httpx>=0.24.0", "aiohttp>=3.8.0"]

[project.urls]
Homepage = "https://correctover.com"

[tool.setuptools.packages.find]
include = ["correctover*"]

[tool.setuptools.package-data]
correctover = ["*.pyc"]
"""

with open(os.path.join(TMPDIR, "pyproject.toml"), "w", encoding="utf-8") as f:
    f.write(pyproject)
with open(os.path.join(TMPDIR, "README.md"), "w") as f:
    f.write("# Correctover SDK\nFailure is not fatal.\n")
with open(os.path.join(TMPDIR, "LICENSE"), "w") as f:
    f.write(f"CORRECTOVER SDK v{VERSION} — PROPRIETARY COMMERCIAL LICENSE\nCopyright (c) 2024-2026 Correctover Team.\n")

result = subprocess.run(
    [PYTHON, "-m", "build", "--wheel", "--no-isolation"],
    cwd=TMPDIR, capture_output=True, text=True,
)
if result.returncode != 0:
    print(f"  [FAIL] {result.stderr}")
    print(result.stdout[:500])
    shutil.rmtree(TMPDIR)
    sys.exit(1)

for line in result.stdout.splitlines():
    if any(kw in line.lower() for kw in ("built", "error", "copying")):
        print(f"  {line}")

os.makedirs(DIST_DIR, exist_ok=True)
build_dist = os.path.join(TMPDIR, "dist")
for f in glob.glob(os.path.join(build_dist, "*.whl")):
    shutil.copy2(f, os.path.join(DIST_DIR, os.path.basename(f)))
    size_kb = os.path.getsize(f) / 1024
    print(f"  [OUT] {os.path.basename(f)} ({size_kb:.0f} KB)")

shutil.rmtree(TMPDIR)
print()
print(f"=== BUILD SUCCESS v{VERSION} ===")
