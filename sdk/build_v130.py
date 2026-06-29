#!/usr/bin/env python3
"""Build correctover v1.3.0 using a temp directory to avoid self-copy issues."""
import os, sys, shutil, py_compile, subprocess, glob, marshal, struct, tempfile

HERE = r"C:\d\workspace\correctover\sdk"
NB_DIR = r"D:\workspace\neuralbridge-sdk"
NB_PKG = os.path.join(NB_DIR, "neuralbridge")
VERSION = "1.3.0"
PYTHON = sys.executable

TMPDIR = tempfile.mkdtemp(prefix="correctover-build-")
TMP_PKG = os.path.join(TMPDIR, "correctover")
DIST_DIR = os.path.join(HERE, "dist")

print(f"Correctover SDK v{VERSION}")
print(f"  Temp: {TMPDIR}")
print(f"  Python: {PYTHON}")
print()

# Step 1: Copy & namespace replace
print("[1/5] Copying source files...")
for root, dirs, fnames in os.walk(NB_PKG):
    if "__pycache__" in root:
        continue
    for f in fnames:
        if not f.endswith(".py"):
            continue
        src = os.path.join(root, f)
        rel = os.path.relpath(src, NB_PKG)
        dst = os.path.join(TMP_PKG, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "r", encoding="utf-8") as fh:
            content = fh.read()
        for old, new in [("neuralbridge", "correctover"), ("NeuralBridge", "Correctover"), ("NEURALBRIDGE", "CORRECTOVER")]:
            content = content.replace(old, new)
        content = content.replace(
            "license-api-neuralbridge-hk-rewfrmblft.cn-hongkong.fcapp.run",
            "license-api-correctover-hk.oss-cn-hongkong.aliyuncs.com",
        )
        # Fix multi-line f-strings
        content = content.replace('_print(f"\n  ✅ 修复脚本已生成: ', '_print(f"\\n  ✅ 修复脚本已生成: ')
        content = content.replace('_print(f"\n  ❌ 无法写入修复脚本: ', '_print(f"\\n  ❌ 无法写入修复脚本: ')
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"  [COPY] {rel}")

# Step 2: Override correctover-specific files
print()
print("[2/5] Overriding correctover-specific files...")

# _version.py
with open(os.path.join(TMP_PKG, "_version.py"), "w") as f:
    f.write(
        '# Copyright 2024-2026 Correctover Team\n'
        '# Proprietary Commercial License\n'
        '"""Version info for Correctover SDK."""\n'
        f'__version__ = "{VERSION}"\n'
        'version = __version__\n'
    )
print("  [OVERRIDE] _version.py")

# _fixes2.py from repo
fixes2_repo = os.path.join(HERE, "_fixes2_repo.py")
if os.path.exists(fixes2_repo):
    shutil.copy2(fixes2_repo, os.path.join(TMP_PKG, "_fixes2.py"))
    print("  [OVERRIDE] _fixes2.py (from repo)")

# __init__.py from repo (has _apply_patches calls)
init_src = os.path.join(HERE, "correctover", "__init__.py")
if os.path.exists(init_src):
    shutil.copy2(init_src, os.path.join(TMP_PKG, "__init__.py"))
    print("  [OVERRIDE] __init__.py (from repo, with _apply_patches)")

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
print("  [OK] .pyc files moved from __pycache__")

# Strip absolute paths
print("  [STRIP] Removing absolute paths from .pyc...")
for root, dirs, files in os.walk(TMP_PKG):
    for fn in files:
        if not fn.endswith(".pyc"):
            continue
        fpath = os.path.join(root, fn)
        with open(fpath, "rb") as fh:
            data = fh.read()
        flags = struct.unpack("<I", data[4:8])[0]
        header = 16
        try:
            code = marshal.loads(data[header:])
        except Exception:
            continue

        def _strip(obj, visited=None):
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
                    c = _strip(c, visited)
                new_consts.append(c)
            if new_consts != list(obj.co_consts):
                obj = obj.replace(co_consts=tuple(new_consts))
            return obj

        code = _strip(code)
        new_body = marshal.dumps(code)
        with open(fpath, "wb") as fh:
            fh.write(data[:header] + new_body)

# Remove .py sources (keep __init__.py)
for root, dirs, files in os.walk(TMP_PKG):
    for f in files:
        if f.endswith(".py") and f != "__init__.py":
            os.remove(os.path.join(root, f))
print("  [OK] Source .py files removed (except __init__.py)")

# Verify
pyc_count = sum(1 for _, _, fs in os.walk(TMP_PKG) for f in fs if f.endswith(".pyc"))
print(f"  [OK] {pyc_count} compiled .pyc files")

# Step 4: Build wheel
print()
print("[4/5] Building wheel...")
if os.path.exists(DIST_DIR):
    shutil.rmtree(DIST_DIR)

# Create build config
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

# Create minimal README and LICENSE
with open(os.path.join(TMPDIR, "README.md"), "w") as f:
    f.write("# Correctover SDK\nFailure is not fatal.\n")

license_text = f"CORRECTOVER SDK v{VERSION} — PROPRIETARY COMMERCIAL LICENSE\nCopyright (c) 2024-2026 Correctover Team.\n"
with open(os.path.join(TMPDIR, "LICENSE"), "w") as f:
    f.write(license_text)

# Build from temp dir
result = subprocess.run(
    [PYTHON, "-m", "build", "--wheel", "--no-isolation"],
    cwd=TMPDIR,
    capture_output=True,
    text=True,
)
if result.returncode != 0:
    print(f"  [FAIL] {result.stderr}")
    print(result.stdout)
    shutil.rmtree(TMPDIR)
    sys.exit(1)

for line in result.stdout.splitlines():
    if any(kw in line.lower() for kw in ("built", "error", "copying")):
        print(f"  {line}")

# Collect wheel
os.makedirs(DIST_DIR, exist_ok=True)
build_dist = os.path.join(TMPDIR, "dist")
for f in glob.glob(os.path.join(build_dist, "*.whl")):
    shutil.copy2(f, os.path.join(DIST_DIR, os.path.basename(f)))
    size_kb = os.path.getsize(f) / 1024
    print(f"  [OUT] {os.path.basename(f)} ({size_kb:.0f} KB)")

# Cleanup
shutil.rmtree(TMPDIR)
print()
print(f"=== BUILD SUCCESS v{VERSION} ===")
